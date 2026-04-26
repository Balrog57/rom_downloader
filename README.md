# ROM Downloader

Application Python pour comparer un DAT 1G1R a un dossier de ROMs, detecter les jeux manquants et tenter leur recuperation via les sources integrees.

## Utilisation

Installation Windows depuis GitHub Releases:

```powershell
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/Balrog57/rom_downloader/main/install.ps1 | iex"
```

Interface graphique:

```powershell
python main.py --gui
```

Sans argument, l'application lance aussi la GUI:

```powershell
python main.py
```

Ligne de commande:

```powershell
python main.py <fichier.dat> <dossier_roms> [--dry-run] [--limit N] [--parallel N] [--tosort] [--clean-torrentzip]
```

Exemples:

```powershell
python main.py "dat\retool - french no unl\Nintendo - Game Boy (20260405-031740) (Retool 2026-04-06 18-53-11) (602) (-nz) [-AaBbcDdefkMmopPruv].dat" "Roms\Game Boy"
python main.py "dat\retool - french no unl\Sony - PlayStation 2 (2026-04-05 01-38-25) (Retool 2026-04-06 18-57-20) (2,560) (-nz) [-AaBbcDdefkMmopPruv].dat" "Roms\PS2" --limit 10
python main.py "dat\retool - french no unl\Nintendo - Game Boy (20260405-031740) (Retool 2026-04-06 18-53-11) (602) (-nz) [-AaBbcDdefkMmopPruv].dat" "Roms\Game Boy" --tosort
python main.py "dat\retool - french no unl\Nintendo - Game Boy (20260405-031740) (Retool 2026-04-06 18-53-11) (602) (-nz) [-AaBbcDdefkMmopPruv].dat" "Roms\Game Boy" --analyze
python main.py "dat\retool - french no unl\Nintendo - Game Boy (20260405-031740) (Retool 2026-04-06 18-53-11) (602) (-nz) [-AaBbcDdefkMmopPruv].dat" "Roms\Game Boy" --analyze --analyze-candidates 10
python main.py "dat\retool - french no unl\Nintendo - Game Boy (20260405-031740) (Retool 2026-04-06 18-53-11) (602) (-nz) [-AaBbcDdefkMmopPruv].dat" "Roms\Game Boy" --analyze --analyze-candidates all
python main.py --sources
python main.py --version
python main.py --healthcheck-sources
python main.py --provider-registry
python main.py --clear-listing-cache
python main.py --clear-cache-source Minerva
```

## Structure du depot

- `main.py`: point d'entree de l'application.
- `VERSION`: version applicative courante, utilisee par `--version`, la GUI et les releases.
- `src/`: code Python de l'application.
- `src/pipeline.py`: agregations testables du pipeline resolution/telechargement.
- `src/progress.py`: helpers de progression, debit et ETA des transferts.
- `src/core/`: 27 modules extraits de l'ancien monolithe `core.py`.
- `src/network/`: modules reseau (sessions, circuits, exceptions, cache, metrics, downloads, search, async_search).
- `assets/`: images et icones utilisees par l'interface.
- `dat/`: fichiers DAT disponibles dans le menu de selection.
- `db/shard_*.zip`: shards SQLite compresses pour la recherche locale par MD5.
- `.env.example`: exemple de configuration locale.
- `requirements.txt`: dependances Python.
- `install.ps1`: installateur Windows qui telecharge la derniere release GitHub.
- `release.ps1`: helper mainteneur pour mettre a jour `VERSION`, commit, tag et pousser une release.
- `PACKAGING_WINDOWS.md`: notes pour une archive Windows portable.

Le depot ne contient plus de runtime externe ni de dossier de generation. Les fichiers temporaires, caches, rapports locaux et donnees extraites restent ignores par Git.

## Interface

