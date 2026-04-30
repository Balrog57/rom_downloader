import os
import threading
import time
import concurrent.futures
from urllib.parse import quote

from ..network.sessions import create_optimized_session
from ..network.circuits import SourceCircuitBreaker
from ..network.cache_runtime import get_session_cache, clear_session_cache, RuntimeCache
from ..network.downloads import ParallelDownloadPool
from ..network.metrics import load_provider_metrics, save_provider_metrics, prioritize_sources, record_provider_attempt
from ..network.exceptions import ChecksumMismatchError, SourceTimeoutError, DownloadNetworkError
from ..progress import DownloadProgressMeter, format_duration

from .env import *
from .constants import *
from .dependencies import *
from .sources import (
    normalize_source_label,
    find_source_config,
    source_timeout_seconds,
    source_delay_seconds,
    source_policy_summary,
    reserve_source_quota,
    resolve_game_sources_with_cache,
    source_order_key,
)
from .dat_profile import finalize_dat_profile, prepare_sources_for_profile, describe_dat_profile
from .search_pipeline import search_all_sources
from .scrapers import (
    download_lolroms_file,
    get_vimm_session,
)
from .downloads import download_file, download_from_archive_org
from .premium_downloads import download_from_premium_source
from .api_keys import load_api_keys, is_1fichier_url
from .torrent import download_from_minerva_torrent
from .archive_org import download_from_archive_org as _archive_org_download
from .verification import (
    file_exists_in_folder,
    snapshot_folder_files,
    resolve_downloaded_file_path,
    verify_downloaded_md5,
    cleanup_invalid_download,
    cleanup_failed_download_outputs,
    clean_download_resolution,
)
from .interactive import create_download_session


def resolve_next_provider(game_info: dict, sources: list, session, system_name: str,
                          dat_profile: dict | None, attempted_sources: list[str]) -> dict | None:
    """Retrouve un provider alternatif pour le meme jeu en excluant ceux deja testes."""
    retry_game = clean_download_resolution(game_info)
    found, _not_available = search_all_sources(
        [retry_game],
        sources,
        session,
        system_name,
        dat_profile,
        excluded_sources={normalize_source_label(source) for source in attempted_sources}
    )
    return found[0] if found else None


