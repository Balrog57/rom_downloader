#!/usr/bin/env python3
r"""
ROM Downloader

Compare un DAT No-Intro ou Redump retraite avec Retool a un dossier cible
et telecharge uniquement les ROMs manquantes.

Sources supportees:
    GRATUITES:
    - Minerva No-Intro / Redump / TOSEC
    - archive.org
    - LoLROMs
    - EdgeEmu
    - PlanetEmu
    - 1fichier (gratuit)

Usage en ligne de commande:
    python main.py <dat_file> <rom_folder> [--dry-run] [--limit N] [--tosort] [--clean-torrentzip]

Usage interactif (sans arguments):
    python main.py
    (pose les questions pour les chemins)

Usage GUI (interface graphique):
    python main.py --gui

Options:
    --dry-run         Simulation sans telechargement
    --limit N         Limite le nombre de telechargements
    --tosort          Deplace les ROMs hors DAT dans un sous-dossier ToSort
    --clean-torrentzip Recompresse les archives validees MD5 en ZIP TorrentZip/RomVault
    --gui             Lance l'interface graphique
    --sources         Affiche la liste des sources de telechargement
"""

import os
from pathlib import Path

from ..progress import format_duration
from ..network.utils import format_bytes as _format_bytes_impl
from ..network.cache import (
    load_resolution_cache_file,
    save_resolution_cache_file,
    clear_resolution_cache_file,
    load_listing_cache_file,
    save_listing_cache_file,
    clear_listing_cache_file,
    describe_cache_file as _describe_cache_impl,
    listing_cache_get as _listing_cache_get_impl,
    listing_cache_set as _listing_cache_set_impl,
)

from .env import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .dependencies import *  # noqa: F401,F403
from .rom_database import *  # noqa: F401,F403
from .sources import *  # noqa: F401,F403
from .diagnostics import *  # noqa: F401,F403
from .dat_parser import *  # noqa: F401,F403
from .signatures import *  # noqa: F401,F403
from .scan_cache import *  # noqa: F401,F403
from .scanner import *  # noqa: F401,F403
from .torrentzip import *  # noqa: F401,F403
from .reports import *  # noqa: F401,F403
from .minerva import *  # noqa: F401,F403
from .dat_profile import *  # noqa: F401,F403
from .torrent import *  # noqa: F401,F403
from .api_keys import *  # noqa: F401,F403
from .premium_downloads import *  # noqa: F401,F403
from .archive_org import *  # noqa: F401,F403
from .scrapers import *  # noqa: F401,F403
from .search_pipeline import *  # noqa: F401,F403
from .downloads import *  # noqa: F401,F403
from .interactive import *  # noqa: F401,F403
from .verification import *  # noqa: F401,F403
from .download_orchestrator import *  # noqa: F401,F403
from .pipeline import *  # noqa: F401,F403
from .cli import *  # noqa: F401,F403
from .gui import *  # noqa: F401,F403
from .main_entry import *  # noqa: F401,F403


def load_preferences() -> dict:
    """Charge les preferences locales de la GUI."""
    return load_json_file(PREFERENCES_FILE, {})


def save_preferences(preferences: dict) -> bool:
    """Sauvegarde les preferences locales de la GUI."""
    return save_json_file(PREFERENCES_FILE, preferences or {})


def format_bytes(size: int | float | None) -> str:
    """DEPRECATED - Utilisez network.utils.format_bytes."""
    return _format_bytes_impl(size)


def load_resolution_cache() -> dict:
    """DEPRECATED - Utilisez network.cache.load_resolution_cache_file."""
    return load_resolution_cache_file()


def save_resolution_cache(cache: dict) -> bool:
    """DEPRECATED - Utilisez network.cache.save_resolution_cache_file."""
    return save_resolution_cache_file(cache)


def clear_resolution_cache() -> None:
    """DEPRECATED - Utilisez network.cache.clear_resolution_cache_file."""
    return clear_resolution_cache_file()


def load_listing_cache() -> dict:
    """DEPRECATED - Utilisez network.cache.load_listing_cache_file."""
    return load_listing_cache_file()


def save_listing_cache(cache: dict) -> bool:
    """DEPRECATED - Utilisez network.cache.save_listing_cache_file."""
    return save_listing_cache_file(cache)


def clear_listing_cache() -> None:
    """DEPRECATED - Utilisez network.cache.clear_listing_cache_file."""
    return clear_listing_cache_file()


def listing_cache_prefixes_for_source(source_name: str) -> set[str]:
    """Retourne les prefixes de cache listing lies a une source."""
    label = normalize_source_label(source_name)
    prefixes = set()
    for token in ('minerva', 'lolroms', 'edgeemu', 'planetemu'):
        if token in label:
            prefixes.add(token)
    return prefixes


def cache_entry_matches_source(entry: dict, source_name: str) -> bool:
    """Indique si une entree de cache resolution concerne une source."""
    target = normalize_source_label(source_name)
    if not target:
        return False
    labels = set()
    for value in entry.get('sources', []) + entry.get('found_sources', []):
        normalized = normalize_source_label(value)
        if normalized:
            labels.add(normalized)
    return any(target == label or target in label or label in target for label in labels)


def clear_resolution_cache_for_source(source_name: str) -> int:
    """Supprime les entrees de resolution qui mentionnent une source."""
    cache = load_resolution_cache()
    entries = cache.setdefault('entries', {})
    before = len(entries)
    cache['entries'] = {
        key: value for key, value in entries.items()
        if not cache_entry_matches_source(value, source_name)
    }
    removed = before - len(cache['entries'])
    if removed:
        save_resolution_cache(cache)
    return removed


def clear_listing_cache_for_source(source_name: str) -> int:
    """Supprime les listings caches associes a une source."""
    prefixes = listing_cache_prefixes_for_source(source_name)
    if not prefixes:
        return 0
    cache = load_listing_cache()
    entries = cache.setdefault('entries', {})
    before = len(entries)
    cache['entries'] = {
        key: value for key, value in entries.items()
        if not any(key.startswith(f"{prefix}:") for prefix in prefixes)
    }
    removed = before - len(cache['entries'])
    if removed:
        save_listing_cache(cache)
    return removed


def clear_caches_for_source(source_name: str) -> dict:
    """Invalide les caches runtime pour une source precise."""
    return {
        'resolution': clear_resolution_cache_for_source(source_name),
        'listing': clear_listing_cache_for_source(source_name),
    }


def describe_cache_file(path: Path, ttl_seconds: int | None = None) -> dict:
    """DEPRECATED - Utilisez network.cache.describe_cache_file."""
    return _describe_cache_impl(path, ttl_seconds)


def format_cache_status(label: str, status: dict) -> str:
    """Formate un etat cache pour affichage CLI/GUI."""
    if not status.get('present'):
        return f"{label}: absent"
    age = format_duration(status.get('age_seconds') or 0)
    freshness = "frais" if status.get('fresh') else "expire"
    return f"{label}: {format_bytes(status.get('size'))}, age {age}, {freshness}"


def listing_cache_get(cache: dict, key: str):
    """DEPRECATED - Utilisez network.cache.listing_cache_get."""
    return _listing_cache_get_impl(cache, key)


def listing_cache_set(cache: dict, key: str, value) -> None:
    """DEPRECATED - Utilisez network.cache.listing_cache_set."""
    return _listing_cache_set_impl(cache, key, value)