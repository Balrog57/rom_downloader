import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .constants import MINERVA_TORRENT_BACKEND_WARNING_SHOWN
from .dependencies import import_optional_package, OPTIONAL_IMPORT_ERRORS
from .env import APP_ROOT


def resolve_executable_path(candidates: tuple[str, ...], fallback_paths: tuple[str, ...] = ()) -> str:
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    for raw_path in fallback_paths:
        expanded = os.path.expandvars(raw_path)
        if expanded and os.path.exists(expanded):
            return expanded

    return ''


def resolve_aria2c_path() -> str:
    fallback_paths = (
        r'%LOCALAPPDATA%\Microsoft\WinGet\Links\aria2c.exe',
        r'%LOCALAPPDATA%\Microsoft\WindowsApps\aria2c.exe',
        r'%ProgramData%\chocolatey\bin\aria2c.exe',
    )
    resolved = resolve_executable_path(('aria2c.exe', 'aria2c'), fallback_paths)
    if resolved:
        return resolved

    winget_root = Path(os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\WinGet\Packages'))
    if winget_root.exists():
        for path in winget_root.glob('aria2.aria2_*/*/aria2c.exe'):
            if path.exists():
                return str(path)
    return ''


def bdecode_minimal(data: bytes):
    def parse(index: int):
        token = data[index:index + 1]
        if token == b'i':
            end = data.index(b'e', index)
            return int(data[index + 1:end]), end + 1
        if token == b'l':
            index += 1
            values = []
            while data[index:index + 1] != b'e':
                value, index = parse(index)
                values.append(value)
            return values, index + 1
        if token == b'd':
            index += 1
            values = {}
            while data[index:index + 1] != b'e':
                key, index = parse(index)
                value, index = parse(index)
                values[key] = value
            return values, index + 1
        if token.isdigit():
            colon = data.index(b':', index)
            length = int(data[index:colon])
            start = colon + 1
            end = start + length
            return data[start:end], end
        raise ValueError(f"Torrent bencode invalide a l'offset {index}")

    value, final_index = parse(0)
    if final_index != len(data):
        raise ValueError("Torrent bencode invalide: donnees restantes")
    return value


def _decode_torrent_text(value) -> str:
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    return str(value)


def list_torrent_files_from_bytes(torrent_data: bytes) -> list[dict]:
    meta = bdecode_minimal(torrent_data)
    info = meta.get(b'info') or meta.get('info') or {}
    root_name = _decode_torrent_text(info.get(b'name') or info.get('name') or '').replace('\\', '/')
    files = []

    if b'files' in info or 'files' in info:
        for index, item in enumerate(info.get(b'files') or info.get('files') or [], start=1):
            parts = item.get(b'path') or item.get('path') or []
            path = '/'.join(_decode_torrent_text(part) for part in parts)
            full_path = '/'.join(part for part in (root_name, path) if part)
            files.append({
                'index': index,
                'path': full_path,
                'name': Path(path).name,
                'size': int(item.get(b'length') or item.get('length') or 0),
            })
    else:
        files.append({
            'index': 1,
            'path': root_name,
            'name': Path(root_name).name,
            'size': int(info.get(b'length') or info.get('length') or 0),
        })
    return files


def select_torrent_file(torrent_files: list[dict], target_filename: str) -> dict | None:
    wanted = str(target_filename or '').replace('\\', '/').lower()
    wanted_name = Path(wanted).name
    for item in torrent_files:
        item_path = item.get('path', '').replace('\\', '/')
        item_name = item.get('name', '')
        normalized_path = item_path.lower()
        normalized_name = item_name.lower()
        if normalized_name == wanted or normalized_path == wanted or normalized_path.endswith('/' + wanted):
            return item
        if wanted_name and normalized_name == wanted_name:
            return item
    return None


def download_from_minerva_torrent_aria2(torrent_url: str, target_filename: str, dest_path: str,
                                        torrent_data: bytes | None = None) -> bool:
    import requests as requests_mod
    aria2c = resolve_aria2c_path()
    if not aria2c:
        return False

    temp_dir = Path(tempfile.mkdtemp(prefix='minerva-aria2-'))
    destination = Path(dest_path)
    timeout_ms = int(os.environ.get('MINERVA_TORRENT_TIMEOUT_MS', '0') or '0')
    try:
        if torrent_data is None:
            response = requests_mod.get(torrent_url, timeout=60)
            response.raise_for_status()
            torrent_data = response.content

        torrent_files = list_torrent_files_from_bytes(torrent_data)
        selected = select_torrent_file(torrent_files, target_filename)
        if not selected:
            print(f"  Erreur torrent: fichier cible introuvable: {target_filename}")
            return False

        torrent_file = temp_dir / 'minerva.torrent'
        torrent_file.write_bytes(torrent_data)
        print(f"  Backend torrent: aria2c")
        print(f"  Fichier selectionne dans le torrent: {selected['path']}")

        cmd = [
            aria2c,
            '--dir', str(temp_dir),
            '--select-file', str(selected['index']),
            '--seed-time=0',
            '--summary-interval=0',
            '--console-log-level=warn',
            '--quiet=true',
            '--allow-overwrite=true',
            '--auto-file-renaming=false',
            '--bt-enable-lpd=true',
            '--enable-dht=true',
            '--enable-peer-exchange=true',
            str(torrent_file),
        ]
        timeout_seconds = max(1, timeout_ms // 1000) if timeout_ms > 0 else None
        result = subprocess.run(
            cmd,
            cwd=str(temp_dir),
            timeout=timeout_seconds,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors='replace',
        )
        if result.returncode != 0:
            print(f"  Erreur torrent aria2c: code retour {result.returncode}")
            output = (result.stdout or '').strip()
            if output:
                print("\n".join(f"    {line}" for line in output.splitlines()[-8:]))
            return False

        source_file = temp_dir / selected['path']
        if not source_file.exists():
            matches = list(temp_dir.rglob(selected['name']))
            source_file = matches[0] if matches else source_file
        if not source_file.exists():
            print(f"  Erreur torrent: fichier telecharge introuvable: {selected['path']}")
            return False

        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_file), str(destination))
        print(f"  Torrent termine: {destination}")
        return destination.exists()
    except subprocess.TimeoutExpired:
        print(f"  Erreur torrent aria2c: timeout apres {timeout_ms} ms")
        return False
    except Exception as e:
        print(f"  Erreur torrent aria2c: {e}")
        return False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


