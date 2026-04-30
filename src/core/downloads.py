import os
import re
import time
from urllib.parse import unquote

import requests

from ..progress import DownloadProgressMeter, format_duration
from ..network.sessions import create_optimized_session
from ..network.utils import format_bytes
from ..network.exceptions import SourceTimeoutError, DownloadNetworkError, ResumeNotSupportedError

from .env import DOWNLOAD_CHUNK_SIZE
from .constants import *
from .sources import source_timeout_seconds


def download_file_legacy(url: str, dest_path: str, session: requests.Session, progress_callback=None) -> bool:
    """Download a file from URL to destination path with retry support."""
    max_retries = 3
    retry_delay = 5

    for attempt in range(max_retries):
        try:
            request_kwargs = {
                'stream': True,
                'timeout': 120,
                'allow_redirects': True,
            }
            archive_hosts = ('archive.org', '.archive.org')
            if any(host in (url or '').lower() for host in archive_hosts):
                access_key = os.environ.get('IAS3_ACCESS_KEY', '')
                secret_key = os.environ.get('IAS3_SECRET_KEY', '')
                if access_key and secret_key:
                    from requests.auth import HTTPBasicAuth
                    request_kwargs['auth'] = HTTPBasicAuth(access_key, secret_key)

            with session.get(url, **request_kwargs) as response:
                response.raise_for_status()

                server_filename = ''
                cd = response.headers.get('content-disposition', '')
                match = re.search(r'filename=(?:"([^"]+)"|([^;]+))', cd, re.IGNORECASE)
                if match:
                    server_filename = match.group(1) or match.group(2)
                
                if not server_filename:
                    server_filename = os.path.basename(unquote(response.url.split('?')[0]))
                
                if server_filename:
                    server_filename = re.sub(r'[\\/*?:"<>|]', "", server_filename)
                    dest_path = os.path.join(os.path.dirname(dest_path), server_filename)

                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0

                with open(dest_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)

                            if total_size > 0 and progress_callback:
                                progress = (downloaded / total_size) * 100
                                progress_callback(progress)

                if progress_callback:
                    progress_callback(100.0)
                return True

        except (requests.Timeout, requests.exceptions.ConnectTimeout,
                requests.exceptions.ReadTimeout) as e:
            print(f"  Tentative {attempt + 1}/{max_retries} echouee (timeout): {e}")
            if os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                except:
                    pass
            if attempt < max_retries - 1:
                print(f"  Nouvelle tentative dans {retry_delay} secondes...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                raise SourceTimeoutError(str(e)) from e
        except Exception as e:
            print(f"  Tentative {attempt + 1}/{max_retries} echouee: {e}")
            if os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                except:
                    pass
            if attempt < max_retries - 1:
                print(f"  Nouvelle tentative dans {retry_delay} secondes...")
                time.sleep(retry_delay)
                retry_delay *= 2

    return False


def _response_preview(response: requests.Response, max_bytes: int = 512) -> str:
    """Retourne un court extrait de reponse sans lever d'erreur secondaire."""
    try:
        preview = response.raw.read(max_bytes, decode_content=True)
        return preview.decode('utf-8', errors='ignore').strip()[:200]
    except Exception:
        try:
            return response.text.strip()[:200]
        except Exception:
            return ''


def _looks_like_cloudflare_block(response: requests.Response, snippet: str) -> bool:
    server = (response.headers.get('server') or '').lower()
    content_type = (response.headers.get('content-type') or '').lower()
    text = (snippet or '').lower()

    cf_headers = {'cf-ray', 'cf-cache-status', 'cf-request-id'}
    if cf_headers.intersection(set(k.lower() for k in response.headers.keys())):
        if response.status_code >= 400:
            return True

    if response.status_code in {403, 429, 503}:
        if 'cloudflare' in server or 'text/html' in content_type:
            if not text:
                return True
            return any(marker in text for marker in (
                'just a moment',
                'attention required',
                'cloudflare',
                'cf-ray',
                'challenge-platform',
                'ddos-guard',
                'under attack mode',
                'checking your browser',
                'enable javascript',
            ))
    return False


def download_file(url: str, dest_path: str, session: requests.Session, progress_callback=None,
                  timeout_seconds: int = 120, progress_detail_callback=None,
                  extra_headers: dict | None = None) -> bool:
    """Download a file with retry, larger chunks and resumable .part files."""
    max_retries = 3
    retry_delay = 3
    timeout_seconds = source_timeout_seconds({'timeout_seconds': timeout_seconds}, 120)

    for attempt in range(max_retries):
        current_dest_path = dest_path
        part_path = current_dest_path + '.part'
        try:
            resume_from = os.path.getsize(part_path) if os.path.exists(part_path) else 0
            request_kwargs = {
                'stream': True,
                'timeout': timeout_seconds,
                'allow_redirects': True,
            }
            headers = dict(extra_headers or {})
            if resume_from > 0:
                headers['Range'] = f'bytes={resume_from}-'
            if headers:
                request_kwargs['headers'] = headers
            archive_hosts = ('archive.org', '.archive.org')
            if any(host in (url or '').lower() for host in archive_hosts):
                access_key = os.environ.get('IAS3_ACCESS_KEY', '')
                secret_key = os.environ.get('IAS3_SECRET_KEY', '')
                if access_key and secret_key:
                    from requests.auth import HTTPBasicAuth
                    request_kwargs['auth'] = HTTPBasicAuth(access_key, secret_key)

            with session.get(url, **request_kwargs) as response:
                content_type = (response.headers.get('content-type', '') or '').lower()
                if response.status_code >= 400:
                    snippet = _response_preview(response)
                    if _looks_like_cloudflare_block(response, snippet):
                        raise DownloadNetworkError(
                            f"Blocage Cloudflare ({response.status_code}) pour {response.url}: {snippet}"
                        )
                    response.raise_for_status()

                if 'text/html' in content_type and not url.lower().endswith('.html'):
                    snippet = _response_preview(response)
                    if _looks_like_cloudflare_block(response, snippet):
                        raise DownloadNetworkError(
                            f"Blocage Cloudflare ({response.status_code}) pour {response.url}: {snippet}"
                        )
                    raise DownloadNetworkError(
                        f"Reponse HTML inattendue (Cloudflare?): {snippet}"
                    )

                server_filename = ''
                cd = response.headers.get('content-disposition', '')
                match = re.search(r'filename=(?:"([^"]+)"|([^;]+))', cd, re.IGNORECASE)
                if match:
                    server_filename = match.group(1) or match.group(2)
                if not server_filename:
                    server_filename = os.path.basename(unquote(response.url.split('?')[0]))
                if server_filename:
                    server_filename = re.sub(r'[\\/*?:"<>|]', "", server_filename)
                    current_dest_path = os.path.join(os.path.dirname(dest_path), server_filename)
                    part_path = current_dest_path + '.part'
                    resume_from = os.path.getsize(part_path) if os.path.exists(part_path) else 0

                content_length = int(response.headers.get('content-length', 0))
                content_range = response.headers.get('content-range', '')
                total_size = content_length
                if content_range and '/' in content_range:
                    try:
                        total_size = int(content_range.rsplit('/', 1)[1])
                    except Exception:
                        total_size = content_length + resume_from
                elif resume_from and response.status_code == 206:
                    total_size = content_length + resume_from

                if resume_from and response.status_code != 206:
                    raise ResumeNotSupportedError(
                        f"Serveur retourne {response.status_code} au lieu de 206 pour Range bytes={resume_from}-"
                    )

                downloaded = resume_from
                progress_meter = DownloadProgressMeter(total_size, resume_from)
                mode = 'ab' if resume_from and response.status_code == 206 else 'wb'
                with open(part_path, mode) as handle:
                    for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0 and progress_callback:
                            progress_callback((downloaded / total_size) * 100)
                        progress_snapshot = progress_meter.snapshot(downloaded)
                        if progress_snapshot:
                            if progress_detail_callback:
                                progress_detail_callback(progress_snapshot)
                            print(
                                f"  Progression: {progress_snapshot['percent']:.1f}% "
                                f"- {format_bytes(progress_snapshot['speed'])}/s - "
                                f"ETA {format_duration(progress_snapshot['eta'])}"
                            )

                if progress_callback:
                    progress_callback(100.0)
                os.replace(part_path, current_dest_path)
                return True

        except (requests.Timeout, requests.exceptions.ConnectTimeout,
                requests.exceptions.ReadTimeout) as e:
            print(f"  Tentative {attempt + 1}/{max_retries} echouee (timeout): {e}")
            if attempt < max_retries - 1:
                print(f"  Nouvelle tentative dans {retry_delay} secondes...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                raise SourceTimeoutError(str(e)) from e
        except requests.exceptions.HTTPError as e:
            print(f"  Tentative {attempt + 1}/{max_retries} echouee (HTTP): {e}")
            if attempt < max_retries - 1:
                print(f"  Nouvelle tentative dans {retry_delay} secondes...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                raise DownloadNetworkError(str(e)) from e
        except (ResumeNotSupportedError, SourceTimeoutError, DownloadNetworkError):
            raise
        except Exception as e:
            print(f"  Tentative {attempt + 1}/{max_retries} echouee: {e}")
            if attempt < max_retries - 1:
                print(f"  Nouvelle tentative dans {retry_delay} secondes...")
                time.sleep(retry_delay)
                retry_delay *= 2

    return False


def download_from_archive_org(identifier: str, filename: str, dest_path: str, session: requests.Session = None, progress_callback=None) -> bool:
    """Download a specific file from archive.org by identifier and filename."""
    from .archive_org import download_from_archive_org as _impl
    return _impl(identifier, filename, dest_path, session, progress_callback)


__all__ = [
    'download_file_legacy',
    'download_file',
    'download_from_archive_org',
]
