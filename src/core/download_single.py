import os
import time
from pathlib import Path
from typing import Callable

from ..network.sessions import create_optimized_session
from ..network.circuits import SourceCircuitBreaker
from ..network.cache_runtime import get_session_cache, clear_session_cache, RuntimeCache
from ..network.metrics import load_provider_metrics, save_provider_metrics, prioritize_sources, record_provider_attempt
from ..network.exceptions import ChecksumMismatchError, SourceTimeoutError, DownloadNetworkError
from ..network.utils import format_bytes
from ..progress import format_duration

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
)
from .dat_profile import finalize_dat_profile, prepare_sources_for_profile
from .search_pipeline import search_all_sources
from .scanner import scan_local_roms, find_missing_games, build_dat_md5_lookup
from .dat_parser import parse_dat_file, normalize_checksum
from .verification import (
    file_exists_in_folder,
    snapshot_folder_files,
    resolve_downloaded_file_path,
    verify_downloaded_md5,
    cleanup_invalid_download,
    expected_game_md5_values,
)
from .torrentzip import (
    repack_verified_archives_to_torrentzip,
    extract_archive_member_to_file,
    create_torrentzip_single_file,
)
from .signatures import hash_file_signatures
from .download_orchestrator import (
    attempt_download_from_resolved_provider,
    download_with_provider_retries,
    adapt_sources_for_circuit_state,
)
from .local_database import (
    create_download_job,
    update_download_job,
    update_download_queue_item,
    record_download_attempt,
    record_provider_success,
    record_provider_candidates,
)
from .api_keys import load_api_keys


def auto_extract_and_repack(
    downloaded_path: str,
    game_info: dict,
    dat_games: dict,
    output_folder: str,
    clean_torrentzip: bool = True,
    log_func: Callable = print,
) -> dict:
    """Apres verification MD5, extrait les ROMs des archives et recreer des ZIP TorrentZip.

    Si le fichier telecharge est une archive (.7z, .rar, .zip non-TorrentZip):
    1. Extrait les ROMs du DAT depuis l'archive
    2. Verifie les MD5 des fichiers extraits
    3. Cree des ZIP TorrentZip conformes RomVault
    4. Supprime l'archive source si differente du ZIP final

    Retourne un dict avec:
        - 'final_paths': liste des chemins des fichiers finaux (ZIP TorrentZip ou fichier brut)
        - 'extracted': True si une extraction a eu lieu
        - 'repacked': nombre de ZIP TorrentZip crees
        - 'deleted_source': True si l'archive source a ete supprimee
        - 'md5_ok': True si la verification MD5 est OK
        - 'md5_message': message de verification
    """
    result = {
        'final_paths': [],
        'extracted': False,
        'repacked': 0,
        'deleted_source': False,
        'md5_ok': True,
        'md5_message': '',
    }

    if not downloaded_path or not os.path.exists(downloaded_path):
        result['md5_ok'] = False
        result['md5_message'] = 'Fichier telecharge introuvable'
        return result

    file_path = Path(downloaded_path)
    suffix = file_path.suffix.lower()

    md5_ok, md5_message = verify_downloaded_md5(game_info, downloaded_path)
    result['md5_ok'] = md5_ok
    result['md5_message'] = md5_message

    if not md5_ok:
        return result

    if suffix not in {'.7z', '.rar', '.zip'}:
        result['final_paths'] = [downloaded_path]
        return result

    if not clean_torrentzip:
        result['final_paths'] = [downloaded_path]
        return result

    expected_md5 = expected_game_md5_values(game_info)
    if not expected_md5:
        result['final_paths'] = [downloaded_path]
        return result

    from .signatures import iter_archive_member_signatures

    matches = []
    seen_md5 = set()
    md5_lookup = build_dat_md5_lookup(dat_games) if dat_games else {}
    for entry in iter_archive_member_signatures(file_path):
        entry_md5 = normalize_checksum(entry.get('md5', ''), 'md5')
        if entry_md5 in expected_md5 and entry_md5 not in seen_md5:
            rom_info = md5_lookup.get(entry_md5, [{}])[0] if md5_lookup else {}
            rom_name = rom_info.get('rom_name') or entry.get('name') or file_path.stem
            matches.append({
                'member': entry.get('member') or entry.get('name'),
                'md5': entry_md5,
                'rom_name': rom_name,
                'game_name': rom_info.get('game_name', ''),
            })
            seen_md5.add(entry_md5)

    if not matches:
        result['final_paths'] = [downloaded_path]
        return result

    import tempfile
    created_zips = []
    source_deleted = False

    for match in matches:
        rom_name = Path(match['rom_name']).name
        target_zip = file_path.parent / f"{Path(rom_name).stem}.zip"

        if (file_path.resolve() == target_zip.resolve()
                and len(matches) == 1
                and suffix == '.zip'):
            from .torrentzip import zip_is_torrentzip_compatible
            if zip_is_torrentzip_compatible(file_path):
                result['final_paths'] = [str(target_zip)]
                result['repacked'] = 0
                return result

        with tempfile.TemporaryDirectory(prefix='rom_downloader_extract_') as temp_dir:
            temp_extracted = Path(temp_dir) / rom_name
            try:
                extract_archive_member_to_file(file_path, match['member'], temp_extracted)
            except Exception as exc:
                log_func(f"  Erreur extraction {match['member']}: {exc}")
                continue

            extracted_md5 = hash_file_signatures(temp_extracted).get('md5', '')
            if extracted_md5 != match['md5']:
                log_func(f"  MD5 extrait incorrect pour {rom_name}")
                continue

            try:
                comment = create_torrentzip_single_file(temp_extracted, rom_name, target_zip)
                log_func(f"  TorrentZip: {target_zip.name} ({comment})")
                created_zips.append(str(target_zip))
                result['repacked'] += 1

                ok, msg = verify_downloaded_md5({'roms': [{'md5': match['md5']}]}, str(target_zip))
                if not ok:
                    log_func(f"  Verification TorrentZip KO: {msg}")
                else:
                    result['final_paths'].append(str(target_zip))
            except Exception as exc:
                log_func(f"  Erreur TorrentZip {rom_name}: {exc}")

    if created_zips:
        result['extracted'] = True
        archive_resolved = str(file_path.resolve()).lower()
        output_resolved = {str(Path(p).resolve()).lower() for p in created_zips}
        if file_path.exists() and archive_resolved not in output_resolved:
            try:
                file_path.unlink()
                result['deleted_source'] = True
                log_func(f"  Archive source supprimee: {file_path.name}")
            except Exception as exc:
                log_func(f"  Erreur suppression {file_path.name}: {exc}")

    if not result['final_paths'] and os.path.exists(downloaded_path):
        result['final_paths'] = [downloaded_path]

    return result


