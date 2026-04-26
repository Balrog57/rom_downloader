import html as html_module
import os
import re
import time

import requests

from .api_keys import is_1fichier_url, load_api_keys
from .env import DOWNLOAD_CHUNK_SIZE
from . import rom_database as _rom_db


WAIT_REGEXES_1F = [
    r'var\s+ct\s*=\s*(\d+)\s*\*\s*60',
    r'var\s+ct\s*=\s*(\d+)\s*\*60',
    r'(?:veuillez\s+)?patiente[rz]\s*(\d+)\s*(?:min|minute)s?\b',
    r'please\s+wait\s*(\d+)\s*(?:min|minute)s?\b',
    r'(?:veuillez\s+)?patiente[rz]\s*(\d+)\s*(?:sec|secondes?|s)\b',
    r'please\s+wait\s*(\d+)\s*(?:sec|seconds?)\b',
    r'var\s+ct\s*=\s*(\d+)\s*;',
]


def extract_wait_seconds_1f(html_text: str) -> int:
    for i, pattern in enumerate(WAIT_REGEXES_1F):
        match = re.search(pattern, html_text, re.IGNORECASE)
        if match:
            value = int(match.group(1))
            if i < 2 or 'min' in pattern.lower():
                seconds = value * 60
            else:
                seconds = value
            return seconds
    return 0


def download_1fichier_free(url: str, dest_path: str, session: requests.Session, progress_callback=None) -> bool:
    try:
        response = session.get(url, allow_redirects=True, timeout=30)
        response.raise_for_status()
        html = response.text

        wait_seconds = extract_wait_seconds_1f(html)
        if wait_seconds > 0:
            print(f"  Attente: {wait_seconds} secondes...")
            for remaining in range(wait_seconds, 0, -1):
                time.sleep(1)

        form_match = re.search(r'<form[^>]*id=[\"\']f1[\"\'][^>]*>(.*?)</form>', html, re.DOTALL | re.IGNORECASE)
        if form_match:
            form_html = form_match.group(1)
            data = {}
            for inp_match in re.finditer(r'<input[^>]+>', form_html, re.IGNORECASE):
                inp = inp_match.group(0)
                name_m = re.search(r'name=[\"\']([^\"\']+)', inp)
                value_m = re.search(r'value=[\"\']([^\"\']*)', inp)
                if name_m:
                    name = name_m.group(1)
                    value = html_module.unescape(value_m.group(1) if value_m else '')
                    data[name] = value

            response = session.post(str(response.url), data=data, allow_redirects=True, timeout=30)
            response.raise_for_status()
            html = response.text

        patterns = [
            r'href=[\"\']([^\"\']+)[\"\'][^>]*>(?:cliquer|click|télécharger|download)',
            r'href=[\"\']([^\"\']*/dl/[^\"\']+)',
            r'(https?://[a-z0-9.-]*1fichier\.com/[A-Za-z0-9]{8,})'
        ]

        from urllib.parse import urljoin
        direct_link = None
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                captured = match.group(1)
                direct_link = captured if captured.startswith(('http://', 'https://')) else urljoin(str(response.url), captured)
                if any(x in direct_link.lower() for x in ['/register', '/login', '/inscription']):
                    continue
                break

        if not direct_link:
            print(f"  Erreur: Lien de telechargement introuvable")
            return False

        with session.get(direct_link, stream=True, allow_redirects=True, timeout=120) as resp:
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
        print(f"  Erreur 1fichier (mode gratuit): {e}")
        return False


def download_1fichier(file_id: str, dest_path: str, api_key: str, progress_callback=None) -> bool:
    if not api_key:
        print("  Erreur: Cle API 1fichier manquante")
        return False

    try:
        config = _rom_db.ROM_DATABASE.get('config_urls', {})
        api_url = config.get('1fichier_getlink', '')
        params = {
            'apikey': api_key,
            'file_id': file_id
        }

        response = requests.post(api_url, data=params, timeout=30)

        if response.status_code != 200:
            print(f"  Erreur API 1fichier: {response.status_code}")
            return False

        result = response.json()

        if result.get('status') != 'OK':
            print(f"  Erreur: {result.get('message', 'Unknown error')}")
            return False

        download_url = result.get('download_url')
        if not download_url:
            print("  Erreur: Pas d'URL de telechargement")
            return False

        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})

        with session.get(download_url, stream=True, allow_redirects=True, timeout=120) as resp:
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
        print(f"  Erreur 1fichier (API): {e}")
        return False


