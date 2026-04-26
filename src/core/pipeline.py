import os
import time
from urllib.parse import quote

import requests

from ..pipeline import build_pipeline_summary, merge_provider_metrics
from ..network.sessions import create_optimized_session
from ..network.circuits import SourceCircuitBreaker
from ..network.metrics import load_provider_metrics, save_provider_metrics, prioritize_sources

from .env import *
from .constants import *
from .dependencies import *
from .dat_parser import parse_dat_file, strip_rom_extension
from .scanner import (
    scan_local_roms,
    find_missing_games,
    detect_system_name,
    find_roms_not_in_dat,
    move_files_to_tosort,
    build_analysis_summary,
    print_analysis_summary,
)
from .dat_profile import detect_dat_profile, finalize_dat_profile, prepare_sources_for_profile, describe_dat_profile
from .sources import get_default_sources, build_custom_source, normalize_source_label
from .reports import write_download_report
from .torrentzip import repack_verified_archives_to_torrentzip
from .download_orchestrator import (
    download_missing_games_sequentially,
    download_with_provider_retries,
    file_exists_in_folder,
    verify_downloaded_md5,
    cleanup_invalid_download,
    attempt_download_from_resolved_provider,
)
from .scrapers import (
    download_planetemu,
    download_cdromance,
    download_vimm,
    get_lolroms_session,
    get_cdromance_session,
    get_vimm_session,
)
from .search_pipeline import search_all_sources, search_all_sources_legacy
from .downloads import download_file, download_file_legacy, download_from_archive_org
from .premium_downloads import download_from_premium_source
from .api_keys import load_api_keys
from .torrent import download_from_minerva_torrent
from .search_pipeline import search_all_sources


def _extract_session_metrics(result: dict) -> dict:
    """Extract provider metrics from download result for persistence."""
    if not result:
        return {}
    metrics = {}
    for item in result.get('resolved_items', []) + result.get('failed_items', []):
        source = item.get('source', 'unknown')
        if source not in metrics:
            metrics[source] = {'attempts': 0, 'downloaded': 0, 'failed': 0, 'dry_run': 0}
        metrics[source]['attempts'] = metrics[source]['attempts'] + 1
    for item in result.get('downloaded_items', []):
        source = item.get('source', 'unknown')
        if source in metrics:
            metrics[source]['downloaded'] = metrics[source].get('downloaded', 0) + 1
    for item in result.get('failed_items', []):
        source = item.get('source', 'unknown')
        if source in metrics:
            metrics[source]['failed'] = metrics[source].get('failed', 0) + 1
    return metrics


