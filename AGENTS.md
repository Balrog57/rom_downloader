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
- **`src/core/`**: 27 modules split from an old monolith. `_facade.py` re-exports everything via `from .xxx import *` for backward compat. Some functions in `_facade.py` are deprecated wrappers delegating to `src/network/` or `src/`.
- **`src/network/`**: Isolated networking components (sessions, circuit breakers, caches, async search, download/search pools).
- **`src/providers/`**: Provider registry (`base.py`, `registry.py`) plus per-provider implementations (minerva, archive_org, premium).
- **`src/pipeline.py` + `src/progress.py`**: Top-level pipeline summary and download progress helpers (not inside `core/`).

## Key conventions

- Codebase language is **French**: comments, docstrings, user-facing strings, error messages, CLI flags are all in French.
- `src/core/__init__.py` star-imports every sub-module. Adding a new public function in a `src/core/` module makes it available as `from src.core import func` — no extra wiring needed.
- Deprecated wrappers in `_facade.py` delegate to `src/network/cache.py` or `src/network/utils.py`. Prefer the new location when writing new code.
- Integration/network test files are **gitignored** (`test_integration_*.py`, `test_network_modules.py`). Don't try to add them to CI.
- CI includes an "obsolete reference guard" that fails if code references old filenames (`rom_downloader.py`, `dat.exemple`, `rom_db_shards`, `minerva_torrent_download.js`). Do not reintroduce these patterns.

## Runtime requirements

- `db/shard_*.zip` must exist for local MD5 search. Smoke checks verify this.
- `dat/` subdirectories (`no-intro/`, `redump/`, `retool - french no unl/`) are section headers in the GUI DAT selector, not selectable items.
- `.env` holds API keys (1fichier, AllDebrid, RealDebrid, IA S3, `LIBTORRENT_DLL_DIR`). Copy from `.env.example`. Never commit `.env`.
- `libtorrent` is optional (not in `requirements.txt`). If missing, only Minerva torrent downloads are affected; everything else works. On Windows, `LIBTORRENT_DLL_DIR` in `.env` may be needed for OpenSSL 1.1 DLLs.
- `aiohttp` is optional with transparent sync fallback for async listing pre-fetch.
- `tkinterdnd2` is optional (drag-and-drop in GUI).

## Versioning

- Version lives in `VERSION` file (SemVer: `MAJOR.MINOR.PATCH`), read by `--version`, GUI, and release workflow.
- CI runs on `windows-latest` with Python 3.13.