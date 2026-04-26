import os
from pathlib import Path

from .dat_parser import normalize_checksum, parse_rom_size, strip_rom_extension, add_local_name_reference
from .signatures import (
    build_target_signature_sets,
    hash_file_signatures,
    iter_archive_member_signatures,
    index_signature_value,
)
from .scan_cache import (
    load_scan_cache,
    save_scan_cache,
    cache_key_for_file,
    file_cache_state,
    target_sizes_cache_key,
    cached_entries_for_file,
    update_file_scan_cache,
)
from .env import SCAN_CACHE_FILENAME


def scan_local_roms(rom_folder: str, dat_games: dict | None = None) -> tuple:
    """Scan a folder for local ROM files."""
    print(f"Scanning local ROMs folder: {rom_folder}")

    local_roms = set()
    local_roms_normalized = set()
    local_game_names = set()
    signature_index = {'md5': {}, 'crc': {}, 'sha1': {}}
    rom_path = Path(rom_folder)

    if not rom_path.exists():
        print(f"Warning: ROM folder does not exist: {rom_folder}")
        return local_roms, local_roms_normalized, local_game_names, signature_index

    target_signatures = build_target_signature_sets(dat_games)
    target_sizes = target_signatures['size']
    target_sizes_key = target_sizes_cache_key(target_sizes)
    archive_extensions = ('.zip', '.7z', '.rar')
    hashed_items = 0
    cache = load_scan_cache(rom_path)
    next_cache = {'version': 2, 'files': {}}
    cache_hits = 0
    cache_misses = 0

    for file_path in rom_path.rglob('*'):
        if file_path.is_file():
            filename = file_path.name
            if filename == SCAN_CACHE_FILENAME:
                continue
            if filename.lower().startswith('rom_downloader_report_') and file_path.suffix.lower() == '.txt':
                continue

            add_local_name_reference(filename, local_roms, local_roms_normalized, local_game_names)
            cache_key = cache_key_for_file(file_path, rom_path)
            state = file_cache_state(file_path)
            if state is not None:
                state['target_sizes_key'] = target_sizes_key
            cached_entries = cached_entries_for_file(cache, cache_key, state) if state else None
            entries_for_cache = []

            if cached_entries is not None:
                cache_hits += 1
                for cached_entry in cached_entries:
                    internal_name = cached_entry.get('name', '')
                    if internal_name:
                        add_local_name_reference(internal_name, local_roms, local_roms_normalized, local_game_names)
                    reference = {
                        'path': str(file_path),
                        **cached_entry
                    }
                    for checksum_type in ('md5', 'crc', 'sha1'):
                        index_signature_value(signature_index, checksum_type, reference.get(checksum_type, ''), reference)
                    if any(reference.get(checksum_type) for checksum_type in ('md5', 'crc', 'sha1')):
                        hashed_items += 1
                if state is not None:
                    update_file_scan_cache(next_cache, cache_key, state, cached_entries)
                continue

            cache_misses += 1

            if file_path.suffix.lower() in archive_extensions:
                try:
                    for archive_entry in iter_archive_member_signatures(
                            file_path,
                            target_sizes=target_sizes,
                            require_hashes=False):
                        internal_name = archive_entry['name']
                        add_local_name_reference(internal_name, local_roms, local_roms_normalized, local_game_names)

                        reference = {
                            'path': str(file_path),
                            **archive_entry
                        }
                        for checksum_type in ('md5', 'crc', 'sha1'):
                            index_signature_value(signature_index, checksum_type, reference.get(checksum_type, ''), reference)
                        hashed_items += 1
                        entries_for_cache.append(archive_entry)
                except Exception as e:
                    print(f"  Avertissement: archive locale ignoree ({file_path.name}): {e}")
            else:
                try:
                    file_size = file_path.stat().st_size
                except Exception:
                    continue

                if target_sizes and file_size not in target_sizes:
                    continue

                try:
                    signatures = hash_file_signatures(file_path)
                except Exception:
                    continue

                reference = {
                    'path': str(file_path),
                    'member': '',
                    'name': filename,
                    'size': file_size,
                    **signatures
                }
                for checksum_type in ('md5', 'crc', 'sha1'):
                    index_signature_value(signature_index, checksum_type, reference.get(checksum_type, ''), reference)
                hashed_items += 1
                entries_for_cache.append({
                    'member': '',
                    'name': filename,
                    'size': file_size,
                    **signatures
                })

            if state is not None:
                update_file_scan_cache(next_cache, cache_key, state, entries_for_cache)

    save_scan_cache(rom_path, next_cache)
    print(f"Found {len(local_roms)} local ROM files")
    print(f"Indexed {hashed_items} local entries by checksums")
    print(f"Scan cache: {cache_hits} reutilise(s), {cache_misses} rescannes")
    return local_roms, local_roms_normalized, local_game_names, signature_index


