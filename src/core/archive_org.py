import os
import re
import time
from urllib.parse import quote

import requests

from .env import APP_ROOT, DOWNLOAD_CHUNK_SIZE


ARCHIVE_CHECKSUM_QUERY_FIELDS = {
    'md5': ['md5'],
    'crc': ['crc32', 'crc'],
    'sha1': ['sha1']
}

ARCHIVE_CHECKSUM_FILE_FIELDS = {
    'md5': ['md5'],
    'crc': ['crc32', 'crc'],
    'sha1': ['sha1']
}

ARCHIVE_SEARCH_TIMEOUT = 20
ARCHIVE_ITEM_TIMEOUT = 30
ARCHIVE_CHECKSUM_RESULT_LIMIT = 20
ARCHIVE_NAME_RESULT_LIMIT = 10
ARCHIVE_NAME_COLLECTIONS = ('softwarelibrary', 'retrogames', '')
ARCHIVE_CHECKSUM_NAME_CROSSCHECK = False


def search_archive_items_limited(query: str, limit: int) -> list:
    from .dependencies import import_optional_package
    internetarchive = import_optional_package('internetarchive')
    return list(__import__('itertools').islice(
        internetarchive.search_items(
            query,
            request_kwargs={'timeout': ARCHIVE_SEARCH_TIMEOUT}
        ),
        limit
    ))


def get_archive_item_files(identifier: str):
    from .dependencies import import_optional_package
    internetarchive = import_optional_package('internetarchive')
    item = internetarchive.get_item(
        identifier,
        request_kwargs={'timeout': ARCHIVE_ITEM_TIMEOUT}
    )
    return item.get_files()


def archive_org_result(identifier: str, file_name: str, checksum_type: str, checksum_value: str, source: str) -> dict:
    return {
        'found': True,
        'identifier': identifier,
        'filename': file_name,
        checksum_type: checksum_value,
        'checksum_type': checksum_type,
        'source': source
    }


def archive_org_matches_name(file_name: str, rom_name: str) -> bool:
    from ._facade import strip_rom_extension
    if not file_name or not rom_name:
        return False

    file_lower = file_name.lower()
    rom_lower = rom_name.lower()
    clean_name = rom_lower.split('(')[0].strip()
    return (
        rom_lower in file_lower
        or clean_name in file_lower
        or strip_rom_extension(file_name).lower() == strip_rom_extension(rom_name).lower()
    )


def get_archive_file_checksum(file_info: dict, checksum_type: str) -> str:
    from ._facade import normalize_checksum
    for field_name in ARCHIVE_CHECKSUM_FILE_FIELDS.get(checksum_type, []):
        checksum_value = normalize_checksum(file_info.get(field_name, ''), checksum_type)
        if checksum_value:
            return checksum_value
    return ''


def search_archive_org_by_checksum(checksum_value: str, rom_name: str, checksum_type: str) -> dict:
    from ._facade import normalize_checksum
    normalized_checksum = normalize_checksum(checksum_value, checksum_type)
    if not normalized_checksum:
        return {'found': False}

    label = checksum_type.upper()
    strategies_tried = []
    query_fields = ARCHIVE_CHECKSUM_QUERY_FIELDS.get(checksum_type, [checksum_type])

    print(f"  Recherche archive.org par {label}: {normalized_checksum}")

    for query_field in query_fields:
        try:
            query = f'{query_field}:{normalized_checksum}'
            print(f"    -> Recherche: {query}")
            results = search_archive_items_limited(query, ARCHIVE_CHECKSUM_RESULT_LIMIT)

            for result in results:
                identifier = result.get('identifier', '')
                if not identifier:
                    continue

                try:
                    files = get_archive_item_files(identifier)

                    for file_info in files:
                        file_name = file_info.get('name', '')
                        file_checksum = get_archive_file_checksum(file_info, checksum_type)
                        if file_checksum and file_checksum == normalized_checksum:
                            print(f"    [OK] Trouve: {identifier}/{file_name}")
                            return archive_org_result(identifier, file_name, checksum_type, normalized_checksum, f'archive_org_{checksum_type}')
                except Exception:
                    continue

            strategies_tried.append(query_field)
        except Exception as e:
            print(f"    [ERREUR] Recherche {label}: {e}")
            strategies_tried.append(f'{query_field}_error: {e}')

    if rom_name and ARCHIVE_CHECKSUM_NAME_CROSSCHECK:
        clean_name = rom_name.split('(')[0].strip()
        quoted_name = f'"{clean_name}"' if clean_name else ''

        for collection in ARCHIVE_NAME_COLLECTIONS:
            try:
                query = f'{quoted_name} AND collection:{collection}' if collection else quoted_name
                print(f"    -> Recherche nom: {query[:50]}...")
                results = search_archive_items_limited(query, ARCHIVE_NAME_RESULT_LIMIT)

                for result in results:
                    identifier = result.get('identifier', '')
                    if not identifier:
                        continue

                    try:
                        files = get_archive_item_files(identifier)

                        for file_info in files:
                            file_name = file_info.get('name', '')
                            if not archive_org_matches_name(file_info.get('name', ''), rom_name):
                                continue

                            file_checksum = get_archive_file_checksum(file_info, checksum_type)
                            if file_checksum and file_checksum == normalized_checksum:
                                print(f"    [OK] Trouve (nom+{label}): {identifier}/{file_name}")
                                return archive_org_result(identifier, file_name, checksum_type, normalized_checksum, f'archive_org_{checksum_type}')
                    except Exception:
                        continue

                strategies_tried.append(f'name_{collection or "all"}')
            except Exception as e:
                strategies_tried.append(f'name_error_{collection}: {e}')

    print(f"  [KO] Non trouve sur archive.org (strategies: {', '.join(strategies_tried)})")
    return {'found': False, 'strategies_tried': strategies_tried}


