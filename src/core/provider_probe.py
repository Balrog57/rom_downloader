"""Probe non destructif des providers pour alimenter les candidats SQLite."""

from __future__ import annotations

import requests

from .catalog import list_catalog_games, list_catalog_systems
from .dat_profile import detect_dat_profile, finalize_dat_profile, prepare_sources_for_profile
from .local_database import record_provider_candidates
from .sources import get_default_sources, resolve_game_sources_with_cache


def _select_probe_system(system_query: str, catalog_dir=None) -> dict | None:
    query = (system_query or "").strip().lower()
    if not query:
        return None
    systems = list_catalog_systems(catalog_dir=catalog_dir)
    for system in systems:
        if system.get("system_id", "").lower() == query:
            return system
    exact = [
        system for system in systems
        if system.get("system_name", "").lower() == query
        or system.get("dat_label", "").lower() == query
    ]
    if exact:
        return exact[0]
    partial = [
        system for system in systems
        if query in f"{system.get('system_name', '')} {system.get('dat_label', '')}".lower()
    ]
    return partial[0] if partial else None


def probe_catalog_providers(system_query: str, limit: int = 50, sources: list | None = None,
                            session=None, catalog_dir=None, resolver=None) -> dict:
    """Resout les providers candidats d'un systeme sans telecharger les fichiers."""
    system = _select_probe_system(system_query, catalog_dir=catalog_dir)
    if not system:
        return {"system_found": False, "resolved": 0, "missing": 0, "stored": 0, "games": 0}

    dat_profile = finalize_dat_profile(detect_dat_profile(system["dat_path"]))
    system_name = dat_profile.get("system_name") or system["system_name"]
    active_sources = sources or prepare_sources_for_profile(get_default_sources(), dat_profile)
    active_session = session or requests.Session()
    resolve = resolver or resolve_game_sources_with_cache
    games = list_catalog_games(system["system_id"], catalog_dir=catalog_dir)
    if limit:
        games = games[:max(0, int(limit))]

    resolved = 0
    missing = 0
    stored = 0
    for game in games:
        found, _unavailable, _cache_hit = resolve(
            game,
            active_sources,
            active_session,
            system_name,
            dat_profile,
            cache={"entries": {}},
        )
        if found:
            resolved += 1
            stored += record_provider_candidates(game.get("game_id", ""), found, path=catalog_dir)
        else:
            missing += 1

    return {
        "system_found": True,
        "system_id": system["system_id"],
        "system_name": system_name,
        "games": len(games),
        "resolved": resolved,
        "missing": missing,
        "stored": stored,
    }


def format_probe_report(result: dict) -> str:
    """Formate le resume du probe provider."""
    if not result.get("system_found"):
        return "Aucun systeme catalogue ne correspond a la recherche."
    return (
        f"Probe providers: {result.get('system_name', '')}\n"
        f"Jeux testes: {result.get('games', 0)}\n"
        f"Resolus: {result.get('resolved', 0)}\n"
        f"Introuvables: {result.get('missing', 0)}\n"
        f"Candidats enregistres: {result.get('stored', 0)}"
    )


__all__ = [
    "probe_catalog_providers",
    "format_probe_report",
]