def find_missing_games(dat_games: dict, local_roms: set, local_roms_normalized: set, local_game_names: set,
                       signature_index: dict | None = None) -> list:
    """Compare DAT games with local ROMs and return missing ones.

    A local ROM validates a DAT entry by checksum only. Names are kept in the
    scan indexes for reports/ToSort, but they must not mark a game as present.
    """
    print("Comparing DAT games with local ROMs...")

    signature_index = signature_index or {'md5': {}, 'crc': {}, 'sha1': {}}
    missing = []
    for game_name, game_info in dat_games.items():
        found = False

        has_md5 = any(normalize_checksum(rom_info.get('md5', ''), 'md5') for rom_info in game_info.get('roms', []))
        checksum_order = ('md5', 'crc', 'sha1') if has_md5 else ('crc', 'sha1')

        for checksum_type in checksum_order:
            for rom_info in game_info.get('roms', []):
                checksum_value = normalize_checksum(rom_info.get(checksum_type, ''), checksum_type)
                if checksum_value and checksum_value in signature_index.get(checksum_type, {}):
                    found = True
                    break
            if found:
                break

        if not found:
            missing.append(game_info)

    print(f"Found {len(missing)} missing games")
    return missing


def estimate_games_size(games: list | dict) -> tuple[int, int]:
    """Estime la taille brute des ROMs DAT a partir des champs size."""
    iterable = games.values() if isinstance(games, dict) else games
    total = 0
    unknown = 0
    for game_info in iterable:
        rom_sizes = []
        for rom_info in game_info.get('roms', []):
            parsed_size = parse_rom_size(rom_info.get('size'))
            if parsed_size is not None:
                rom_sizes.append(parsed_size)
        if rom_sizes:
            total += sum(rom_sizes)
        else:
            unknown += 1
    return total, unknown


def build_analysis_summary(dat_file: str, rom_folder: str, dat_games: dict, missing_games: list,
                           dat_profile: dict, sources: list, tosort_candidates: list | None = None) -> dict:
    """Construit le resume de pre-analyse sans refaire les scans."""
    from .dat_profile import describe_dat_profile
    from ..network.utils import format_bytes
    from .dat_parser import normalize_checksum
    total_size, total_unknown = estimate_games_size(dat_games)
    missing_size, missing_unknown = estimate_games_size(missing_games)
    present = max(0, len(dat_games) - len(missing_games))
    return {
        'dat_file': dat_file,
        'rom_folder': rom_folder,
        'system_name': dat_profile.get('system_name') or detect_system_name(dat_file),
        'dat_profile': describe_dat_profile(dat_profile),
        'total_games': len(dat_games),
        'present_games': present,
        'missing_games': len(missing_games),
        'missing_percent': (len(missing_games) / len(dat_games) * 100) if dat_games else 0.0,
        'total_size': total_size,
        'total_unknown_sizes': total_unknown,
        'missing_size': missing_size,
        'missing_unknown_sizes': missing_unknown,
        'active_sources': [source['name'] for source in sources if source.get('enabled', True)],
        'tosort_candidates': len(tosort_candidates) if tosort_candidates is not None else None,
    }


def analyze_dat_folder(dat_file: str, rom_folder: str, include_tosort: bool = False,
                       custom_sources: list | None = None, candidate_limit: int = 0) -> dict:
    """Analyse un couple DAT/dossier avant tout telechargement."""
    from .dat_profile import detect_dat_profile, finalize_dat_profile
    from .sources import prepare_sources_for_profile, get_default_sources, parse_candidate_limit
    dat_games = parse_dat_file(dat_file)
    dat_profile = finalize_dat_profile(detect_dat_profile(dat_file))
    sources = prepare_sources_for_profile(
        [source.copy() for source in (custom_sources if custom_sources else get_default_sources())],
        dat_profile
    )
    local_roms, local_roms_normalized, local_game_names, signature_index = scan_local_roms(rom_folder, dat_games)
    missing_games = find_missing_games(dat_games, local_roms, local_roms_normalized, local_game_names, signature_index)
    tosort_candidates = None
    if include_tosort:
        tosort_candidates = find_roms_not_in_dat(dat_games, local_roms, local_roms_normalized, rom_folder)
    summary = build_analysis_summary(dat_file, rom_folder, dat_games, missing_games, dat_profile, sources, tosort_candidates)
    candidate_limit = parse_candidate_limit(candidate_limit, len(missing_games), 0)
    if candidate_limit:
        system_name = dat_profile.get('system_name') or detect_system_name(dat_file)
        summary.update(analyze_source_candidates(missing_games, sources, system_name, dat_profile, candidate_limit))
    return summary


