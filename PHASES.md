# ROM Downloader – Phases d'amelioration

## Historique des phases (toutes completees et poussees sur GitHub)

| Phase | Statut | Description | Commit |
|---|---|---|---|
| **Phase 0** | Done | Eclatement `core.py` (8367 lignes) en 27 modules sous `src/core/` + facade `_facade.py` | `8cf29c9` |
| **Phase 1** | Done | Sessions HTTP optimisees : `create_optimized_session()` avec pooling urllib3 (20 connexions), retry 502/503/504, chunks 256KB uniformes | `e17cc05` |
| **Phase 2** | Done | `ParallelDownloadPool` remplace le `ThreadPoolExecutor` artisanal dans `download_orchestrator.py`. Accepte `download_fn` callback pour deleguer a `download_with_provider_retries` | `5dc130d` |
| **Phase 3** | Done | `_resolve_games_parallel()` utilise `ParallelSearchPool` pour EdgeEmu/CDRomance/Vimm/RetroGameSets en parallel (5 workers). Listings (PlanetEmu/LoLROMs) restent sequentiels | `4d7fc1c` |
| **Phase 4** | Done | Circuit-breaker `SourceCircuitBreaker(failure_threshold=10, recovery_timeout=300)` integre dans `download_orchestrator.py` et `pipeline.py` | `e4ff97a` |
| **Phase 5** | Done | Resume robuste : fichiers `.part` preserves sur erreur transitoire, validation MD5 finale via `ChecksumMismatchError`, `cleanup_invalid_download()` si KO | `58ac64a` |
| **Phase 6** | Done | RuntimeCache LRU integre dans `search_pipeline.py` pour listings (`get_listing/set_listing`) et resolutions (`get_resolution/set_resolution`). Singleton `get_session_cache()` | `05d697d` |
| **Phase 7** | Done | Module `async_search.py` avec `aiohttp` + fallback synchrone. `async_fetch_url()`, `async_fetch_listing()`, `async_resolve_game()`, `run_async()`. `aiohttp` ajoute dans requirements.txt | `be5e888` |
| **Phase 8** | Done | Metriques persistantes + `prioritize_sources()` appele dans `pipeline.py`. `_extract_session_metrics()` + `merge_provider_metrics()` + `save_provider_metrics()` en fin de run | `aaf85a5` |
| **Phase 9** | Done | Exceptions custom : `SourceTimeoutError`, `DownloadNetworkError`, `ResumeNotSupportedError`, `ChecksumMismatchError`, `QuotaExceededError`, `SourceUnavailableError`, `TorrentDownloadError`. Utilisees dans `download_orchestrator.py`, `downloads.py`, `pipeline.py` | `e4ff97a` |

---

## Architecture finale

```
src/network/
  sessions.py       # create_optimized_session() + timed_request() + safe_stream_write()
  circuits.py       # SourceCircuitBreaker (failure_threshold, recovery_timeout)
  exceptions.py     # RomDownloaderError + 7 sous-classes
  cache_runtime.py  # RuntimeCache LRU thread-safe (get/set_listing, get/set_resolution)
  cache.py          # Cache persistant JSON (7 jours)
  metrics.py        # load/save_provider_metrics(), prioritize_sources(), record_provider_attempt()
  downloads.py      # ParallelDownloadPool (download_fn callback, circuit_breaker, metrics)
  search.py         # ParallelSearchPool (search_listings_parallel, search_scrapers_parallel)
  async_search.py   # aiohttp async + fallback synchrone
  utils.py          # Utilitaires purs

src/core/           # 27 modules extrait de core.py
  _facade.py        # Re-exports pour compatibilite (from .module import *)
  pipeline.py       # run_download() orchestrateur principal
  download_orchestrator.py  # download_with_provider_retries() + download_missing_games_sequentially()
  search_pipeline.py        # search_all_sources() avec _resolve_games_parallel()
  downloads.py      # download_file() + download_from_archive_org() avec resume .part
  verification.py   # verify_downloaded_md5() + validate_download_checksum()
  scrapers.py       # EdgeEmu/PlanetEmu/LoLROMs/CDRomance/Vimm/RetroGameSets
  ...               # 20+ autres modules (env, constants, sources, dat_parser, etc.)

src/pipeline.py     # build_pipeline_summary() + failure_cause_counts()
```

---

## Tests de validation

- `tests/smoke_checks.py` : DAT discovery + DB shards + providers
- `tests/core_helper_checks.py` : format_duration, DownloadProgressMeter, source_timeout_seconds, verify_downloaded_md5, etc.
- `tests/test_integration_gw.py` : Integration test avec DAT "Nintendo - Game & Watch"
- `tests/test_network_modules.py` : Verification de tous les modules network

DAT de test : **Nintendo - Game & Watch (20241105-120946)** (53 jeux, petit systeme)
DAT alternative : **Nintendo - Game Boy (20260405-031740)**

---

## Gain estime par phase

| Phase | Impact Rapidite | Impact Fiabilite |
|---|---|---|
| 1 (HTTP sessions) | ** | ** |
| 2 (Downloads paralleles) | *** | * |
| 3 (Search parallele) | *** | * |
| 4 (Circuit-breaker) | ** | *** |
| 5 (Resume + MD5) | * | *** |
| 6 (Cache runtime) | ** | ** |
| 7 (aiohttp) | *** | * |
| 8 (Metriques/priorisation) | ** | ** |
| 9 (Exceptions custom) | * | *** |