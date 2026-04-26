"""Recherche asynchrone via aiohttp avec fallback synchrone.

Fournit:
- async_fetch_page(): fetch HTML async, fallback sync
- async_fetch_listings_parallel(): fetch plusieurs listings en parallele
- async_resolve_games(): resout des jeux via scrapers en thread pool
- run_async(): lance une coroutine async de maniere safe

Utilise aiohttp si disponible, sinon fallback vers requests synchrone.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Callable, Any

try:
    import aiohttp
    _AIOHTTP_AVAILABLE = True
except ImportError:
    _AIOHTTP_AVAILABLE = False


async def async_fetch_page(
    url: str,
    timeout: int = 30,
    headers: dict | None = None,
) -> str | None:
    """Fetch une page HTML via aiohttp. Retourne le texte ou None si echec."""
    if not _AIOHTTP_AVAILABLE:
        return None
    session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout),
        headers=headers or {},
    )
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                text = await resp.text()
                return text
            return None
    except Exception:
        return None
    finally:
        await session.close()


async def async_fetch_listings_parallel(
    urls: list[str],
    timeout: int = 30,
    headers: dict | None = None,
) -> dict[str, str | None]:
    """Fetch plusieurs URLs en parallele via aiohttp.

    Retourne {url: html_text ou None}.
    Si aiohttp n'est pas disponible, retourne {}.
    """
    if not _AIOHTTP_AVAILABLE or not urls:
        return {}

    connector = aiohttp.TCPConnector(limit=10, ssl=False)
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout),
        connector=connector,
        headers=headers or {},
    ) as session:
        tasks = {}
        for url in urls:
            tasks[url] = asyncio.create_task(_safe_fetch(session, url))

        results = {}
        for url, task in tasks.items():
            try:
                results[url] = await task
            except Exception:
                results[url] = None
        return results


async def _safe_fetch(session: aiohttp.ClientSession, url: str) -> str | None:
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                return await resp.text()
            return None
    except Exception:
        return None


async def async_resolve_games(
    games: list[dict],
    resolve_fn: Callable[[dict], Any],
    max_workers: int = 5,
) -> list[tuple[dict, Any]]:
    """Resout des jeux en executant resolve_fn dans un thread pool.

    Chaque resolve_fn(game_info) est execute dans un thread separe.
    Retourne [(game_info, resolve_fn(game_info)), ...].
    """
    loop = asyncio.get_event_loop()
    results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(resolve_fn, game): game
            for game in games
        }
        for future in concurrent.futures.as_completed(futures):
            game = futures[future]
            try:
                result = future.result()
            except Exception:
                result = None
            results.append((game, result))

    return results


def resolve_games_threaded(
    games: list[dict],
    resolve_fn: Callable[[dict], Any],
    max_workers: int = 5,
) -> list[tuple[dict, Any]]:
    """Version synchrone de async_resolve_games.

    Execute resolve_fn pour chaque jeu dans un thread pool.
    Utilise quand on ne peut pas lancer asyncio.run() (ex: deja dans un event loop).
    """
    results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(resolve_fn, game): game
            for game in games
        }
        for future in concurrent.futures.as_completed(futures):
            game = futures[future]
            try:
                result = future.result()
            except Exception:
                result = None
            results.append((game, result))

    return results


def fetch_listings_async(
    urls: list[str],
    sync_fns: dict[str, Callable[[], Any]],
    timeout: int = 30,
) -> dict[str, Any]:
    """Fetch des listings en async si aiohttp disponible, sinon synchrone.

    Args:
        urls: liste d'URLs a fetcher
        sync_fns: mapping url -> fonction synchrone a appeler si async echoue
        timeout: timeout en secondes

    Returns:
        dict {url: parsed_result} ou les resultats sont ceux des sync_fns
    """
    if not _AIOHTTP_AVAILABLE:
        return {url: fn() for url, fn in sync_fns.items() if url in urls}

    import bs4

    async def _fetch_and_parse():
        pages = await async_fetch_listings_parallel(urls, timeout=timeout)
        results = {}
        for url in urls:
            html = pages.get(url)
            if html is not None and url in sync_fns:
                try:
                    results[url] = sync_fns[url]()
                except Exception:
                    results[url] = sync_fns[url]()
            elif url in sync_fns:
                results[url] = sync_fns[url]()
        return results

    try:
        return asyncio.run(_fetch_and_parse())
    except RuntimeError:
        return {url: fn() for url, fn in sync_fns.items() if url in urls}


def run_async(coro):
    """Lance une coroutine async de maniere safe.

    Si un event loop est deja en cours d'execution,
    lance dans un thread separe.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


__all__ = [
    'async_fetch_page',
    'async_fetch_listings_parallel',
    'async_resolve_games',
    'resolve_games_threaded',
    'fetch_listings_async',
    'run_async',
    '_AIOHTTP_AVAILABLE',
]