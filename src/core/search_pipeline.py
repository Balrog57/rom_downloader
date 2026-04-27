import re
import concurrent.futures
from urllib.parse import quote

import requests

from ..network.cache_runtime import get_session_cache
from ..network.search import ParallelSearchPool
from ..network.async_search import async_fetch_listings_parallel, _AIOHTTP_AVAILABLE

from .constants import *
from .env import *
from .dependencies import *
from .dat_parser import strip_rom_extension, normalize_checksum
from .rom_database import load_rom_database, database_result_filename
from .sources import SYSTEM_MAPPINGS, normalize_source_label, source_is_excluded
from .archive_org import search_archive_org_by_md5, search_archive_org_by_crc, search_archive_org_by_sha1, search_archive_org_by_name
from .minerva import (
    search_minerva_hash_database_for_games,
    search_database_for_game,
    select_database_result,
    build_minerva_directory_url,
    collect_minerva_files_from_url,
    resolve_minerva_torrent_url,
    build_minerva_torrent_urls,
)
from .dat_profile import finalize_dat_profile, prepare_sources_for_profile, describe_dat_profile
from .scrapers import (
    get_cdromance_session,
    get_vimm_session,
    get_lolroms_session,
    resolve_lolroms_system_path,
    list_lolroms_directory,
    _lolroms_subdir_for_system,
    iter_game_candidate_names,
    resolve_edgeemu_game,
    list_planetemu_directory,
    resolve_cdromance_game,
    resolve_vimm_game,
    resolve_retrogamesets_game,
    list_myrient_directory,
    match_myrient_files,
    search_archive_org_for_games,
)


