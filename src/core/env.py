import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resource_root() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    return Path(bundle_root).resolve() if bundle_root else _repo_root()


def _app_root() -> Path:
    override = os.environ.get("ROM_DOWNLOADER_APP_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _repo_root()


RESOURCE_ROOT = _resource_root()
APP_ROOT = _app_root()
IS_FROZEN = bool(getattr(sys, "frozen", False))
SCAN_CACHE_FILENAME = ".rom_downloader_scan_cache.json"
DEFAULT_PARALLEL_DOWNLOADS = 3
PREFERENCES_FILE = APP_ROOT / ".rom_downloader_preferences.json"
RESOLUTION_CACHE_FILE = APP_ROOT / ".rom_downloader_resolution_cache.json"
LISTING_CACHE_FILE = APP_ROOT / ".rom_downloader_listing_cache.json"
RESOLUTION_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
LISTING_CACHE_TTL_SECONDS = 24 * 60 * 60
DOWNLOAD_CHUNK_SIZE = 256 * 1024


def load_env_file(file_path: str = '.env'):
    """Charge les variables d'un fichier .env dans os.environ."""
    if not os.path.exists(file_path):
        return
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    val = value.strip()
                    if (val.startswith('"') and val.endswith('"')) or \
                       (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    os.environ[key.strip()] = val
    except FileNotFoundError as e:
        print(f"  Erreur lancement du helper torrent: {e}")
        return False
    except Exception as e:
        print(f"Avertissement: Erreur lors du chargement du fichier .env: {e}")


load_env_file(APP_ROOT / '.env')

if 'IA_S3_ACCESS_KEY' in os.environ and 'IAS3_ACCESS_KEY' not in os.environ:
    os.environ['IAS3_ACCESS_KEY'] = os.environ['IA_S3_ACCESS_KEY']
if 'IA_S3_SECRET_KEY' in os.environ and 'IAS3_SECRET_KEY' not in os.environ:
    os.environ['IAS3_SECRET_KEY'] = os.environ['IA_S3_SECRET_KEY']

__all__ = [
    'APP_ROOT',
    'RESOURCE_ROOT',
    'IS_FROZEN',
    'SCAN_CACHE_FILENAME',
    'DEFAULT_PARALLEL_DOWNLOADS',
    'PREFERENCES_FILE',
    'RESOLUTION_CACHE_FILE',
    'LISTING_CACHE_FILE',
    'RESOLUTION_CACHE_TTL_SECONDS',
    'LISTING_CACHE_TTL_SECONDS',
    'DOWNLOAD_CHUNK_SIZE',
    'load_env_file',
]