def attempt_download_from_resolved_provider(game_info: dict, output_folder: str, sources: list,
                                            session, myrient_url: str = '',
                                            progress_callback=None, log_func=print,
                                            progress_detail_callback=None) -> tuple[bool, str]:
    """Telecharge une resolution provider deja choisie, puis valide son MD5 DAT."""
    source = game_info.get('source', 'unknown')
    filename = game_info.get('download_filename', game_info.get('game_name', ''))
    dest_path = os.path.join(output_folder, filename)
    download_url = game_info.get('download_url')
    torrent_url = game_info.get('torrent_url')
    before_download = snapshot_folder_files(output_folder)
    success = False
    source_config = find_source_config(sources, source)
    download_timeout = source_timeout_seconds(source_config, 120)

    _delay = source_delay_seconds(source_config, 0.0)
    if _delay and not torrent_url:
        log_func(f"  Delai {_delay:.1f}s avant telechargement ({source})...")
        time.sleep(_delay)

    if source == 'archive_org':
        identifier = game_info.get('archive_org_identifier', '')
        if identifier and filename:
            success = download_from_archive_org(identifier, filename, dest_path, progress_callback)

    elif source == 'EdgeEmu' and download_url:
        success = download_file(download_url, dest_path, session, progress_callback, download_timeout, progress_detail_callback)

    elif source == 'PlanetEmu':
        from .scrapers import download_planetemu
        page_url = game_info.get('page_url')
        if page_url:
            success = download_planetemu(page_url, dest_path, session, progress_callback)

    elif source == 'LoLROMs' and download_url:
        success = download_lolroms_file(download_url, dest_path, progress_callback, download_timeout, progress_detail_callback)

    elif source == 'Vimm\'s Lair':
        from .scrapers import download_vimm
        page_url = game_info.get('page_url')
        if page_url:
            success = download_vimm(page_url, dest_path, get_vimm_session(), progress_callback)

    elif source == 'RomHustler':
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin
        from .constants import ROMHUSTLER_BASE
        from .scrapers import _romhustler_session as _rh_sess

        def _romhustler_final_url(url: str) -> str:
            if not url:
                return ''
            if 'dl.romhustler.org/files/guest/' in url:
                return url
            resp = rh_session.get(url, timeout=30, headers={'Referer': page_url or ROMHUSTLER_BASE})
            if resp.status_code != 200:
                return url
            content_type = (resp.headers.get('content-type') or '').lower()
            if 'text/html' not in content_type:
                return url
            soup = BeautifulSoup(resp.text, 'html.parser')
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                if 'dl.romhustler.org/files/guest/' in href:
                    return href
            return url

        def _download_romhustler_file(url: str) -> bool:
            part_path = dest_path + '.part'
            with rh_session.get(url, stream=True, allow_redirects=True, timeout=download_timeout) as resp:
                resp.raise_for_status()
                content_type = (resp.headers.get('content-type') or '').lower()
                if 'text/html' in content_type:
                    preview = resp.raw.read(160, decode_content=True)
                    message = preview.decode('utf-8', errors='ignore').strip()
                    raise DownloadNetworkError(f"RomHustler n'a pas retourne un fichier: {message[:120]}")
                total = int(resp.headers.get('content-length', 0))
                downloaded = 0
                with open(part_path, 'wb') as handle:
                    for chunk in resp.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        downloaded += len(chunk)
                        if total > 0 and progress_callback:
                            progress_callback((downloaded / total) * 100)
                if progress_callback:
                    progress_callback(100.0)
            os.replace(part_path, dest_path)
            return True

        page_url = game_info.get('page_url')
        download_url = game_info.get('download_url')
        rh_session = _rh_sess()
        if download_url:
            final_url = _romhustler_final_url(download_url)
            success = _download_romhustler_file(final_url)
        elif page_url:
            try:
                resp = rh_session.get(page_url, timeout=30)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    for a in soup.find_all('a', href=True):
                        if '/download/' in a.get('href', ''):
                            dl_url = urljoin(ROMHUSTLER_BASE, a['href'])
                            final_url = _romhustler_final_url(dl_url)
                            success = _download_romhustler_file(final_url)
                            break
            except Exception:
                pass

    elif source == 'CoolROM':
        page_url = game_info.get('page_url')
        if page_url:
            cr_session = requests.Session()
            cr_session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://coolrom.com.au/',
            })
            try:
                resp = cr_session.get(page_url, timeout=30)
                if resp.status_code == 200:
                    from bs4 import BeautifulSoup
                    import re as _re
                    from urllib.parse import urljoin
                    from .constants import COOLROM_BASE
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    for a in soup.find_all('a', href=True):
                        href = a.get('href', '')
                        if 'dl.coolrom.com.au' in href:
                            success = download_file(href, dest_path, cr_session, progress_callback, download_timeout, progress_detail_callback)
                            break
                        if '/dl/' in href:
                            dl_url = urljoin(COOLROM_BASE, href)
                            success = download_file(dl_url, dest_path, cr_session, progress_callback, download_timeout, progress_detail_callback)
                            break
            except Exception:
                pass

    elif source == 'RomsXISOs' and download_url:
        if game_info.get('is_gdrive'):
            try:
                with session.get(download_url, stream=True, allow_redirects=True, timeout=download_timeout) as gresp:
                    gresp.raise_for_status()
                    cd = gresp.headers.get('content-disposition', '')
                    if 'text/html' in gresp.headers.get('content-type', '') and 'export=download' in download_url:
                        confirm_url = None
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(gresp.text, 'html.parser')
                        form = soup.find('form', id='download-form') or soup.find('form')
                        if form:
                            action = form.get('action', '')
                            confirm_url = action if action.startswith('http') else urljoin(download_url, action)
                        if confirm_url:
                            import re as _re
                            virus_scan_match = _re.search(r'href="([^"]*scan[^"]*)"', resp.text, re.IGNORECASE) if 'resp' in dir() else None
                            with session.get(confirm_url, stream=True, allow_redirects=True, timeout=download_timeout) as dresp:
                                dresp.raise_for_status()
                                total = int(dresp.headers.get('content-length', 0))
                                with open(dest_path, 'wb') as f:
                                    for chunk in dresp.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                                        if chunk:
                                            f.write(chunk)
                                success = True
                    else:
                        total = int(gresp.headers.get('content-length', 0))
                        downloaded_sz = 0
                        with open(dest_path, 'wb') as f:
                            for chunk in gresp.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                                if chunk:
                                    f.write(chunk)
                                    downloaded_sz += len(chunk)
                        success = True
            except Exception as e:
                log_func(f"  [RomsXISOs] Erreur GDrive: {e}")
        else:
            success = download_file(download_url, dest_path, session, progress_callback, download_timeout, progress_detail_callback)

    elif source == 'StartGame' and download_url:
        if is_1fichier_url(download_url):
            success = download_from_premium_source('1fichier', download_url, dest_path, load_api_keys(), progress_callback)
        else:
            success = download_file(download_url, dest_path, session, progress_callback, download_timeout, progress_detail_callback)

    elif source == 'NoPayStation' and download_url:
        success = download_file(download_url, dest_path, session, progress_callback, download_timeout, progress_detail_callback)

    elif source == 'hShop':
        page_url = game_info.get('page_url')
        if page_url:
            hs_session = requests.Session()
            hs_session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            })
            try:
                resp = hs_session.get(page_url, timeout=30)
                if resp.status_code == 200:
                    from bs4 import BeautifulSoup
                    from urllib.parse import urljoin
                    from .constants import HSHOP_BASE
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    for a in soup.find_all('a', href=True):
                        href = a.get('href', '')
                        if '.cia' in href or '.3ds' in href or '/dl/' in href:
                            dl_url = urljoin(HSHOP_BASE, href)
                            success = download_file(dl_url, dest_path, hs_session, progress_callback, download_timeout, progress_detail_callback)
                            break
            except Exception:
                pass

    elif source == 'RetroGameSets' and download_url:
        if is_1fichier_url(download_url):
            success = download_from_premium_source('1fichier', download_url, dest_path, load_api_keys(), progress_callback)
        else:
            log_func(f"  URL: {download_url[:80]}...")
            success = download_file(download_url, dest_path, session, progress_callback, download_timeout, progress_detail_callback)

    elif source.startswith('Minerva') and torrent_url:
        log_func(f"  Torrent: {torrent_url[:80]}...")
        torrent_target = game_info.get('torrent_target_filename') or filename
        success = download_from_minerva_torrent(torrent_url, torrent_target, dest_path, progress_callback)

    elif source == 'database' and download_url:
        log_func(f"  URL: {download_url[:80]}...")
        if '1fichier.com' in download_url:
            success = download_from_premium_source('1fichier', download_url, dest_path, load_api_keys(), progress_callback)
        elif game_info.get('database_host') == 'minerva-torrent' and torrent_url:
            log_func(f"  Torrent (DB): {torrent_url[:80]}...")
            torrent_target = game_info.get('torrent_target_filename') or game_info.get('minerva_full_path') or filename
            success = download_from_minerva_torrent(torrent_url, torrent_target, dest_path, progress_callback)
        else:
            success = download_file(download_url, dest_path, session, progress_callback, download_timeout, progress_detail_callback)

    else:
        source_info = next((item for item in sources if item['name'] == source), None)
        base_url = source_info['base_url'] if source_info else myrient_url
        if base_url:
            download_url = f"{base_url.rstrip('/')}/{quote(filename)}"
            log_func(f"  URL: {download_url[:80]}...")
            success = download_file(download_url, dest_path, session, progress_callback, download_timeout, progress_detail_callback)

    downloaded_path = ''
    if success:
        downloaded_path = resolve_downloaded_file_path(dest_path, output_folder, before_download)
        md5_ok, md5_message = verify_downloaded_md5(game_info, downloaded_path)
        log_func(f"  {md5_message}")
        if not md5_ok:
            cleanup_invalid_download(downloaded_path)
            raise ChecksumMismatchError(md5_message)
    else:
        cleanup_failed_download_outputs(dest_path, output_folder, before_download)

    return success, downloaded_path


