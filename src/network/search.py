"""Recherche parallele et aggregee sur toutes les sources."""

from __future__ import annotations

import concurrent.futures
from typing import Callable

from .circuits import SourceCircuitBreaker
from .cache_runtime import RuntimeCache


class ParallelSearchPool:
    """Execute les recherches sur plusieurs sources en parallele."""

    def __init__(
        self,
        max_workers: int = 10,
        circuit_breaker: SourceCircuitBreaker | None = None,
        runtime_cache: RuntimeCache | None = None,
    ):
        self.max_workers = max(1, max_workers)
        self.circuit = circuit_breaker or SourceCircuitBreaker()
        self.cache = runtime_cache or RuntimeCache()
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="search_worker_",
        )

    def search_listings_parallel(
        self,
        sources: list[dict],
        list_func: Callable[[dict], list[dict]],
    ) -> dict[str, list[dict]]:
        """Pre-fetch les listings directory de toutes les sources en parallele."""
        results: dict[str, list[dict]] = {}
        futures: dict[concurrent.futures.Future, str] = {}
        source_names = [s.get("name", "") for s in sources]

        for idx, source in enumerate(sources):
            name = source.get("name", "")
            if self.circuit.is_open(name):
                results[name] = []
                continue
            cache_key = f"listing:{name}:{source.get('base_url', '')}"
            cached = self.cache.get_listing(cache_key)
            if cached is not None:
                results[name] = cached
                continue
            future = self.executor.submit(list_func, source)
            futures[future] = idx

        for future in concurrent.futures.as_completed(futures):
            idx = futures[future]
            name = source_names[idx]
            try:
                data = future.result()
                cache_key = f"listing:{name}:{sources[idx].get('base_url', '')}"
                self.cache.set_listing(cache_key, data)
                results[name] = data
            except Exception:
                self.circuit.record_failure(name)
                results[name] = []

        return results

    def search_scrapers_parallel(
        self,
        missing_games: list[dict],
        scraper_funcs: list[tuple[str, Callable[[dict], dict | None]]],
    ) -> list[dict]:
        """Execute les scrapers pour les jeux manquants en parallele."""
        if not missing_games:
            return []

        found: list[dict] = []
        futures: dict[concurrent.futures.Future, tuple[str, dict]] = {}

        for game_info in missing_games:
            for scraper_name, func in scraper_funcs:
                if self.circuit.is_open(scraper_name):
                    continue
                future = self.executor.submit(func, game_info)
                futures[future] = (scraper_name, game_info)

        for future in concurrent.futures.as_completed(futures):
            scraper_name, game_info = futures[future]
            try:
                result = future.result()
                if result:
                    merged = dict(game_info)
                    merged.update(result)
                    merged["source"] = scraper_name
                    found.append(merged)
                    self.circuit.record_success(scraper_name)
            except Exception:
                self.circuit.record_failure(scraper_name)

        return found

    def shutdown(self, wait: bool = True) -> None:
        self.executor.shutdown(wait=wait)


__all__ = ["ParallelSearchPool"]