def search_all_sources_legacy(missing_games: list, sources: list, session: requests.Session, system_name: str = None) -> tuple:
    """
    Search for missing games across all configured sources.
    Utilise la base de donnees locale (74,189 URLs) + recherche directe + nouveaux scrapers.
    Returns (found_games: list, not_found_games: list)
    """
    from . import _facade
    print("\n" + "=" * 70)
    print(f"Recherche des jeux manquants pour le systeme: {system_name or 'Inconnu'}")
    print("=" * 70)
    
    effective_profile = None
    if effective_profile and effective_profile.get('system_name'):
        system_name = effective_profile.get('system_name')

    sources = prepare_sources_for_profile(sources, effective_profile)

    load_rom_database()
    
    if effective_profile:
        print(f"DAT detecte: {describe_dat_profile(effective_profile)}")

    all_found = []
    still_missing = missing_games.copy()
    
    mappings = SYSTEM_MAPPINGS.get(system_name, {}) if system_name else {}
    
    print(f"\n{'=' * 70}")
    print("ETAPE 1: Recherche dans la base de donnees locale")
    print(f"{'=' * 70}")
    
    found_in_db = []
    not_in_db = []
    
    for game_info in still_missing:
        game_name = game_info['game_name']
        roms = game_info.get('roms', [])
        
        db_results, search_hint = search_database_for_game(game_info)
        
        if db_results:
            best_result = None
            for result in db_results:
                host = result.get('host', '')
                if 'archive.org' in host:
                    best_result = result
                    break
                elif 'myrient' in host and not best_result:
                    best_result = result
            
            if not best_result:
                best_result = db_results[0]
            
            game_info['download_filename'] = database_result_filename(best_result, game_name)
            game_info['download_url'] = best_result.get('url')
            game_info['source'] = 'database'
            game_info['database_host'] = best_result.get('host')
            found_in_db.append(game_info)
            print(f"  [DB] {game_name} -> {best_result.get('host')}")
        else:
            not_in_db.append(game_info)
    
    all_found.extend(found_in_db)
    still_missing = not_in_db
    
    print(f"\n  Trouve dans la base: {len(found_in_db)} jeux")
    print(f"  Non trouve dans la base: {len(still_missing)} jeux")
    
    if still_missing and system_name:
        for source in sources:
            if source['type'] == 'edgeemu' and source.get('enabled', True) and source.get('compatible', True):
                slug = mappings.get('edgeemu')
                if slug:
                    print(f"\n--- Recherche sur EdgeEmu ({slug}) ---")
                    newly_found = []
                    remaining = []
                    for game_info in still_missing:
                        edge_match = resolve_edgeemu_game(game_info, slug, session)
                        if edge_match:
                            game_info['download_url'] = edge_match['url']
                            game_info['source'] = 'EdgeEmu'
                            game_info['download_filename'] = edge_match['filename']
                            newly_found.append(game_info)
                            print(f"  [EdgeEmu] {game_info['game_name']} trouve")
                        else:
                            remaining.append(game_info)
                    all_found.extend(newly_found)
                    still_missing = remaining

            elif source['type'] == 'planetemu' and source.get('enabled', True) and source.get('compatible', True):
                slug = mappings.get('planetemu')
                if slug:
                    print(f"\n--- Recherche sur PlanetEmu ({slug}) ---")
                    planet_files = list_planetemu_directory(slug, session)
                    if planet_files:
                        newly_found = []
                        remaining = []
                        for game_info in still_missing:
                            name_lower = game_info['game_name'].lower()
                            if name_lower in planet_files:
                                game_info['page_url'] = planet_files[name_lower]['page_url']
                                game_info['source'] = 'PlanetEmu'
                                game_info['download_filename'] = f"{game_info['game_name']}.zip"
                                newly_found.append(game_info)
                                print(f"  [PlanetEmu] {game_info['game_name']} trouve")
                            else:
                                remaining.append(game_info)
                        all_found.extend(newly_found)
                        still_missing = remaining

            elif source['type'] == 'cdromance' and source.get('enabled', True):
                print(f"\n--- Recherche sur CDRomance ---")
                cd_session = get_cdromance_session()
                newly_found = []
                remaining = []
                for game_info in still_missing:
                    cd_match = resolve_cdromance_game(game_info, cd_session)
                    if cd_match:
                        game_info['page_url'] = cd_match['page_url']
                        game_info['source'] = 'CDRomance'
                        game_info['download_filename'] = f"{game_info['game_name']}.zip"
                        newly_found.append(game_info)
                        print(f"  [CDRomance] {game_info['game_name']} trouve")
                    else:
                        remaining.append(game_info)
                all_found.extend(newly_found)
                still_missing = remaining

            elif source['type'] == 'vimm' and source.get('enabled', True):
                slug = mappings.get('vimm')
                if slug:
                    print(f"\n--- Recherche sur Vimm's Lair ({slug}) ---")
                    vimm_session = get_vimm_session()
                    newly_found = []
                    remaining = []
                    for game_info in still_missing:
                        vimm_match = resolve_vimm_game(game_info, slug, vimm_session)
                        if vimm_match:
                            game_info['page_url'] = vimm_match['page_url']
                            game_info['source'] = 'Vimm\'s Lair'
                            game_info['download_filename'] = f"{game_info['game_name']}.zip"
                            newly_found.append(game_info)
                            print(f"  [Vimm] {game_info['game_name']} trouve")
                        else:
                            remaining.append(game_info)
                    all_found.extend(newly_found)
                    still_missing = remaining

            elif source['type'] == 'retrogamesets' and source.get('enabled', True):
                slug = mappings.get('retrogamesets')
                if slug:
                    print(f"\n--- Recherche sur RetroGameSets ({slug}) ---")
                    newly_found = []
                    remaining = []
                    for game_info in still_missing:
                        rgs_match = resolve_retrogamesets_game(game_info, slug, session)
                        if rgs_match:
                            game_info['download_url'] = rgs_match['url']
                            game_info['source'] = 'RetroGameSets'
                            game_info['download_filename'] = f"{game_info['game_name']}.zip"
                            newly_found.append(game_info)
                            print(f"  [RetroGameSets] {game_info['game_name']} trouve")
                        else:
                            remaining.append(game_info)
                    all_found.extend(newly_found)
                    still_missing = remaining

    myrient_sources = [s for s in sources if s['type'] == 'myrient' and s.get('enabled', True)]
    
    if myrient_sources and still_missing:
        for source in myrient_sources:
            print(f"\n--- Recherche directe sur {source['name']} ---")
            
            base_url = source['base_url']
            if base_url.endswith('/No-Intro/') and system_name:
                base_url = f"{base_url}{quote(system_name)}/"
            
            myrient_files = list_myrient_directory(base_url, session)
            
            if myrient_files:
                found, still_missing = match_myrient_files(still_missing, myrient_files, source['name'])
                for f in found:
                    f['download_url'] = f"{base_url.rstrip('/')}/{quote(f['download_filename'])}"
                all_found.extend(found)
    
    archive_sources = [
        s for s in sources
        if s['type'] == 'archive_org' and s.get('enabled', True) and s.get('compatible', True)
    ]
    
    if archive_sources and still_missing:
        print(f"\n--- Recherche archive.org par MD5 (fallback) ---")
        found, still_missing = search_archive_org_for_games(still_missing)
        all_found.extend(found)
    
    print(f"\n{'=' * 70}")
    print("RESUME DE LA RECHERCHE")
    print(f"{'=' * 70}")
    print(f"  Jeux trouves (base locale): {len(found_in_db)}")
    print(f"  Jeux trouves (Myrient direct): {len(all_found) - len(found_in_db)}")
    print(f"  Total trouves: {len(all_found)}")
    print(f"  Jeux non trouves: {len(still_missing)}")
    print(f"{'=' * 70}")
    
    return all_found, still_missing