def analyze_source_candidates(missing_games: list, sources: list, system_name: str,
                              dat_profile: dict | None, candidate_limit: int = 10) -> dict:
    """Resolve les sources candidates pour un echantillon de jeux manquants."""
    from .sources import resolve_game_sources_with_cache, parse_candidate_limit
    from ._facade import create_download_session, load_resolution_cache, save_resolution_cache
    session = create_download_session()
    resolution_cache = load_resolution_cache()
    dirty = False
    samples = []
    source_counts = {}
    for game_info in list(missing_games)[:parse_candidate_limit(candidate_limit, len(missing_games), 0)]:
        found, unavailable, cache_hit = resolve_game_sources_with_cache(
            game_info,
            sources,
            session,
            system_name,
            dat_profile,
            cache=resolution_cache
        )
        dirty = dirty or not cache_hit
        candidate_sources = [item.get('source', 'Inconnu') for item in found]
        for source_name in candidate_sources:
            source_counts[source_name] = source_counts.get(source_name, 0) + 1
        samples.append({
            'game_name': game_info.get('game_name', 'Jeu inconnu'),
            'sources': candidate_sources,
            'not_found': not bool(found),
            'cache_hit': cache_hit,
            'unavailable': len(unavailable),
        })
    if dirty:
        save_resolution_cache(resolution_cache)
    return {
        'candidate_sample_size': len(samples),
        'candidate_source_counts': source_counts,
        'candidate_samples': samples,
    }


def format_analysis_summary(summary: dict) -> str:
    """Retourne un resume de pre-analyse lisible."""
    from ..network.utils import format_bytes
    lines = [
        "PRE-ANALYSE",
        "=" * 60,
        f"DAT: {summary.get('dat_file')}",
        f"Dossier: {summary.get('rom_folder')}",
        f"Systeme: {summary.get('system_name') or 'Inconnu'}",
        f"Profil: {summary.get('dat_profile')}",
        f"Jeux DAT: {summary.get('total_games', 0)}",
        f"Presents: {summary.get('present_games', 0)}",
        f"Manquants: {summary.get('missing_games', 0)} ({summary.get('missing_percent', 0):.1f}%)",
        f"Taille DAT estimee: {format_bytes(summary.get('total_size'))}",
        f"Taille manquante estimee: {format_bytes(summary.get('missing_size'))}",
    ]
    if summary.get('missing_unknown_sizes'):
        lines.append(f"Tailles manquantes inconnues: {summary.get('missing_unknown_sizes')}")
    if summary.get('tosort_candidates') is not None:
        lines.append(f"Candidats ToSort: {summary.get('tosort_candidates')}")
    if summary.get('candidate_sample_size'):
        lines.append(f"Echantillon sources candidates: {summary.get('candidate_sample_size')} jeu(x)")
        source_counts = summary.get('candidate_source_counts') or {}
        if source_counts:
            formatted = ', '.join(f"{name}: {count}" for name, count in sorted(source_counts.items()))
            lines.append(f"Sources candidates: {formatted}")
        for sample in summary.get('candidate_samples', [])[:8]:
            sources = ', '.join(sample.get('sources') or [])
            lines.append(f"  - {sample.get('game_name')}: {sources or 'aucune source'}")
    lines.append(f"Sources actives: {', '.join(summary.get('active_sources') or []) or 'Aucune'}")
    lines.append("=" * 60)
    return "\n".join(lines)


def print_analysis_summary(summary: dict) -> None:
    """Affiche la pre-analyse."""
    print(format_analysis_summary(summary))


