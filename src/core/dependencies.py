import importlib
import os
import subprocess
import sys
from pathlib import Path

from .env import APP_ROOT


def install_python_packages(packages: list[str], quiet: bool = True) -> bool:
    """Installe des packages Python pour l'interpreteur courant."""
    cmd = [
        sys.executable, '-m', 'pip', 'install',
        '--disable-pip-version-check',
        '--no-warn-script-location',
    ]
    cmd.extend(packages)
    if quiet:
        cmd.append('-q')
    try:
        return subprocess.run(cmd, check=False).returncode == 0
    except Exception as e:
        print(f"Avertissement: installation pip impossible: {e}")
        return False


OPTIONAL_IMPORT_ERRORS = {}
OPTIONAL_DLL_HANDLES = []


def _split_env_paths(value: str) -> list[Path]:
    return [Path(part.strip('"')) for part in (value or '').split(os.pathsep) if part.strip()]


def _directory_has_libtorrent_openssl_dlls(path: Path) -> bool:
    return (
        path.exists()
        and (path / 'libcrypto-1_1-x64.dll').exists()
        and (path / 'libssl-1_1-x64.dll').exists()
    )


def prepare_libtorrent_dll_search() -> list[Path]:
    """Ajoute les dossiers DLL OpenSSL 1.1 necessaires au wheel libtorrent Windows."""
    if os.name != 'nt' or not hasattr(os, 'add_dll_directory'):
        return []

    candidate_dirs: list[Path] = []
    for env_name in ('LIBTORRENT_DLL_DIR', 'OPENSSL_DLL_DIR'):
        candidate_dirs.extend(_split_env_paths(os.environ.get(env_name, '')))

    for base in (APP_ROOT, APP_ROOT / 'bin', APP_ROOT / 'vendor', APP_ROOT / 'vendor' / 'openssl'):
        candidate_dirs.append(base)

    for parent in [APP_ROOT.parent, APP_ROOT.parent.parent]:
        if not parent.exists():
            continue
        for pattern in ('DB.Browser.for.SQLite*', 'OpenSSL*', 'SeaTools*', 'NSCB*'):
            candidate_dirs.extend(path for path in parent.glob(pattern) if path.is_dir())

    added_dirs = []
    seen = set()
    for path in candidate_dirs:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        key = str(resolved).lower()
        if key in seen or not _directory_has_libtorrent_openssl_dlls(resolved):
            continue
        seen.add(key)
        try:
            OPTIONAL_DLL_HANDLES.append(os.add_dll_directory(str(resolved)))
            os.environ['PATH'] = str(resolved) + os.pathsep + os.environ.get('PATH', '')
            added_dirs.append(resolved)
        except OSError:
            continue
    return added_dirs


def import_optional_package(import_name: str, pip_name: str | None = None, auto_install: bool = False):
    """Importe un package optionnel, avec installation automatique si demandee."""
    if import_name == 'libtorrent':
        prepare_libtorrent_dll_search()
    try:
        return importlib.import_module(import_name)
    except ImportError as e:
        OPTIONAL_IMPORT_ERRORS[import_name] = str(e)
        if import_name == 'libtorrent':
            prepare_libtorrent_dll_search()
            try:
                return importlib.import_module(import_name)
            except ImportError as retry_error:
                OPTIONAL_IMPORT_ERRORS[import_name] = str(retry_error)
        if not auto_install:
            return None
    package_name = pip_name or import_name
    print(f"Installation du package optionnel {package_name}...")
    if install_python_packages([package_name]):
        try:
            return importlib.import_module(import_name)
        except ImportError as e:
            OPTIONAL_IMPORT_ERRORS[import_name] = str(e)
            print(f"Avertissement: {package_name} installe mais import impossible: {e}")
    return None


def load_json_file(path, default):
    """DEPRECATED - Utilisez network.utils.load_json_file."""
    from ..network.utils import load_json_file as _impl
    return _impl(path, default)


def save_json_file(path, data) -> bool:
    """DEPRECATED - Utilisez network.utils.save_json_file."""
    from ..network.utils import save_json_file as _impl
    return _impl(path, data)


try:
    import requests
    from bs4 import BeautifulSoup
    import internetarchive
    import cloudscraper
except ImportError:
    print("Installation des packages requis (requests, beautifulsoup4, internetarchive, cloudscraper)...")
    install_python_packages(['requests', 'beautifulsoup4', 'internetarchive', 'cloudscraper'])
    import requests
    from bs4 import BeautifulSoup
    import internetarchive
    import cloudscraper

__all__ = [
    'install_python_packages',
    'OPTIONAL_IMPORT_ERRORS',
    'OPTIONAL_DLL_HANDLES',
    '_split_env_paths',
    '_directory_has_libtorrent_openssl_dlls',
    'prepare_libtorrent_dll_search',
    'import_optional_package',
    'load_json_file',
    'save_json_file',
]