def search_archive_org_by_md5(md5_hash: str, rom_name: str) -> dict:
    return search_archive_org_by_checksum(md5_hash, rom_name, 'md5')


def search_archive_org_by_crc(crc_hash: str, rom_name: str) -> dict:
    return search_archive_org_by_checksum(crc_hash, rom_name, 'crc')


def search_archive_org_by_sha1(sha1_hash: str, rom_name: str) -> dict:
    return search_archive_org_by_checksum(sha1_hash, rom_name, 'sha1')


def download_from_ia_zip(identifier: str, zip_path: str, filename: str, dest_path: str, progress_callback=None) -> bool:
    try:
        url = f"https://archive.org/download/{identifier}/{quote(zip_path.replace(chr(92), '/'))}/{quote(filename.replace(chr(92), '/'))}"

        print(f"  Tentative IA-ZIP: {identifier}/{zip_path}/{filename}")

        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})

        access_key = os.environ.get('IAS3_ACCESS_KEY')
        secret_key = os.environ.get('IAS3_SECRET_KEY')
        auth = None
        if access_key and secret_key:
            from requests.auth import HTTPBasicAuth
            auth = HTTPBasicAuth(access_key, secret_key)

        resp = session.get(url, stream=True, allow_redirects=True, timeout=120, auth=auth)

        if "view_archive.php" in resp.url and "file=" not in resp.url:
            final_url = f"{resp.url}&file={quote(filename)}"
            print(f"  Redirection view_archive: {final_url}")
            resp = session.get(final_url, stream=True, allow_redirects=True, timeout=120, auth=auth)

        if resp.status_code == 503:
            print("  [WARN] Service IA (view_archive) temporairement indisponible (503)")
            return False

        resp.raise_for_status()

        total = int(resp.headers.get('content-length', 0))
        downloaded = 0

        with open(dest_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0 and progress_callback:
                        progress_callback((downloaded / total) * 100)

        if progress_callback:
            progress_callback(100.0)
        return True
    except Exception as e:
        print(f"  [ERREUR] IA-ZIP: {e}")
        return False


def search_archive_org_by_name(rom_name: str, rom_extension: str = '.zip') -> dict:
    if not rom_name:
        return {'found': False}

    print(f"  Recherche archive.org par nom: {rom_name}")

    try:
        query = f'"{rom_name}" AND collection:No-Intro'
        results = search_archive_items_limited(query, ARCHIVE_CHECKSUM_RESULT_LIMIT)

        for result in results:
            identifier = result.get('identifier', '')
            if not identifier:
                continue

            try:
                files = get_archive_item_files(identifier)

                for file_info in files:
                    file_name = file_info.get('name', '')
                    if rom_name.lower() in file_name.lower() or file_name.lower() in rom_name.lower():
                        if file_name.endswith(rom_extension) or file_name.endswith('.gb') or file_name.endswith('.zip'):
                            print(f"  Trouve sur archive.org: {identifier}/{file_name}")
                            return {
                                'found': True,
                                'identifier': identifier,
                                'filename': file_name,
                                'source': 'archive_org_name'
                            }
            except Exception as e:
                continue

        query = f'"{rom_name}"'
        results = search_archive_items_limited(query, ARCHIVE_NAME_RESULT_LIMIT)

        for result in results:
            identifier = result.get('identifier', '')
            if not identifier:
                continue

            try:
                files = get_archive_item_files(identifier)

                for file_info in files:
                    file_name = file_info.get('name', '')
                    if rom_name.lower() in file_name.lower():
                        if file_name.endswith(('.zip', '.gb', '.7z', '.rar')):
                            print(f"  Trouve sur archive.org (sans collection): {identifier}/{file_name}")
                            return {
                                'found': True,
                                'identifier': identifier,
                                'filename': file_name,
                                'source': 'archive_org_name'
                            }
            except Exception as e:
                continue

        print(f"  Non trouve sur archive.org avec le nom: {rom_name}")
        return {'found': False}

    except Exception as e:
        print(f"  Erreur recherche archive.org par nom: {e}")
        return {'found': False}


def download_from_archive_org(identifier: str, filename: str, dest_path: str, session: requests.Session = None, progress_callback=None) -> bool:
    from .dependencies import import_optional_package
    internetarchive = import_optional_package('internetarchive')
    max_retries = 3

    for attempt in range(max_retries):
        try:
            print(f"  Telechargement depuis archive.org: {identifier}/{filename}")

            item = internetarchive.get_item(identifier)
            file_obj = item.get_file(filename)

            if file_obj is None:
                print(f"  Fichier non trouve: {filename}")
                return False

            response = file_obj.download()

            if hasattr(response, 'iter_content'):
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0

                with open(dest_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0 and progress_callback:
                                progress_callback((downloaded / total_size) * 100)
            else:
                file_obj.download(dest_path)

            if progress_callback:
                progress_callback(100.0)

            print(f"  Telechargement termine: {dest_path}")
            return True

        except Exception as e:
            print(f"  [WARN] Tentative internetarchive {attempt + 1}/{max_retries} echouee: {e}")
            if os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                except Exception:
                    pass

            try:
                download_url = f"https://archive.org/download/{identifier}/{quote(filename)}"
                print(f"  Fallback HTTP direct: {download_url}")
                if session is None:
                    session = requests.Session()
                    session.headers.update({'User-Agent': 'Mozilla/5.0'})

                auth = None
                access_key = os.environ.get('IAS3_ACCESS_KEY', '')
                secret_key = os.environ.get('IAS3_SECRET_KEY', '')
                if access_key and secret_key:
                    from requests.auth import HTTPBasicAuth
                    auth = HTTPBasicAuth(access_key, secret_key)

                with session.get(download_url, stream=True, allow_redirects=True, timeout=120, auth=auth) as response:
                    response.raise_for_status()
                    total_size = int(response.headers.get('content-length', 0))
                    downloaded = 0

                    with open(dest_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if total_size > 0 and progress_callback:
                                    progress_callback((downloaded / total_size) * 100)

                if progress_callback:
                    progress_callback(100.0)

                if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
                    print(f"  Telechargement HTTP archive.org termine: {dest_path}")
                    return True
            except Exception as http_error:
                print(f"  [WARN] Fallback HTTP archive.org echouee: {http_error}")
                if os.path.exists(dest_path):
                    try:
                        os.remove(dest_path)
                    except Exception:
                        pass

            if attempt < max_retries - 1:
                time.sleep(2)

    return False


__all__ = [
    'ARCHIVE_CHECKSUM_QUERY_FIELDS',
    'ARCHIVE_CHECKSUM_FILE_FIELDS',
    'ARCHIVE_SEARCH_TIMEOUT',
    'ARCHIVE_ITEM_TIMEOUT',
    'ARCHIVE_CHECKSUM_RESULT_LIMIT',
    'ARCHIVE_NAME_RESULT_LIMIT',
    'ARCHIVE_NAME_COLLECTIONS',
    'ARCHIVE_CHECKSUM_NAME_CROSSCHECK',
    'search_archive_items_limited',
    'get_archive_item_files',
    'archive_org_result',
    'archive_org_matches_name',
    'get_archive_file_checksum',
    'search_archive_org_by_checksum',
    'search_archive_org_by_md5',
    'search_archive_org_by_crc',
    'search_archive_org_by_sha1',
    'download_from_ia_zip',
    'download_from_archive_org',
    'search_archive_org_by_name',
]