def _resolve_games_parallel(
    still_missing: list,
    resolve_fn,
    resolve_key_prefix: str,
    source_label: str,
    system_name: str,
    extra_fields_fn=None,
    max_workers: int = 5,
) -> tuple[list, list]:
    """Resout les jeux en parallele via un scraper, retourne (found, remaining)."""
    session_cache = get_session_cache()
    search_pool = ParallelSearchPool(max_workers=max_workers)

    def _resolve_one(game_info):
        resolve_key = f"{resolve_key_prefix}:{game_info['game_name']}:{system_name}"
        cached = session_cache.get_resolution(resolve_key)
        if cached is not None:
            return (game_info, cached)
        result = resolve_fn(game_info)
        if result is not None:
            session_cache.set_resolution(resolve_key, result)
        return (game_info, result)

    scraper_funcs = [("resolve", _resolve_one)]
    pairs = []
    futures = {}
    for game_info in still_missing:
        future = search_pool.executor.submit(_resolve_one, game_info)
        futures[future] = game_info

    found = []
    remaining = []
    for future in concurrent.futures.as_completed(futures):
        game_info = futures[future]
        try:
            _, result = future.result()
        except Exception:
            remaining.append(game_info)
            continue
        if result:
            merged = dict(game_info)
            if extra_fields_fn:
                extra_fields_fn(merged, result)
            merged['source'] = source_label
            found.append(merged)
            print(f"  [{source_label}] {game_info['game_name']} trouve")
        else:
            remaining.append(game_info)

    search_pool.shutdown(wait=False)
    return found, remaining


