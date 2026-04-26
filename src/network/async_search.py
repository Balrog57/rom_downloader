"""Recherche asynchrone via aiohttp avec fallback synchrone.

Fournit async_fetch_listing() et async_resolve_game() qui tentent
d'abord un fetch async via aiohttp, puis fallback sur la fonction
synchrone si aiohttp n'est pas disponible ou en cas d'erreur.
"""

from __future__ import annotations

import asyncio
from typing import Callable, Any

try:
    import aiohttp
    _AIOHTTP_AVAILABLE = True
except ImportError:
    _AIOHTTP_AVAILABLE = False


async def async_fetch_url(
    url: str,
    timeout: int = 30,
    headers: dict | None = None,
    session: aiohttp.ClientSession | None = None,
) -> str | None:
    """Fetch un URL en async via aiohttp. Retourne le texte ou None."""
    if not _AIOHTTP_AVAILABLE:
        return None
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout))
    try:
        async with session.get(url, headers=headers or {}) as resp:
            if resp.status == 200:
                return await resp.text()
            return None
    except Exception:
        return None
    finally:
        if own_session:
            await session.close()


async def async_fetch_listing(
    url: str,
    sync_fn: Callable[..., Any],
    *args,
    timeout: int = 30,
    headers: dict | None = None,
    **kwargs,
) -> Any:
    """Fetch un listing directory. Essaie async d'abord, fallback synchrone."""
    if _AIOHTTP_AVAILABLE:
        text = await async_fetch_url(url, timeout=timeout, headers=headers)
        if text is not None:
            try:
                from .cache_runtime import get_session_cache
                return text
            except Exception:
                pass
    return sync_fn(*args, **kwargs)


async def async_resolve_game(
    resolve_fn: Callable[..., Any],
    game_info: dict,
    *args,
    **kwargs,
) -> Any:
    """Resout un jeu via la fonction synchrone (les scrapers sont synchrone-dominant).

    Ce wrapper est prevu pour etre utilise dans un event loop parallele.
    La fonction synchrone est executee dans un thread pool.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, resolve_fn, game_info, *args, **kwargs)


def run_async(coro):
    """Lance une coroutine async de maniere safe. Fallback synchrone si pas d'event loop."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


__all__ = [
    'async_fetch_url',
    'async_fetch_listing',
    'async_resolve_game',
    'run_async',
    '_AIOHTTP_AVAILABLE',
]