def run_download_legacy(dat_file, rom_folder, myrient_url, output_folder, dry_run, limit, move_to_tosort=False, custom_sources=None):
    """Run the download process."""
    from . import _facade
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })

    dat_games = parse_dat_file(dat_file)

    local_roms, local_roms_normalized, local_game_names, signature_index = scan_local_roms(rom_folder, dat_games)

    missing_games = find_missing_games(dat_games, local_roms, local_roms_normalized, local_game_names, signature_index)

    dat_profile = _facade.dat_profile
    system_name = dat_profile.get('system_name') or detect_system_name(dat_file)
    print(f"Systeme detecte : {system_name}")

    print(f"DAT detecte : {describe_dat_profile(dat_profile)}")

    sources = [source.copy() for source in (custom_sources if custom_sources else get_default_sources())]
    if myrient_url and myrient_url not in [s['base_url'] for s in sources]:
        sources.insert(0, build_custom_source(myrient_url))
    sources = prepare_sources_for_profile(sources, dat_profile)
    report_active_sources = [source['name'] for source in sources if source.get('enabled', True)]
    print_analysis_summary(build_analysis_summary(dat_file, rom_folder, dat_games, missing_games, dat_profile, sources))

    if not missing_games:
        print("\nAucun jeu manquant trouve !")
    else:
        sources = custom_sources if custom_sources else get_default_sources().copy()
        
        if myrient_url and myrient_url not in [s['base_url'] for s in sources]:
            sources.insert(0, build_custom_source(myrient_url))
        
        to_download, not_available = search_all_sources(missing_games, sources, session, system_name)

        if not_available:
            print("\n" + "=" * 60)
            print("Jeux NON trouves sur aucune source:")
            print("=" * 60)
            for game_info in not_available:
                print(f"  - {game_info['game_name']}")
            print()

        if to_download:
            print(f"\n{'Telechargement' if not dry_run else 'Simulation'} de {len(to_download)} jeu(x)...")

            downloaded = 0
            failed = 0
            skipped = 0

            for i, game_info in enumerate(to_download, 1):
                game_name = game_info['game_name']
                source = game_info.get('source', 'unknown')
                filename = game_info.get('download_filename', game_name)

                print(f"\n[{i}/{len(to_download)}] {game_name} [{source}]")

                if limit and downloaded >= limit:
                    print("  Ignore (limite atteinte)")
                    skipped += 1
                    continue

                exists, existing_path = file_exists_in_folder(output_folder, filename)
                if exists:
                    print(f"  Deja present: {os.path.basename(existing_path)}")
                    skipped += 1
                    continue

                if dry_run:
                    print(f"  Serait telecharge vers: {output_folder}")
                    continue

                dest_path = os.path.join(output_folder, filename)
                success = False
                
                download_url = game_info.get('download_url')
                torrent_url = game_info.get('torrent_url')
                
                if source == 'archive_org':
                    identifier = game_info.get('archive_org_identifier', '')
                    if identifier and filename:
                        success = download_from_archive_org(identifier, filename, dest_path)

                elif source == 'EdgeEmu':
                    success = download_file(download_url, dest_path, session)

                elif source == 'PlanetEmu':
                    page_url = game_info.get('page_url')
                    if page_url:
                        success = download_planetemu(page_url, dest_path, session)

                elif source == 'LoLROMs' and download_url:
                    success = download_file(download_url, dest_path, get_lolroms_session())

                elif source == 'CDRomance':
                    page_url = game_info.get('page_url')
                    if page_url:
                        success = download_cdromance(page_url, dest_path, get_cdromance_session())

                elif source == 'Vimm\'s Lair':
                    page_url = game_info.get('page_url')
                    if page_url:
                        success = download_vimm(page_url, dest_path, get_vimm_session())

                elif source == 'RetroGameSets' and download_url:
                    api_keys = load_api_keys()
                    success = download_from_premium_source('1fichier', download_url, dest_path, api_keys)

                elif source.startswith('Minerva') and torrent_url:
                    print(f"  Torrent: {torrent_url[:80]}...")
                    success = download_from_minerva_torrent(torrent_url, filename, dest_path)

                elif source in ['myrient', 'Myrient', 'Myrient No-Intro', 'Myrient Redump', 'Myrient TOSEC', 'Myrient Custom'] and download_url:
                    print(f"  URL: {download_url[:80]}...")
                    success = download_file(download_url, dest_path, session)

                elif source == 'database' and download_url:
                    print(f"  URL: {download_url[:80]}...")

                    if '1fichier.com' in download_url:
                        api_keys = load_api_keys()
                        success = download_from_premium_source('1fichier', download_url, dest_path, api_keys)
                    elif 'archive.org' in download_url:
                        success = download_file(download_url, dest_path, session)
                    elif 'myrient' in download_url:
                        success = download_file(download_url, dest_path, session)
                    else:
                        success = download_file(download_url, dest_path, session)

                else:
                    source_info = next((s for s in sources if s['name'] == source), None)
                    base_url = source_info['base_url'] if source_info else myrient_url
                    download_url = f"{base_url.rstrip('/')}/{quote(filename)}"
                    print(f"  URL: {download_url[:80]}...")
                    success = download_file(download_url, dest_path, session)

                if success:
                    print(f"  Telecharge: {filename}")
                    downloaded += 1
                    time.sleep(0.5)
                else:
                    failed += 1

            print("\n" + "=" * 60)
            print("Resume:")
            print(f"  Telecharges: {downloaded}")
            print(f"  Echecs: {failed}")
            print(f"  Ignores: {skipped}")
            if dry_run:
                print("\n(Simulation - aucun fichier telecharge)")

    if move_to_tosort and missing_games:
        print("\n" + "=" * 60)
        print("Recherche des fichiers a deplacer vers ToSort...")
        print("=" * 60)
        
        tosort_folder = os.path.join(rom_folder, "ToSort")
        
        files_to_move = find_roms_not_in_dat(dat_games, local_roms, local_roms_normalized, rom_folder)
        
        if files_to_move:
            print(f"\n{len(files_to_move)} fichiers a deplacer vers: {tosort_folder}")
            moved, failed = move_files_to_tosort(files_to_move, rom_folder, tosort_folder, dry_run)
            print(f"\nResume ToSort:")
            print(f"  Deplaces: {moved}")
            print(f"  Echecs: {failed}")
        else:
            print("\nAucun fichier a deplacer.")