def search_all_sources(
    missing_games: list,
    sources: list,
    session: requests.Session,
    system_name: str = None,
    dat_profile: dict | None = None,
    excluded_sources: set[str] | None = None
) -> tuple:
    """
    Search for missing games across all configured sources.
    Les liens directs sont prioritaires; Minerva passe ensuite, puis archive.org en dernier recours.
    Returns (found_games: list, not_found_games: list)
    """
    print("\n" + "=" * 70)
    print(f"Recherche des jeux manquants pour le systeme: {system_name or 'Inconnu'}")
    print("=" * 70)

    load_rom_database()
    excluded_sources = {
        normalize_source_label(source_name)
        for source_name in (excluded_sources or set())
        if source_name
    }

    all_found = []
    still_missing = missing_games.copy()
    direct_found = []
    found_in_db = []
    minerva_found = []
    archive_found = []

    mappings = SYSTEM_MAPPINGS.get(system_name, {}) if system_name else {}

    print(f"\n{'=' * 70}")
    print("ETAPE 1: Recherche dans la base de donnees locale (MD5 shards + fallback)")
    print(f"{'=' * 70}")

    not_in_db = []
    if 'database' in excluded_sources:
        not_in_db = still_missing
        print("  [DB] ignoree pour ce retry")
    else:
        for game_info in still_missing:
            game_name = game_info['game_name']
            db_results, search_hint = search_database_for_game(game_info)

            best_result = select_database_result(db_results)
            if best_result:
                game_info['download_filename'] = database_result_filename(best_result, game_name)
                game_info['download_url'] = best_result.get('url')
                game_info['source'] = 'database'
                game_info['database_host'] = best_result.get('host')
                found_in_db.append(game_info)
                print(f"  [DB] {game_name} -> {best_result.get('host')}{f' ({search_hint})' if search_hint else ''}")
            else:
                not_in_db.append(game_info)

    all_found.extend(found_in_db)
    still_missing = not_in_db

    print(f"\n  Trouve dans la base: {len(found_in_db)} jeux")
    print(f"  Non trouve dans la base: {len(still_missing)} jeux")

    print(f"\n{'=' * 70}")
    print("ETAPE 2: Recherche directe sur les sources DDL")
    print(f"{'=' * 70}")

    direct_sources = [
        s for s in sources
        if s.get('enabled', True)
        and s.get('compatible', True)
        and not source_is_excluded(s, excluded_sources)
        and s['type'] in {'myrient'}
    ]

    # Pre-fetch async des listings DDL si aiohttp disponible
    if _AIOHTTP_AVAILABLE and direct_sources and still_missing:
        prefetch_urls = []
        for source in direct_sources:
            if source['type'] == 'minerva':
                base_url = build_minerva_directory_url(source, system_name)
                listing_key = f"listing:minerva:{base_url}"
                session_cache = get_session_cache()
                if session_cache.get_listing(listing_key) is None:
                    prefetch_urls.append(base_url)
            elif source.get('base_url'):
                base_url = source['base_url']
                if base_url.endswith('/No-Intro/') and system_name:
                    base_url = f"{base_url}{quote(system_name)}/"
                listing_key = f"listing:myrient:{base_url}"
                session_cache = get_session_cache()
                if session_cache.get_listing(listing_key) is None:
                    prefetch_urls.append(base_url)

        if prefetch_urls:
            print(f"  Pre-fetch async de {len(prefetch_urls)} listing(s)...")
            import asyncio
            from ..network.async_search import async_fetch_listings_parallel
            try:
                asyncio.run(async_fetch_listings_parallel(prefetch_urls, timeout=30))
            except Exception:
                pass

    if direct_sources and still_missing:
        for source in direct_sources:
            if not still_missing:
                break
            print(f"\n--- Recherche directe sur {source['name']} ---")

            if source['type'] == 'minerva':
                base_url = build_minerva_directory_url(source, system_name)
                listing_key = f"listing:minerva:{base_url}"
                session_cache = get_session_cache()
                minerva_files = session_cache.get_listing(listing_key)
                if minerva_files is None:
                    minerva_files = collect_minerva_files_from_url(base_url, session, source.get('scan_depth', 0))
                    session_cache.set_listing(listing_key, minerva_files)
                if minerva_files:
                    torrent_url = resolve_minerva_torrent_url(source, system_name, session)
                    if not torrent_url:
                        candidates = build_minerva_torrent_urls(source, system_name)
                        probe_url = candidates[0] if candidates else 'aucune URL candidate'
                        print(f"  Avertissement: torrent Minerva introuvable pour {source['name']} ({probe_url})")
                        print("  Bascule vers les sources de fallback pour ce systeme.")
                        continue

                    found, still_missing = match_myrient_files(still_missing, minerva_files, source['name'])
                    for game in found:
                        game['torrent_url'] = torrent_url
                        game['source'] = source['name']
                    direct_found.extend(found)
                    all_found.extend(found)
            else:
                base_url = source['base_url']
                if base_url.endswith('/No-Intro/') and system_name:
                    base_url = f"{base_url}{quote(system_name)}/"

                listing_key = f"listing:myrient:{base_url}"
                session_cache = get_session_cache()
                myrient_files = session_cache.get_listing(listing_key)
                if myrient_files is None:
                    myrient_files = list_myrient_directory(base_url, session)
                    session_cache.set_listing(listing_key, myrient_files)
                if myrient_files:
                    found, still_missing = match_myrient_files(still_missing, myrient_files, source['name'])
                    for game in found:
                        game['download_url'] = f"{base_url.rstrip('/')}/{quote(game['download_filename'])}"
                    direct_found.extend(found)
                    all_found.extend(found)

    print(f"\n  Trouve via source DDL directe: {len(direct_found)} jeux")
    print(f"  Restants apres DDL direct: {len(still_missing)} jeux")

    if still_missing and system_name:
        for source in sources:
            if not still_missing:
                break
            if source_is_excluded(source, excluded_sources):
                continue

            if source['type'] == 'edgeemu' and source.get('enabled', True):
                slug = mappings.get('edgeemu')
                if slug and still_missing:
                    print(f"\n--- Recherche sur EdgeEmu ({slug}) ---")
                    def _edge_fields(merged, result):
                        merged['download_url'] = result['url']
                        merged['download_filename'] = result['filename']
                    newly_found, remaining = _resolve_games_parallel(
                        still_missing,
                        lambda gi: resolve_edgeemu_game(gi, slug, session),
                        "resolve:edgeemu",
                        "EdgeEmu",
                        system_name,
                        extra_fields_fn=_edge_fields,
                    )
                    all_found.extend(newly_found)
                    still_missing = remaining

            elif source['type'] == 'planetemu' and source.get('enabled', True):
                slug = mappings.get('planetemu')
                if slug:
                    print(f"\n--- Recherche sur PlanetEmu ({slug}) ---")
                    listing_key = f"listing:planetemu:{slug}"
                    session_cache = get_session_cache()
                    planet_files = session_cache.get_listing(listing_key)
                    if planet_files is None:
                        planet_files = list_planetemu_directory(slug, session)
                        session_cache.set_listing(listing_key, planet_files)
                    if planet_files:
                        newly_found = []
                        remaining = []
                        for game_info in still_missing:
                            name_lower = game_info['game_name'].lower()
                            entry = planet_files.get(name_lower)
                            if entry and isinstance(entry, dict):
                                game_info['page_url'] = entry.get('page_url', '')
                                game_info['source'] = 'PlanetEmu'
                                game_info['download_filename'] = f"{game_info['game_name']}.zip"
                                newly_found.append(game_info)
                                print(f"  [PlanetEmu] {game_info['game_name']} trouve")
                            else:
                                remaining.append(game_info)
                        all_found.extend(newly_found)
                        still_missing = remaining

            elif source['type'] == 'lolroms' and source.get('enabled', True):
                lolroms_paths = []
                subdir = _lolroms_subdir_for_system(system_name)
                if subdir:
                    base_system = re.sub(r'\s*\(.+?\)\s*$', '', system_name).strip()
                    base_path = resolve_lolroms_system_path(base_system)
                    if base_path:
                        lolroms_paths.append(f"{base_path}/{subdir}")
                else:
                    resolved = resolve_lolroms_system_path(system_name)
                    if resolved:
                        lolroms_paths.append(resolved)
                if lolroms_paths:
                    for lolroms_path in lolroms_paths:
                        if not still_missing:
                            break
                        print(f"\n--- Recherche sur LoLROMs ({lolroms_path}) ---")
                        listing_key = f"listing:lolroms:{lolroms_path}"
                        session_cache = get_session_cache()
                        lolroms_files = session_cache.get_listing(listing_key)
                        if lolroms_files is None:
                            lolroms_files = list_lolroms_directory(lolroms_path, include_subdirs=True)
                            session_cache.set_listing(listing_key, lolroms_files)
                    if lolroms_files:
                        newly_found = []
                        remaining = []
                        for game_info in still_missing:
                            matched = None
                            for candidate_name in iter_game_candidate_names(game_info):
                                matched = lolroms_files.get(candidate_name.lower())
                                if matched:
                                    break

                            if matched and isinstance(matched, dict):
                                game_info['download_url'] = matched.get('url', '')
                                game_info['source'] = 'LoLROMs'
                                game_info['download_filename'] = matched.get('filename', f"{game_info['game_name']}.zip")
                                newly_found.append(game_info)
                                print(f"  [LoLROMs] {game_info['game_name']} trouve")
                            else:
                                remaining.append(game_info)

                        all_found.extend(newly_found)
                        still_missing = remaining

            elif source['type'] == 'cdromance' and source.get('enabled', True):
                if still_missing:
                    print(f"\n--- Recherche sur CDRomance ---")
                    cd_session = get_cdromance_session()
                    def _cd_fields(merged, result):
                        merged['page_url'] = result['page_url']
                        merged['download_filename'] = f"{merged['game_name']}.zip"
                    newly_found, remaining = _resolve_games_parallel(
                        still_missing,
                        lambda gi: resolve_cdromance_game(gi, cd_session),
                        "resolve:cdromance",
                        "CDRomance",
                        system_name,
                        extra_fields_fn=_cd_fields,
                    )
                    all_found.extend(newly_found)
                    still_missing = remaining

            elif source['type'] == 'vimm' and source.get('enabled', True):
                slug = mappings.get('vimm')
                if slug and still_missing:
                    print(f"\n--- Recherche sur Vimm's Lair ({slug}) ---")
                    vimm_session = get_vimm_session()
                    def _vimm_fields(merged, result):
                        merged['page_url'] = result['page_url']
                        merged['download_filename'] = f"{merged['game_name']}.zip"
                    newly_found, remaining = _resolve_games_parallel(
                        still_missing,
                        lambda gi: resolve_vimm_game(gi, slug, vimm_session),
                        "resolve:vimm",
                        "Vimm's Lair",
                        system_name,
                        extra_fields_fn=_vimm_fields,
                    )
                    all_found.extend(newly_found)
                    still_missing = remaining

            elif source['type'] == 'retrogamesets' and source.get('enabled', True):
                slug = mappings.get('retrogamesets')
                if slug and still_missing:
                    print(f"\n--- Recherche sur RetroGameSets ({slug}) ---")
                    def _rgs_fields(merged, result):
                        merged['download_url'] = result['url']
                        merged['download_filename'] = f"{merged['game_name']}.zip"
                    newly_found, remaining = _resolve_games_parallel(
                        still_missing,
                        lambda gi: resolve_retrogamesets_game(gi, slug, session),
                        "resolve:retrogamesets",
                        "RetroGameSets",
                        system_name,
                        extra_fields_fn=_rgs_fields,
                    )
                    all_found.extend(newly_found)
                    still_missing = remaining

    minerva_sources = [
        s for s in sources
        if s.get('enabled', True)
        and s.get('compatible', True)
        and not source_is_excluded(s, excluded_sources)
        and s['type'] == 'minerva'
    ]

    if minerva_sources and still_missing:
        print(f"\n{'=' * 70}")
        print("ETAPE 4: Minerva via torrent")
        print(f"{'=' * 70}")

        print("\n--- Recherche Minerva officielle par MD5 DAT ---")
        found, still_missing = search_minerva_hash_database_for_games(still_missing)
        minerva_found.extend(found)
        all_found.extend(found)

        for source in minerva_sources:
            if not still_missing:
                break
            print(f"\n--- Recherche torrent sur {source['name']} ---")
            base_url = build_minerva_directory_url(source, system_name)
            listing_key = f"listing:minerva:{base_url}"
            session_cache = get_session_cache()
            minerva_files = session_cache.get_listing(listing_key)
            if minerva_files is None:
                minerva_files = collect_minerva_files_from_url(base_url, session, source.get('scan_depth', 0))
                session_cache.set_listing(listing_key, minerva_files)
            if not minerva_files:
                continue

            torrent_url = resolve_minerva_torrent_url(source, system_name, session)
            if not torrent_url:
                candidates = build_minerva_torrent_urls(source, system_name)
                probe_url = candidates[0] if candidates else 'aucune URL candidate'
                print(f"  Avertissement: torrent Minerva introuvable pour {source['name']} ({probe_url})")
                continue

            found, still_missing = match_myrient_files(still_missing, minerva_files, source['name'])
            for game in found:
                game['torrent_url'] = torrent_url
                game['source'] = source['name']
            minerva_found.extend(found)
            all_found.extend(found)

    archive_sources = [
        s for s in sources
        if s['type'] == 'archive_org'
        and s.get('enabled', True)
        and not source_is_excluded(s, excluded_sources)
    ]
    if archive_sources and still_missing:
        print(f"\n{'=' * 70}")
        print("ETAPE 5: Dernier recours archive.org")
        print(f"{'=' * 70}")
        print(f"\n--- Recherche archive.org par checksum puis nom ---")
        found, still_missing = search_archive_org_for_games(still_missing)
        archive_found.extend(found)
        all_found.extend(found)

    print(f"\n{'=' * 70}")
    print("RESUME DE LA RECHERCHE")
    print(f"{'=' * 70}")
    print(f"  Jeux trouves (DDL direct): {len(direct_found)}")
    print(f"  Jeux trouves (base locale): {len(found_in_db)}")
    print(f"  Jeux trouves (Minerva torrent): {len(minerva_found)}")
    print(f"  Jeux trouves (archive.org dernier recours): {len(archive_found)}")
    print(f"  Total trouves: {len(all_found)}")
    print(f"  Jeux non trouves: {len(still_missing)}")
    print(f"{'=' * 70}")

    return all_found, still_missing


__all__ = [
    'search_all_sources_legacy',
    'search_all_sources',
]