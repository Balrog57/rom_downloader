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


def validate_env() -> dict:
    """Valide les variables d'environnement et retourne un resume des cles connues.
    
    Retourne un dict avec:
      - present: cles configurees avec leur statut
      - missing_optional: cles absentes mais non critiques
      - warnings: avertissements
    """
    example_keys = {
        "ONE_FICHIER_API_KEY": "optionnel (1fichier)",
        "ALLDEBRID_API_KEY": "optionnel (AllDebrid)",
        "REALDEBRID_API_KEY": "optionnel (RealDebrid)",
        "ARCHIVE_ORG_USERNAME": "optionnel (archive.org)",
        "ARCHIVE_ORG_PASSWORD": "optionnel (archive.org)",
        "LOLROMS_COOKIE": "optionnel (LoLROMs Cloudflare cookie)",
        "LOLROMS_USER_AGENT": "optionnel (LoLROMs UA)",
        "LOLROMS_BROWSER_HEADLESS": "optionnel (LoLROMs browser)",
        "LOLROMS_BROWSER_MODE": "optionnel (LoLROMs browser mode)",
        "LOLROMS_BROWSER_CHANNEL": "optionnel (LoLROMs browser channel)",
        "LOLROMS_BROWSER_PROFILE": "optionnel (LoLROMs browser profile)",
        "LOLROMS_BROWSER_DOWNLOAD_ATTEMPTS": "optionnel (LoLROMs browser attempts)",
        "LIBTORRENT_DLL_DIR": "optionnel (libtorrent DLLs)",
    }
    present = {}
    missing_optional = []
    
    for key, description in example_keys.items():
        value = os.environ.get(key, "").strip()
        if value:
            present[key] = description
        else:
            missing_optional.append(key)
    
    warnings = []
    if os.environ.get("ONE_FICHIER_API_KEY", "").strip() and not os.environ.get("ALLDEBRID_API_KEY", "").strip():
        warnings.append("1fichier configure mais AllDebrid absent (recommandé pour 1fichier)")
    if os.environ.get("ARCHIVE_ORG_USERNAME", "").strip() and not os.environ.get("ARCHIVE_ORG_PASSWORD", "").strip():
        warnings.append("archive.org username present mais mot de passe absent")
    
    return {
        "present": present,
        "missing_optional": missing_optional,
        "warnings": warnings,
    }

def save_env_file(env_vars: dict, file_path: str | None = None):
    """Sauvegarde les variables dans un fichier .env.

    Conserve les commentaires et l'ordre existant si le fichier existe deja.
    Met a jour les cles presentes dans env_vars, ajoute celles qui manquent a la fin.
    """
    file_path = file_path or (APP_ROOT / '.env')
    file_path = Path(file_path)

    known_keys = set(env_vars.keys())
    lines: list[str] = []
    seen_keys: set[str] = set()

    if file_path.exists():
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith('#') or not stripped:
                        lines.append(line.rstrip('\n'))
                        continue
                    if '=' in stripped:
                        key, _ = stripped.split('=', 1)
                        key = key.strip()
                        if key in known_keys:
                            val = str(env_vars[key])
                            if ' ' in val or '#' in val:
                                val = f'"{val}"'
                            lines.append(f"{key}={val}")
                            seen_keys.add(key)
                        else:
                            lines.append(line.rstrip('\n'))
                    else:
                        lines.append(line.rstrip('\n'))
        except Exception as e:
            print(f"Avertissement: erreur lecture .env: {e}")

    for key, val in env_vars.items():
        if key not in seen_keys:
            val = str(val)
            if ' ' in val or '#' in val:
                val = f'"{val}"'
            lines.append(f"{key}={val}")

    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
    except Exception as e:
        print(f"Erreur ecriture .env: {e}")


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
    'save_env_file',
]
