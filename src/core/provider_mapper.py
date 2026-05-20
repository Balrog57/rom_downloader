"""Scanner en masse: pour chaque systeme catalogue, sonde les providers mappables
et alimente provider_candidates + provider_metrics dans SQLite, sans telecharger."""

from __future__ import annotations

import time
import requests

from .catalog import list_catalog_systems, list_catalog_games
from .dat_profile import detect_dat_profile, finalize_dat_profile, prepare_sources_for_profile
from .local_database import (
    record_provider_candidates,
    record_provider_metric,
    list_provider_candidates,
)
from .sources import (
    get_default_sources,
    resolve_system_mapping,
    resolve_game_sources_with_cache,
    normalize_source_label,
)
from .mapping_status import build_mapping_status


def map_all_providers(
    samples_per_system: int = 5,
    providers_filter: list[str] | None = None,
    report_every: int = 10,
    dry_run: bool = False,
    log_func=print,
    resolver=None,
    max_systems: int | None = None,
    catalog_dir=None,
) -> dict:
    """Parcourt tous les systemes, sonde les providers mappables, alimente SQLite.

    Retourne un resume: combien de systemes couverts, combien de candidats generes,
    et la liste des systemes sans aucun provider fonctionnel.
    """
    all_systems = list_catalog_systems(catalog_dir=catalog_dir)
    all_sources = get_default_sources()
    all_providers = sorted({
        source.get("type", "") for source in all_sources
        if source.get("type")
    })
    if providers_filter:
        all_providers = [p for p in all_providers if p in providers_filter]

    mapping_status = {} if resolver else build_mapping_status(provider_types=all_providers)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    resolve = resolver or resolve_game_sources_with_cache

    total_systems = len(all_systems)
    summary = {
        "total_systems": total_systems,
        "providers_tested": all_providers,
        "samples_per_system": samples_per_system,
        "systems_processed": 0,
        "systems_with_candidates": 0,
        "systems_without_providers": [],
        "total_candidates": 0,
        "per_provider": {},
    }

    start_time = time.time()
    systems_with_providers: dict[str, set] = {}

    for index, system in enumerate(all_systems):
        if max_systems is not None and index >= max_systems:
            break
        sys_name = system["system_name"]
        sys_id = system["system_id"]

        log_func(f"[{index + 1}/{total_systems}] {sys_name}")

        try:
            dat_profile = finalize_dat_profile(detect_dat_profile(system["dat_path"]))
        except Exception:
            log_func(f"  SKIP: impossible de charger le profil DAT")
            continue

        sources = prepare_sources_for_profile(all_sources, dat_profile)
        games = list_catalog_games(sys_id, catalog_dir=catalog_dir)
        if samples_per_system and len(games) > samples_per_system:
            games = games[:samples_per_system]

        provider_found_for_system = set()
        candidates_for_system = 0

        for provider_type in all_providers:
            mapped = resolve_system_mapping(sys_name, provider_type)
            if not mapped:
                continue

            for game in games:
                enriched = dict(game)
                enriched.update({
                    "roms": [{}],
                    "game_id": game.get("game_id", ""),
                    "system_id": sys_id,
                })
                try:
                    found, _unavailable, _cache_hit = resolve(
                        enriched,
                        [s for s in sources if s.get("type") == provider_type and s.get("enabled", True)],
                        session,
                        sys_name,
                        dat_profile,
                        cache={"entries": {}},
                    )
                except Exception:
                    continue
                if found:
                    stored = record_provider_candidates(game.get("game_id", ""), found, path=catalog_dir)
                    candidates_for_system += stored
                    if stored:
                        provider_found_for_system.add(provider_type)
                        for candidate in found:
                            record_provider_metric(
                                candidate.get("source", provider_type),
                                "resolved",
                                0.0,
                                0,
                                path=catalog_dir,
                            )

        systems_with_providers[sys_id] = provider_found_for_system

        if provider_found_for_system:
            summary["systems_with_candidates"] += 1
        else:
            summary["systems_without_providers"].append(sys_name)
            log_func(f"  AUCUN provider fonctionnel trouve")

        summary["total_candidates"] += candidates_for_system
        summary["systems_processed"] += 1

        if sys_id in systems_with_providers or not provider_found_for_system:
            pass

        if (index + 1) % report_every == 0:
            elapsed = time.time() - start_time
            rate = total_systems / elapsed if elapsed > 0 else 0
            log_func(
                f"  --- Etape {index + 1}/{total_systems} "
                f"({summary['systems_with_candidates']} avec providers, "
                f"{summary['total_candidates']} candidats) "
                f"[{elapsed:.0f}s, {rate:.1f} sys/s]"
            )

    for provider_type in all_providers:
        covered = sum(
            1 for s in systems_with_providers.values()
            if provider_type in s
        )
        summary["per_provider"][provider_type] = {
            "covered": covered,
            "total": total_systems,
            "pct": round(100.0 * covered / total_systems, 1) if total_systems else 0,
        }

    elapsed = time.time() - start_time
    summary["elapsed_seconds"] = round(elapsed, 1)
    summary["systems_without_providers_count"] = len(summary["systems_without_providers"])

    return summary


def format_map_all_report(summary: dict) -> str:
    """Formate le resume de map_all_providers pour la CLI."""
    lines = [
        "=" * 60,
        "MAPPAGE PROVIDERS EN MASSE",
        "=" * 60,
        f"Systemes parcourus: {summary.get('systems_processed', 0)}/{summary.get('total_systems', 0)}",
        f"Avec au moins 1 provider: {summary.get('systems_with_candidates', 0)}",
        f"Sans aucun provider: {summary.get('systems_without_providers_count', 0)}",
        f"Total candidats generes: {summary.get('total_candidates', 0)}",
        f"Duree: {summary.get('elapsed_seconds', 0)}s",
        "",
        "Couverture par provider:",
    ]
    for provider, info in sorted(
        (summary.get("per_provider") or {}).items(),
        key=lambda x: x[1].get("covered", 0),
        reverse=True,
    ):
        lines.append(f"  {provider}: {info.get('covered', 0)}/{info.get('total', 0)} ({info.get('pct', 0)}%)")

    without = summary.get("systems_without_providers") or []
    if without:
        lines.extend(["", f"Systemes sans provider ({len(without)}):"])
        for name in without[:30]:
            lines.append(f"  - {name}")
        if len(without) > 30:
            lines.append(f"  ... {len(without) - 30} autre(s)")

    return "\n".join(lines)


__all__ = [
    "map_all_providers",
    "format_map_all_report",
]