def download_with_provider_retries(game_info: dict, sources: list, session, system_name: str,
                                   dat_profile: dict | None, output_folder: str,
                                   myrient_url: str = '', dry_run: bool = False,
                                   progress_callback=None, log_func=print,
                                   is_running=lambda: True, source_usage: dict | None = None,
                                   source_usage_lock=None, progress_detail_callback=None,
                                   circuit_breaker=None) -> tuple[str, dict]:
    """Essaie les providers un par un jusqu'a obtenir un fichier valide MD5 DAT."""
    original_game = clean_download_resolution(game_info)
    current_game = game_info.copy()
    attempted_sources = []
    attempted_source_labels = set()
    provider_attempts = []

    while current_game and is_running():
        attempt_started = time.time()
        source = current_game.get('source', 'unknown')
        source_label = normalize_source_label(source)
        if source_label in attempted_source_labels:
            log_func(f"  Provider deja teste: {source}")
            break
        attempted_source_labels.add(source_label)

        if circuit_breaker and circuit_breaker.is_open(source):
            log_func(f"  Circuit ouvert pour {source}: ignore pendant la session")
            provider_attempts.append({
                'source': source,
                'status': 'skipped',
                'duration_seconds': round(time.time() - attempt_started, 3),
                'detail': 'circuit_open',
            })
            current_game = resolve_next_provider(
                original_game,
                sources,
                session,
                system_name,
                dat_profile,
                attempted_sources
            )
            if current_game:
                log_func(f"  Retry avec: {current_game.get('source', 'unknown')}")
            continue
        quota_ok, quota_detail = reserve_source_quota(source, sources, source_usage, source_usage_lock)
        if not quota_ok:
            attempted_sources.append(source)
            provider_attempts.append({
                'source': source,
                'status': 'quota_skipped',
                'duration_seconds': round(time.time() - attempt_started, 3),
                'detail': quota_detail,
            })
            log_func(f"  Provider {source} ignore: {quota_detail}")
            current_game = resolve_next_provider(
                original_game,
                sources,
                session,
                system_name,
                dat_profile,
                attempted_sources
            )
            if current_game:
                log_func(f"  Retry avec: {current_game.get('source', 'unknown')}")
            continue
        filename = current_game.get('download_filename', current_game.get('game_name', ''))
        attempted_sources.append(source)
        source_config = find_source_config(sources, source)
        policy = source_policy_summary(source_config or {})
        quota_suffix = f", usage {quota_detail}" if quota_detail else ""
        log_func(f"  Provider: {source}{f' ({policy}{quota_suffix})' if policy or quota_suffix else ''}")

        if dry_run:
            if current_game.get('torrent_url'):
                log_func(f"  Serait telecharge via torrent Minerva vers: {output_folder}")
            else:
                log_func(f"  Serait telecharge vers: {output_folder}")
            item_copy = current_game.copy()
            item_copy['attempted_sources'] = attempted_sources.copy()
            item_copy['provider_attempts'] = [{
                'source': source,
                'status': 'dry_run',
                'duration_seconds': round(time.time() - attempt_started, 3),
            }]
            return 'dry_run', item_copy

        exists, existing_path = file_exists_in_folder(output_folder, filename)
        if exists:
            md5_ok, md5_message = verify_downloaded_md5(current_game, existing_path)
            log_func(f"  Fichier existant: {os.path.basename(existing_path)}")
            log_func(f"  {md5_message}")
            if md5_ok:
                item_copy = current_game.copy()
                item_copy['downloaded_path'] = existing_path
                item_copy['attempted_sources'] = attempted_sources.copy()
                provider_attempts.append({
                    'source': source,
                    'status': 'skipped',
                    'duration_seconds': round(time.time() - attempt_started, 3),
                    'detail': 'existing_valid',
                })
                item_copy['provider_attempts'] = provider_attempts.copy()
                return 'skipped', item_copy
            cleanup_invalid_download(existing_path)
            log_func("  Fichier existant supprime: MD5 incorrect")

        try:
            success, downloaded_path = attempt_download_from_resolved_provider(
                current_game,
                output_folder,
                sources,
                session,
                myrient_url,
                progress_callback,
                log_func,
                progress_detail_callback
            )
        except ChecksumMismatchError as exc:
            provider_attempts.append({
                'source': source,
                'status': 'failed',
                'duration_seconds': round(time.time() - attempt_started, 3),
                'detail': 'validation',
            })
            log_func(f"  Provider {source} checksum invalide, recherche d'un autre provider...")
            current_game = resolve_next_provider(
                original_game,
                sources,
                session,
                system_name,
                dat_profile,
                attempted_sources
            )
            if current_game:
                log_func(f"  Retry avec: {current_game.get('source', 'unknown')}")
            continue
        except SourceTimeoutError as exc:
            provider_attempts.append({
                'source': source,
                'status': 'failed',
                'duration_seconds': round(time.time() - attempt_started, 3),
                'detail': 'timeout',
            })
            if circuit_breaker:
                circuit_breaker.record_failure(source)
            log_func(f"  Provider {source} timeout, recherche d'un autre provider...")
            current_game = resolve_next_provider(
                original_game,
                sources,
                session,
                system_name,
                dat_profile,
                attempted_sources
            )
            if current_game:
                log_func(f"  Retry avec: {current_game.get('source', 'unknown')}")
            continue
        except DownloadNetworkError as exc:
            detail = str(exc)
            provider_attempts.append({
                'source': source,
                'status': 'failed',
                'duration_seconds': round(time.time() - attempt_started, 3),
                'detail': detail or 'network_error',
            })
            if circuit_breaker:
                circuit_breaker.record_failure(source)
            suffix = f": {detail[:180]}" if detail else ""
            log_func(f"  Provider {source} erreur reseau{suffix}")
            log_func("  Recherche d'un autre provider...")
            current_game = resolve_next_provider(
                original_game,
                sources,
                session,
                system_name,
                dat_profile,
                attempted_sources
            )
            if current_game:
                log_func(f"  Retry avec: {current_game.get('source', 'unknown')}")
            continue
        except Exception as exc:
            provider_attempts.append({
                'source': source,
                'status': 'failed',
                'duration_seconds': round(time.time() - attempt_started, 3),
                'detail': str(exc),
            })
            if circuit_breaker:
                circuit_breaker.record_failure(source)
            log_func(f"  Provider {source} invalide ou en echec, recherche d'un autre provider...")
            current_game = resolve_next_provider(
                original_game,
                sources,
                session,
                system_name,
                dat_profile,
                attempted_sources
            )
            if current_game:
                log_func(f"  Retry avec: {current_game.get('source', 'unknown')}")
            continue
        if success:
            if circuit_breaker:
                circuit_breaker.record_success(source)
            item_copy = current_game.copy()
            item_copy['downloaded_path'] = downloaded_path
            item_copy['attempted_sources'] = attempted_sources.copy()
            provider_attempts.append({
                'source': source,
                'status': 'downloaded',
                'duration_seconds': round(time.time() - attempt_started, 3),
            })
            item_copy['provider_attempts'] = provider_attempts.copy()
            return 'downloaded', item_copy

    item_copy = (current_game or game_info).copy()
    item_copy['attempted_sources'] = attempted_sources.copy()
    item_copy['provider_attempts'] = provider_attempts.copy()
    return ('stopped' if not is_running() else 'failed'), item_copy