Le champ DAT de la GUI est un menu deroulant alimente par `dat/**/*.dat`, avec recherche texte et filtres par section.
Les dossiers directs de `dat/` sont affiches comme titres de section en italique et ne sont pas selectionnables. Les fichiers DAT sous chaque section sont selectionnables.
Le bouton `Parcourir` reste disponible comme secours pour choisir un DAT externe.
La GUI retient localement le dernier DAT, le dernier dossier, les options ToSort/TorrentZip, le parallelisme et l'etat des logs.
Le panneau `Logs` est repliable et affiche le detail des operations sans quitter la fenetre.
L'ecran `Configurer les sources` permet aussi de changer l'ordre des sources directes, les activer/desactiver, fixer un timeout et un quota par run, saisir les cles API locales dans `.env`, voir l'etat des caches, vider tous les caches, invalider la source selectionnee et consulter les statistiques cumulees par provider. `Passerelle 1fichier` represente l'hebergeur utilise quand un site renvoie un lien 1fichier; ce n'est pas un site de recherche.

Les sources de telechargement sont automatiques: les sources directes sont essayees avant Minerva, puis archive.org en dernier recours.
La resolution des providers est mise en cache temporairement dans `.rom_downloader_resolution_cache.json` pour eviter de refaire les memes recherches pendant plusieurs essais; `--refresh-cache` force une reconstruction.
Les listings distants scrapes sont mis en cache 24 h dans `.rom_downloader_listing_cache.json`; `--clear-listing-cache` supprime tous les listings et `--clear-cache-source <source>` invalide les caches associes a une source.
Les telechargements HTTP utilisent des fichiers `.part`, reprennent quand le serveur accepte les requetes `Range`, journalisent debit/ETA pendant les gros transferts et remontent ces infos dans la barre de statut GUI.
Les quotas par source sont appliques pendant les retries: quand une source atteint sa limite de tentatives sur un run, le moteur passe au provider suivant.
Avant d'ignorer un fichier deja present, l'application valide le MD5 DAT quand il existe, puis la taille DAT si aucun MD5 n'est disponible.

## Architecture reseau (`src/network/`)

Le module `src/network/` contient les composants reseau isoles et testables :

| Module | Role |
|--------|------|
| `sessions.py` | `create_optimized_session()` avec pooling urllib3 (20 connexions), retry 502/503/504, chunks 256KB |
| `circuits.py` | `SourceCircuitBreaker` - exclut les sources defaillantes (threshold=10, recovery=300s) |
| `exceptions.py` | Exceptions custom : `SourceTimeoutError`, `ChecksumMismatchError`, `DownloadNetworkError`, `ResumeNotSupportedError`, etc. |
| `cache_runtime.py` | `RuntimeCache` LRU thread-safe (listings + resolutions en memoire) |
| `cache.py` | Cache persistant JSON (7 jours) |
| `metrics.py` | `load/save_provider_metrics()`, `prioritize_sources()`, `record_provider_attempt()` |
| `downloads.py` | `ParallelDownloadPool` avec callback `download_fn`, circuit-breaker, metrics |
| `search.py` | `ParallelSearchPool` pour recherche/listings paralleles |
| `async_search.py` | Pre-fetch async via `aiohttp` + fallback synchrone transparent |
| `utils.py` | Utilitaires purs |

## Architecture pipeline (`src/core/`)

L'ancien monolithe `core.py` (8367 lignes) a ete eclate en 27 modules :

- `pipeline.py` : orchestrateur principal `run_download()`
- `download_orchestrator.py` : `download_with_provider_retries()` + `download_missing_games_sequentially()` avec ParallelDownloadPool
- `search_pipeline.py` : `search_all_sources()` avec `_resolve_games_parallel()` (5 workers)
- `downloads.py` : `download_file()` avec resume `.part` + Range headers
- `verification.py` : `verify_downloaded_md5()` + `validate_download_checksum()`
- `scrapers.py` : EdgeEmu, PlanetEmu, LoLROMs, CDRomance, Vimm, RetroGameSets
- Et 21 autres modules (env, constants, sources, dat_parser, minerva, etc.)

