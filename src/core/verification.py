import os
from pathlib import Path

from ..network.utils import format_bytes
from ..network.exceptions import ChecksumMismatchError

from .constants import *
from .env import *
from .dependencies import *
from .dat_parser import normalize_checksum
from .signatures import hash_file_signatures, iter_archive_member_signatures


def file_exists_in_folder(folder: str, filename: str) -> tuple:
    """
    Check if a file exists in folder, handling variations in extensions.
    Returns (exists: bool, actual_path: str)
    """
    exact_path = os.path.join(folder, filename)
    if os.path.exists(exact_path):
        return True, exact_path

    name_no_ext = filename
    for ext in ROM_EXTENSIONS:
        if filename.lower().endswith(ext):
            name_no_ext = filename[:-len(ext)]
            break

    if os.path.exists(folder):
        for f in os.listdir(folder):
            f_no_ext = f
            for ext in ROM_EXTENSIONS:
                if f.lower().endswith(ext):
                    f_no_ext = f[:-len(ext)]
                    break
            if f_no_ext.lower() == name_no_ext.lower():
                return True, os.path.join(folder, f)

    return False, None


def snapshot_folder_files(folder: str) -> dict:
    """Capture l'etat des fichiers avant un telechargement."""
    snapshot = {}
    folder_path = Path(folder)
    if not folder_path.exists():
        return snapshot

    for file_path in folder_path.glob('*'):
        if not file_path.is_file():
            continue
        try:
            stat = file_path.stat()
            snapshot[str(file_path.resolve())] = (stat.st_mtime_ns, stat.st_size)
        except Exception:
            continue

    return snapshot


def resolve_downloaded_file_path(dest_path: str, folder: str, before_snapshot: dict) -> str:
    """Retrouve le fichier reel ecrit, meme si le serveur impose un nom different."""
    expected = Path(dest_path)
    if expected.exists():
        return str(expected)

    folder_path = Path(folder)
    if not folder_path.exists():
        return ''

    changed_files = []
    for file_path in folder_path.glob('*'):
        if not file_path.is_file():
            continue
        try:
            resolved = str(file_path.resolve())
            stat = file_path.stat()
            state = (stat.st_mtime_ns, stat.st_size)
        except Exception:
            continue
        if before_snapshot.get(resolved) != state:
            changed_files.append((state[0], str(file_path)))

    if not changed_files:
        return ''

    changed_files.sort(reverse=True)
    return changed_files[0][1]


def expected_game_md5_values(game_info: dict) -> set:
    """Retourne les MD5 attendus par le DAT pour ce jeu."""
    expected = set()
    for rom_info in game_info.get('roms', []):
        md5_value = normalize_checksum(rom_info.get('md5', ''), 'md5')
        if md5_value:
            expected.add(md5_value)
    return expected


def expected_game_sizes(game_info: dict) -> set[int]:
    """Retourne les tailles attendues par le DAT pour ce jeu."""
    expected = set()
    for rom_info in game_info.get('roms', []):
        try:
            size = int(rom_info.get('size') or 0)
        except (TypeError, ValueError):
            size = 0
        if size > 0:
            expected.add(size)
    return expected


def cleanup_invalid_download(path: str):
    """Supprime un telechargement qui ne correspond pas au MD5 du DAT."""
    if not path:
        return
    try:
        file_path = Path(path)
        if file_path.exists() and file_path.is_file():
            file_path.unlink()
    except Exception:
        pass


def cleanup_failed_download_outputs(dest_path: str, folder: str, before_snapshot: dict):
    """Supprime les sorties creees ou modifiees par une tentative ratee."""
    candidates = set()
    resolved_dest = resolve_downloaded_file_path(dest_path, folder, before_snapshot)
    if resolved_dest:
        candidates.add(resolved_dest)
    if dest_path:
        candidates.add(dest_path)

    for candidate in candidates:
        cleanup_invalid_download(candidate)


