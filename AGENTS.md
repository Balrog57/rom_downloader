# AGENTS.md

## Commands

```powershell
# Compile-check all Python files
$files = @("main.py") + (Get-ChildItem src,tests -Recurse -Filter *.py | ForEach-Object { $_.FullName }); python -m py_compile @files

# Run tests (standalone scripts, NOT pytest)
python tests\smoke_checks.py
python tests\core_helper_checks.py

# Quick sanity checks
python main.py --version
python main.py --sources
```

There is no pytest. Tests are plain scripts that call `main()` and raise `SystemExit` on failure.

## Architecture

- **Entry point**: `main.py` → `src.cli.main()` → dispatches to `src.core.cli_mode` (CLI) or `src.core.gui` (GUI)
- **`src/core/`**: 27 modules split from an old monolith. `_facade.py` re-exports everything via `from .xxx import *` for backward compat. `load_json_file` / `save_json_file` in `_facade.py` are deprecated wrappers delegating to `src/network/utils.py`; cache helpers delegate to `src/network/cache.py`. Prefer the new location when writing new code.
- **`src/network/`**: Isolated networking components (sessions, circuit breakers, caches, async search, download/search pools).
- **`src/providers/`**: Provider registry (`base.py`, `registry.py`) plus per-provider implementations (minerva, archive_org, premium).
- **`src/pipeline.py` + `src/progress.py`**: Top-level pipeline summary and download progress helpers (not inside `core/`).

## Key conventions

- Codebase language is **French**: comments, docstrings, user-facing strings, error messages, CLI flags are all in French.
- `src/core/__init__.py` star-imports every sub-module. Adding a new public function in a `src/core/` module makes it available as `from src.core import func` — no extra wiring needed.
- `libtorrent` and `tkinterdnd2` are optional but listed in `requirements.txt`. `libtorrent` may fail to import on Windows if OpenSSL 1.1 DLLs are missing (`LIBTORRENT_DLL_DIR` in `.env`). The app degrades gracefully — only Minerva torrent downloads are affected.
- Integration/network test files are **gitignored** (`test_integration_*.py`, `test_network_modules.py`). Don't try to add them to CI.
- **ROM_DATABASE global**: Never do `from .rom_database import ROM_DATABASE` — that captures a stale `None` binding. Always use `from . import rom_database as _rom_db` and access `_rom_db.ROM_DATABASE` live. Guard with `if _rom_db.ROM_DATABASE is None: load_rom_database()` before `.get()` calls.
- `requirements.txt` uses **compatible-release pins** (e.g. `requests>=2.31,<3`). `requirements-lock.txt` is a `pip freeze` snapshot for reproducible CI. Regenerate with `pip freeze > requirements-lock.txt` after any dependency change.

## Runtime requirements

- `db/shard_*.zip` must exist for local MD5 search. Smoke checks verify this.
- `dat/` subdirectories (`no-intro/`, `redump/`, `retool - french no unl/`) are section headers in the GUI DAT selector, not selectable items.
- `.env` holds API keys (1fichier, AllDebrid, RealDebrid, IA S3, `LIBTORRENT_DLL_DIR`). Copy from `.env.example`. Never commit `.env`.
- `aiohttp` is required for async listing pre-fetch. If missing, the app falls back to sync scraping transparently.

## Versioning

- Version lives in `VERSION` file (SemVer: `MAJOR.MINOR.PATCH`), read by `--version`, GUI, and release workflow.
- CI runs on `windows-latest` with Python 3.13.

## Download pipeline (LoLROMs & .7z handling)

- **LoLROMs scraper** (`src/core/scrapers.py`): Uses `cloudscraper` to bypass Cloudflare. Scrapes HTML directory listings, recurses into subdirectories (`Multi-Boot`, `eReader`, `Video`, `Play-Yan`, `Hacks (Color)`, `T-En`) for GBA. Files are `.7z` archives containing `.gba` ROMs.
- **Search pipeline** (`src/core/search_pipeline.py`): For LoLROMs, resolves system path, scrapes listing, matches via `iter_game_candidate_names()` (exact lower-case match first, then normalised fuzzy match). Results include `download_url` pointing to `.7z` files.
- **Download pipeline** (`src/core/downloads.py`): `download_file()` with retry (3 attempts, exponential backoff), resumable `.part` files, Cloudflare HTML detection. When `content-type` is `text/html` for a non-HTML URL, raises `DownloadNetworkError` to avoid saving Cloudflare challenge pages as ROM files.
- **Download orchestrator** (`src/core/download_orchestrator.py`): Downloads `.7z` via `download_file()` using the cloudscraper session. The download destination uses the server filename (`.7z`), not the DAT's `.gba` extension. LoLROMs downloads include a configurable delay (`delay_seconds` in source policies, default 2s) to avoid Cloudflare rate-limiting.
- **MD5 verification** (`src/core/verification.py`): Supports `.7z` — iterates archive entries and compares `.gba` MD5 against the DAT. Works correctly for No-Intro DATs (which reference `.gba` ROMs directly).
- **TorrentZip repack** (`src/core/torrentzip.py`): `repack_verified_archives_to_torrentzip()` extracts `.gba` from `.7z`/`.zip`/`.rar`, creates TorrentZip-compatible `.zip` files, and deletes the source archive. Only runs if `--clean-torrentzip` or `clean_torrentzip=True` is set.
- **Key issue**: If `clean_torrentzip` is not enabled, downloaded `.7z` files stay as `.7z` in the ROM folder. RomVault expects `.zip`. Always run with `--clean-torrentzip` for GBA sets downloaded from LoLROMs.

## SYSTEM_MAPPINGS (sources.py)

- `SYSTEM_MAPPINGS` maps DAT system names to source-specific slugs for each provider (`lolroms`, `vimm`, `edgeemu`, `planetemu`, `romhustler`, `coolrom`, `retrogamesets`, `romsxisos`, `startgame`, `hshop`, `nopaystation`).
- LoLROMs paths use the exact directory name on the site (e.g. `'Nintendo - Game Boy Advance'`, `'SEGA/Mega Drive'`, `'SONY/PlayStation'`).
- Subdirectory aliases for GBA LoLROMs are defined in `LOLROMS_SUBDIR_ALIASES` in `scrapers.py`.
- CDRomance has been fully removed (site dead since January 2026). No `cdromance` type, no `CDROMANCE_BASE`, no `resolve_cdromance_game`, no `download_cdromance`, no `get_cdromance_session`.

## Download delay & Cloudflare protection

- `download_file()` in `downloads.py` now detects HTML content-type responses (Cloudflare challenge pages) and raises `DownloadNetworkError` instead of saving garbage.
- `source_delay_seconds(source_config, default)` in `sources.py` reads `delay_seconds` from source policies. LoLROMs uses a 3s delay between downloads to avoid Cloudflare rate-limiting.
- When LoLROMs downloads fail repeatedly, the `SourceCircuitBreaker` trips after 10 failures and blocks the source for 300s. Reducing `parallel_downloads` to 1 and adding `delay_seconds` mitigates this.

## Provider stats

- `provider_stats` in `.rom_downloader_preferences.json` tracks `attempts`, `downloaded`, `failed`, `skipped`, `dry_run`, `quota_skipped`, `seconds` per provider.
- The `SourceCircuitBreaker` (threshold=10 failures, recovery=300s) can block a provider mid-session if downloads fail repeatedly.