def download_alldebrid(url: str, dest_path: str, api_key: str, progress_callback=None) -> bool:
    if not api_key:
        print("  Erreur: Cle API AllDebrid manquante")
        return False

    try:
        config = _rom_db.ROM_DATABASE.get('config_urls', {})
        api_url = config.get('alldebrid_unlock', '')
        params = {
            'agent': 'rom_downloader',
            'apikey': api_key,
            'link': url
        }

        response = requests.get(api_url, params=params, timeout=30)

        if response.status_code != 200:
            print(f"  Erreur API AllDebrid: {response.status_code}")
            return False

        result = response.json()

        if result.get('status') != 'success':
            error = result.get('error', {})
            print(f"  Erreur: {error.get('message', 'Unknown error')}")
            return False

        download_url = result.get('data', {}).get('downloadLink')
        if not download_url:
            print("  Erreur: Pas d'URL de telechargement")
            return False

        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})

        with session.get(download_url, stream=True, allow_redirects=True, timeout=120) as resp:
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
        print(f"  Erreur AllDebrid: {e}")
        return False


def download_realdebrid(url: str, dest_path: str, api_key: str, progress_callback=None) -> bool:
    if not api_key:
        print("  Erreur: Cle API RealDebrid manquante")
        return False

    try:
        config = _rom_db.ROM_DATABASE.get('config_urls', {})
        api_url = config.get('realdebrid_unlock', '')
        params = {
            'auth_token': api_key,
            'link': url
        }

        response = requests.post(api_url, data=params, timeout=30)

        if response.status_code != 200:
            print(f"  Erreur API RealDebrid: {response.status_code}")
            return False

        result = response.json()

        if 'error' in result:
            print(f"  Erreur: {result.get('error', 'Unknown error')}")
            return False

        download_url = result.get('download')
        if not download_url:
            print("  Erreur: Pas d'URL de telechargement")
            return False

        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})

        with session.get(download_url, stream=True, allow_redirects=True, timeout=120) as resp:
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
        print(f"  Erreur RealDebrid: {e}")
        return False


def download_from_premium_source(source_type: str, url: str, dest_path: str,
                                api_keys: dict, progress_callback=None) -> bool:
    if source_type == '1fichier':
        api_key = api_keys.get('1fichier', '')

        if api_key:
            file_id = url.split('?')[-1].split('#')[0] if '?' in url else ''
            if file_id:
                result = download_1fichier(file_id, dest_path, api_key, progress_callback)
                if result:
                    return True

        alldebrid_key = api_keys.get('alldebrid', '')
        if alldebrid_key:
            print("  Tentative via AllDebrid...")
            if download_alldebrid(url, dest_path, alldebrid_key, progress_callback):
                return True

        realdebrid_key = api_keys.get('realdebrid', '')
        if realdebrid_key:
            print("  Tentative via RealDebrid...")
            if download_realdebrid(url, dest_path, realdebrid_key, progress_callback):
                return True

        print("  Bascule en mode gratuit 1fichier...")
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})
        return download_1fichier_free(url, dest_path, session, progress_callback)

    elif source_type == 'alldebrid':
        return download_alldebrid(url, dest_path, api_keys.get('alldebrid', ''), progress_callback)

    elif source_type == 'realdebrid':
        return download_realdebrid(url, dest_path, api_keys.get('realdebrid', ''), progress_callback)

    return False


__all__ = [
    'WAIT_REGEXES_1F',
    'extract_wait_seconds_1f',
    'download_1fichier_free',
    'download_1fichier',
    'download_alldebrid',
    'download_realdebrid',
    'download_from_premium_source',
]