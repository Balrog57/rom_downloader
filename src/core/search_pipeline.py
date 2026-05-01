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
from .sources import SYSTEM_MAPPINGS, normalize_source_label, source_is_excluded, source_order_key
from .archive_org import search_archive_org_by_md5, search_archive_org_by_crc, search_archive_org_by_sha1, search_archive_org_by_name
from .minerva import (
    search_minerva_hash_database_for_games,
    search_database_for_game,
    select_ddl_result,
    select_torrent_result,
    select_archive_result,
    build_minerva_directory_url,
    collect_minerva_files_from_url,
    resolve_minerva_torrent_url,
    build_minerva_torrent_urls,
)
from .dat_profile import finalize_dat_profile, prepare_sources_for_profile, describe_dat_profile
from .scrapers import (
    get_vimm_session,
    get_lolroms_session,
    resolve_lolroms_system_path,
    list_lolroms_directory,
    _lolroms_subdir_for_system,
    iter_game_candidate_names,
    find_listing_match,
    resolve_edgeemu_game,
    list_planetemu_directory,
    resolve_vimm_game,
    resolve_retrogamesets_game,
    search_archive_org_for_games,
    list_romhustler_directory,
    resolve_romhustler_game,
    _romhustler_session as _romhustler_session_fn,
    _COOLROM_NINTENDO_SYSTEMS,
    list_coolrom_directory,
    resolve_coolrom_game,
    _coolrom_session as _coolrom_session_fn,
    resolve_nopaystation_game,
    list_startgame_directory,
    resolve_startgame_game,
    _startgame_session as _startgame_session_fn,
    resolve_hshop_game,
    _hshop_session as _hshop_session_fn,
    list_romsxisos_directory,
    resolve_romsxisos_game,
)


def _source_is_usable(source: dict) -> bool:
    """Indique si une source peut participer a la resolution courante."""
    return bool(source.get('enabled', True) and source.get('compatible', True))


