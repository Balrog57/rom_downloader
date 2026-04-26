import html as html_module
import re

from urllib.parse import quote, urljoin

from .constants import (
    MINERVA_BROWSE_BASE,
    MINERVA_TORRENT_BASE_CANDIDATES,
    MINERVA_TORRENT_AVAILABILITY,
    MINERVA_TORRENT_URL_CACHE,
    ROM_EXTENSIONS,
)
from .env import APP_ROOT
from .sources import normalize_source_label, get_default_sources
from .rom_database import (
    is_minerva_database_result,
    search_by_md5,
    search_by_crc,
    search_by_sha1,
    search_by_name,
)


def build_minerva_directory_url(source: dict, system_name: str | None) -> str:
    base_url = source.get('base_url', '').rstrip('/') + '/'
    if source.get('fixed_directory'):
        return base_url
    if not system_name:
        return base_url

    path_mode = source.get('minerva_path_mode', 'single')
    if path_mode == 'split':
        segments = [segment.strip() for segment in system_name.split(' - ') if segment.strip()]
    else:
        segments = [system_name.strip()]

    if not segments:
        return base_url

    return base_url + '/'.join(quote(segment) for segment in segments) + '/'


def build_minerva_torrent_name(source: dict, system_name: str | None) -> str:
    collection = source.get('collection', '').strip()
    if not collection:
        return ''

    if system_name:
        if source.get('torrent_scope') == 'vendor':
            target = system_name.split(' - ')[0].strip()
        else:
            target = system_name.strip()
    else:
        target = ''

    if not target:
        return ''

    return f"Minerva_Myrient - {collection} - {target}.torrent"


def build_minerva_torrent_urls(source: dict, system_name: str | None) -> list[str]:
    torrent_name = build_minerva_torrent_name(source, system_name)
    if not torrent_name:
        return []

    quoted_name = quote(torrent_name)
    return [urljoin(base_url, quoted_name) for base_url in MINERVA_TORRENT_BASE_CANDIDATES]


def is_minerva_torrent_available(torrent_url: str, session) -> bool:
    if not torrent_url:
        return False

    cached = MINERVA_TORRENT_AVAILABILITY.get(torrent_url)
    if cached is not None:
        return cached

    try:
        response = session.get(torrent_url, timeout=20, stream=True, allow_redirects=True)
        available = response.status_code == 200
        response.close()
    except Exception:
        available = False

    MINERVA_TORRENT_AVAILABILITY[torrent_url] = available
    return available


def resolve_minerva_torrent_url(source: dict, system_name: str | None, session) -> str:
    torrent_name = build_minerva_torrent_name(source, system_name)
    if not torrent_name:
        return ''

    cached = MINERVA_TORRENT_URL_CACHE.get(torrent_name)
    if cached is not None:
        return cached

    for torrent_url in build_minerva_torrent_urls(source, system_name):
        if is_minerva_torrent_available(torrent_url, session):
            MINERVA_TORRENT_URL_CACHE[torrent_name] = torrent_url
            return torrent_url

    MINERVA_TORRENT_URL_CACHE[torrent_name] = ''
    return ''


def list_minerva_directory(minerva_url: str, session) -> tuple[set, list]:
    print(f"Fetching Minerva directory listing: {minerva_url}")
    from ..network.cache import load_listing_cache_file, save_listing_cache_file, listing_cache_get, listing_cache_set
    cache = load_listing_cache_file()
    cache_key = f"minerva:{minerva_url}"
    cached = listing_cache_get(cache, cache_key)
    if cached:
        print("  Listing Minerva depuis le cache")
        return set(cached.get('files', [])), list(cached.get('directories', []))

    files = set()
    directories = []

    try:
        response = session.get(minerva_url, timeout=60)
        if response.status_code != 200:
            print(f"Erreur Minerva ({response.status_code}) pour {minerva_url}")
            return files, directories

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        seen_dirs = set()
        for link in soup.find_all('a', href=True):
            href = html_module.unescape(link.get('href', '')).strip()
            text = html_module.unescape(link.get_text().strip())

            if not href or not text or text in {'Home', 'Browse', 'Search', 'Contact Us', 'FAQ', 'DMCA', 'Root', '../'}:
                continue

            if href.startswith('/rom'):
                if text.lower().endswith(ROM_EXTENSIONS):
                    files.add(text.rstrip('/'))
                continue

            if '/browse/' in href and text.endswith('/'):
                directory_url = urljoin(MINERVA_BROWSE_BASE, href.replace('/browse/', ''))
                normalized = directory_url.rstrip('/').lower()
                if normalized not in seen_dirs:
                    seen_dirs.add(normalized)
                    directories.append({
                        'name': text.rstrip('/'),
                        'url': directory_url
                    })

        print(f"Found {len(files)} files and {len(directories)} subdirectories on Minerva")
        listing_cache_set(cache, cache_key, {'files': sorted(files), 'directories': directories})
        save_listing_cache_file(cache)
    except Exception as e:
        print(f"Error fetching Minerva directory: {e}")

    return files, directories