def download_single_game(
    game_info: dict,
    sources: list,
    session,
    system_name: str,
    dat_profile: dict | None,
    output_folder: str,
    dat_games: dict | None = None,
    myrient_url: str = '',
    dry_run: bool = False,
    progress_callback=None,
    status_callback=None,
    log_func: Callable = print,
    is_running: Callable = lambda: True,
    circuit_breaker: SourceCircuitBreaker | None = None,
    source_usage: dict | None = None,
    source_usage_lock=None,
    progress_detail_callback=None,
    clean_torrentzip: bool = True,
    parallel_downloads: int = 1,
    system_id: str = '',
    game_id: str = '',
) -> dict:
    """Telecharge un seul jeu avec resolution, verification MD5, extraction et TorrentZip.

    Pipeline complet pour un jeu:
    1. Resolution du provider (avec cache)
    2. Telechargement avec retry provider
    3. Verification MD5
    4. Auto-extraction et repack TorrentZip (si clean_torrentzip=True)
    5. Enregistrement en base

    Retourne un dict avec:
        - 'status': 'downloaded'|'skipped'|'failed'|'stopped'|'dry_run'|'not_found'
        - 'game_info': dict avec les infos du jeu et provider_attempts
        - 'final_paths': liste des chemins finaux apres extraction/repack
        - 'md5_message': message de verification MD5
        - 'extract_result': resultat de l'extraction TorrentZip (ou None)
    """
    game_name = game_info.get('game_name', 'Jeu inconnu')
    result = {
        'status': 'not_found',
        'game_info': game_info.copy(),
        'final_paths': [],
        'md5_message': '',
        'extract_result': None,
    }

    job_id = create_download_job(
        system_id or game_info.get('system_id', ''),
        [game_info],
        output_folder,
    )

    update_download_queue_item(
        job_id,
        game_id=game_id or game_info.get('game_id', ''),
        game_name=game_name,
        status='running',
        locked_by='single_game',
        increment_attempts=True,
    )

    found, unavailable, cache_hit = resolve_game_sources_with_cache(
        game_info,
        sources,
        session,
        system_name,
        dat_profile,
    )

    if not found:
        log_func(f"Aucun provider disponible pour {game_name}")
        result['status'] = 'not_found'
        record_download_attempt({
            'job_id': job_id,
            'game_id': game_id or game_info.get('game_id', ''),
            'system_id': system_id or game_info.get('system_id', ''),
            'game_name': game_name,
            'provider': '',
            'status': 'not_found',
            'detail': 'Aucun provider disponible',
            'duration_seconds': 0,
        })
        update_download_job(job_id, status='completed')
        return result

    first_resolution = found[0]
    first_resolution.setdefault('game_id', game_id or game_info.get('game_id', ''))
    first_resolution.setdefault('system_id', system_id or game_info.get('system_id', ''))

    if game_id or game_info.get('game_id'):
        record_provider_candidates(game_id or game_info.get('game_id', ''), found)

    log_func(f"Telechargement: {game_name} [{first_resolution.get('source', 'unknown')}]")

    status, result_item = download_with_provider_retries(
        first_resolution,
        sources,
        session,
        system_name,
        dat_profile,
        output_folder,
        myrient_url,
        dry_run,
        progress_callback,
        log_func,
        is_running=is_running,
        source_usage=source_usage,
        source_usage_lock=source_usage_lock,
        progress_detail_callback=progress_detail_callback,
        circuit_breaker=circuit_breaker,
    )

    result['status'] = status
    result['game_info'] = result_item

    if status == 'downloaded' and not dry_run:
        downloaded_path = result_item.get('downloaded_path', '')
        if downloaded_path and os.path.exists(downloaded_path):
            extract_result = auto_extract_and_repack(
                downloaded_path,
                result_item,
                dat_games,
                output_folder,
                clean_torrentzip=clean_torrentzip,
                log_func=log_func,
            )
            result['extract_result'] = extract_result
            result['final_paths'] = extract_result['final_paths']
            result['md5_message'] = extract_result['md5_message']
            if extract_result['repacked'] > 0:
                log_func(f"  Repack TorrentZip: {extract_result['repacked']} fichier(s)")
            if extract_result['deleted_source']:
                log_func(f"  Archive source supprimee")
        else:
            result['final_paths'] = [downloaded_path] if downloaded_path else []
    elif status == 'skipped':
        downloaded_path = result_item.get('downloaded_path', '')
        if downloaded_path and os.path.exists(downloaded_path):
            result['final_paths'] = [downloaded_path]

    attempts = result_item.get('provider_attempts', [])
    provider = attempts[-1].get('source') if attempts else result_item.get('source', '')
    last_attempt = attempts[-1] if attempts else {}
    duration = sum(float(a.get('duration_seconds', 0) or 0) for a in attempts)
    path = result['final_paths'][0] if result['final_paths'] else (result_item.get('downloaded_path') or '')
    size = os.path.getsize(path) if path and os.path.exists(path) else 0

    record_download_attempt({
        'job_id': job_id,
        'game_id': game_id or game_info.get('game_id', ''),
        'system_id': system_id or game_info.get('system_id', ''),
        'game_name': game_name,
        'provider': provider,
        'status': 'completed' if status == 'downloaded' else ('skipped' if status == 'skipped' else status),
        'error_code': last_attempt.get('error_code') or result_item.get('error_code') or '',
        'detail': result.get('md5_message', '') or (attempts[-1].get('detail', '') if attempts else ''),
        'duration_seconds': duration,
        'file_path': path,
        'size': size,
        'candidate_url': last_attempt.get('candidate_url') or result_item.get('download_url') or result_item.get('torrent_url') or result_item.get('page_url') or result_item.get('archive_org_identifier') or '',
        'http_status': last_attempt.get('http_status') or result_item.get('http_status') or 0,
        'content_type': last_attempt.get('content_type') or result_item.get('content_type') or '',
        'announced_size': last_attempt.get('announced_size') or result_item.get('announced_size') or 0,
        'hash_final': last_attempt.get('hash_final') or result_item.get('hash_final') or '',
        'html_snippet': last_attempt.get('html_snippet') or result_item.get('html_snippet') or '',
        'provider_rank': last_attempt.get('provider_rank') or result_item.get('provider_rank') or 0,
    })

    if status in ('downloaded', 'skipped') and (game_id or game_info.get('game_id')):
        record_provider_success(
            game_id or game_info.get('game_id', ''),
            result_item,
            {
                'file_path': path,
                'size': size,
                'duration_seconds': duration,
                'average_speed': size / duration if size and duration else 0,
            },
        )

    update_download_job(job_id, status='completed' if status == 'downloaded' else status)

    return result


__all__ = [
    'auto_extract_and_repack',
    'download_single_game',
]