## Optimisations implementees

| Optimisation | Impact rapidite | Impact fiabilite |
|---|---|---|
| Sessions HTTP optimisees (pooling, retry, 256KB chunks) | ** | ** |
| Telechargements paralleles (ParallelDownloadPool) | *** | * |
| Recherche parallele (ParallelSearchPool, 5 workers) | *** | * |
| Pre-fetch async des listings (aiohttp) | *** | * |
| Circuit-breaker (10 echecs = source ignoree 5 min) | ** | *** |
| Resume robuste (`.part` + Range headers) | * | *** |
| Validation MD5 finale obligatoire | - | *** |
| Cache LRU runtime (listings + resolutions) | ** | ** |
| Metriques persistantes + prioritisation dynamique des sources | ** | ** |
| Exceptions custom (7 types hierarchises) | * | *** |

## Dependances

Dependances Python principales:

- `requests` - sessions HTTP avec pooling et retry
- `beautifulsoup4` - parsing HTML des scrapers
- `internetarchive` - recherche et telechargement archive.org
- `cloudscraper` - contournement Cloudflare
- `py7zr` - lecture/verification des archives `.7z`
- `rarfile` - lecture/verification des archives `.rar`
- `tkinterdnd2` - glisser-deposer GUI (optionnel)
- `aiohttp` - pre-fetch async des listings (fallback synchrone si absent)

`charset_normalizer` n'est pas liste directement car il est installe comme dependance transitive de `requests`.
Le programme tente encore d'installer certaines dependances optionnelles si elles manquent au moment d'une verification d'archive.
Les torrents Minerva utilisent `aria2c` en priorite. Le binding Python `libtorrent` reste optionnel et n'est pas liste dans `requirements.txt` car les wheels disponibles dependent fortement de la version Python et de Windows. Si `libtorrent` est absent ou renvoie `DLL load failed`, seuls les telechargements Minerva via ce backend sont affectes; les sources HTTP, la DB locale, l'analyse DAT et la GUI restent fonctionnelles. Sous Windows, si `libtorrent` reclame OpenSSL 1.1, renseigner `LIBTORRENT_DLL_DIR` dans `.env` vers le dossier contenant `libcrypto-1_1-x64.dll` et `libssl-1_1-x64.dll`.
Voir `PACKAGING_WINDOWS.md` pour preparer une archive portable.

## Base locale

La recherche locale utilise les shards compresses `db/shard_*.zip`.
Ces fichiers doivent etre presents dans le depot pour activer la recherche MD5 hors ligne.

Le cache local `db/retrogamesets/`, les rapports de sortie et les caches Python sont ignores par Git.

## Verification

```powershell
$files = @("main.py") + (Get-ChildItem src,tests -Recurse -Filter *.py | ForEach-Object { $_.FullName })
python -m py_compile @files
python tests\smoke_checks.py
python tests\core_helper_checks.py
python tests\test_integration_gw.py
python tests\test_network_modules.py
python main.py --sources
python main.py --version
python main.py --clear-listing-cache
```

## Versioning et releases Windows

Le depot utilise un versioning SemVer dans `VERSION` (`MAJOR.MINOR.PATCH`).

Pour publier une version:

```powershell
.\release.ps1 -Version 0.1.0 -Push
```

Le workflow GitHub Actions `Release Windows` compile `ROMDownloader.exe`, cree `ROMDownloader-windows-<version>.zip`, publie le checksum SHA256 et attache les fichiers a la release GitHub.

L'installateur Windows telecharge la derniere release publique, l'installe dans `%LOCALAPPDATA%\ROMDownloader`, cree les raccourcis Menu Demarrer/Bureau, et conserve `.env` ainsi que les preferences lors d'une reinstall avec `-Force`.