def collect_minerva_files_from_url(minerva_url: str, session, depth: int = 0) -> set:
    files, directories = list_minerva_directory(minerva_url, session)
    if depth <= 0 or not directories:
        return files

    collected = set(files)
    for directory in directories:
        collected.update(collect_minerva_files_from_url(directory['url'], session, depth - 1))
    return collected


def select_database_result(db_results: list) -> dict | None:
    candidates = []
    for result in db_results:
        if is_minerva_database_result(result):
            continue
        host = (result.get('host') or '').lower()
        url = (result.get('url') or '').lower()
        if 'myrient' in host or 'myrient' in url:
            continue
        if 'archive.org' in host or 'archive.org' in url:
            continue
        candidates.append(result)

    if not candidates:
        return None

    for result in candidates:
        host = (result.get('host') or '').lower()
        url = (result.get('url') or '').lower()
        if '1fichier.com' in host or '1fichier.com' in url:
            return result

    return candidates[0]


def search_database_for_game(game_info: dict) -> tuple[list, str]:
    from ._facade import normalize_checksum, strip_rom_extension
    roms = game_info.get('roms', [])
    search_plan = [
        ('MD5', 'md5', search_by_md5),
        ('CRC', 'crc', search_by_crc),
        ('SHA1', 'sha1', search_by_sha1)
    ]

    for label, checksum_type, resolver in search_plan:
        for rom_info in roms:
            checksum_value = normalize_checksum(rom_info.get(checksum_type, ''), checksum_type)
            if not checksum_value:
                continue
            results = resolver(checksum_value)
            if results:
                return results, f"{label}: {checksum_value}"

    primary_rom = game_info.get('primary_rom', '')
    primary_name = strip_rom_extension(primary_rom).strip()
    if primary_name:
        results = search_by_name(primary_name)
        if results:
            return results, f"nom ROM: {primary_name}"

    game_name = game_info.get('game_name', '')
    if game_name:
        results = search_by_name(game_name)
        if results:
            return results, f"nom jeu: {game_name}"

    return [], ''


def search_minerva_hash_database_for_game(game_info: dict) -> dict | None:
    from ._facade import normalize_checksum
    for rom_info in game_info.get('roms', []):
        md5_value = normalize_checksum(rom_info.get('md5', ''), 'md5')
        if not md5_value:
            continue

        for result in search_by_md5(md5_value):
            if not is_minerva_database_result(result):
                continue
            torrent_url = result.get('torrent_url') or result.get('url')
            if not torrent_url:
                continue

            file_name = result.get('file_name') or result.get('filename') or result.get('full_name') or rom_info.get('name')
            full_path = result.get('full_path') or file_name
            resolved = game_info.copy()
            resolved['source'] = 'Minerva Official Hashes'
            resolved['database_host'] = 'minerva-torrent'
            resolved['download_filename'] = file_name
            resolved['torrent_target_filename'] = full_path
            resolved['torrent_url'] = torrent_url
            resolved['minerva_md5'] = md5_value
            resolved['minerva_full_path'] = full_path
            resolved['minerva_torrent_path'] = result.get('torrent_path', '')
            return resolved

    return None


def search_minerva_hash_database_for_games(missing_games: list) -> tuple[list, list]:
    found = []
    still_missing = []
    for game_info in missing_games:
        resolved = search_minerva_hash_database_for_game(game_info)
        if resolved:
            found.append(resolved)
            print(f"  [Minerva hashes] {game_info['game_name']} -> {resolved.get('download_filename')}")
        else:
            still_missing.append(game_info)
    return found, still_missing


__all__ = [
    'build_minerva_directory_url',
    'build_minerva_torrent_name',
    'build_minerva_torrent_urls',
    'is_minerva_torrent_available',
    'resolve_minerva_torrent_url',
    'list_minerva_directory',
    'collect_minerva_files_from_url',
    'select_database_result',
    'search_database_for_game',
    'search_minerva_hash_database_for_game',
    'search_minerva_hash_database_for_games',
]