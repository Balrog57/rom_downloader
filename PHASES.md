# Plan d'amelioration ROM Downloader – Phases restantes

## Historique (deja implante et pousse sur GitHub)

| Phase | Statut | Description | Commit |
|---|---|---|---|
| **Phase 0** | Done | Creation modules `src/network/` (sessions, circuits, exceptions, cache_runtime, metrics, downloads, search, cache, utils) | `b0eb908` |
| **Phase 1** | Done | Sessions HTTP optimisees : `create_optimized_session()` avec pooling urllib3 (20 connexions), retry 502/503/504, chunks 256KB | `8848f0d` |
| **Phase 2** | Partial | Chunk size uniformise a 256KB dans tout core.py | `8848f0d` |
| **Phase 3** | Partial | Structure `ParallelDownloadPool` et `ParallelSearchPool` crees | `b0eb908` |
| **Phase 4** | Done | Circuit-breaker integre dans `download_with_provider_retries` et `download_missing_games_sequentially` (threshold=10, recovery=300s) | `ed9a6ea` |
| **Phase 5** | Partial | Resume robuste deja present dans `download_file()` (fichiers `.part` + Range headers) ; reste a integrer le MD5 validator dans `ParallelDownloadPool` | – |
| **Phase 6** | Partial | `RuntimeCache` crees, pas encore integre dans `search_all_sources` | – |
| **Phase 7** | Pending | Async scraping avec aiohttp | – |
| **Phase 8** | Done | Metriques persistantes : `load/save_provider_metrics()` integre en fin de `run_download()` | `521d71f` |
| **Phase 9** | Partial | Exceptions custom crees ; reste a les utiliser dans le pipeline au lieu de `raise Exception` bruts | – |

---

## Phases restantes – Plan detaille

### Phase 2 – Telechargements paralleles (completion)
**Objectif** : Remplacer le `ThreadPoolExecutor` artisanal de `download_missing_games_sequentially` par `ParallelDownloadPool`.

**Actions** :
1. `ParallelDownloadPool` implementer `_download_torrent()` avec delegation a `download_from_minerva_torrent()`
2. `run_download()` : instancier `download_pool = ParallelDownloadPool(max_workers=parallel_downloads, circuit_breaker=circuit_breaker, metrics=session_metrics)`
3. remplacer le bloc `worker_download()` + `futures` par `download_pool.submit_download()` et `as_completed()`
4. fallback sequentiel garde pour le cas `parallel_downloads == 1`

---

### Phase 3 – Recherche parallele (completion)
**Objectif** : Pre-fetcher les listings DDL et paralleler les scrapers.

**Actions** :
1. `search_all_sources()` : instancier `search_pool = ParallelSearchPool(max_workers=10, circuit_breaker=circuit_breaker, runtime_cache=session_cache)`
2. Etape 2 (DDL direct) : `search_pool.search_listings_parallel(direct_sources, list_func=list_myrient_directory)` pour pre-fetcher tous les listings
3. Etape 3 (scrapers) : `search_pool.search_scrapers_parallel(still_missing, scraper_funcs)`
4. Etape 4 (archive.org) : conserver sequentiel car API rate-limitee
5. `session_cache` mis a jour avec les resultats

---

### Phase 5 – Resume robuste + MD5 final (completion)
**Objectif** : Valider MD5 sur le fichier final, meme pour archives et torrents.

**Actions** :
1. `verify_downloaded_md5()` deja present dans core.py ; l'utiliser comme `md5_validator` de `ParallelDownloadPool.download_game()`
2. Si torrent => extraction obligatoire avant validation (impossible avant)
3. Si archive (zip/7z/rar) => extraire le contenu, valider le MD5 de l'interieur
4. `cleanup_invalid_download()` appele si MD5 KO
5. Ne jamais supprimer le `.part` en cas d'erreur transitoire ; seulement apres validation finale KO

---

### Phase 6 – Cache runtime (completion)
**Objectif** : Eviter les requetes HTTP redondantes pendant la session.

**Actions** :
1. `list_myrient_directory(url)` : wrapper avec cache LRU via `session_cache`
2. `resolve_edgeemu_game()`, `resolve_planetemu_game()` : cache par `(game_name, system_name)`
3. Resultats `archive.org` par checksum : cache via `session_cache.set_resolution()`

---

### Phase 7 – Async scraping avec aiohttp
**Objectif** : Paralleler le scraping avec des milliers de connexions I/O.

**Actions** :
1. Ajouter `aiohttp` dans `requirements.txt`
2. `src/network/async_search.py` : `AsyncScraperSession` avec `aiohttp.ClientSession`
3. Wrapper pour les fonctions de scraping (EdgeEmu, PlanetEmu, LoLROMs)
4. Fallback synchrone transparent si aiohttp manque
5. **Uniquement** le search/resolution devient async ; garder `requests` pour les downloads lourds

---

### Phase 9 – Exceptions custom + rapports fins (completion)
**Objectif** : Remplacer `Exception` generiques par types precis.

**Actions** :
1. Dans `download_file()` : lever `SourceTimeoutError` sur timeout, `DownloadNetworkError` sur HTTP KO, `ResumeNotSupportedError` si serveur refuse 206
2. Dans le torrent handler : lever `TorrentDownloadError`
3. Mettre a jour `failure_cause_counts()` dans `pipeline.py` pour capturer les nouveaux types
4. Adapter les tests `tests/core_helper_checks.py` si besoin

---

## Prochaines etapes recommandees

1. **Finaliser Phase 2** (ParallelDownloadPool) – impact performance maximal
2. **Finaliser Phase 3** (ParallelSearchPool) – accelere la resolution
3. **Finaliser Phase 5** (MD5 final + resume) – securite des downloads
4. **Phase 9** (exceptions) – fiabilite du reporting
5. **Phase 6** (cache runtime) – optimisation secondaire
6. **Phase 7** (aiohttp) – si besoin de plus de concurrence I/O

---

## Architecture cible

```
src/network/
  sessions.py       # HTTP pooling + retry (Phase 1 Done)
  circuits.py       # Circuit-breaker (Phase 4 Done)
  exceptions.py     # Custom exceptions (Phase 9 Started)
  cache_runtime.py  # LRU memoire (Phase 6 Started)
  cache.py          # Cache persistant JSON (Phase 0 Done)
  metrics.py        # Stats + prioritisation (Phase 8 Done)
  downloads.py      # ParallelDownloadPool (Phase 2 Started)
  search.py         # ParallelSearchPool (Phase 3 Started)
  async_search.py   # aiohttp wrapper (Phase 7 Pending)
  utils.py          # Utilitaires purs (Phase 0 Done)

src/core.py         # Facade minimale (progressivement videe)
```