def run_download(dat_file, rom_folder, myrient_url, output_folder, dry_run, limit,
                 move_to_tosort=False, clean_torrentzip=False, custom_sources=None,
                 parallel_downloads: int | None = None, refresh_resolution_cache: bool = False):
    """Run the download process with archive.org as the final fallback."""
    from . import _facade
    if refresh_resolution_cache:
        _facade.clear_resolution_cache()
        _facade.clear_listing_cache()

    session = create_optimized_session()
    circuit_breaker = SourceCircuitBreaker()
    session_metrics = load_provider_metrics()

    dat_games = parse_dat_file(dat_file)
    local_roms, local_roms_normalized, local_game_names, signature_index = scan_local_roms(rom_folder, dat_games)
    missing_games = find_missing_games(dat_games, local_roms, local_roms_normalized, local_game_names, signature_index)
    dat_profile = finalize_dat_profile(detect_dat_profile(dat_file))
    report_active_sources = []
    to_download = []
    not_available = []
    downloaded_items = []
    failed_items = []
    skipped_items = []
    tosort_moved = 0
    tosort_failed = 0
    torrentzip_summary = {'repacked': 0, 'skipped': 0, 'failed': 0, 'deleted': 0}
    sources = [source.copy() for source in (custom_sources if custom_sources else get_default_sources())]
    if myrient_url and myrient_url not in [s['base_url'] for s in sources]:
        sources.insert(0, build_custom_source(myrient_url))
    sources = prepare_sources_for_profile(sources, dat_profile)
    report_active_sources = [source['name'] for source in sources if source.get('enabled', True)]
    print_analysis_summary(build_analysis_summary(dat_file, rom_folder, dat_games, missing_games, dat_profile, sources))

    system_name = dat_profile.get('system_name') or detect_system_name(dat_file)
    print(f"Systeme detecte : {system_name}")

    if not missing_games:
        print("\nAucun jeu manquant trouve !")
    else:
        sources = [source.copy() for source in (custom_sources if custom_sources else get_default_sources())]

        if myrient_url and myrient_url not in [s['base_url'] for s in sources]:
            sources.insert(0, build_custom_source(myrient_url))

        sources = prepare_sources_for_profile(sources, dat_profile)
        sources = prioritize_sources(sources, session_metrics)
        report_active_sources = [source['name'] for source in sources if source.get('enabled', True)]

        if parallel_downloads is None:
            parallel_downloads = int(os.environ.get('ROM_DOWNLOADER_PARALLEL_DOWNLOADS', DEFAULT_PARALLEL_DOWNLOADS))

        result = download_missing_games_sequentially(
            missing_games,
            sources,
            session,
            system_name,
            dat_profile,
            output_folder,
            myrient_url,
            dry_run,
            limit,
            None,
            print,
            parallel_downloads=parallel_downloads,
            circuit_breaker=circuit_breaker,
        )
        to_download = result['resolved_items']
        not_available = result['not_available']
        downloaded_items = result['downloaded_items']
        failed_items = result['failed_items']
        skipped_items = result['skipped_items']

        if not_available:
            print("\n" + "=" * 60)
            print("Jeux NON trouves sur aucune source:")
            print("=" * 60)
            for game_info in not_available:
                print(f"  - {game_info['game_name']}")
            print()

        if False and to_download:
            print(f"\n{'Telechargement' if not dry_run else 'Simulation'} de {len(to_download)} jeu(x)...")

            downloaded = 0
            failed = 0
            skipped = 0

            for i, game_info in enumerate(to_download, 1):
                game_name = game_info['game_name']
                source = game_info.get('source', 'unknown')
                filename = game_info.get('download_filename', game_name)

                print(f"\n[{i}/{len(to_download)}] {game_name} [{source}]")

                if limit and downloaded >= limit:
                    print("  Ignore (limite atteinte)")
                    skipped += 1
                    skipped_items.append(game_info.copy())
                    continue

                status, result_item = download_with_provider_retries(
                    game_info,
                    sources,
                    session,
                    system_name,
                    dat_profile,
                    output_folder,
                    myrient_url,
                    dry_run,
                    None,
                    print
                )

                if status == 'downloaded':
                    print(f"  Telecharge: {result_item.get('download_filename', game_name)}")
                    downloaded += 1
                    downloaded_items.append(result_item.copy())
                    time.sleep(0.5)
                elif status == 'skipped':
                    skipped += 1
                    skipped_items.append(result_item.copy())
                elif status == 'dry_run':
                    pass
                else:
                    failed += 1
                    failed_items.append(result_item.copy())
                continue

            print("\n" + "=" * 60)
            print("Resume:")
            print(f"  Telecharges: {downloaded}")
            print(f"  Echecs: {failed}")
            print(f"  Ignores: {skipped}")
            if dry_run:
                print("\n(Simulation - aucun fichier telecharge)")

    if missing_games:
        print("\n" + "=" * 60)
        print("Resume:")
        print(f"  Telecharges: {result['downloaded']}")
        print(f"  Echecs: {result['failed']}")
        print(f"  Ignores: {result['skipped']}")
        print(f"  Non trouves: {len(not_available)}")
        if dry_run:
            print("\n(Simulation - aucun fichier telecharge)")

    if move_to_tosort:
        print("\n" + "=" * 60)
        print("Recherche des fichiers a deplacer vers ToSort...")
        print("=" * 60)

        tosort_folder = os.path.join(rom_folder, "ToSort")

        files_to_move = find_roms_not_in_dat(dat_games, local_roms, local_roms_normalized, rom_folder)

        if files_to_move:
            print(f"\n{len(files_to_move)} fichiers a deplacer vers: {tosort_folder}")
            moved, failed = move_files_to_tosort(files_to_move, rom_folder, tosort_folder, dry_run)
            tosort_moved = moved
            tosort_failed = failed
            print("\nResume ToSort:")
            print(f"  Deplaces: {moved}")
            print(f"  Echecs: {failed}")
        else:
            print("\nAucun fichier a deplacer.")

    if clean_torrentzip:
        print("\n" + "=" * 60)
        print("Nettoyage des archives validees en ZIP TorrentZip/RomVault...")
        print("=" * 60)
        torrentzip_summary = repack_verified_archives_to_torrentzip(
            dat_games,
            output_folder,
            dry_run,
            print
        )

    session_metrics = save_provider_metrics(merge_provider_metrics(load_provider_metrics(), _extract_session_metrics(result)))

    report_path = write_download_report(output_folder, {
        'dat_file': dat_file,
        'system_name': system_name,
        'dat_profile': describe_dat_profile(dat_profile),
        'output_folder': output_folder,
        'source_url': myrient_url,
        'active_sources': report_active_sources,
        'total_dat_games': len(dat_games),
        'missing_before': len(missing_games),
        'resolved_items': to_download,
        'downloaded_items': downloaded_items,
        'failed_items': failed_items,
        'skipped_items': skipped_items,
        'not_available': not_available,
        'tosort_moved': tosort_moved,
        'tosort_failed': tosort_failed,
        'torrentzip_repacked': torrentzip_summary.get('repacked', 0),
        'torrentzip_skipped': torrentzip_summary.get('skipped', 0),
        'torrentzip_deleted': torrentzip_summary.get('deleted', 0),
        'torrentzip_failed': torrentzip_summary.get('failed', 0),
    })
    return report_path


__all__ = [
    'run_download',
    '_extract_session_metrics',
    'run_download_legacy',
]