def verify_downloaded_md5(game_info: dict, downloaded_path: str) -> tuple[bool, str]:
    """
    Verifie le MD5 du fichier telecharge contre le DAT.
    Pour un ZIP, on verifie les entrees internes, car les DAT No-Intro
    reference souvent la ROM contenue plutot que le conteneur ZIP.
    """
    expected_md5 = expected_game_md5_values(game_info)
    expected_sizes = expected_game_sizes(game_info)
    if not expected_md5 and not expected_sizes:
        return True, "MD5/taille DAT absents: validation ignoree"

    if not downloaded_path or not os.path.exists(downloaded_path):
        return False, "Validation MD5 impossible: fichier telecharge introuvable"

    file_path = Path(downloaded_path)
    suffix = file_path.suffix.lower()

    if suffix in {'.zip', '.7z', '.rar'}:
        try:
            if expected_md5:
                for archive_entry in iter_archive_member_signatures(file_path):
                    if archive_entry.get('md5') in expected_md5:
                        return True, f"MD5 OK: {archive_entry.get('member') or archive_entry.get('name')}"
                return False, f"MD5 KO: aucune entree {suffix} ne correspond au DAT"
            for archive_entry in iter_archive_member_signatures(file_path, target_sizes=expected_sizes, require_hashes=False):
                if archive_entry.get('size') in expected_sizes:
                    return True, f"Taille DAT OK: {archive_entry.get('member') or archive_entry.get('name')} ({format_bytes(archive_entry.get('size'))})"
            expected_display = ', '.join(format_bytes(size) for size in sorted(expected_sizes))
            return False, f"Taille DAT KO: aucune entree {suffix} ne correspond a {expected_display}"
        except Exception as e:
            return False, f"Validation KO: archive {suffix} illisible ou non verifiable ({e})"

    if not expected_md5 and expected_sizes:
        actual_size = file_path.stat().st_size
        if actual_size in expected_sizes:
            return True, f"Taille DAT OK: {format_bytes(actual_size)}"
        expected_display = ', '.join(format_bytes(size) for size in sorted(expected_sizes))
        return False, f"Taille DAT KO: {format_bytes(actual_size)} != {expected_display}"

    try:
        signatures = hash_file_signatures(file_path)
    except Exception as e:
        return False, f"MD5 KO: impossible de lire le fichier ({e})"

    actual_md5 = signatures.get('md5', '')
    if actual_md5 in expected_md5:
        return True, f"MD5 OK: {actual_md5}"

    expected_display = ', '.join(sorted(expected_md5))
    return False, f"MD5 KO: {actual_md5 or 'absent'} != {expected_display}"


DOWNLOAD_RESOLUTION_KEYS = {
    'download_filename',
    'download_url',
    'torrent_url',
    'torrent_target_filename',
    'source',
    'database_host',
    'page_url',
    'archive_org_identifier',
    'archive_org_filename',
    'archive_org_md5',
    'archive_org_crc',
    'archive_org_sha1',
    'archive_org_checksum_type',
    'downloaded_path',
    'attempted_sources',
}


def clean_download_resolution(game_info: dict) -> dict:
    """Copie un jeu DAT sans les champs de provider deja resolus."""
    cleaned = game_info.copy()
    for key in DOWNLOAD_RESOLUTION_KEYS:
        cleaned.pop(key, None)
    return cleaned


def validate_download_checksum(game_info: dict, file_path: str) -> bool:
    """Valide le checksum du fichier telecharge, leve ChecksumMismatchError si echec."""
    ok, message = verify_downloaded_md5(game_info, file_path)
    if not ok:
        raise ChecksumMismatchError(message)
    return True


__all__ = [
    'file_exists_in_folder',
    'snapshot_folder_files',
    'resolve_downloaded_file_path',
    'expected_game_md5_values',
    'expected_game_sizes',
    'cleanup_invalid_download',
    'cleanup_failed_download_outputs',
    'verify_downloaded_md5',
    'validate_download_checksum',
    'DOWNLOAD_RESOLUTION_KEYS',
    'clean_download_resolution',
]