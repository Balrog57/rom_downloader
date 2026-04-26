"""Cache runtime en memoire (LRU) pour listings et resolutions."""

from __future__ import annotations

import threading
from typing import Any


class RuntimeCache:
    """Cache thread-safe en memoire, persistant pendant la session."""

    def __init__(self, max_listing: int = 256, max_resolution: int = 1024):
        self._listing: dict[str, Any] = {}
        self._resolution: dict[str, Any] = {}
        self._listing_lock = threading.Lock()
        self._resolution_lock = threading.Lock()
        self._listing_access: dict[str, int] = {}
        self._resolution_access: dict[str, int] = {}
        self._listing_counter = 0
        self._resolution_counter = 0
        self._max_listing = max_listing
        self._max_resolution = max_resolution

    def get_listing(self, url: str) -> Any | None:
        with self._listing_lock:
            if url in self._listing:
                self._listing_counter += 1
                self._listing_access[url] = self._listing_counter
                return self._listing[url]
        return None

    def set_listing(self, url: str, value: Any) -> None:
        with self._listing_lock:
            self._listing_counter += 1
            self._listing[url] = value
            self._listing_access[url] = self._listing_counter
            _evict_lru(self._listing, self._listing_access, self._max_listing)

    def get_resolution(self, key: str) -> Any | None:
        with self._resolution_lock:
            if key in self._resolution:
                self._resolution_counter += 1
                self._resolution_access[key] = self._resolution_counter
                return self._resolution[key]
        return None

    def set_resolution(self, key: str, value: Any) -> None:
        with self._resolution_lock:
            self._resolution_counter += 1
            self._resolution[key] = value
            self._resolution_access[key] = self._resolution_counter
            _evict_lru(self._resolution, self._resolution_access, self._max_resolution)

    def invalidate(self) -> None:
        with self._listing_lock:
            self._listing.clear()
            self._listing_access.clear()
        with self._resolution_lock:
            self._resolution.clear()
            self._resolution_access.clear()


def _evict_lru(store: dict, access: dict, limit: int) -> None:
    while len(store) > limit:
        oldest = min(access, key=access.get)
        store.pop(oldest, None)
        access.pop(oldest, None)


_session_cache = RuntimeCache()


def get_session_cache() -> RuntimeCache:
    return _session_cache


def clear_session_cache() -> None:
    _session_cache.invalidate()


__all__ = [
    "RuntimeCache",
    "get_session_cache",
    "clear_session_cache",
]
