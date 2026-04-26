"""Gestion optimisee des sessions HTTP (pooling, retries, timeouts, chunks)."""

from __future__ import annotations

import os

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_CHUNK_SIZE = 256 * 1024
DEFAULT_TIMEOUT_SECONDS = 120


def create_optimized_session(
    pool_connections: int = 20,
    pool_maxsize: int = 20,
    max_retries: int = 3,
    backoff_factor: float = 1.0,
    status_forcelist: tuple[int, ...] = (502, 503, 504),
) -> requests.Session:
    """Cree une session HTTP avec pooling agressif et retry automatique."""
    session = requests.Session()
    retry = Retry(
        total=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=list(status_forcelist),
        allowed_methods=["HEAD", "GET", "OPTIONS", "POST"],
    )
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=pool_connections,
        pool_maxsize=pool_maxsize,
        pool_block=False,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
    )
    return session


def timed_request(
    session: requests.Session,
    method: str,
    url: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    **kwargs,
) -> requests.Response:
    """Requete HTTP avec archive.org auto-auth et timeout configurable."""
    request_kwargs = {"timeout": timeout_seconds, **kwargs}
    if any(host in (url or "").lower() for host in ("archive.org", ".archive.org")):
        access_key = os.environ.get("IAS3_ACCESS_KEY", "")
        secret_key = os.environ.get("IAS3_SECRET_KEY", "")
        if access_key and secret_key:
            from requests.auth import HTTPBasicAuth
            request_kwargs.setdefault("auth", HTTPBasicAuth(access_key, secret_key))
    return session.request(method, url, **request_kwargs)


def get_chunk_size() -> int:
    return DEFAULT_CHUNK_SIZE


def safe_stream_write(
    response: requests.Response,
    handle,
    downloaded: int = 0,
    total_size: int = 0,
    progress_callback=None,
    progress_detail_callback=None,
) -> int:
    """Ecrit les chunks d'une response dans un fichier handle en trackant progression."""
    chunk_size = get_chunk_size()
    for chunk in response.iter_content(chunk_size=chunk_size):
        if not chunk:
            continue
        handle.write(chunk)
        downloaded += len(chunk)
        if total_size > 0 and progress_callback:
            progress_callback((downloaded / total_size) * 100)
    return downloaded


__all__ = [
    "create_optimized_session",
    "timed_request",
    "get_chunk_size",
    "safe_stream_write",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_TIMEOUT_SECONDS",
]
