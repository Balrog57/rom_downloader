import hashlib
import json
from pathlib import Path

from .env import SCAN_CACHE_FILENAME


def load_scan_cache(rom_path: Path) -> dict:
    """Charge le cache de scan local, s'il existe."""
    cache_path = rom_path / SCAN_CACHE_FILENAME
    try:
        with open(cache_path, 'r', encoding='utf-8') as cache_file:
            cache = json.load(cache_file)
        if cache.get('version') == 2:
            return cache
    except Exception:
        pass
    return {'version': 2, 'files': {}}


def save_scan_cache(rom_path: Path, cache: dict):
    """Sauvegarde le cache de scan local."""
    cache_path = rom_path / SCAN_CACHE_FILENAME
    try:
        with open(cache_path, 'w', encoding='utf-8') as cache_file:
            json.dump(cache, cache_file, ensure_ascii=False)
    except Exception as e:
        print(f"  Avertissement: cache de scan non sauvegarde: {e}")


def cache_key_for_file(file_path: Path, rom_path: Path) -> str:
    """Cle stable relative au dossier scanne."""
    try:
        return str(file_path.relative_to(rom_path))
    except Exception:
        return str(file_path)


def file_cache_state(file_path: Path) -> dict | None:
    """Etat minimal permettant de detecter un fichier inchange."""
    try:
        stat = file_path.stat()
    except Exception:
        return None
    return {'mtime_ns': stat.st_mtime_ns, 'size': stat.st_size}


def target_sizes_cache_key(target_sizes: set) -> str:
    """Fingerprint compact des tailles DAT utilisees pour filtrer le scan."""
    if not target_sizes:
        return ''
    digest = hashlib.sha1()
    for item in sorted(target_sizes):
        digest.update(str(item).encode('ascii', errors='ignore'))
        digest.update(b'\0')
    return digest.hexdigest()


def cached_entries_for_file(cache: dict, key: str, state: dict) -> list | None:
    """Retourne les entrees de cache si le fichier n'a pas change."""
    cached = cache.get('files', {}).get(key)
    if not cached:
        return None
    if cached.get('state') == state:
        return cached.get('entries', [])
    return None


def update_file_scan_cache(cache: dict, key: str, state: dict, entries: list):
    """Met a jour les entrees scannees d'un fichier."""
    cache.setdefault('files', {})[key] = {'state': state, 'entries': entries}


__all__ = [
    'load_scan_cache',
    'save_scan_cache',
    'cache_key_for_file',
    'file_cache_state',
    'target_sizes_cache_key',
    'cached_entries_for_file',
    'update_file_scan_cache',
]