def search_all_sources_legacy(missing_games: list, sources: list, session: requests.Session, system_name: str = None) -> tuple:
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
    prefer_1fichier = any(
        _source_is_usable(source)
        and source.get('type') in {'retrogamesets', 'startgame'}
        and int(source.get('order', 99)) <= 11
        for source in sources
    )
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
                elif 'minerva' in host and not best_result:
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
        for source in sorted(sources, key=source_order_key):
            if not _source_is_usable(source):
                continue
            if source['type'] == 'edgeemu':
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

            elif source['type'] == 'planetemu':
                slug = mappings.get('planetemu')
                if slug:
                    print(f"\n--- Recherche sur PlanetEmu ({slug}) ---")
                    planet_files = list_planetemu_directory(slug, session)
                    if planet_files:
                        newly_found = []
                        remaining = []
                        for game_info in still_missing:
                            _matched_name, entry = find_listing_match(game_info, planet_files)
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

            elif source['type'] == 'vimm':
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

            elif source['type'] == 'retrogamesets':
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

    minerva_sources = [s for s in sources if s['type'] == 'minerva' and s.get('enabled', True)]

    if minerva_sources and still_missing:
        for source in minerva_sources:
            print(f"\n--- Recherche directe sur {source['name']} ---")

            base_url = build_minerva_directory_url(source, system_name)
            minerva_files = collect_minerva_files_from_url(base_url, session, source.get('scan_depth', 0))

            if minerva_files:
                torrent_url = resolve_minerva_torrent_url(source, system_name, session)
                if not torrent_url:
                    candidates = build_minerva_torrent_urls(source, system_name)
                    probe_url = candidates[0] if candidates else 'aucune URL candidate'
                    print(f"  Avertissement: torrent Minerva introuvable pour {source['name']} ({probe_url})")
                    continue

                newly_found = []
                remaining = []
                for game_info in still_missing:
                    _matched_name, matched = find_listing_match(game_info, minerva_files)
                    if matched:
                        game_info['download_filename'] = matched.get('filename', f"{game_info['game_name']}.zip")
                        game_info['torrent_url'] = torrent_url
                        game_info['source'] = source['name']
                        newly_found.append(game_info)
                        detail = f" -> {matched.get('filename')}" if matched.get('filename') else ''
                        print(f"  [{source['name']}] {game_info['game_name']} trouve{detail}")
                    else:
                        remaining.append(game_info)
                all_found.extend(newly_found)
                still_missing = remaining

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
    Recherche des jeux manquants selon le pipeline prioritaire:
    1. Base locale (liens DDL uniquement -- 1fichier, autres hebergeurs directs)
    2. Sources DDL live (EdgeEmu, PlanetEmu, LoLROMs, Vimm, RetroGameSets)
    3. Torrent Minerva (base locale torrent + browse Minerva)
    4. archive.org (dernier recours)
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
    prefer_1fichier = any(
        _source_is_usable(source)
        and source.get('type') in {'retrogamesets', 'startgame'}
        and int(source.get('order', 99)) <= 11
        for source in sources
    )
    sources = prepare_sources_for_profile(
        [source.copy() for source in (sources or [])],
        dat_profile,
        prefer_1fichier=prefer_1fichier
    )

    all_found = []
    still_missing = missing_games.copy()
    ddl_found = []
    db_ddl_found = []
    db_torrent_found = []
    minerva_found = []
    archive_found = []

    mappings = SYSTEM_MAPPINGS.get(system_name, {}) if system_name else {}
    prefer_1fichier = any(
        _source_is_usable(source)
        and source.get('type') in {'retrogamesets', 'startgame'}
        and int(source.get('order', 99)) <= 11
        for source in sources
    )

    # ── ETAPE 1: Base locale (liens DDL uniquement) ──

    print(f"\n{'=' * 70}")
    print("ETAPE 1: Base locale (liens DDL directs)")
    print(f"{'=' * 70}")

    not_in_db = []
    if 'database' in excluded_sources:
        not_in_db = still_missing
        print("  [DB] ignoree pour ce retry")
    else:
        ddl_results_for_games = []
        torrent_pending = []
        archive_pending = []
        for game_info in still_missing:
            game_name = game_info['game_name']
            db_results, search_hint = search_database_for_game(game_info)

            if db_results:
                ddl_result = select_ddl_result(db_results, prefer_1fichier=prefer_1fichier)
                if ddl_result:
                    game_info['download_filename'] = database_result_filename(ddl_result, game_name)
                    game_info['download_url'] = ddl_result.get('url')
                    game_info['source'] = 'database'
                    game_info['database_host'] = ddl_result.get('host')
                    if '1fichier.com' in (ddl_result.get('url') or ''):
                        game_info['source'] = 'database (1fichier)'
                    db_ddl_found.append(game_info)
                    print(f"  [DB DDL] {game_name} -> {ddl_result.get('host')}{f' ({search_hint})' if search_hint else ''}")
                else:
                    torrent_result = select_torrent_result(db_results)
                    if torrent_result:
                        torrent_pending.append((game_info, torrent_result, search_hint))
                        not_in_db.append(game_info)
                    else:
                        archive_result = select_archive_result(db_results)
                        if archive_result:
                            archive_pending.append((game_info, archive_result, search_hint))
                            not_in_db.append(game_info)
                        else:
                            not_in_db.append(game_info)
            else:
                not_in_db.append(game_info)

    all_found.extend(db_ddl_found)
    remaining_after_ddl_db = not_in_db
    print(f"\n  Trouve en base (DDL): {len(db_ddl_found)} jeux")
    print(f"  Restants: {len(remaining_after_ddl_db)} jeux")

    still_missing = remaining_after_ddl_db

    # ── ETAPE 2: Sources DDL live ──

    print(f"\n{'=' * 70}")
    print("ETAPE 2: Recherche DDL directe (scrapers live)")
    print(f"{'=' * 70}")

    if still_missing and system_name:
        for source in sorted(sources, key=source_order_key):
            if not still_missing:
                break
            if source_is_excluded(source, excluded_sources):
                continue
            if not _source_is_usable(source):
                continue

            if source['type'] == 'edgeemu':
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
                    ddl_found.extend(newly_found)
                    still_missing = remaining

            elif source['type'] == 'planetemu':
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
                            _matched_name, entry = find_listing_match(game_info, planet_files)
                            if entry and isinstance(entry, dict):
                                game_info['page_url'] = entry.get('page_url', '')
                                game_info['source'] = 'PlanetEmu'
                                game_info['download_filename'] = f"{game_info['game_name']}.zip"
                                newly_found.append(game_info)
                                print(f"  [PlanetEmu] {game_info['game_name']} trouve")
                            else:
                                remaining.append(game_info)
                        all_found.extend(newly_found)
                        ddl_found.extend(newly_found)
                        still_missing = remaining

            elif source['type'] == 'lolroms':
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
                if lolroms_paths and still_missing:
                    lolroms_files = None
                    for lolroms_path in lolroms_paths:
                        if not still_missing:
                            break
                        print(f"\n--- Recherche sur LoLROMs ({lolroms_path}) ---")
                        listing_key = f"listing:lolroms:{lolroms_path}"
                        session_cache = get_session_cache()
                        path_files = session_cache.get_listing(listing_key)
                        if path_files is None:
                            path_files = list_lolroms_directory(lolroms_path, include_subdirs=True)
                            session_cache.set_listing(listing_key, path_files)
                        if path_files:
                            lolroms_files = path_files
                    if lolroms_files and still_missing:
                        newly_found = []
                        remaining = []
                        for game_info in still_missing:
                            _matched_name, matched = find_listing_match(game_info, lolroms_files)

                            if matched and isinstance(matched, dict):
                                game_info['download_url'] = matched.get('url', '')
                                game_info['source'] = 'LoLROMs'
                                game_info['download_filename'] = matched.get('filename', f"{game_info['game_name']}.zip")
                                newly_found.append(game_info)
                                detail = f" -> {matched.get('filename')}" if matched.get('filename') else ''
                                print(f"  [LoLROMs] {game_info['game_name']} trouve{detail}")
                            else:
                                remaining.append(game_info)

                        all_found.extend(newly_found)
                        ddl_found.extend(newly_found)
                        still_missing = remaining

            elif source['type'] == 'vimm':
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
                    ddl_found.extend(newly_found)
                    still_missing = remaining

            elif source['type'] == 'retrogamesets':
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
                    ddl_found.extend(newly_found)
                    still_missing = remaining

            elif source['type'] == 'romhustler':
                slug = mappings.get('romhustler')
                if slug and still_missing:
                    print(f"\n--- Recherche sur RomHustler ({slug}) ---")
                    rh_session = _romhustler_session_fn()
                    def _rh_fields(merged, result):
                        merged['download_url'] = result.get('url', '')
                        merged['page_url'] = result.get('page_url', '')
                        merged['download_filename'] = result.get('filename', f"{merged['game_name']}.zip")
                    newly_found, remaining = _resolve_games_parallel(
                        still_missing,
                        lambda gi: resolve_romhustler_game(gi, slug, rh_session),
                        "resolve:romhustler",
                        "RomHustler",
                        system_name,
                        extra_fields_fn=_rh_fields,
                    )
                    all_found.extend(newly_found)
                    ddl_found.extend(newly_found)
                    still_missing = remaining

            elif source['type'] == 'coolrom':
                slug = mappings.get('coolrom')
                if slug and slug not in _COOLROM_NINTENDO_SYSTEMS and still_missing:
                    print(f"\n--- Recherche sur CoolROM ({slug}) ---")
                    cr_session = _coolrom_session_fn()
                    def _cr_fields(merged, result):
                        merged['page_url'] = result.get('page_url', '')
                        merged['download_url'] = result.get('url', '')
                        merged['download_filename'] = result.get('filename', f"{merged['game_name']}.zip")
                        merged['game_id'] = result.get('game_id', '')
                    newly_found, remaining = _resolve_games_parallel(
                        still_missing,
                        lambda gi: resolve_coolrom_game(gi, slug, cr_session),
                        "resolve:coolrom",
                        "CoolROM",
                        system_name,
                        extra_fields_fn=_cr_fields,
                    )
                    all_found.extend(newly_found)
                    ddl_found.extend(newly_found)
                    still_missing = remaining

            elif source['type'] == 'nopaystation':
                tsv_name = mappings.get('nopaystation')
                if tsv_name and still_missing:
                    print(f"\n--- Recherche sur NoPayStation ({tsv_name}) ---")
                    def _nps_fields(merged, result):
                        merged['download_url'] = result['url']
                        merged['download_filename'] = result.get('filename', f"{merged['game_name']}.pkg")
                    newly_found, remaining = _resolve_games_parallel(
                        still_missing,
                        lambda gi: resolve_nopaystation_game(gi, tsv_name, session),
                        "resolve:nopaystation",
                        "NoPayStation",
                        system_name,
                        extra_fields_fn=_nps_fields,
                    )
                    all_found.extend(newly_found)
                    ddl_found.extend(newly_found)
                    still_missing = remaining

            elif source['type'] == 'startgame':
                slug = mappings.get('startgame')
                if slug and still_missing:
                    print(f"\n--- Recherche sur StartGame ({slug}) ---")
                    sg_session = _startgame_session_fn()
                    def _sg_fields(merged, result):
                        merged['download_url'] = result.get('url', '')
                        merged['download_filename'] = result.get('filename', f"{merged['game_name']}.zip")
                    newly_found, remaining = _resolve_games_parallel(
                        still_missing,
                        lambda gi: resolve_startgame_game(gi, slug, sg_session),
                        "resolve:startgame",
                        "StartGame",
                        system_name,
                        extra_fields_fn=_sg_fields,
                    )
                    all_found.extend(newly_found)
                    ddl_found.extend(newly_found)
                    still_missing = remaining

            elif source['type'] == 'hshop':
                category = mappings.get('hshop')
                if category and still_missing:
                    print(f"\n--- Recherche sur hShop ({category}) ---")
                    hs_session = _hshop_session_fn()
                    def _hs_fields(merged, result):
                        merged['page_url'] = result.get('page_url', '')
                        merged['download_filename'] = result.get('filename', f"{merged['game_name']}.cia")
                    newly_found, remaining = _resolve_games_parallel(
                        still_missing,
                        lambda gi: resolve_hshop_game(gi, category, hs_session),
                        "resolve:hshop",
                        "hShop",
                        system_name,
                        extra_fields_fn=_hs_fields,
                    )
                    all_found.extend(newly_found)
                    ddl_found.extend(newly_found)
                    still_missing = remaining

            elif source['type'] == 'romsxisos':
                slug = mappings.get('romsxisos')
                if slug and still_missing:
                    print(f"\n--- Recherche sur RomsXISOs ({slug}) ---")
                    rx_session = requests.Session()
                    rx_session.headers.update({
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    })
                    def _rx_fields(merged, result):
                        merged['download_url'] = result.get('url', '')
                        merged['download_filename'] = result.get('filename', f"{merged['game_name']}.zip")
                        merged['is_gdrive'] = result.get('is_gdrive', False)
                    newly_found, remaining = _resolve_games_parallel(
                        still_missing,
                        lambda gi: resolve_romsxisos_game(gi, slug, rx_session),
                        "resolve:romsxisos",
                        "RomsXISOs",
                        system_name,
                        extra_fields_fn=_rx_fields,
                    )
                    all_found.extend(newly_found)
                    ddl_found.extend(newly_found)
                    still_missing = remaining

    print(f"\n  Trouve via DDL direct: {len(ddl_found)} jeux")
    print(f"  Restants apres DDL: {len(still_missing)} jeux")

    # ── ETAPE 3: Minerva torrent (base locale torrent + browse) ──

    minerva_sources = [
        s for s in sources
        if s.get('enabled', True)
        and s.get('compatible', True)
        and not source_is_excluded(s, excluded_sources)
        and s['type'] == 'minerva'
    ]

    if minerva_sources and still_missing:
        print(f"\n{'=' * 70}")
        print("ETAPE 3: Minerva via torrent")
        print(f"{'=' * 70}")

        # 3a: Resultats torrent deja trouves en base locale
        if torrent_pending:
            remaining_ids = {id(game_info) for game_info in still_missing}
            for game_info, torrent_result, search_hint in torrent_pending:
                if id(game_info) not in remaining_ids:
                    continue
                game_info['download_filename'] = database_result_filename(torrent_result, game_info['game_name'])
                game_info['download_url'] = torrent_result.get('url')
                game_info['source'] = 'Minerva Official Hashes'
                game_info['database_host'] = 'minerva-torrent'
                if torrent_result.get('torrent_url'):
                    game_info['torrent_url'] = torrent_result['torrent_url']
                if torrent_result.get('torrent_path') or torrent_result.get('full_path'):
                    game_info['torrent_target_filename'] = torrent_result.get('full_path') or torrent_result.get('file_name') or game_info['game_name']
                if torrent_result.get('full_path'):
                    game_info['minerva_full_path'] = torrent_result['full_path']
                db_torrent_found.append(game_info)
                hint = f' ({search_hint})' if search_hint else ''
                print(f"  [DB torrent] {game_info['game_name']} -> minerva-torrent{hint}")
            if db_torrent_found:
                all_found.extend(db_torrent_found)
            print(f"\n  Trouve en base (torrent Minerva): {len(db_torrent_found)} jeux")

        # 3b: Recherche MD5 DAT dans la base Minerva
        db_torrent_ids = {id(game_info) for game_info in db_torrent_found}
        still_missing = [g for g in still_missing if id(g) not in db_torrent_ids]
        if still_missing:
            print("\n--- Recherche Minerva officielle par MD5 DAT ---")
            found, still_missing = search_minerva_hash_database_for_games(still_missing)
            minerva_found.extend(found)
            all_found.extend(found)

        # 3c: Browse Minerva par dossier
        for source in minerva_sources:
            if not still_missing:
                break
            print(f"\n--- Recherche torrent sur {source['name']} ---")
            base_url = build_minerva_directory_url(source, system_name)
            listing_key = f"listing:minerva:{base_url}"
            session_cache = get_session_cache()
            minerva_files = session_cache.get_listing(listing_key)

            # Pre-fetch async si aiohttp dispo
            if _AIOHTTP_AVAILABLE and minerva_files is None:
                prefetch_urls = [base_url]
                try:
                    import asyncio
                    asyncio.run(async_fetch_listings_parallel(prefetch_urls, timeout=30))
                    minerva_files = session_cache.get_listing(listing_key)
                except Exception:
                    pass

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

            newly_found = []
            remaining = []
            for game_info in still_missing:
                _matched_name, matched = find_listing_match(game_info, minerva_files)
                if matched:
                    game_info['download_filename'] = matched.get('filename', f"{game_info['game_name']}.zip")
                    game_info['torrent_url'] = torrent_url
                    game_info['source'] = source['name']
                    newly_found.append(game_info)
                    detail = f" -> {matched.get('filename')}" if matched.get('filename') else ''
                    print(f"  [{source['name']}] {game_info['game_name']} trouve{detail}")
                else:
                    remaining.append(game_info)
            minerva_found.extend(newly_found)
            all_found.extend(newly_found)
            still_missing = remaining

        if not minerva_found and still_missing:
            print("  Aucun jeu trouve via Minerva (listing vide ou introuvable)")

        print(f"\n  Trouve via Minerva (torrent): {len(minerva_found)} jeux")
        print(f"  Restants apres Minerva: {len(still_missing)} jeux")

    # ── ETAPE 4: archive.org (dernier recours) ──

    archive_sources = [
        s for s in sources
        if s['type'] == 'archive_org'
        and s.get('enabled', True)
        and not source_is_excluded(s, excluded_sources)
    ]
    if archive_sources and still_missing:
        print(f"\n{'=' * 70}")
        print("ETAPE 4: Dernier recours archive.org")
        print(f"{'=' * 70}")

        # 4a: Resultats archive.org deja trouves en base locale
        if archive_pending:
            remaining_ids = {id(game_info) for game_info in still_missing}
            for game_info, archive_result, search_hint in archive_pending:
                if id(game_info) not in remaining_ids:
                    continue
                game_info['download_filename'] = database_result_filename(archive_result, game_info['game_name'])
                game_info['download_url'] = archive_result.get('url')
                game_info['source'] = 'database'
                game_info['database_host'] = archive_result.get('host', 'archive.org')
                archive_found.append(game_info)
                hint = f' ({search_hint})' if search_hint else ''
                print(f"  [DB archive.org] {game_info['game_name']} -> archive.org{hint}")
            if archive_found:
                all_found.extend(archive_found)

        # 4b: Recherche live sur archive.org
        archive_ids = {id(game_info) for game_info in archive_found}
        remaining_for_archive = [g for g in still_missing if id(g) not in archive_ids]
        if remaining_for_archive:
            print(f"\n--- Recherche archive.org par checksum puis nom ---")
            found, still_missing = search_archive_org_for_games(remaining_for_archive)
            archive_found.extend(found)
            all_found.extend(found)
        else:
            still_missing = remaining_for_archive

    print(f"\n{'=' * 70}")
    print("RESUME DE LA RECHERCHE")
    print(f"{'=' * 70}")
    print(f"  Etape 1 - Base locale (DDL): {len(db_ddl_found)} jeux")
    print(f"  Etape 2 - DDL direct: {len(ddl_found)} jeux")
    print(f"  Etape 3 - Minerva torrent: {len(db_torrent_found) + len(minerva_found)} jeux")
    print(f"  Etape 4 - archive.org: {len(archive_found)} jeux")
    print(f"  Total trouves: {len(all_found)}")
    print(f"  Jeux non trouves: {len(still_missing)}")
    print(f"{'=' * 70}")

    return all_found, still_missing


__all__ = [
    'search_all_sources_legacy',
    'search_all_sources',
]