def download_missing_games_sequentially(
    missing_games: list,
    sources: list,
    session,
    system_name: str,
    dat_profile: dict | None,
    output_folder: str,
    myrient_url: str = '',
    dry_run: bool = False,
    limit: int | None = None,
    progress_callback=None,
    log_func=print,
    status_callback=None,
    is_running=lambda: True,
    parallel_downloads: int = 1,
    circuit_breaker=None,
) -> dict:
    """
    Traite les jeux un par un: resolution DDL, telechargement, validation MD5,
    fallback provider, puis passage au jeu suivant.
    """
    from . import _facade
    resolved_items = []
    downloaded_items = []
    failed_items = []
    skipped_items = []
    not_available = []
    downloaded = 0
    failed = 0
    skipped = 0
    handled = 0
    parallel_downloads = max(1, int(parallel_downloads or 1))
    resolution_cache = _facade.load_resolution_cache()
    resolution_cache_dirty = False
    source_usage = {}
    source_usage_lock = threading.Lock()

    total = len(missing_games)
    total_work = min(total, limit) if limit else total
    completed_work = 0

    def report_overall_progress():
        if not progress_callback:
            return
        if total_work <= 0:
            progress_callback(100.0)
            return
        progress_callback(min(100.0, (completed_work / total_work) * 100.0))

    def mark_game_handled():
        nonlocal completed_work
        completed_work = min(total_work, completed_work + 1)
        report_overall_progress()
        if status_callback:
            status_callback(f"Progression globale: {completed_work}/{total_work} telechargement(s) traites")

    report_overall_progress()

    if parallel_downloads > 1 and not dry_run:
        log_lock = threading.Lock()

        def safe_log(message=""):
            with log_lock:
                log_func(message)

        max_workers = min(parallel_downloads, limit or total)
        log_func(f"Telechargements paralleles: {max_workers}")

        pool = ParallelDownloadPool(
            max_workers=max_workers,
            circuit_breaker=circuit_breaker,
        )

        def _orchestrator_worker(first_resolution: dict) -> tuple[str, dict]:
            worker_session = create_download_session()
            game_label = first_resolution.get('game_name', 'Jeu')

            def worker_progress_detail(update):
                if status_callback:
                    status_callback(
                        f"{game_label[:42]} - {update.get('percent', 0):.1f}% - "
                        f"{_facade.format_bytes(update.get('speed'))}/s - ETA {_facade.format_duration(update.get('eta'))}"
                    )

            return download_with_provider_retries(
                first_resolution,
                sources,
                worker_session,
                system_name,
                dat_profile,
                output_folder,
                myrient_url,
                dry_run,
                None,
                safe_log,
                is_running=is_running,
                source_usage=source_usage,
                source_usage_lock=source_usage_lock,
                progress_detail_callback=worker_progress_detail,
                circuit_breaker=circuit_breaker
            )

        pool.download_fn = _orchestrator_worker
        futures = {}

        for index, original_game in enumerate(missing_games, 1):
            if not is_running():
                log_func("Arrete par l'utilisateur.")
                break

            if limit and handled >= limit:
                log_func(f"\nLimite atteinte ({limit} jeu(x) traite(s)).")
                break

            game_name = original_game.get('game_name', 'Jeu inconnu')
            log_func(f"\n[{index}/{total}] Recherche: {game_name}")
            if status_callback:
                status_callback(f"Recherche {index}/{total}: {game_name[:60]}")

            found, unavailable, cache_hit = resolve_game_sources_with_cache(
                original_game,
                sources,
                session,
                system_name,
                dat_profile,
                cache=resolution_cache
            )
            resolution_cache_dirty = resolution_cache_dirty or not cache_hit
            if cache_hit:
                log_func("  Resolution: cache")

            handled += 1
            if not found:
                log_func("  Aucun provider disponible")
                not_available.append((unavailable[0] if unavailable else original_game).copy())
                mark_game_handled()
                continue

            first_resolution = found[0]
            resolved_items.append(first_resolution.copy())
            log_func(f"  Soumis: {game_name} [{first_resolution.get('source', 'unknown')}]")
            future = pool.submit(first_resolution)
            futures[future] = game_name

        for future in concurrent.futures.as_completed(futures):
            game_name = futures[future]
            if status_callback:
                status_callback(f"Validation: {game_name[:60]}")
            try:
                status, result_item = future.result()
            except Exception as e:
                status = 'failed'
                result_item = {'game_name': game_name, 'error': str(e)}

            if status == 'downloaded':
                safe_log(f"  Telecharge: {result_item.get('download_filename', game_name)}")
                downloaded += 1
                downloaded_items.append(result_item.copy())
            elif status == 'skipped':
                skipped += 1
                skipped_items.append(result_item.copy())
            elif status == 'stopped':
                safe_log("Arrete par l'utilisateur.")
                break
            else:
                safe_log(f"  Echec du telechargement: {game_name}")
                failed += 1
                failed_items.append(result_item.copy())
            mark_game_handled()

        pool.shutdown(wait=False)

        if resolution_cache_dirty:
            _facade.save_resolution_cache(resolution_cache)

        return {
            'resolved_items': resolved_items,
            'downloaded_items': downloaded_items,
            'failed_items': failed_items,
            'skipped_items': skipped_items,
            'not_available': not_available,
            'downloaded': downloaded,
            'failed': failed,
            'skipped': skipped,
        }

    for index, original_game in enumerate(missing_games, 1):
        if not is_running():
            log_func("Arrete par l'utilisateur.")
            break

        if limit and handled >= limit:
            log_func(f"\nLimite atteinte ({limit} jeu(x) traite(s)).")
            break

        game_name = original_game.get('game_name', 'Jeu inconnu')
        log_func(f"\n[{index}/{total}] {game_name}")
        if status_callback:
            status_callback(f"Recherche {index}/{total}: {game_name[:60]}")

        found, unavailable, cache_hit = resolve_game_sources_with_cache(
            original_game,
            sources,
            session,
            system_name,
            dat_profile,
            cache=resolution_cache
        )
        resolution_cache_dirty = resolution_cache_dirty or not cache_hit
        if cache_hit:
            log_func("  Resolution: cache")

        if not found:
            log_func("  Aucun provider disponible")
            not_available.append((unavailable[0] if unavailable else original_game).copy())
            handled += 1
            mark_game_handled()
            continue

        first_resolution = found[0]
        log_func(f"  Provider initial: {first_resolution.get('source', 'unknown')}")
        if status_callback:
            status_callback(f"Telechargement {index}/{total}: {game_name[:60]}")

        def progress_detail_callback(update, current_name=game_name):
            if not status_callback:
                return
            status_callback(
                f"{current_name[:42]} - {update.get('percent', 0):.1f}% - "
                f"{_facade.format_bytes(update.get('speed'))}/s - ETA {_facade.format_duration(update.get('eta'))}"
            )

        status, result_item = download_with_provider_retries(
            first_resolution,
            sources,
            session,
            system_name,
            dat_profile,
            output_folder,
            myrient_url,
            dry_run,
            None,
            log_func,
            is_running=is_running,
            source_usage=source_usage,
            source_usage_lock=source_usage_lock,
            progress_detail_callback=progress_detail_callback,
            circuit_breaker=circuit_breaker,
        )

        if status == 'downloaded':
            log_func(f"  Telecharge: {result_item.get('download_filename', game_name)}")
            downloaded += 1
            downloaded_items.append(result_item.copy())
            resolved_items.append(result_item.copy())
            time.sleep(0.5)
        elif status == 'skipped':
            skipped += 1
            skipped_items.append(result_item.copy())
            resolved_items.append(result_item.copy())
        elif status == 'dry_run':
            resolved_items.append(result_item.copy())
            handled += 1
        elif status == 'stopped':
            log_func("Arrete par l'utilisateur.")
            break
        else:
            log_func("  Echec du telechargement")
            failed += 1
            failed_items.append(result_item.copy())
            handled += 1
            mark_game_handled()
            continue

        if status in {'downloaded', 'skipped'}:
            handled += 1
            mark_game_handled()
        elif status == 'dry_run':
            mark_game_handled()

    if resolution_cache_dirty:
        _facade.save_resolution_cache(resolution_cache)

    return {
        'resolved_items': resolved_items,
        'downloaded_items': downloaded_items,
        'failed_items': failed_items,
        'skipped_items': skipped_items,
        'not_available': not_available,
        'downloaded': downloaded,
        'failed': failed,
        'skipped': skipped,
    }


__all__ = [
    'resolve_next_provider',
    'attempt_download_from_resolved_provider',
    'download_with_provider_retries',
    'download_missing_games_sequentially',
]