def find_roms_not_in_dat(dat_games: dict, local_roms: set, local_roms_normalized: set,
                         rom_folder: str) -> list:
    """Find local files whose content checksums are not present in the DAT."""
    print("Finding ROMs not in DAT file by checksums...")
    generated_report_prefix = 'rom_downloader_report_'
    files_to_move = []
    rom_path = Path(rom_folder)
    target_signatures = build_target_signature_sets(dat_games)

    if not rom_path.exists():
        return files_to_move

    def signatures_match_dat(signatures: dict) -> bool:
        for checksum_type in ('md5', 'crc', 'sha1'):
            checksum_value = normalize_checksum(signatures.get(checksum_type, ''), checksum_type)
            if checksum_value and checksum_value in target_signatures.get(checksum_type, set()):
                return True
        return False

    for file_path in rom_path.rglob('*'):
        if not file_path.is_file():
            continue
        filename = file_path.name

        if 'ToSort' in file_path.parts:
            continue
        if filename == SCAN_CACHE_FILENAME or filename.startswith('.rom_downloader_'):
            continue
        if filename.endswith('.part'):
            continue
        if filename.lower().startswith(generated_report_prefix) and file_path.suffix.lower() == '.txt':
            continue
        if file_path.name.lower() == 'repack_archives_to_individual_zip.bat':
            continue

        file_is_in_dat = False
        if file_path.suffix.lower() in {'.zip', '.7z', '.rar'}:
            try:
                for archive_entry in iter_archive_member_signatures(
                        file_path,
                        target_sizes=target_signatures.get('size', set()),
                        require_hashes=False):
                    if signatures_match_dat(archive_entry):
                        file_is_in_dat = True
                        break
            except Exception as e:
                print(f"  Avertissement: archive ToSort non verifiable ({file_path.name}): {e}")
        else:
            try:
                file_is_in_dat = signatures_match_dat(hash_file_signatures(file_path))
            except Exception as e:
                print(f"  Avertissement: fichier ToSort non verifiable ({file_path.name}): {e}")

        if not file_is_in_dat:
            files_to_move.append(str(file_path))

    print(f"Found {len(files_to_move)} files not in DAT")
    return files_to_move


def move_files_to_tosort(files_to_move: list, rom_folder: str, tosort_folder: str, dry_run: bool = False) -> tuple:
    """Move files to ToSort folder."""
    moved = 0
    failed = 0

    if not dry_run:
        os.makedirs(tosort_folder, exist_ok=True)

    for file_path in files_to_move:
        try:
            filename = os.path.basename(file_path)
            dest_path = os.path.join(tosort_folder, filename)

            if os.path.exists(dest_path):
                base, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(dest_path):
                    dest_path = os.path.join(tosort_folder, f"{base}_{counter}{ext}")
                    counter += 1

            if dry_run:
                print(f"  [DRY-RUN] Would move: {filename}")
                moved += 1
            else:
                os.rename(file_path, dest_path)
                print(f"  Moved: {filename}")
                moved += 1
        except Exception as e:
            print(f"  Failed to move {os.path.basename(file_path)}: {e}")
            failed += 1

    return moved, failed


def build_dat_md5_lookup(dat_games: dict) -> dict:
    """Indexe les ROMs du DAT par MD5."""
    lookup = {}
    for game_info in dat_games.values():
        for rom_info in game_info.get('roms', []):
            md5_value = normalize_checksum(rom_info.get('md5', ''), 'md5')
            if not md5_value:
                continue
            lookup.setdefault(md5_value, []).append({
                'game_name': game_info.get('game_name', ''),
                'rom_name': Path(rom_info.get('name', '')).name,
                'md5': md5_value,
            })
    return lookup


def detect_system_name(dat_file_path: str) -> str:
    """Retourne le nom de systeme normalise a partir du profil DAT."""
    from .dat_profile import detect_dat_profile, finalize_dat_profile
    profile_system_name = finalize_dat_profile(detect_dat_profile(dat_file_path)).get('system_name', '')
    if profile_system_name:
        return profile_system_name

    import os
    import re
    import xml.etree.ElementTree as ET
    try:
        tree = ET.parse(dat_file_path)
        root = tree.getroot()
        header_name = root.findtext('./header/name', default='').strip()
        if header_name:
            return re.sub(r'\s+', ' ', header_name)
    except Exception:
        pass

    filename = os.path.basename(dat_file_path)
    name = os.path.splitext(filename)[0]
    name = re.sub(r'[\(\[].*?[\)\]]', '', name).strip()
    name = re.sub(r'\s+', ' ', name)
    return name


__all__ = [
    'scan_local_roms',
    'find_missing_games',
    'estimate_games_size',
    'build_analysis_summary',
    'analyze_dat_folder',
    'analyze_source_candidates',
    'format_analysis_summary',
    'print_analysis_summary',
    'find_roms_not_in_dat',
    'move_files_to_tosort',
    'build_dat_md5_lookup',
    'detect_system_name',
]