LIBTORRENT_SESSION_USABLE = None


def is_libtorrent_session_usable() -> bool:
    global LIBTORRENT_SESSION_USABLE
    if LIBTORRENT_SESSION_USABLE is not None:
        return LIBTORRENT_SESSION_USABLE

    code = (
        "from src.core import import_optional_package;"
        "lt=import_optional_package('libtorrent', auto_install=False);"
        "assert lt is not None;"
        "s=lt.session();"
        "print('ok')"
    )
    env = os.environ.copy()
    env['PYTHONPATH'] = str(APP_ROOT) + os.pathsep + env.get('PYTHONPATH', '')
    try:
        result = subprocess.run(
            [sys.executable, '-c', code],
            cwd=str(APP_ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        LIBTORRENT_SESSION_USABLE = result.returncode == 0
    except Exception:
        LIBTORRENT_SESSION_USABLE = False
    return LIBTORRENT_SESSION_USABLE


def download_from_minerva_torrent(torrent_url: str, target_filename: str, dest_path: str,
                                  progress_callback=None) -> bool:
    import requests as requests_mod
    global MINERVA_TORRENT_BACKEND_WARNING_SHOWN

    if not torrent_url or not target_filename:
        print("  Erreur: URL de torrent ou nom de fichier manquant")
        return False

    torrent_data = None
    try:
        response = requests_mod.get(torrent_url, timeout=60)
        response.raise_for_status()
        torrent_data = response.content
    except Exception as e:
        print(f"  Erreur recuperation torrent Minerva: {e}")
        return False

    backend = os.environ.get('MINERVA_TORRENT_BACKEND', 'auto').strip().lower()
    if backend in ('', 'auto', 'aria2', 'aria2c'):
        if download_from_minerva_torrent_aria2(torrent_url, target_filename, dest_path, torrent_data):
            if progress_callback:
                progress_callback(100.0)
            return True
        if backend in ('aria2', 'aria2c'):
            return False

    if not is_libtorrent_session_usable():
        if not MINERVA_TORRENT_BACKEND_WARNING_SHOWN:
            print("  Minerva torrent ignore: backend libtorrent instable ou indisponible.")
            print("  Installe aria2c ou definis MINERVA_TORRENT_BACKEND=aria2 pour utiliser le backend externe.")
            MINERVA_TORRENT_BACKEND_WARNING_SHOWN = True
        return False

    lt = import_optional_package('libtorrent', auto_install=False)
    if lt is None:
        if not MINERVA_TORRENT_BACKEND_WARNING_SHOWN:
            py_version = f"{sys.version_info.major}.{sys.version_info.minor}"
            import_error = OPTIONAL_IMPORT_ERRORS.get('libtorrent', 'module introuvable')
            print("  Minerva torrent ignore: backend libtorrent indisponible.")
            print(f"  Python courant: {py_version}; erreur import: {import_error}")
            print("  Solution: installer un binding libtorrent compatible avec cet interpreteur")
            print("  et placer libcrypto-1_1-x64.dll/libssl-1_1-x64.dll dans PATH,")
            print("  ou definir LIBTORRENT_DLL_DIR dans .env vers le dossier qui les contient.")
            MINERVA_TORRENT_BACKEND_WARNING_SHOWN = True
        return False

    temp_dir = Path(tempfile.mkdtemp(prefix='minerva-torrent-'))
    destination = Path(dest_path)
    timeout_ms = int(os.environ.get('MINERVA_TORRENT_TIMEOUT_MS', '0') or '0')
    started = time.time()

    try:
        info = lt.torrent_info(lt.bdecode(torrent_data))
        session = lt.session({
            'listen_interfaces': '0.0.0.0:6881',
            'enable_dht': True,
            'enable_lsd': True,
            'enable_upnp': True,
            'enable_natpmp': True,
        })
        handle = session.add_torrent({'ti': info, 'save_path': str(temp_dir)})
        files = info.files()
        wanted = str(target_filename or '').replace('\\', '/').lower()
        selected_index = None
        selected_path = ''
        selected_size = 0

        for index in range(files.num_files()):
            file_path = files.file_path(index).replace('\\', '/')
            file_name = Path(file_path).name
            normalized_path = file_path.lower()
            normalized_name = file_name.lower()
            if normalized_name == wanted or normalized_path == wanted or normalized_path.endswith('/' + wanted):
                selected_index = index
                selected_path = file_path
                selected_size = files.file_size(index)
                break

        if selected_index is None:
            print(f"  Erreur torrent: fichier cible introuvable: {target_filename}")
            return False

        handle.prioritize_files([0] * files.num_files())
        handle.file_priority(selected_index, 7)
        print(f"  Torrent charge: {info.name()} ({files.num_files()} fichiers)")
        print(f"  Fichier selectionne dans le torrent: {selected_path}")

        last_progress = -1.0
        while not handle.is_seed():
            status = handle.status()
            progress = max(0.0, min(status.progress * 100.0, 100.0))
            if progress_callback and progress - last_progress >= 0.5:
                progress_callback(progress)
                last_progress = progress
            if timeout_ms > 0 and (time.time() - started) * 1000 > timeout_ms:
                print(f"  Erreur torrent: timeout apres {timeout_ms} ms")
                return False
            selected_file = temp_dir / selected_path
            if selected_file.exists() and (selected_size <= 0 or selected_file.stat().st_size >= selected_size):
                break
            time.sleep(1)

        source_file = temp_dir / selected_path
        if not source_file.exists():
            print(f"  Erreur torrent: fichier telecharge introuvable: {selected_path}")
            return False

        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_file), str(destination))
        if progress_callback:
            progress_callback(100.0)
        print(f"  Torrent termine: {destination}")
        return destination.exists()
    except Exception as e:
        print(f"  Erreur telechargement torrent Minerva: {e}")
        return False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


__all__ = [
    'resolve_executable_path',
    'resolve_aria2c_path',
    'bdecode_minimal',
    '_decode_torrent_text',
    'list_torrent_files_from_bytes',
    'select_torrent_file',
    'download_from_minerva_torrent_aria2',
    'LIBTORRENT_SESSION_USABLE',
    'is_libtorrent_session_usable',
    'download_from_minerva_torrent',
]