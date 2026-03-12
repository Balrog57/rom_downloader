# ROM Downloader Project Context

## Project Overview
This project is an autonomous ROM downloader utility written in Python. Its primary purpose is to compare a No-Intro DAT file with a local folder of ROMs, identify missing games, and automatically download them from various supported sources. It utilizes a large local database of URLs (`rom_database.json`) extracted from RGSX, making it independent of external database services for most of its queries.

The application features multiple interfaces:
- **Command Line Interface (CLI)** for automated or batch processing.
- **Interactive Console Mode** which prompts the user for necessary paths.
- **Graphical User Interface (GUI)** built with `tkinter` (and optionally `tkinterdnd2` for drag-and-drop support).

## Main Technologies
- **Language:** Python 3.8+
- **Core Dependencies:** 
  - `requests` (for HTTP requests and API interactions)
  - `beautifulsoup4` (for web scraping, specifically parsing Myrient directories)
  - `internetarchive` (for querying and downloading from Archive.org)
- **GUI Framework:** `tkinter` (Standard Python GUI library)
- **Data Storage:** JSON (`rom_database.json` for URLs, `api_keys.json` for premium credentials).

## Architecture & Key Components
- **`rom_downloader.py`**: The central script containing all the logic. It handles:
  - DAT file parsing (XML parsing via `xml.etree.ElementTree`).
  - Local ROM scanning and matching (normalizing filenames, checking inside archives).
  - Source management (Free sources like Archive.org, Myrient, and Premium sources like 1fichier, AllDebrid, RealDebrid).
  - Multi-source fallback search mechanism (Local DB -> Direct Scraping -> Archive.org MD5 search).
  - Download execution with retry mechanisms and progress tracking.
  - The `tkinter` UI implementation.
- **`rom_database.json`**: A crucial local database containing over 74,000 URLs to avoid unnecessary web scraping and rely on known good links.
- **Auto-Installation**: The script attempts to automatically install its required `pip` dependencies if they are not found upon execution.

## Building and Running
No specific build step is required as it is a Python script.

**To run the GUI:**
```bash
python rom_downloader.py --gui
```

**To run via CLI:**
```bash
python rom_downloader.py <path_to_dat_file> <path_to_rom_folder> [optional_myrient_url]
```
*Options:*
- `--dry-run`: Simulate the process without downloading.
- `--limit N`: Limit the number of downloads.
- `--tosort`: Move unrecognized ROM files to a `ToSort` folder.
- `--configure-api`: Set up API keys for premium hosters.

**To run interactively:**
```bash
python rom_downloader.py
```

## Development Conventions
- **Dependency Management:** Dependencies are dynamically checked and installed via `os.system("pip install...")` at the top of the main script. 
- **Modularity:** The main script is heavily procedural but organized into distinct functional blocks (Database loading, API config, Downloaders for specific sources, Matching logic, CLI/GUI entry points).
- **Error Handling:** The script includes fallback mechanisms (e.g., trying Archive.org by MD5 if direct links fail) and retry logic for downloads to ensure robustness.