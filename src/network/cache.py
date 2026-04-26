"""Fonctions de cache persistant (resolution et listings)."""

from __future__ import annotations

import time
from pathlib import Path

from .utils import load_json_file, save_json_file


def _get_cache_file(name: str) -> Path:
    """Determine le fichier cache depuis les variables d'environnement ou defaut."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    return root / f".rom_downloader_{name}_cache.json"


RESOLUTION_CACHE_FILE = _get_cache_file("resolution")
LISTING_CACHE_FILE = _get_cache_file("listing")
RESOLUTION_CACHE_TTL = 7 * 24 * 60 * 60
LISTING_CACHE_TTL = 24 * 60 * 60


def load_resolution_cache_file(path: Path | None = None) -> dict:
    data = load_json_file(path or RESOLUTION_CACHE_FILE, {'version': 1, 'entries': {}})
    if not isinstance(data, dict):
        return {'version': 1, 'entries': {}}
    data.setdefault('version', 1)
    data.setdefault('entries', {})
    return data


def save_resolution_cache_file(cache: dict, path: Path | None = None) -> bool:
    cache = cache or {'version': 1, 'entries': {}}
    cache['version'] = 1
    cache.setdefault('entries', {})
    return save_json_file(path or RESOLUTION_CACHE_FILE, cache)


def clear_resolution_cache_file(path: Path | None = None) -> None:
    try:
        target = path or RESOLUTION_CACHE_FILE
        if target.exists():
            target.unlink()
    except Exception as e:
        print(f"Avertissement: cache de resolution non supprime: {e}")


def load_listing_cache_file(path: Path | None = None) -> dict:
    data = load_json_file(path or LISTING_CACHE_FILE, {'version': 1, 'entries': {}})
    if not isinstance(data, dict):
        return {'version': 1, 'entries': {}}
    data.setdefault('version', 1)
    data.setdefault('entries', {})
    return data


def save_listing_cache_file(cache: dict, path: Path | None = None) -> bool:
    cache = cache or {'version': 1, 'entries': {}}
    cache['version'] = 1
    cache.setdefault('entries', {})
    return save_json_file(path or LISTING_CACHE_FILE, cache)


def clear_listing_cache_file(path: Path | None = None) -> None:
    try:
        target = path or LISTING_CACHE_FILE
        if target.exists():
            target.unlink()
    except Exception as e:
        print(f"Avertissement: cache de listings non supprime: {e}")


def describe_cache_file(path: Path, ttl_seconds: int | None = None) -> dict:
    if not path.exists():
        return {
            'path': str(path),
            'present': False,
            'size': 0,
            'age_seconds': None,
            'fresh': False,
        }
    age_seconds = max(0, int(time.time() - path.stat().st_mtime))
    return {
        'path': str(path),
        'present': True,
        'size': path.stat().st_size,
        'age_seconds': age_seconds,
        'fresh': bool(ttl_seconds and age_seconds <= ttl_seconds),
    }


def listing_cache_get(cache: dict, key: str, ttl_seconds: int = LISTING_CACHE_TTL):
    entry = (cache or {}).get('entries', {}).get(key)
    if not entry:
        return None
    if time.time() - float(entry.get('created_at', 0)) > ttl_seconds:
        return None
    return entry.get('value')


def listing_cache_set(cache: dict, key: str, value) -> None:
    cache.setdefault('entries', {})[key] = {
        'created_at': time.time(),
        'value': value,
    }


__all__ = [
    "RESOLUTION_CACHE_FILE",
    "LISTING_CACHE_FILE",
    "RESOLUTION_CACHE_TTL",
    "LISTING_CACHE_TTL",
    "load_resolution_cache_file",
    "save_resolution_cache_file",
    "clear_resolution_cache_file",
    "load_listing_cache_file",
    "save_listing_cache_file",
    "clear_listing_cache_file",
    "describe_cache_file",
    "listing_cache_get",
    "listing_cache_set",
]
