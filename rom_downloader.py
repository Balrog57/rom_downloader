#!/usr/bin/env python3
r"""
ROM Downloader

Compare un DAT No-Intro ou Redump retraite avec Retool a un dossier cible
et telecharge uniquement les ROMs manquantes.

Sources supportees:
    GRATUITES:
    - Minerva No-Intro / Redump / TOSEC
    - archive.org
    - LoLROMs
    - EdgeEmu
    - PlanetEmu
    - 1fichier (gratuit)

Usage en ligne de commande:
    python rom_downloader.py <dat_file> <rom_folder> [url_source] [--dry-run] [--limit N] [--tosort] [--clean-torrentzip]

Usage interactif (sans arguments):
    python rom_downloader.py
    (pose les questions pour les chemins)

Usage GUI (interface graphique):
    python rom_downloader.py --gui

Options:
    --dry-run         Simulation sans telechargement
    --limit N         Limite le nombre de telechargements
    --tosort          Deplace les ROMs hors DAT dans un sous-dossier ToSort
    --clean-torrentzip Recompresse les archives validees MD5 en ZIP TorrentZip/RomVault
    --gui             Lance l'interface graphique
    --sources         Affiche la liste des sources de telechargement
"""

import argparse
import concurrent.futures
import hashlib
import html as html_module
import importlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import zlib
from datetime import datetime
from itertools import islice
from pathlib import Path
from urllib.parse import quote, unquote, urljoin

APP_ROOT = Path(__file__).resolve().parent
SCAN_CACHE_FILENAME = ".rom_downloader_scan_cache.json"
DEFAULT_PARALLEL_DOWNLOADS = 3

# ============================================================================
# Chargement des variables d'environnement (.env)
# ============================================================================

def load_env_file(file_path: str = '.env'):
    """Charge les variables d'un fichier .env dans os.environ."""
    if not os.path.exists(file_path):
        return
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    # Supprime les guillemets si présents
                    val = value.strip()
                    if (val.startswith('"') and val.endswith('"')) or \
                       (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    os.environ[key.strip()] = val
    except FileNotFoundError as e:
        print(f"  Erreur lancement du helper torrent: {e}")
        return False
    except Exception as e:
        print(f"Avertissement: Erreur lors du chargement du fichier .env: {e}")

# Charger le fichier .env dès le début
load_env_file()

# Mapping des credentials archive.org pour la librairie internetarchive
if 'IA_S3_ACCESS_KEY' in os.environ and 'IAS3_ACCESS_KEY' not in os.environ:
    os.environ['IAS3_ACCESS_KEY'] = os.environ['IA_S3_ACCESS_KEY']
if 'IA_S3_SECRET_KEY' in os.environ and 'IAS3_SECRET_KEY' not in os.environ:
    os.environ['IAS3_SECRET_KEY'] = os.environ['IA_S3_SECRET_KEY']


def install_python_packages(packages: list[str], quiet: bool = True) -> bool:
    """Installe des packages Python pour l'interpreteur courant."""
    cmd = [
        sys.executable, '-m', 'pip', 'install',
        '--disable-pip-version-check',
        '--no-warn-script-location',
    ]
    cmd.extend(packages)
    if quiet:
        cmd.append('-q')
    try:
        return subprocess.run(cmd, check=False).returncode == 0
    except Exception as e:
        print(f"Avertissement: installation pip impossible: {e}")
        return False


def import_optional_package(import_name: str, pip_name: str | None = None, auto_install: bool = False):
    """Importe un package optionnel, avec installation automatique si demandee."""
    try:
        return importlib.import_module(import_name)
    except ImportError:
        if not auto_install:
            return None
    package_name = pip_name or import_name
    print(f"Installation du package optionnel {package_name}...")
    if install_python_packages([package_name]):
        try:
            return importlib.import_module(import_name)
        except ImportError as e:
            print(f"Avertissement: {package_name} installe mais import impossible: {e}")
    return None


try:
    import requests
    from bs4 import BeautifulSoup
    import internetarchive
    import cloudscraper
except ImportError:
    print("Installation des packages requis (requests, beautifulsoup4, internetarchive, cloudscraper)...")
    install_python_packages(['requests', 'beautifulsoup4', 'internetarchive', 'charset_normalizer', 'cloudscraper'])
    import requests
    from bs4 import BeautifulSoup
    import internetarchive
    import cloudscraper

# ============================================================================
# Extensions de ROMs supportées (constante globale)
# ============================================================================

ROM_EXTENSIONS = (
    # Archives
    '.zip', '.7z', '.rar', '.gz', '.z', '.tar', '.tar.gz',
    # Nintendo - Game Boy
    '.gb', '.gbc', '.gba',
    # Nintendo - NES/SNES
    '.nes', '.smc', '.sfc', '.fig',
    # Nintendo - N64
    '.n64', '.z64', '.v64', '.ndd',
    # Nintendo - DS/3DS
    '.nds', '.dsi', '.3ds', '.cia', '.cxi',
    # Nintendo - GameCube/Wii
    '.gcm', '.rvz', '.ciso', '.gcz', '.wbfs', '.nkit.iso', '.nkit.gcm', '.nkit.rvz',
    # Sega - Master System/Game Gear
    '.sms', '.gg', '.sg',
    # Sega - Mega Drive/Genesis
    '.md', '.gen', '.smd',
    # Sega - 32X/CD
    '.32x', '.cdx',
    # Sega - CD images
    '.chd', '.cue', '.iso', '.bin', '.img', '.ccd', '.sub',
    # Sony - PlayStation
    '.psx', '.psf', '.pbp', '.ecm',
    # NEC - PC Engine/TurboGrafx
    '.pce', '.pcfx',
    # SNK - Neo Geo Pocket
    '.ngp', '.ngc', '.neo',
    # Atari
    '.lnx', '.rom', '.a26', '.a52', '.a78', '.j64', '.jag',
    # Bandai - WonderSwan
    '.ws', '.wsc', '.swc',
    # Virtual Boy
    '.vb',
    # Commodore/Amiga
    '.adf', '.adz', '.dms', '.ipf', '.hdf', '.hdz',
    # Commodore C64
    '.d64', '.d6z', '.d71', '.d7z', '.d80', '.d81', '.d82', '.d8z', '.g64', '.g6z',
    '.nib', '.nbz', '.x64', '.x6z', '.crt', '.t64',
    # Disk images (various)
    '.dsk', '.m3u', '.mds', '.mdf', '.nrg', '.b5i', '.bwi', '.cdi', '.c2d', '.daa', '.pdi',
    '.dim', '.d88', '.88d', '.hdm', '.hdi', '.tfd', '.dfi', '.fdi',
    # Tape images
    '.tap', '.tzx', '.cdt', '.z80', '.sna',
    # Atari ST
    '.st', '.msa',
    # ColecoVision
    '.col', '.cv',
)

MINERVA_BROWSE_BASE = 'https://minerva-archive.org/browse/'
MINERVA_TORRENT_BASE_CANDIDATES = (
    'https://minerva-archive.org/assets/Minerva_Myrient_v0.3/',
    'https://minerva-archive.org/assets/',
    'https://cdn.minerva-archive.org/'
)
LOLROMS_BASE = 'https://lolroms.com/'
CDROMANCE_BASE = 'https://cdromance.org/'
VIMM_BASE = 'https://vimm.net/'
RETRO_GAME_SETS_BASE = 'https://retrogamesets.fr/'
NPM_CACHE_DIR = APP_ROOT / '.npm-cache'
WEBTORRENT_HELPER = APP_ROOT / 'scripts' / 'minerva_torrent_download.js'
BALROG_ASSETS_DIR = APP_ROOT / 'assets'
BALROG_WINDOW_ICON = BALROG_ASSETS_DIR / 'Retrogaming-Toolkit-AIO.ico'
BALROG_1G1R_ICON = BALROG_ASSETS_DIR / 'icon_1g1r.png'

UI_COLOR_BG = '#151515'
UI_COLOR_CARD_BG = '#1e1e1e'
UI_COLOR_CARD_BORDER = '#444444'
UI_COLOR_INPUT_BG = '#202020'
UI_COLOR_INPUT_BORDER = '#3d3d3d'
UI_COLOR_TEXT_MAIN = '#ffffff'
UI_COLOR_TEXT_SUB = '#aaaaaa'
UI_COLOR_ACCENT = '#ff6699'
UI_COLOR_ACCENT_HOVER = '#ff3385'
UI_COLOR_GHOST = '#2b2b2b'
UI_COLOR_GHOST_HOVER = '#333333'
UI_COLOR_SUCCESS = '#2ecc71'
UI_COLOR_ERROR = '#e74c3c'
UI_COLOR_WARNING = '#f39c12'

SOURCE_FAMILY_MAP = {
    'No-Intro': 'no-intro',
    'Redump': 'redump',
    'TOSEC': 'tosec'
}
WEBTORRENT_MODULE_DIR = APP_ROOT / 'node_modules' / 'torrent-stream'

WINDOWS_NODE_PATHS = (
    r'%ProgramFiles%\nodejs\node.exe',
    r'%ProgramFiles(x86)%\nodejs\node.exe',
    r'%LocalAppData%\Programs\nodejs\node.exe'
)
WINDOWS_NPM_PATHS = (
    r'%ProgramFiles%\nodejs\npm.cmd',
    r'%ProgramFiles%\nodejs\npm',
    r'%ProgramFiles(x86)%\nodejs\npm.cmd',
    r'%AppData%\npm\npm.cmd'
)
MINERVA_TORRENT_AVAILABILITY = {}
MINERVA_TORRENT_URL_CACHE = {}
LOLROMS_SESSION = None

# ============================================================================
# Base de données locale des URLs (extrait de RGSX games.zip)
# 74,189 URLs - 100% autonome, ne dépend plus de RGSX
# ============================================================================

ROM_DATABASE_FILE = APP_ROOT / 'rom_database.zip'
ROM_DATABASE_SHARDS_DIR = APP_ROOT / 'rom_db_shards'
DEFAULT_CONFIG_URLS = {
    'archive_org': 'https://archive.org/download/',
    'edgeemu_base': 'https://edgeemu.net',
    'edgeemu_browse': 'https://edgeemu.net/browse-',
    'planetemu_base': 'https://www.planetemu.net',
    'planetemu_roms': 'https://www.planetemu.net/roms/',
    'planetemu_download_api': 'https://www.planetemu.net/php/roms/download.php',
    '1fichier_free': 'https://1fichier.com/',
    '1fichier_apikeys': 'https://1fichier.com/console/params.pl',
    'alldebrid_apikeys': 'https://alldebrid.com/apikeys/',
    'alldebrid_unlock': 'https://api.alldebrid.com/v4/link/unlock',
    'realdebrid_apikeys': 'https://real-debrid.com/apitoken',
    'realdebrid_unlock': 'https://api.real-debrid.com/rest/1.0/unrestrict/link',
}
ROM_DATABASE = None
ROM_DB_SHARD_CONNECTIONS = {}


def load_rom_database():
    """Charge la configuration; les index ROM sont lus depuis les shards zip."""
    global ROM_DATABASE

    if ROM_DATABASE is not None:
        return ROM_DATABASE

    try:
        import zipfile
        if os.path.exists(ROM_DATABASE_FILE):
            with zipfile.ZipFile(ROM_DATABASE_FILE, 'r') as zf:
                with zf.open('rom_database.json') as f:
                    ROM_DATABASE = json.load(f)
            config = DEFAULT_CONFIG_URLS.copy()
            config.update(ROM_DATABASE.get('config_urls', {}))
            ROM_DATABASE['config_urls'] = config
            print(f"Base de donnees legacy chargee : {ROM_DATABASE.get('total_urls', 0):,} URLs")
        else:
            shard_count = len(list(ROM_DATABASE_SHARDS_DIR.glob('shard_*.zip'))) if ROM_DATABASE_SHARDS_DIR.exists() else 0
            ROM_DATABASE = {
                'urls': [],
                'sources': {},
                'config_urls': DEFAULT_CONFIG_URLS.copy(),
                'shard_count': shard_count
            }
            if shard_count:
                print(f"Base locale en shards chargee : {shard_count} shards zip")
            else:
                print(f"ATTENTION: aucun shard trouve dans {ROM_DATABASE_SHARDS_DIR}")
                print("Executez scripts/build_minerva_hash_shards.py pour reconstruire la base.")

        return ROM_DATABASE
    except Exception as e:
        print(f"Erreur chargement base de donnees: {e}")
        ROM_DATABASE = {'urls': [], 'sources': {}, 'config_urls': DEFAULT_CONFIG_URLS.copy()}
        return ROM_DATABASE


def load_rom_db_shard(shard_char: str):
    """Ouvre un shard SQLite zippe et garde la connexion en cache."""
    shard_char = (shard_char or '').lower()
    if not re.fullmatch(r'[0-9a-f]', shard_char):
        return None, set()

    cached = ROM_DB_SHARD_CONNECTIONS.get(shard_char)
    if cached:
        return cached['conn'], cached['columns']

    shard_zip = ROM_DATABASE_SHARDS_DIR / f"shard_{shard_char}.zip"
    shard_db_name = f"shard_{shard_char}.db"
    if not shard_zip.exists():
        return None, set()

    try:
        import sqlite3
        import zipfile
        from tempfile import NamedTemporaryFile

        with zipfile.ZipFile(shard_zip, 'r') as zf:
            with zf.open(shard_db_name) as db_file:
                with NamedTemporaryFile(delete=False, suffix='.db') as tmp:
                    tmp.write(db_file.read())
                    tmp_path = tmp.name

        conn = sqlite3.connect(tmp_path)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(roms)").fetchall()}
        ROM_DB_SHARD_CONNECTIONS[shard_char] = {
            'conn': conn,
            'columns': columns,
            'tmp_path': tmp_path
        }
        return conn, columns
    except Exception as e:
        print(f"Erreur ouverture shard {shard_char}: {e}")
        return None, set()


def build_minerva_torrent_url_from_path(torrent_path: str) -> str:
    """Construit une URL de torrent Minerva depuis le chemin officiel de la DB hashes."""
    torrent_path = (torrent_path or '').replace('\\', '/').lstrip('./')
    if not torrent_path:
        return ''
    if torrent_path.startswith(('http://', 'https://')):
        return torrent_path
    return urljoin('https://minerva-archive.org/assets/', quote(torrent_path, safe='/'))


def is_minerva_database_result(result: dict) -> bool:
    """Detecte une entree de shard qui pointe vers un torrent Minerva."""
    host = (result.get('host') or '').lower()
    url = (result.get('url') or '').lower()
    torrent_url = (result.get('torrent_url') or '').lower()
    return (
        'minerva-torrent' in host
        or 'minerva-archive.org' in url
        or 'minerva-archive.org' in torrent_url
        or bool(result.get('torrent_path'))
    )

def search_by_md5(md5_hash: str) -> list:
    """Recherche une ROM par MD5 dans les shards SQLite zippes."""
    md5_hash = normalize_checksum(md5_hash, 'md5')
    if not md5_hash:
        return []

    conn, columns = load_rom_db_shard(md5_hash[0])
    if not conn:
        return []

    try:
        cursor = conn.cursor()
        if 'entries' in columns:
            cursor.execute("SELECT entries, urls FROM roms WHERE md5 = ?", (md5_hash,))
            row = cursor.fetchone()
            if not row:
                return []

            entries = json.loads(row[0] or '[]')
            urls = json.loads(row[1] or '[]')
            results = []
            for index, entry in enumerate(entries):
                torrent_path = entry.get('torrent_path') or entry.get('torrents') or ''
                torrent_url = entry.get('torrent_url') or build_minerva_torrent_url_from_path(torrent_path)
                if not torrent_url and index < len(urls):
                    torrent_url = urls[index]
                file_name = entry.get('file_name') or entry.get('filename') or entry.get('full_name') or md5_hash
                results.append({
                    'md5': md5_hash,
                    'url': torrent_url,
                    'torrent_url': torrent_url,
                    'torrent_path': torrent_path,
                    'host': entry.get('host') or 'minerva-torrent',
                    'filename': file_name,
                    'file_name': file_name,
                    'full_name': file_name,
                    'full_path': entry.get('full_path') or file_name,
                    'size': entry.get('size'),
                    'crc': entry.get('crc32') or entry.get('crc'),
                    'sha1': entry.get('sha1'),
                    'game_name': file_name
                })
            return results

        cursor.execute("SELECT urls FROM roms WHERE md5 = ?", (md5_hash,))
        row = cursor.fetchone()
        if not row:
            return []

        urls = json.loads(row[0])
        results = []
        for url in urls:
            host = 'archive.org'
            if 'minerva-archive.org' in url:
                host = 'minerva-torrent'
            elif '1fichier.com' in url:
                host = '1fichier'
            results.append({
                'md5': md5_hash,
                'url': url,
                'torrent_url': url if host == 'minerva-torrent' else '',
                'host': host,
                'game_name': md5_hash
            })
        return results
    except Exception as e:
        print(f"Erreur lors de la recherche MD5 dans le shard {md5_hash[0]}: {e}")
        return []


def database_result_filename(entry: dict, fallback: str = '') -> str:
    """Retourne le meilleur nom de fichier disponible pour une entrée de base locale."""
    return (
        entry.get('filename')
        or entry.get('full_name')
        or entry.get('game_name')
        or fallback
    )


def search_by_crc(crc_hash: str) -> list:
    """
    Recherche une ROM par CRC dans la base locale.
    La base actuelle ne contient pas d'index CRC dédié.
    """
    return []


def search_by_sha1(sha1_hash: str) -> list:
    """
    Recherche une ROM par SHA1 dans la base locale.
    La base actuelle ne contient pas d'index SHA1 dédié.
    """
    return []


def search_by_name(game_name: str) -> list:
    """
    Recherche une ROM par son nom dans la base de données locale.
    """
    if ROM_DATABASE is None:
        load_rom_database()
    
    if not game_name:
        return []
    
    exact_results = []
    partial_results = []
    game_normalized = strip_rom_extension(game_name).lower().strip()
    if not game_normalized:
        return []

    urls = ROM_DATABASE.get('urls', [])
    for entry in urls:
        filename = database_result_filename(entry).lower()
        filename_no_ext = strip_rom_extension(filename).lower()
        entry_game_name = str(entry.get('game_name', '')).lower().strip()
        entry_game_name_normalized = str(entry.get('game_name_normalized', '')).lower().strip()

        candidates = {
            value for value in (
                filename,
                filename_no_ext,
                entry_game_name,
                entry_game_name_normalized
            ) if value
        }

        if game_normalized in candidates:
            exact_results.append(entry)
        elif any(game_normalized in candidate for candidate in candidates):
            partial_results.append(entry)

        if len(exact_results) + len(partial_results) >= 50:
            break

    return exact_results + partial_results

# ============================================================================
# Configuration des sources de téléchargement
# ============================================================================

# Sources extraites de games.zip RGSX (74,189 URLs analysées)
# Ces sources sont utilisées indépendamment de RGSX

def get_default_sources_legacy():
    if ROM_DATABASE is None:
        load_rom_database()
    config = ROM_DATABASE.get('config_urls', {})
    return [
        {
            'name': 'archive.org',
            'base_url': config.get('archive_org', ''),
            'type': 'archive_org',
            'enabled': True,
            'description': 'Source principale',
            'priority': 1
        },
        {
            'name': 'Myrient No-Intro',
            'base_url': config.get('myrient_no_intro', ''),
            'type': 'myrient',
            'enabled': True,
            'description': 'ROMs No-Intro',
            'priority': 2
        },
        {
            'name': 'Myrient Redump',
            'base_url': config.get('myrient_redump', ''),
            'type': 'myrient',
            'enabled': True,
            'description': 'ROMs Redump',
            'priority': 2
        },
        {
            'name': 'Myrient TOSEC',
            'base_url': config.get('myrient_tosec', ''),
            'type': 'myrient',
            'enabled': True,
            'description': 'ROMs TOSEC',
            'priority': 2
        },
        {
            'name': 'EdgeEmu',
            'base_url': config.get('edgeemu_browse', ''),
            'type': 'edgeemu',
            'enabled': False,
            'description': 'Lien direct (Excellent pour le retro)',
            'priority': 2
        },
        {
            'name': 'PlanetEmu',
            'base_url': config.get('planetemu_roms', ''),
            'type': 'planetemu',
            'enabled': False,
            'description': 'Lien direct (POST) - Source FR majeure',
            'priority': 2
        },
        {
            'name': '1fichier (Gratuit)',
            'base_url': config.get('1fichier_free', ''),
            'type': 'free_host',
            'enabled': True,
            'description': 'Mode gratuit avec attente (si lien détecté)',
            'priority': 3
        }
    ]

# Mappings des systèmes pour les scrapers
# Permet de traduire le nom du système (extrait du DAT) en slug pour le site
SOURCE_TYPE_ORDER = {
    'edgeemu': 20,
    'planetemu': 30,
    'lolroms': 40,
    'cdromance': 45,
    'vimm': 50,
    'retrogamesets': 60,
    'free_host': 70,
    'myrient': 80,
    'minerva': 100,
    'archive_org': 110,
}


def source_order_key(source: dict) -> tuple:
    """Trie les sources avec archive.org en tout dernier recours."""
    return (
        SOURCE_TYPE_ORDER.get(source.get('type'), 60),
        source.get('priority', 50),
        source.get('name', '').lower()
    )


def normalize_source_label(value: str) -> str:
    """Normalise un nom de provider pour les retries."""
    return re.sub(r'\s+', ' ', (value or '').strip().lower())


def source_is_excluded(source: dict, excluded_sources: set[str]) -> bool:
    """Indique si une source est deja exclue pour un retry."""
    if not excluded_sources:
        return False
    labels = {
        normalize_source_label(source.get('name', '')),
        normalize_source_label(source.get('type', '')),
    }
    if source.get('type') == 'archive_org':
        labels.add('archive.org')
        labels.add('archive_org')
    return bool(labels & excluded_sources)


def get_default_sources():
    if ROM_DATABASE is None:
        load_rom_database()

    config = ROM_DATABASE.get('config_urls', {})
    sources = [
        {
            'name': 'Minerva No-Intro',
            'base_url': f'{MINERVA_BROWSE_BASE}No-Intro/',
            'type': 'minerva',
            'enabled': True,
            'description': 'Dernier recours torrent pour les DAT No-Intro / Retool',
            'collection': 'No-Intro',
            'minerva_path_mode': 'single',
            'scan_depth': 0,
            'torrent_scope': 'system',
            'priority': 100
        },
        {
            'name': 'Minerva Redump',
            'base_url': f'{MINERVA_BROWSE_BASE}Redump/',
            'type': 'minerva',
            'enabled': True,
            'description': 'Dernier recours torrent pour les DAT Redump / Retool',
            'collection': 'Redump',
            'minerva_path_mode': 'single',
            'scan_depth': 0,
            'torrent_scope': 'system',
            'priority': 100
        },
        {
            'name': 'Minerva TOSEC',
            'base_url': f'{MINERVA_BROWSE_BASE}TOSEC/',
            'type': 'minerva',
            'enabled': True,
            'description': 'Dernier recours torrent pour la collection TOSEC',
            'collection': 'TOSEC',
            'minerva_path_mode': 'split',
            'scan_depth': 2,
            'torrent_scope': 'vendor',
            'priority': 100
        },
        {
            'name': 'archive.org',
            'base_url': config.get('archive_org', ''),
            'type': 'archive_org',
            'enabled': True,
            'description': 'Fallback checksum / téléchargement direct',
            'priority': 2
        },
        {
            'name': 'EdgeEmu',
            'base_url': config.get('edgeemu_browse', ''),
            'type': 'edgeemu',
            'enabled': True,
            'description': 'Lien direct (Excellent pour le retro)',
            'priority': 3
        },
        {
            'name': 'PlanetEmu',
            'base_url': config.get('planetemu_roms', ''),
            'type': 'planetemu',
            'enabled': True,
            'description': 'Lien direct (POST) - Source FR majeure',
            'priority': 3
        },
        {
            'name': 'LoLROMs',
            'base_url': LOLROMS_BASE,
            'type': 'lolroms',
            'enabled': True,
            'description': 'Fallback direct via Cloudflare-compatible listing',
            'priority': 3
        },
        {
            'name': 'CDRomance',
            'base_url': CDROMANCE_BASE,
            'type': 'cdromance',
            'enabled': True,
            'description': 'Source majeure pour les jeux CD et traductions',
            'priority': 3
        },
        {
            'name': 'Vimm\'s Lair',
            'base_url': VIMM_BASE,
            'type': 'vimm',
            'enabled': True,
            'description': 'The Vault - Source de reference historique',
            'priority': 3
        },
        {
            'name': 'RetroGameSets',
            'base_url': RETRO_GAME_SETS_BASE,
            'type': 'retrogamesets',
            'enabled': True,
            'description': 'Base de donnees communautaire (1fichier)',
            'priority': 2
        },
        {
            'name': '1fichier (Gratuit)',
            'base_url': config.get('1fichier_free', ''),
            'type': 'free_host',
            'enabled': True,
            'description': 'Mode gratuit avec attente (si lien dÃ©tectÃ©)',
            'priority': 4
        }
    ]
    return sorted(sources, key=source_order_key)

SYSTEM_MAPPINGS = {
    'Nintendo - Game Boy': {
        'edgeemu': 'nintendo-gameboy',
        'planetemu': 'nintendo-game-boy',
        'lolroms': 'Nintendo - Game Boy',
        'vimm': 'GB',
        'retrogamesets': 'Game Boy (Archive)'
    },
    'Nintendo - Game Boy Color': {
        'edgeemu': 'nintendo-gameboycolor',
        'planetemu': 'nintendo-game-boy-color',
        'lolroms': 'Nintendo - Game Boy Color',
        'vimm': 'GBC',
        'retrogamesets': 'Game Boy Color (Archive)'
    },
    'Nintendo - Game Boy Advance': {
        'edgeemu': 'nintendo-gba',
        'planetemu': 'nintendo-game-boy-advance',
        'lolroms': 'Nintendo - Game Boy Advance',
        'vimm': 'GBA',
        'retrogamesets': 'Game Boy Advance (Archive)'
    },
    'Nintendo - Nintendo Entertainment System': {
        'edgeemu': 'nintendo-nes',
        'planetemu': 'nintendo-entertainment-system',
        'lolroms': 'Nintendo - Famicom/Headerless',
        'vimm': 'NES',
        'retrogamesets': 'NES (Archive)'
    },
    'Nintendo - Nintendo Entertainment System (Headered)': {
        'edgeemu': 'nintendo-nes',
        'planetemu': 'nintendo-entertainment-system',
        'lolroms': 'Nintendo - Famicom/Headered',
        'vimm': 'NES'
    },
    'Nintendo - Super Nintendo Entertainment System': {
        'edgeemu': 'nintendo-snes',
        'planetemu': 'nintendo-super-nintendo-entertainment-system',
        'lolroms': 'Nintendo - Super Famicom',
        'vimm': 'SNES',
        'retrogamesets': 'SNES (Archive)'
    },
    'Nintendo - Nintendo 64': {
        'edgeemu': 'nintendo-n64',
        'planetemu': 'nintendo-64',
        'lolroms': 'Nintendo - 64',
        'vimm': 'N64',
        'retrogamesets': 'Nintendo 64 (Archive)'
    },
    'Sega - Mega Drive - Genesis': {
        'edgeemu': 'sega-genesis',
        'planetemu': 'sega-mega-drive',
        'lolroms': 'SEGA/Mega Drive',
        'vimm': 'Genesis',
        'retrogamesets': 'Mega Drive (Archive)'
    },
    'Sega - Master System - Mark III': {
        'edgeemu': 'sega-mastersystem',
        'planetemu': 'sega-master-system',
        'lolroms': 'SEGA/Master System',
        'vimm': 'SMS',
        'retrogamesets': 'Master System (Archive)'
    },
    'Sega - Game Gear': {
        'edgeemu': 'sega-gamegear',
        'planetemu': 'sega-game-gear',
        'lolroms': 'SEGA/Game Gear',
        'vimm': 'GameGear',
        'retrogamesets': 'Game Gear (Archive)'
    },
    'NEC - PC Engine - TurboGrafx 16': {
        'edgeemu': 'nec-pcengine',
        'planetemu': 'nec-pc-engine-turbografx-16-entertainment-super-system',
        'vimm': 'Engine',
        'retrogamesets': 'PC Engine (Archive)'
    },
    'SNK - Neo Geo Pocket Color': {
        'edgeemu': 'snk-neogeopocketcolor',
        'planetemu': 'snk-neo-geo-pocket-color',
        'lolroms': 'SNK/NeoGeo Pocket Color',
        'retrogamesets': 'Neo-Geo Pocket Color (Archive)'
    },
    'Sony - PlayStation': {
        'lolroms': 'SONY/PlayStation',
        'vimm': 'PS1',
        'retrogamesets': 'PlayStation (Archive)'
    },
    'Sony - PlayStation Portable': {
        'lolroms': 'SONY/PlayStation Portable',
        'vimm': 'PSP',
        'retrogamesets': 'PlayStation Portable (Archive)'
    },
    'Nintendo - DS': {
        'lolroms': 'Nintendo - DS',
        'vimm': 'DS',
        'retrogamesets': 'Nintendo DS (LolRoms)'
    },
    'Nintendo - 3DS': {
        'lolroms': 'Nintendo - 3DS',
        'vimm': '3DS',
        'retrogamesets': '3DS (Archive)'
    },
    'Nintendo - GameCube': {
        'lolroms': 'Nintendo - GameCube',
        'vimm': 'GameCube',
        'retrogamesets': 'Game Cube (Archive)'
    },
    'Nintendo - Wii': {
        'lolroms': 'Nintendo - Wii',
        'vimm': 'Wii',
        'retrogamesets': 'Wii (Archive)'
    },
    'Nintendo - Wii U': {
        'lolroms': 'Nintendo - Wii U',
        'vimm': 'WiiU',
        'retrogamesets': 'Wii U (EU) (1Fichier)'
    },
    'Nintendo - Virtual Boy': {
        'lolroms': 'Nintendo - Virtual Boy',
        'vimm': 'VirtualBoy',
        'retrogamesets': 'Virtual Boy (Archive)'
    },
    'Nintendo - Pokémon Mini': {
        'lolroms': 'Nintendo - Pokémon Mini',
        'retrogamesets': 'Pokemon Mini (Archive)'
    }
}


# ============================================================================
# Configuration des clés API
# ============================================================================

def build_minerva_directory_url(source: dict, system_name: str | None) -> str:
    """Construit l'URL de listing Minerva à partir de la source et du système."""
    base_url = source.get('base_url', '').rstrip('/') + '/'
    if source.get('fixed_directory'):
        return base_url
    if not system_name:
        return base_url

    path_mode = source.get('minerva_path_mode', 'single')
    if path_mode == 'split':
        segments = [segment.strip() for segment in system_name.split(' - ') if segment.strip()]
    else:
        segments = [system_name.strip()]

    if not segments:
        return base_url

    return base_url + '/'.join(quote(segment) for segment in segments) + '/'


def build_minerva_torrent_name(source: dict, system_name: str | None) -> str:
    """Construit le nom du torrent Minerva correspondant au système."""
    collection = source.get('collection', '').strip()
    if not collection:
        return ''

    if system_name:
        if source.get('torrent_scope') == 'vendor':
            target = system_name.split(' - ')[0].strip()
        else:
            target = system_name.strip()
    else:
        target = ''

    if not target:
        return ''

    return f"Minerva_Myrient - {collection} - {target}.torrent"


def build_minerva_torrent_urls(source: dict, system_name: str | None) -> list[str]:
    """Construit les URLs candidates du torrent Minerva correspondant au système."""
    torrent_name = build_minerva_torrent_name(source, system_name)
    if not torrent_name:
        return []

    quoted_name = quote(torrent_name)
    return [urljoin(base_url, quoted_name) for base_url in MINERVA_TORRENT_BASE_CANDIDATES]


def is_minerva_torrent_available(torrent_url: str, session: requests.Session) -> bool:
    """Valide rapidement qu'un torrent Minerva existe avant de l'utiliser pour toute une collection."""
    if not torrent_url:
        return False

    cached = MINERVA_TORRENT_AVAILABILITY.get(torrent_url)
    if cached is not None:
        return cached

    try:
        response = session.get(torrent_url, timeout=20, stream=True, allow_redirects=True)
        available = response.status_code == 200
        response.close()
    except Exception:
        available = False

    MINERVA_TORRENT_AVAILABILITY[torrent_url] = available
    return available


def resolve_minerva_torrent_url(source: dict, system_name: str | None, session: requests.Session) -> str:
    """Résout l'URL réelle du torrent Minerva pour un système donné."""
    torrent_name = build_minerva_torrent_name(source, system_name)
    if not torrent_name:
        return ''

    cached = MINERVA_TORRENT_URL_CACHE.get(torrent_name)
    if cached is not None:
        return cached

    for torrent_url in build_minerva_torrent_urls(source, system_name):
        if is_minerva_torrent_available(torrent_url, session):
            MINERVA_TORRENT_URL_CACHE[torrent_name] = torrent_url
            return torrent_url

    MINERVA_TORRENT_URL_CACHE[torrent_name] = ''
    return ''


def normalize_system_name(system_name: str) -> str:
    """Nettoie le nom d'un système issu d'un DAT tout en gardant l'intitulé Minerva."""
    cleaned = re.sub(r'\s+', ' ', (system_name or '')).strip()
    if not cleaned:
        return ''

    cleanup_patterns = [
        r'\s*[\(\[]\s*(?:retool|1g1r)[^\)\]]*[\)\]]\s*$',
        r'\s*-\s*retool\s*$',
        r'\s+retool\s*$'
    ]

    previous = None
    while cleaned and cleaned != previous:
        previous = cleaned
        for pattern in cleanup_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE).strip()

    return re.sub(r'\s+', ' ', cleaned).strip()


def detect_dat_profile(dat_file_path: str) -> dict:
    """
    Détecte le profil d'un DAT afin d'aiguiller automatiquement les sources.
    Compatible avec les DAT No-Intro / Redump retraités via Retool pour le 1G1R.
    """
    header_name = ''
    header_url = ''
    header_description = ''
    retool_marker = ''

    try:
        tree = ET.parse(dat_file_path)
        root = tree.getroot()
        header_name = root.findtext('./header/name', default='').strip()
        header_url = root.findtext('./header/url', default='').strip()
        header_description = root.findtext('./header/description', default='').strip()
        retool_marker = (
            root.findtext('./header/retool', default='').strip()
            or root.findtext('.//retool', default='').strip()
        )
    except Exception:
        pass

    fallback_name = os.path.splitext(os.path.basename(dat_file_path))[0]
    fallback_name = re.sub(r'[\(\[].*?[\)\]]', '', fallback_name).strip()
    fallback_name = re.sub(r'\s+', ' ', fallback_name)

    raw_system_name = header_name or fallback_name
    system_name = normalize_system_name(raw_system_name) or fallback_name

    header_url_lower = header_url.lower()
    header_name_lower = header_name.lower()
    header_description_lower = header_description.lower()

    family = 'unknown'
    family_label = 'Inconnu'
    if 'redump.org' in header_url_lower or 'redump' in header_name_lower:
        family = 'redump'
        family_label = 'Redump'
    elif 'no-intro.org' in header_url_lower or 'no-intro' in header_name_lower:
        family = 'no-intro'
        family_label = 'No-Intro'
    elif 'tosec' in header_url_lower or 'tosec' in header_name_lower:
        family = 'tosec'
        family_label = 'TOSEC'

    is_retool = bool(
        retool_marker
        or re.search(r'\bretool\b', header_name_lower)
        or re.search(r'\bretool\b', header_description_lower)
    )

    return {
        'path': dat_file_path,
        'raw_system_name': raw_system_name,
        'system_name': system_name,
        'header_name': header_name,
        'header_url': header_url,
        'family': family,
        'family_label': family_label,
        'is_retool': is_retool,
        'retool_label': 'Retool / 1G1R' if is_retool else 'DAT brut',
        'default_source_url': ''
    }


def build_profile_default_source_url(dat_profile: dict) -> str:
    """Construit l'URL Minerva par défaut correspondant au profil DAT."""
    family = (dat_profile or {}).get('family', 'unknown')
    system_name = (dat_profile or {}).get('system_name')
    collection = next(
        (name for name, mapped_family in SOURCE_FAMILY_MAP.items() if mapped_family == family),
        ''
    )
    if not collection or not system_name:
        return ''

    source = next(
        (item for item in get_default_sources() if item.get('collection') == collection),
        None
    )
    if not source:
        return ''
    return build_minerva_directory_url(source, system_name)


def finalize_dat_profile(dat_profile: dict) -> dict:
    """Complète un profil DAT avec les champs dérivés utiles à la CLI et à la GUI."""
    profile = (dat_profile or {}).copy()
    profile['default_source_url'] = build_profile_default_source_url(profile)
    return profile


def get_source_family(source: dict) -> str:
    """Retourne la famille logique couverte par une source."""
    if source.get('fixed_directory') or source.get('name') == 'Minerva Custom':
        return 'custom'
    return SOURCE_FAMILY_MAP.get(source.get('collection', '').strip(), '')


def is_source_compatible_with_profile(source: dict, dat_profile: dict | None) -> bool:
    """Détermine si une source est cohérente avec le DAT détecté."""
    if not dat_profile:
        return True

    family = dat_profile.get('family', 'unknown')
    if family == 'unknown':
        return True

    source_type = source.get('type')
    if source_type == 'minerva':
        source_family = get_source_family(source)
        return source_family in {'', 'custom', family}

    if family == 'redump' and source_type in {'edgeemu', 'planetemu', 'lolroms'}:
        return False

    return True


def prepare_sources_for_profile(sources: list, dat_profile: dict | None) -> list:
    """Applique les recommandations de sources à partir du profil DAT."""
    prepared = []
    for source in sources:
        source_copy = source.copy()
        compatible = is_source_compatible_with_profile(source_copy, dat_profile)
        source_copy['compatible'] = compatible

        source_copy['enabled'] = True

        prepared.append(source_copy)

    return prepared


def describe_dat_profile(dat_profile: dict | None) -> str:
    """Retourne un résumé lisible du DAT détecté."""
    if not dat_profile:
        return "DAT inconnu"

    parts = []
    system_name = dat_profile.get('system_name')
    if system_name:
        parts.append(system_name)

    family_label = dat_profile.get('family_label')
    if family_label and family_label != 'Inconnu':
        parts.append(family_label)

    retool_label = dat_profile.get('retool_label')
    if retool_label:
        parts.append(retool_label)

    return " | ".join(parts) if parts else "DAT inconnu"


def list_minerva_directory(minerva_url: str, session: requests.Session) -> tuple[set, list]:
    """Liste les fichiers et sous-dossiers d'un répertoire Minerva."""
    print(f"Fetching Minerva directory listing: {minerva_url}")

    files = set()
    directories = []

    try:
        response = session.get(minerva_url, timeout=60)
        if response.status_code != 200:
            print(f"Erreur Minerva ({response.status_code}) pour {minerva_url}")
            return files, directories

        soup = BeautifulSoup(response.text, 'html.parser')
        seen_dirs = set()
        for link in soup.find_all('a', href=True):
            href = html_module.unescape(link.get('href', '')).strip()
            text = html_module.unescape(link.get_text().strip())

            if not href or not text or text in {'Home', 'Browse', 'Search', 'Contact Us', 'FAQ', 'DMCA', 'Root', '../'}:
                continue

            if href.startswith('/rom'):
                if text.lower().endswith(ROM_EXTENSIONS):
                    files.add(text.rstrip('/'))
                continue

            if '/browse/' in href and text.endswith('/'):
                directory_url = urljoin(MINERVA_BROWSE_BASE, href.replace('/browse/', ''))
                normalized = directory_url.rstrip('/').lower()
                if normalized not in seen_dirs:
                    seen_dirs.add(normalized)
                    directories.append({
                        'name': text.rstrip('/'),
                        'url': directory_url
                    })

        print(f"Found {len(files)} files and {len(directories)} subdirectories on Minerva")
    except Exception as e:
        print(f"Error fetching Minerva directory: {e}")

    return files, directories


def collect_minerva_files_from_url(minerva_url: str, session: requests.Session, depth: int = 0) -> set:
    """Collecte récursivement les fichiers d'un dossier Minerva."""
    files, directories = list_minerva_directory(minerva_url, session)
    if depth <= 0 or not directories:
        return files

    collected = set(files)
    for directory in directories:
        collected.update(collect_minerva_files_from_url(directory['url'], session, depth - 1))
    return collected


def select_database_result(db_results: list) -> dict | None:
    """Choisit un résultat de la base locale sans utiliser les providers de dernier recours."""
    candidates = []
    for result in db_results:
        if is_minerva_database_result(result):
            continue
        host = (result.get('host') or '').lower()
        url = (result.get('url') or '').lower()
        if 'myrient' in host or 'myrient' in url:
            continue
        if 'archive.org' in host or 'archive.org' in url:
            continue
        candidates.append(result)

    if not candidates:
        return None

    for result in candidates:
        host = (result.get('host') or '').lower()
        url = (result.get('url') or '').lower()
        if '1fichier.com' in host or '1fichier.com' in url:
            return result

    return candidates[0]


def search_database_for_game(game_info: dict) -> tuple[list, str]:
    """Recherche un jeu dans la base locale selon la priorité MD5 -> CRC -> SHA1 -> nom."""
    roms = game_info.get('roms', [])
    search_plan = [
        ('MD5', 'md5', search_by_md5),
        ('CRC', 'crc', search_by_crc),
        ('SHA1', 'sha1', search_by_sha1)
    ]

    for label, checksum_type, resolver in search_plan:
        for rom_info in roms:
            checksum_value = normalize_checksum(rom_info.get(checksum_type, ''), checksum_type)
            if not checksum_value:
                continue
            results = resolver(checksum_value)
            if results:
                return results, f"{label}: {checksum_value}"

    primary_rom = game_info.get('primary_rom', '')
    primary_name = strip_rom_extension(primary_rom).strip()
    if primary_name:
        results = search_by_name(primary_name)
        if results:
            return results, f"nom ROM: {primary_name}"

    game_name = game_info.get('game_name', '')
    if game_name:
        results = search_by_name(game_name)
        if results:
            return results, f"nom jeu: {game_name}"

    return [], ''


def search_minerva_hash_database_for_game(game_info: dict) -> dict | None:
    """Resout un jeu via les shards officiels Minerva en matchant le MD5 DAT."""
    for rom_info in game_info.get('roms', []):
        md5_value = normalize_checksum(rom_info.get('md5', ''), 'md5')
        if not md5_value:
            continue

        for result in search_by_md5(md5_value):
            if not is_minerva_database_result(result):
                continue
            torrent_url = result.get('torrent_url') or result.get('url')
            if not torrent_url:
                continue

            file_name = result.get('file_name') or result.get('filename') or result.get('full_name') or rom_info.get('name')
            full_path = result.get('full_path') or file_name
            resolved = game_info.copy()
            resolved['source'] = 'Minerva Official Hashes'
            resolved['database_host'] = 'minerva-torrent'
            resolved['download_filename'] = file_name
            resolved['torrent_target_filename'] = full_path
            resolved['torrent_url'] = torrent_url
            resolved['minerva_md5'] = md5_value
            resolved['minerva_full_path'] = full_path
            resolved['minerva_torrent_path'] = result.get('torrent_path', '')
            return resolved

    return None


def search_minerva_hash_database_for_games(missing_games: list) -> tuple[list, list]:
    """Recherche une liste de jeux dans les shards officiels Minerva par MD5."""
    found = []
    still_missing = []
    for game_info in missing_games:
        resolved = search_minerva_hash_database_for_game(game_info)
        if resolved:
            found.append(resolved)
            print(f"  [Minerva hashes] {game_info['game_name']} -> {resolved.get('download_filename')}")
        else:
            still_missing.append(game_info)
    return found, still_missing


def resolve_executable_path(candidates: tuple[str, ...], fallback_paths: tuple[str, ...] = ()) -> str:
    """Resout le chemin d'un executable depuis le PATH ou des emplacements Windows frequents."""
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    for raw_path in fallback_paths:
        expanded = os.path.expandvars(raw_path)
        if expanded and os.path.exists(expanded):
            return expanded

    return ''


def resolve_node_runtime_paths() -> tuple[str, str]:
    """Retourne les chemins vers node et npm, meme si le PATH du processus GUI est incomplet."""
    node_path = resolve_executable_path(('node', 'node.exe'), WINDOWS_NODE_PATHS)
    npm_path = resolve_executable_path(('npm', 'npm.cmd', 'npm.exe'), WINDOWS_NPM_PATHS)
    return node_path, npm_path


def ensure_webtorrent_runtime() -> bool:
    """Installe le runtime torrent Node localement si nécessaire."""
    if WEBTORRENT_MODULE_DIR.exists():
        return True

    node_path, npm_path = resolve_node_runtime_paths()

    if not node_path:
        print("  Erreur: Node.js est requis pour le téléchargement torrent Minerva")
        return False

    if not npm_path:
        print("  Erreur: npm est requis pour installer le runtime torrent")
        return False

    print("  Installation du runtime torrent Node...")
    env = os.environ.copy()
    env['npm_config_cache'] = str(NPM_CACHE_DIR)

    try:
        subprocess.run(
            [npm_path, 'install', '--no-fund', '--no-audit', '--ignore-scripts', 'torrent-stream'],
            cwd=str(APP_ROOT),
            check=True,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
    except FileNotFoundError as e:
        print(f"  Erreur lancement npm: {e}")
        print(f"  npm detecte: {npm_path or 'introuvable'}")
        return False
    except subprocess.CalledProcessError as e:
        print("  Échec de l'installation du runtime torrent:")
        print(e.stdout or str(e))
        return False

    return WEBTORRENT_MODULE_DIR.exists()


def download_from_minerva_torrent(torrent_url: str, target_filename: str, dest_path: str,
                                  progress_callback=None) -> bool:
    """Télécharge un fichier précis depuis un torrent Minerva via le runtime Node local."""
    if not torrent_url or not target_filename:
        print("  Erreur: URL de torrent ou nom de fichier manquant")
        return False

    if not ensure_webtorrent_runtime():
        return False

    if not WEBTORRENT_HELPER.exists():
        print(f"  Erreur: helper torrent introuvable: {WEBTORRENT_HELPER}")
        return False

    node_path, _ = resolve_node_runtime_paths()
    if not node_path:
        print("  Erreur: executable Node.js introuvable pour le helper torrent")
        return False

    temp_dir = Path(tempfile.mkdtemp(prefix='minerva-torrent-'))
    env = os.environ.copy()
    if 'MINERVA_TORRENT_TIMEOUT_MS' not in env:
        env['MINERVA_TORRENT_TIMEOUT_MS'] = '0'

    try:
        process = subprocess.Popen(
            [node_path, str(WEBTORRENT_HELPER), torrent_url, target_filename, dest_path, str(temp_dir)],
            cwd=str(APP_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=env
        )

        if not process.stdout:
            print("  Erreur: impossible de lire la sortie du helper torrent")
            return False

        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                print(f"  [torrent] {line}")
                continue

            event_type = event.get('type')
            if event_type == 'metadata':
                print(f"  Torrent chargé: {event.get('torrentName', 'Inconnu')} ({event.get('files', 0)} fichiers)")
            elif event_type == 'selected':
                print(f"  Fichier sélectionné dans le torrent: {event.get('file', target_filename)}")
            elif event_type == 'progress':
                progress = float(event.get('progress', 0))
                if progress_callback:
                    progress_callback(progress)
            elif event_type == 'warning':
                print(f"  Avertissement torrent: {event.get('message', '')}")
            elif event_type == 'error':
                print(f"  Erreur torrent: {event.get('message', '')}")
            elif event_type == 'done':
                if progress_callback:
                    progress_callback(100.0)
                print(f"  Torrent terminé: {event.get('destination', dest_path)}")

        return process.wait() == 0 and os.path.exists(dest_path)
    except Exception as e:
        print(f"  Erreur téléchargement torrent Minerva: {e}")
        return False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


API_CONFIG_FILE = 'api_keys.json'


def load_api_keys() -> dict:
    """
    Charge les clés API depuis le fichier de configuration et les variables d'environnement.
    Priorité: Variables d'environnement (.env) > Fichier api_keys.json
    """
    keys = {
        '1fichier': os.environ.get('ONE_FICHIER_API_KEY', ''),
        'alldebrid': os.environ.get('ALLDEBRID_API_KEY', ''),
        'realdebrid': os.environ.get('REALDEBRID_API_KEY', '')
    }
    
    # Si les clés du .env sont vides, on tente de charger depuis le fichier JSON
    if os.path.exists(API_CONFIG_FILE):
        try:
            with open(API_CONFIG_FILE, 'r', encoding='utf-8') as f:
                json_keys = json.load(f)
                # On ne surcharge que si la clé .env est vide
                for k in keys:
                    if not keys[k] and k in json_keys:
                        keys[k] = json_keys[k]
        except Exception as e:
            print(f"Erreur lors du chargement des clés API (JSON): {e}")
    
    return keys


def save_api_keys(keys: dict) -> bool:
    """Sauvegarde les clés API dans le fichier .env."""
    try:
        env_path = '.env'
        # On lit le fichier existant pour ne pas écraser les autres variables
        lines = []
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        
        # Mappings entre clés internes et noms de variables d'env
        mapping = {
            '1fichier': 'ONE_FICHIER_API_KEY',
            'alldebrid': 'ALLDEBRID_API_KEY',
            'realdebrid': 'REALDEBRID_API_KEY'
        }
        
        # On met à jour ou on ajoute les lignes
        new_lines = []
        found_keys = set()
        
        for line in lines:
            stripped = line.strip()
            handled = False
            for k, env_name in mapping.items():
                if stripped.startswith(f"{env_name}="):
                    new_lines.append(f"{env_name}={keys[k]}\n")
                    found_keys.add(k)
                    handled = True
                    break
            if not handled:
                new_lines.append(line)
        
        # On ajoute les clés manquantes
        for k, env_name in mapping.items():
            if k not in found_keys:
                new_lines.append(f"{env_name}={keys[k]}\n")
        
        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
            
        # On met aussi à jour l'os.environ actuel
        for k, env_name in mapping.items():
            os.environ[env_name] = keys[k]
            
        return True
    except Exception as e:
        print(f"Erreur lors de la sauvegarde des clés API dans .env: {e}")
        return False


def configure_api_keys():
    """Interactive configuration of API keys."""
    print("\n" + "=" * 60)
    print("CONFIGURATION DES CLÉS API")
    print("=" * 60)
    
    keys = load_api_keys()
    
    print("\nClés API actuelles:")
    for service, key in keys.items():
        masked = key[:10] + "..." if len(key) > 10 else key
        print(f"  - {service}: {masked if key else '(non configurée)'}")
    
    print("\nPour obtenir vos clés API (voir la configuration de la DB):")
    config = ROM_DATABASE.get('config_urls', {})
    print(f"  1fichier:   {config.get('1fichier_apikeys', 'Consultez le site 1fichier')}")
    print(f"  AllDebrid:  {config.get('alldebrid_apikeys', 'Consultez le site AllDebrid')}")
    print(f"  RealDebrid: {config.get('realdebrid_apikeys', 'Consultez le site RealDebrid')}")
    
    print("\nEntrez vos clés API (laissez vide pour conserver):")
    
    for service in keys:
        new_key = input(f"  Clé {service}: ").strip()
        if new_key:
            keys[service] = new_key
    
    if save_api_keys(keys):
        print("\nClés API sauvegardées avec succès dans le fichier .env!")
    else:
        print("\nErreur lors de la sauvegarde des clés API dans .env.")
    
    return keys


def is_1fichier_url(url: str) -> bool:
    """Détecte si l'URL est un lien 1fichier."""
    return "1fichier.com" in url if url else False


# ============================================================================
# Fonctions pour les services premium (1fichier, AllDebrid, RealDebrid)
# ============================================================================

# Regex pour détecter le compte à rebours 1fichier (mode gratuit)
WAIT_REGEXES_1F = [
    r'var\s+ct\s*=\s*(\d+)\s*\*\s*60',
    r'var\s+ct\s*=\s*(\d+)\s*\*60',
    r'(?:veuillez\s+)?patiente[rz]\s*(\d+)\s*(?:min|minute)s?\b',
    r'please\s+wait\s*(\d+)\s*(?:min|minute)s?\b',
    r'(?:veuillez\s+)?patiente[rz]\s*(\d+)\s*(?:sec|secondes?|s)\b',
    r'please\s+wait\s*(\d+)\s*(?:sec|seconds?)\b',
    r'var\s+ct\s*=\s*(\d+)\s*;',
]


def extract_wait_seconds_1f(html_text: str) -> int:
    """Extrait le temps d'attente depuis le HTML 1fichier"""
    import html as html_module
    for i, pattern in enumerate(WAIT_REGEXES_1F):
        match = re.search(pattern, html_text, re.IGNORECASE)
        if match:
            value = int(match.group(1))
            # Les deux premiers patterns sont en minutes (avec *60)
            if i < 2 or 'min' in pattern.lower():
                seconds = value * 60
            else:
                seconds = value
            return seconds
    return 0


def download_1fichier_free(url: str, dest_path: str, session: requests.Session, progress_callback=None) -> bool:
    """
    Download from 1fichier in FREE mode (without API key).
    Handles wait timer and form submission.
    """
    try:
        # Step 1: Get initial page
        response = session.get(url, allow_redirects=True, timeout=30)
        response.raise_for_status()
        html = response.text
        
        # Step 2: Extract and wait for countdown
        wait_seconds = extract_wait_seconds_1f(html)
        if wait_seconds > 0:
            print(f"  Attente: {wait_seconds} secondes...")
            for remaining in range(wait_seconds, 0, -1):
                time.sleep(1)
        
        # Step 3: Find and submit form
        form_match = re.search(r'<form[^>]*id=[\"\']f1[\"\'][^>]*>(.*?)</form>', html, re.DOTALL | re.IGNORECASE)
        if form_match:
            form_html = form_match.group(1)
            data = {}
            for inp_match in re.finditer(r'<input[^>]+>', form_html, re.IGNORECASE):
                inp = inp_match.group(0)
                name_m = re.search(r'name=[\"\']([^\"\']+)', inp)
                value_m = re.search(r'value=[\"\']([^\"\']*)', inp)
                if name_m:
                    name = name_m.group(1)
                    value = html_module.unescape(value_m.group(1) if value_m else '')
                    data[name] = value
            
            # POST form
            response = session.post(str(response.url), data=data, allow_redirects=True, timeout=30)
            response.raise_for_status()
            html = response.text
        
        # Step 4: Find download link
        patterns = [
            r'href=[\"\']([^\"\']+)[\"\'][^>]*>(?:cliquer|click|télécharger|download)',
            r'href=[\"\']([^\"\']*/dl/[^\"\']+)',
            r'(https?://[a-z0-9.-]*1fichier\.com/[A-Za-z0-9]{8,})'
        ]
        
        direct_link = None
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                captured = match.group(1)
                direct_link = captured if captured.startswith(('http://', 'https://')) else urljoin(str(response.url), captured)
                # Skip non-download pages
                if any(x in direct_link.lower() for x in ['/register', '/login', '/inscription']):
                    continue
                break
        
        if not direct_link:
            print(f"  Erreur: Lien de téléchargement introuvable")
            return False
        
        # Step 5: Download file
        with session.get(direct_link, stream=True, allow_redirects=True, timeout=120) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get('content-length', 0))
            downloaded = 0
            
            with open(dest_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0 and progress_callback:
                            progress_callback((downloaded / total) * 100)
        
        if progress_callback:
            progress_callback(100.0)
        return True
        
    except Exception as e:
        print(f"  Erreur 1fichier (mode gratuit): {e}")
        return False


def download_1fichier(file_id: str, dest_path: str, api_key: str, progress_callback=None) -> bool:
    """
    Download a file from 1fichier using the API.
    file_id: The file ID from the 1fichier URL (e.g., abc123 from the download link)
    """
    if not api_key:
        print("  Erreur: Clé API 1fichier manquante")
        return False
    
    try:
        # Get download link from API
        config = ROM_DATABASE.get('config_urls', {})
        api_url = config.get('1fichier_getlink', '')
        params = {
            'apikey': api_key,
            'file_id': file_id
        }
        
        response = requests.post(api_url, data=params, timeout=30)
        
        if response.status_code != 200:
            print(f"  Erreur API 1fichier: {response.status_code}")
            return False
        
        result = response.json()
        
        if result.get('status') != 'OK':
            print(f"  Erreur: {result.get('message', 'Unknown error')}")
            return False
        
        download_url = result.get('download_url')
        if not download_url:
            print("  Erreur: Pas d'URL de téléchargement")
            return False
        
        # Download the file
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})
        
        with session.get(download_url, stream=True, allow_redirects=True, timeout=120) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get('content-length', 0))
            downloaded = 0
            
            with open(dest_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0 and progress_callback:
                            progress_callback((downloaded / total) * 100)
        
        if progress_callback:
            progress_callback(100.0)
        return True
        
    except Exception as e:
        print(f"  Erreur 1fichier (API): {e}")
        return False


def download_alldebrid(url: str, dest_path: str, api_key: str, progress_callback=None) -> bool:
    """
    Download a file using AllDebrid service.
    url: The original hoster URL (e.g., 1fichier link)
    """
    if not api_key:
        print("  Erreur: Clé API AllDebrid manquante")
        return False
    
    try:
        # Step 1: Unlock the link
        config = ROM_DATABASE.get('config_urls', {})
        api_url = config.get('alldebrid_unlock', '')
        params = {
            'agent': 'rom_downloader',
            'apikey': api_key,
            'link': url
        }
        
        response = requests.get(api_url, params=params, timeout=30)
        
        if response.status_code != 200:
            print(f"  Erreur API AllDebrid: {response.status_code}")
            return False
        
        result = response.json()
        
        if result.get('status') != 'success':
            error = result.get('error', {})
            print(f"  Erreur: {error.get('message', 'Unknown error')}")
            return False
        
        download_url = result.get('data', {}).get('downloadLink')
        if not download_url:
            print("  Erreur: Pas d'URL de téléchargement")
            return False
        
        # Download the file
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})
        
        with session.get(download_url, stream=True, allow_redirects=True, timeout=120) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get('content-length', 0))
            downloaded = 0
            
            with open(dest_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0 and progress_callback:
                            progress_callback((downloaded / total) * 100)
        
        if progress_callback:
            progress_callback(100.0)
        return True
        
    except Exception as e:
        print(f"  Erreur AllDebrid: {e}")
        return False


def download_realdebrid(url: str, dest_path: str, api_key: str, progress_callback=None) -> bool:
    """
    Download a file using RealDebrid service.
    url: The original hoster URL or torrent magnet link
    """
    if not api_key:
        print("  Erreur: Clé API RealDebrid manquante")
        return False
    
    try:
        # Step 1: Unrestrict link
        config = ROM_DATABASE.get('config_urls', {})
        api_url = config.get('realdebrid_unlock', '')
        params = {
            'auth_token': api_key,
            'link': url
        }
        
        response = requests.post(api_url, data=params, timeout=30)
        
        if response.status_code != 200:
            print(f"  Erreur API RealDebrid: {response.status_code}")
            return False
        
        result = response.json()
        
        if 'error' in result:
            print(f"  Erreur: {result.get('error', 'Unknown error')}")
            return False
        
        download_url = result.get('download')
        if not download_url:
            print("  Erreur: Pas d'URL de téléchargement")
            return False
        
        # Download the file
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})
        
        with session.get(download_url, stream=True, allow_redirects=True, timeout=120) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get('content-length', 0))
            downloaded = 0
            
            with open(dest_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0 and progress_callback:
                            progress_callback((downloaded / total) * 100)
        
        if progress_callback:
            progress_callback(100.0)
        return True
        
    except Exception as e:
        print(f"  Erreur RealDebrid: {e}")
        return False


def download_from_premium_source(source_type: str, url: str, dest_path: str, 
                                  api_keys: dict, progress_callback=None) -> bool:
    """
    Download from a premium source (1fichier, AllDebrid, RealDebrid).
    For 1fichier: tries API first, then AllDebrid / RealDebrid, then free mode.
    """
    if source_type == '1fichier':
        api_key = api_keys.get('1fichier', '')
        
        # Try API mode if key available
        if api_key:
            # Extract file ID from URL
            file_id = url.split('?')[-1].split('#')[0] if '?' in url else ''
            if file_id:
                result = download_1fichier(file_id, dest_path, api_key, progress_callback)
                if result:
                    return True

        # Try debrid services before falling back to free 1fichier
        alldebrid_key = api_keys.get('alldebrid', '')
        if alldebrid_key:
            print("  Tentative via AllDebrid...")
            if download_alldebrid(url, dest_path, alldebrid_key, progress_callback):
                return True

        realdebrid_key = api_keys.get('realdebrid', '')
        if realdebrid_key:
            print("  Tentative via RealDebrid...")
            if download_realdebrid(url, dest_path, realdebrid_key, progress_callback):
                return True
        
        # Fallback to free mode
        print("  Bascule en mode gratuit 1fichier...")
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})
        return download_1fichier_free(url, dest_path, session, progress_callback)
    
    elif source_type == 'alldebrid':
        return download_alldebrid(url, dest_path, api_keys.get('alldebrid', ''), progress_callback)
    
    elif source_type == 'realdebrid':
        return download_realdebrid(url, dest_path, api_keys.get('realdebrid', ''), progress_callback)
    
    return False


def print_sources_info():
    """Print information about available download sources."""
    print("\n" + "=" * 70)
    print("SOURCES DE TÉLÉCHARGEMENT DISPONIBLES")
    print("Extrait de games.zip RGSX (74,189 URLs analysées)")
    print("=" * 70)
    
    print("\n--- Sources DDL prioritaires ---")
    for i, source in enumerate(get_default_sources(), 1):
        if source['type'] not in ('archive_org', 'edgeemu', 'planetemu', 'lolroms', 'cdromance', 'vimm', 'retrogamesets', 'free_host'):
            continue
        print(f"\n{i}. {source['name']}")
        print(f"   Type: {source['type']}")
        if source['base_url']:
            print(f"   URL: Masquée")
        print(f"   Description: {source.get('description', 'N/A')}")
        print(f"   Priorité: {source.get('priority', 'N/A')}")
    
    print("\n--- Dernier recours torrent ---")
    for i, source in enumerate(get_default_sources(), 1):
        if source['type'] != 'minerva':
            continue
        print(f"\n{i}. {source['name']}")
        print(f"   Type: {source['type']}")
        print(f"   Collection: {source.get('collection', 'N/A')}")
        print(f"   Description: {source.get('description', 'N/A')}")
        print(f"   Priorité: {source.get('priority', 'N/A')}")
    
    print("\n--- Sources Supplémentaires ---")
    additional_sources = globals().get('ADDITIONAL_SOURCES', [])
    for i, source in enumerate(additional_sources, 1):
        status = "ACTIVABLE" if not source.get('enabled', False) else "ACTIVE"
        print(f"\n{i}. {source['name']} [{status}]")
        print(f"   Type: {source['type']}")
        if source['base_url']:
            print(f"   URL: {source['base_url']}")
        print(f"   Description: {source.get('description', 'N/A')}")
    
    print("\n" + "=" * 70)

# ============================================================================
# Fonctions de traitement
# ============================================================================

ARCHIVE_CHECKSUM_QUERY_FIELDS = {
    'md5': ['md5'],
    'crc': ['crc32', 'crc'],
    'sha1': ['sha1']
}

ARCHIVE_CHECKSUM_FILE_FIELDS = {
    'md5': ['md5'],
    'crc': ['crc32', 'crc'],
    'sha1': ['sha1']
}

ARCHIVE_SEARCH_TIMEOUT = 20
ARCHIVE_ITEM_TIMEOUT = 30
ARCHIVE_CHECKSUM_RESULT_LIMIT = 20
ARCHIVE_NAME_RESULT_LIMIT = 10
ARCHIVE_NAME_COLLECTIONS = ('softwarelibrary', 'retrogames', '')
ARCHIVE_CHECKSUM_NAME_CROSSCHECK = False


def search_archive_items_limited(query: str, limit: int) -> list:
    """Interroge archive.org avec une vraie limite et un timeout reseau."""
    return list(islice(
        internetarchive.search_items(
            query,
            request_kwargs={'timeout': ARCHIVE_SEARCH_TIMEOUT}
        ),
        limit
    ))


def get_archive_item_files(identifier: str):
    """Recupere les fichiers d'un item archive.org avec timeout."""
    item = internetarchive.get_item(
        identifier,
        request_kwargs={'timeout': ARCHIVE_ITEM_TIMEOUT}
    )
    return item.get_files()


def archive_org_result(identifier: str, file_name: str, checksum_type: str, checksum_value: str, source: str) -> dict:
    """Construit une réponse archive.org uniforme."""
    return {
        'found': True,
        'identifier': identifier,
        'filename': file_name,
        checksum_type: checksum_value,
        'checksum_type': checksum_type,
        'source': source
    }


def archive_org_matches_name(file_name: str, rom_name: str) -> bool:
    """Vérifie si un nom de fichier archive.org correspond au nom attendu."""
    if not file_name or not rom_name:
        return False

    file_lower = file_name.lower()
    rom_lower = rom_name.lower()
    clean_name = rom_lower.split('(')[0].strip()
    return (
        rom_lower in file_lower
        or clean_name in file_lower
        or strip_rom_extension(file_name).lower() == strip_rom_extension(rom_name).lower()
    )


def get_archive_file_checksum(file_info: dict, checksum_type: str) -> str:
    """Récupère une somme de contrôle archive.org normalisée."""
    for field_name in ARCHIVE_CHECKSUM_FILE_FIELDS.get(checksum_type, []):
        checksum_value = normalize_checksum(file_info.get(field_name, ''), checksum_type)
        if checksum_value:
            return checksum_value
    return ''


def search_archive_org_by_checksum(checksum_value: str, rom_name: str, checksum_type: str) -> dict:
    """
    Recherche un fichier sur archive.org par checksum, puis recoupe par nom si nécessaire.
    archive.org est interroge en dernier recours, apres Minerva.
    """
    normalized_checksum = normalize_checksum(checksum_value, checksum_type)
    if not normalized_checksum:
        return {'found': False}

    label = checksum_type.upper()
    strategies_tried = []
    query_fields = ARCHIVE_CHECKSUM_QUERY_FIELDS.get(checksum_type, [checksum_type])

    print(f"  Recherche archive.org par {label}: {normalized_checksum}")

    for query_field in query_fields:
        try:
            query = f'{query_field}:{normalized_checksum}'
            print(f"    -> Recherche: {query}")
            results = search_archive_items_limited(query, ARCHIVE_CHECKSUM_RESULT_LIMIT)

            for result in results:
                identifier = result.get('identifier', '')
                if not identifier:
                    continue

                try:
                    files = get_archive_item_files(identifier)

                    for file_info in files:
                        file_name = file_info.get('name', '')
                        file_checksum = get_archive_file_checksum(file_info, checksum_type)
                        if file_checksum and file_checksum == normalized_checksum:
                            print(f"    [OK] Trouvé: {identifier}/{file_name}")
                            return archive_org_result(identifier, file_name, checksum_type, normalized_checksum, f'archive_org_{checksum_type}')
                except Exception:
                    continue

            strategies_tried.append(query_field)
        except Exception as e:
            print(f"    [ERREUR] Recherche {label}: {e}")
            strategies_tried.append(f'{query_field}_error: {e}')

    # Le fallback par nom est deja gere ensuite dans search_archive_org_for_games.
    # Le refaire ici pour chaque checksum multiplie inutilement les requetes archive.org.
    if rom_name and ARCHIVE_CHECKSUM_NAME_CROSSCHECK:
        clean_name = rom_name.split('(')[0].strip()
        quoted_name = f'"{clean_name}"' if clean_name else ''

        for collection in ARCHIVE_NAME_COLLECTIONS:
            try:
                query = f'{quoted_name} AND collection:{collection}' if collection else quoted_name
                print(f"    -> Recherche nom: {query[:50]}...")
                results = search_archive_items_limited(query, ARCHIVE_NAME_RESULT_LIMIT)

                for result in results:
                    identifier = result.get('identifier', '')
                    if not identifier:
                        continue

                    try:
                        files = get_archive_item_files(identifier)

                        for file_info in files:
                            file_name = file_info.get('name', '')
                            if not archive_org_matches_name(file_name, rom_name):
                                continue

                            file_checksum = get_archive_file_checksum(file_info, checksum_type)
                            if file_checksum and file_checksum == normalized_checksum:
                                print(f"    [OK] Trouvé (nom+{label}): {identifier}/{file_name}")
                                return archive_org_result(identifier, file_name, checksum_type, normalized_checksum, f'archive_org_{checksum_type}')
                    except Exception:
                        continue

                strategies_tried.append(f'name_{collection or "all"}')
            except Exception as e:
                strategies_tried.append(f'name_error_{collection}: {e}')

    print(f"  [KO] Non trouvé sur archive.org (stratégies: {', '.join(strategies_tried)})")
    return {'found': False, 'strategies_tried': strategies_tried}


def search_archive_org_by_md5(md5_hash: str, rom_name: str) -> dict:
    """Recherche archive.org par MD5."""
    return search_archive_org_by_checksum(md5_hash, rom_name, 'md5')


def search_archive_org_by_crc(crc_hash: str, rom_name: str) -> dict:
    """Recherche archive.org par CRC."""
    return search_archive_org_by_checksum(crc_hash, rom_name, 'crc')


def search_archive_org_by_sha1(sha1_hash: str, rom_name: str) -> dict:
    """Recherche archive.org par SHA1."""
    return search_archive_org_by_checksum(sha1_hash, rom_name, 'sha1')


def download_from_ia_zip(identifier: str, zip_path: str, filename: str, dest_path: str, progress_callback=None) -> bool:
    """
    Télécharge un fichier spécifique à l'intérieur d'un ZIP sur archive.org.
    Gère les redirections vers view_archive.php.
    """
    try:
        from urllib.parse import quote
        
        # URL de base pour l'accès aux fichiers (IA S3 / Direct)
        clean_zip = quote(zip_path.replace("\\", "/"))
        clean_file = quote(filename.replace("\\", "/"))
        url = f"https://archive.org/download/{identifier}/{clean_zip}/{clean_file}"
        
        print(f"  Tentative IA-ZIP: {identifier}/{zip_path}/{filename}")
        
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})
        
        # Credentials IA
        access_key = os.environ.get('IAS3_ACCESS_KEY')
        secret_key = os.environ.get('IAS3_SECRET_KEY')
        auth = None
        if access_key and secret_key:
            from requests.auth import HTTPBasicAuth
            auth = HTTPBasicAuth(access_key, secret_key)

        # Première tentative
        resp = session.get(url, stream=True, allow_redirects=True, timeout=120, auth=auth)
        
        # Si redirection vers view_archive sans le paramètre file
        if "view_archive.php" in resp.url and "file=" not in resp.url:
            final_url = f"{resp.url}&file={clean_file}"
            print(f"  Redirection view_archive: {final_url}")
            resp = session.get(final_url, stream=True, allow_redirects=True, timeout=120, auth=auth)

        if resp.status_code == 503:
            print("  [WARN] Service IA (view_archive) temporairement indisponible (503)")
            return False
            
        resp.raise_for_status()
        
        total = int(resp.headers.get('content-length', 0))
        downloaded = 0
        
        with open(dest_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0 and progress_callback:
                        progress_callback((downloaded / total) * 100)
        
        if progress_callback:
            progress_callback(100.0)
        return True
    except Exception as e:
        print(f"  [ERREUR] IA-ZIP: {e}")
        return False


def download_from_archive_org(identifier: str, filename: str, dest_path: str, session: requests.Session = None, progress_callback=None) -> bool:
    """
    Download a file from archive.org using the internetarchive library or direct HTTP.
    """
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            print(f"  Téléchargement archive.org: {identifier}/{filename}")
            
            # Méthode 1: Utiliser internetarchive
            try:
                item = internetarchive.get_item(identifier)
                file_obj = item.get_file(filename)
                
                if file_obj:
                    # Télécharger directement
                    with open(dest_path, 'wb') as f:
                        file_obj.download(f)
                    
                    if dest_path.exists():
                        size = dest_path.stat().st_size
                        print(f"  [OK] Téléchargé via internetarchive ({size:,} octets)")
                        if progress_callback:
                            progress_callback(100.0)
                        return True
            except Exception as e:
                print(f"  [WARN] Erreur internetarchive: {e}, tentative HTTP directe...")
            
            # Méthode 2: Download HTTP direct (fallback)
            if session is None:
                session = requests.Session()
                session.headers.update({'User-Agent': 'Mozilla/5.0'})
            
            download_url = f"https://archive.org/download/{identifier}/{quote(filename)}"
            print(f"  URL: {download_url}")
            
            response = session.get(download_url, stream=True, timeout=120)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(dest_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0 and progress_callback:
                            progress_callback((downloaded / total_size) * 100)
            
            if progress_callback:
                progress_callback(100.0)
            
            if dest_path.exists():
                size = dest_path.stat().st_size
                print(f"  [OK] Téléchargé via HTTP direct ({size:,} octets)")
                return True
            else:
                print(f"  [ERREUR] Fichier non créé")
                return False
                
        except Exception as e:
            print(f"  [ERREUR] Tentative {attempt + 1}/{max_retries} échouée: {e}")
            if os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                except:
                    pass
            if attempt < max_retries - 1:
                time.sleep(2)
    
    return False


def search_archive_org_by_name(rom_name: str, rom_extension: str = '.zip') -> dict:
    """
    Search for a ROM on archive.org by name.
    Fallback when MD5 search fails.
    """
    if not rom_name:
        return {'found': False}

    print(f"  Recherche archive.org par nom: {rom_name}")

    try:
        # Search with ROM name and No-Intro collection
        query = f'"{rom_name}" AND collection:No-Intro'
        results = search_archive_items_limited(query, ARCHIVE_CHECKSUM_RESULT_LIMIT)

        for result in results:
            identifier = result.get('identifier', '')
            if not identifier:
                continue

            try:
                files = get_archive_item_files(identifier)

                for file_info in files:
                    file_name = file_info.get('name', '')
                    # Check if filename matches
                    if rom_name.lower() in file_name.lower() or file_name.lower() in rom_name.lower():
                        if file_name.endswith(rom_extension) or file_name.endswith('.gb') or file_name.endswith('.zip'):
                            print(f"  Trouvé sur archive.org: {identifier}/{file_name}")
                            return {
                                'found': True,
                                'identifier': identifier,
                                'filename': file_name,
                                'source': 'archive_org_name'
                            }
            except Exception as e:
                continue

        # Try without collection filter
        query = f'"{rom_name}"'
        results = search_archive_items_limited(query, ARCHIVE_NAME_RESULT_LIMIT)

        for result in results:
            identifier = result.get('identifier', '')
            if not identifier:
                continue

            try:
                files = get_archive_item_files(identifier)

                for file_info in files:
                    file_name = file_info.get('name', '')
                    if rom_name.lower() in file_name.lower():
                        if file_name.endswith(('.zip', '.gb', '.7z', '.rar')):
                            print(f"  Trouvé sur archive.org (sans collection): {identifier}/{file_name}")
                            return {
                                'found': True,
                                'identifier': identifier,
                                'filename': file_name,
                                'source': 'archive_org_name'
                            }
            except Exception as e:
                continue

        print(f"  Non trouvé sur archive.org avec le nom: {rom_name}")
        return {'found': False}

    except Exception as e:
        print(f"  Erreur recherche archive.org par nom: {e}")
        return {'found': False}


def parse_dat_file(dat_path: str) -> dict:
    """Parse a No-Intro DAT XML file and extract ROM information."""
    print(f"Parsing DAT file: {dat_path}")
    
    tree = ET.parse(dat_path)
    root = tree.getroot()
    
    games = {}
    game_elements = root.findall('.//game')
    
    for game in game_elements:
        game_name = game.get('name', '')
        if not game_name:
            continue
        
        rom_elements = game.findall('rom')
        rom_files = []
        for rom_elem in rom_elements:
            rom_info = {
                'name': rom_elem.get('name', ''),
                'size': rom_elem.get('size', '0'),
                'crc': rom_elem.get('crc', ''),
                'md5': rom_elem.get('md5', ''),
                'sha1': rom_elem.get('sha1', '')
            }
            if rom_info['name']:
                rom_files.append(rom_info)
        
        if rom_files:
            games[game_name] = {
                'game_name': game_name,
                'roms': rom_files,
                'primary_rom': rom_files[0]['name'] if rom_files else ''
            }
    
    print(f"Found {len(games)} games in DAT file")
    return games


def normalize_checksum(value: str, checksum_type: str) -> str:
    """Normalise un hash pour les comparaisons."""
    normalized = (value or '').strip().lower()
    if not normalized:
        return ''
    if checksum_type == 'crc':
        return normalized.zfill(8)
    return normalized


def parse_rom_size(value) -> int | None:
    """Convertit une taille de ROM DAT en entier si possible."""
    try:
        size = int(str(value).strip())
        return size if size >= 0 else None
    except Exception:
        return None


def strip_rom_extension(filename: str) -> str:
    """Retire l'extension ROM reconnue d'un nom de fichier."""
    name_no_ext = filename
    for ext in ROM_EXTENSIONS:
        if name_no_ext.lower().endswith(ext):
            return name_no_ext[:-len(ext)]
    return name_no_ext


def add_local_name_reference(filename: str, local_roms: set, local_roms_normalized: set, local_game_names: set):
    """Ajoute un nom de fichier dans les index de comparaison locale."""
    if not filename:
        return
    basename = Path(filename).name
    name_no_ext = strip_rom_extension(basename)
    local_roms.add(basename)
    local_roms_normalized.add(name_no_ext.lower())
    local_game_names.add(name_no_ext.lower())


def compute_stream_checksums(stream) -> tuple[str, str, str]:
    """Calcule CRC32, MD5 et SHA1 d'un flux binaire."""
    md5_hash = hashlib.md5()
    sha1_hash = hashlib.sha1()
    crc_value = 0

    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        if not chunk:
            break
        md5_hash.update(chunk)
        sha1_hash.update(chunk)
        crc_value = zlib.crc32(chunk, crc_value)

    return (
        normalize_checksum(f"{crc_value & 0xffffffff:08x}", 'crc'),
        normalize_checksum(md5_hash.hexdigest(), 'md5'),
        normalize_checksum(sha1_hash.hexdigest(), 'sha1')
    )


def index_signature_value(signature_index: dict, checksum_type: str, checksum_value: str, reference: dict):
    """Indexe une signature locale pour les comparaisons rapides."""
    normalized_value = normalize_checksum(checksum_value, checksum_type)
    if not normalized_value:
        return
    signature_index[checksum_type].setdefault(normalized_value, []).append(reference)


def load_scan_cache(rom_path: Path) -> dict:
    """Charge le cache de scan local, s'il existe."""
    cache_path = rom_path / SCAN_CACHE_FILENAME
    try:
        with open(cache_path, 'r', encoding='utf-8') as cache_file:
            cache = json.load(cache_file)
        if cache.get('version') == 2:
            return cache
    except Exception:
        pass
    return {'version': 2, 'files': {}}


def save_scan_cache(rom_path: Path, cache: dict):
    """Sauvegarde le cache de scan local."""
    cache_path = rom_path / SCAN_CACHE_FILENAME
    try:
        with open(cache_path, 'w', encoding='utf-8') as cache_file:
            json.dump(cache, cache_file, ensure_ascii=False)
    except Exception as e:
        print(f"  Avertissement: cache de scan non sauvegarde: {e}")


def cache_key_for_file(file_path: Path, rom_path: Path) -> str:
    """Cle stable relative au dossier scanne."""
    try:
        return str(file_path.relative_to(rom_path))
    except Exception:
        return str(file_path)


def file_cache_state(file_path: Path) -> dict | None:
    """Etat minimal permettant de detecter un fichier inchange."""
    try:
        stat = file_path.stat()
    except Exception:
        return None
    return {'mtime_ns': stat.st_mtime_ns, 'size': stat.st_size}


def target_sizes_cache_key(target_sizes: set) -> str:
    """Fingerprint compact des tailles DAT utilisees pour filtrer le scan."""
    if not target_sizes:
        return ''
    digest = hashlib.sha1()
    for item in sorted(target_sizes):
        digest.update(str(item).encode('ascii', errors='ignore'))
        digest.update(b'\0')
    return digest.hexdigest()


def cached_entries_for_file(cache: dict, key: str, state: dict) -> list | None:
    """Retourne les entrees de cache si le fichier n'a pas change."""
    cached = cache.get('files', {}).get(key)
    if not cached:
        return None
    if cached.get('state') == state:
        return cached.get('entries', [])
    return None


def update_file_scan_cache(cache: dict, key: str, state: dict, entries: list):
    """Met a jour les entrees scannees d'un fichier."""
    cache.setdefault('files', {})[key] = {'state': state, 'entries': entries}


def build_target_signature_sets(dat_games: dict | None) -> dict:
    """Construit les ensembles de signatures présentes dans le DAT."""
    targets = {
        'md5': set(),
        'crc': set(),
        'sha1': set(),
        'size': set()
    }
    if not dat_games:
        return targets

    for game_info in dat_games.values():
        for rom_info in game_info.get('roms', []):
            for checksum_type in ('md5', 'crc', 'sha1'):
                normalized_value = normalize_checksum(rom_info.get(checksum_type, ''), checksum_type)
                if normalized_value:
                    targets[checksum_type].add(normalized_value)
            rom_size = parse_rom_size(rom_info.get('size'))
            if rom_size is not None:
                targets['size'].add(rom_size)

    return targets


def hash_file_signatures(file_path: Path) -> dict:
    """Calcule les signatures d'un fichier local."""
    with open(file_path, 'rb') as file_handle:
        crc_value, md5_hash, sha1_hash = compute_stream_checksums(file_handle)
    return {
        'crc': crc_value,
        'md5': md5_hash,
        'sha1': sha1_hash
    }


def hash_zip_entry_signatures(zip_file, zip_info) -> dict:
    """Calcule les signatures d'une entrée ZIP locale."""
    with zip_file.open(zip_info, 'r') as entry_handle:
        crc_value, md5_hash, sha1_hash = compute_stream_checksums(entry_handle)
    return {
        'crc': normalize_checksum(f"{zip_info.CRC & 0xffffffff:08x}", 'crc') or crc_value,
        'md5': md5_hash,
        'sha1': sha1_hash
    }


def iter_archive_member_signatures(file_path: Path, target_sizes: set | None = None, require_hashes: bool = True):
    """Retourne les signatures des fichiers contenus dans une archive supportee.

    Quand require_hashes=False, seules les metadonnees disponibles dans l'archive
    sont utilisees. C'est suffisant pour le scan de reprise et evite d'extraire
    des gros 7z PlayStation juste pour les comparer au DAT.
    """
    suffix = file_path.suffix.lower()
    target_sizes = target_sizes or set()

    if suffix == '.zip':
        import zipfile
        with zipfile.ZipFile(file_path, 'r') as zf:
            for zip_info in zf.infolist():
                if zip_info.is_dir():
                    continue
                if target_sizes and zip_info.file_size not in target_sizes:
                    continue
                signatures = {
                    'crc': normalize_checksum(f"{zip_info.CRC & 0xffffffff:08x}", 'crc'),
                    'md5': '',
                    'sha1': ''
                }
                if require_hashes:
                    signatures = hash_zip_entry_signatures(zf, zip_info)
                yield {
                    'name': Path(zip_info.filename).name or zip_info.filename,
                    'member': zip_info.filename,
                    'size': zip_info.file_size,
                    **signatures
                }
        return

    if suffix == '.7z':
        py7zr = import_optional_package('py7zr', auto_install=True)
        if py7zr is None:
            raise RuntimeError("py7zr indisponible")
        if not require_hashes:
            with py7zr.SevenZipFile(file_path, mode='r') as archive:
                for archive_info in archive.list():
                    if getattr(archive_info, 'is_directory', False):
                        continue
                    member_size = getattr(archive_info, 'uncompressed', None)
                    if target_sizes and member_size not in target_sizes:
                        continue
                    crc_value = getattr(archive_info, 'crc32', None)
                    yield {
                        'name': Path(archive_info.filename).name or archive_info.filename,
                        'member': archive_info.filename,
                        'size': member_size,
                        'crc': normalize_checksum(f"{crc_value & 0xffffffff:08x}", 'crc') if crc_value is not None else '',
                        'md5': '',
                        'sha1': ''
                    }
            return
        with tempfile.TemporaryDirectory(prefix='rom_downloader_7z_') as temp_dir:
            with py7zr.SevenZipFile(file_path, mode='r') as archive:
                targets = [
                    archive_info.filename
                    for archive_info in archive.list()
                    if not getattr(archive_info, 'is_directory', False)
                    and (not target_sizes or getattr(archive_info, 'uncompressed', None) in target_sizes)
                ]
                if not targets:
                    return
                archive.extract(path=temp_dir, targets=targets)
            temp_root = Path(temp_dir)
            for extracted in temp_root.rglob('*'):
                if not extracted.is_file():
                    continue
                signatures = hash_file_signatures(extracted)
                yield {
                    'name': extracted.name,
                    'member': str(extracted.relative_to(temp_root)),
                    'size': extracted.stat().st_size,
                    **signatures
                }
        return

    if suffix == '.rar':
        rarfile = import_optional_package('rarfile', auto_install=True)
        if rarfile is None:
            raise RuntimeError("rarfile indisponible")
        with rarfile.RarFile(file_path, 'r') as archive:
            for rar_info in archive.infolist():
                if rar_info.isdir():
                    continue
                if target_sizes and rar_info.file_size not in target_sizes:
                    continue
                crc_header = normalize_checksum(f"{rar_info.CRC & 0xffffffff:08x}", 'crc')
                signatures = {'crc': crc_header, 'md5': '', 'sha1': ''}
                if require_hashes:
                    with archive.open(rar_info, 'r') as entry_handle:
                        crc_value, md5_hash, sha1_hash = compute_stream_checksums(entry_handle)
                    signatures = {
                        'crc': crc_header or crc_value,
                        'md5': md5_hash,
                        'sha1': sha1_hash
                    }
                yield {
                    'name': Path(rar_info.filename).name or rar_info.filename,
                    'member': rar_info.filename,
                    'size': rar_info.file_size,
                    **signatures
                }
        return

    raise RuntimeError(f"archive {suffix} non supportee")


def scan_local_roms(rom_folder: str, dat_games: dict | None = None) -> tuple:
    """Scan a folder for local ROM files."""
    print(f"Scanning local ROMs folder: {rom_folder}")

    local_roms = set()
    local_roms_normalized = set()
    local_game_names = set()
    signature_index = {'md5': {}, 'crc': {}, 'sha1': {}}
    rom_path = Path(rom_folder)

    if not rom_path.exists():
        print(f"Warning: ROM folder does not exist: {rom_folder}")
        return local_roms, local_roms_normalized, local_game_names, signature_index

    target_signatures = build_target_signature_sets(dat_games)
    target_sizes = target_signatures['size']
    target_sizes_key = target_sizes_cache_key(target_sizes)
    archive_extensions = ('.zip', '.7z', '.rar')
    hashed_items = 0
    cache = load_scan_cache(rom_path)
    next_cache = {'version': 2, 'files': {}}
    cache_hits = 0
    cache_misses = 0

    for file_path in rom_path.rglob('*'):
        if file_path.is_file():
            filename = file_path.name
            if filename == SCAN_CACHE_FILENAME:
                continue
            if filename.lower().startswith('rom_downloader_report_') and file_path.suffix.lower() == '.txt':
                continue

            add_local_name_reference(filename, local_roms, local_roms_normalized, local_game_names)
            cache_key = cache_key_for_file(file_path, rom_path)
            state = file_cache_state(file_path)
            if state is not None:
                state['target_sizes_key'] = target_sizes_key
            cached_entries = cached_entries_for_file(cache, cache_key, state) if state else None
            entries_for_cache = []

            if cached_entries is not None:
                cache_hits += 1
                for cached_entry in cached_entries:
                    internal_name = cached_entry.get('name', '')
                    if internal_name:
                        add_local_name_reference(internal_name, local_roms, local_roms_normalized, local_game_names)
                    reference = {
                        'path': str(file_path),
                        **cached_entry
                    }
                    for checksum_type in ('md5', 'crc', 'sha1'):
                        index_signature_value(signature_index, checksum_type, reference.get(checksum_type, ''), reference)
                    if any(reference.get(checksum_type) for checksum_type in ('md5', 'crc', 'sha1')):
                        hashed_items += 1
                if state is not None:
                    update_file_scan_cache(next_cache, cache_key, state, cached_entries)
                continue

            cache_misses += 1

            if file_path.suffix.lower() in archive_extensions:
                try:
                    for archive_entry in iter_archive_member_signatures(
                            file_path,
                            target_sizes=target_sizes,
                            require_hashes=False):
                        internal_name = archive_entry['name']
                        add_local_name_reference(internal_name, local_roms, local_roms_normalized, local_game_names)

                        reference = {
                            'path': str(file_path),
                            **archive_entry
                        }
                        for checksum_type in ('md5', 'crc', 'sha1'):
                            index_signature_value(signature_index, checksum_type, reference.get(checksum_type, ''), reference)
                        hashed_items += 1
                        entries_for_cache.append(archive_entry)
                except Exception as e:
                    print(f"  Avertissement: archive locale ignoree ({file_path.name}): {e}")
            else:
                try:
                    file_size = file_path.stat().st_size
                except Exception:
                    continue

                if target_sizes and file_size not in target_sizes:
                    continue

                try:
                    signatures = hash_file_signatures(file_path)
                except Exception:
                    continue

                reference = {
                    'path': str(file_path),
                    'member': '',
                    'name': filename,
                    'size': file_size,
                    **signatures
                }
                for checksum_type in ('md5', 'crc', 'sha1'):
                    index_signature_value(signature_index, checksum_type, reference.get(checksum_type, ''), reference)
                hashed_items += 1
                entries_for_cache.append({
                    'member': '',
                    'name': filename,
                    'size': file_size,
                    **signatures
                })

            if state is not None:
                update_file_scan_cache(next_cache, cache_key, state, entries_for_cache)

    save_scan_cache(rom_path, next_cache)
    print(f"Found {len(local_roms)} local ROM files")
    print(f"Indexed {hashed_items} local entries by checksums")
    print(f"Scan cache: {cache_hits} reutilise(s), {cache_misses} rescannes")
    return local_roms, local_roms_normalized, local_game_names, signature_index


def find_missing_games(dat_games: dict, local_roms: set, local_roms_normalized: set, local_game_names: set,
                       signature_index: dict | None = None) -> list:
    """Compare DAT games with local ROMs and return missing ones.

    A local ROM validates a DAT entry by checksum only. Names are kept in the
    scan indexes for reports/ToSort, but they must not mark a game as present.
    """
    print("Comparing DAT games with local ROMs...")

    signature_index = signature_index or {'md5': {}, 'crc': {}, 'sha1': {}}
    missing = []
    for game_name, game_info in dat_games.items():
        found = False

        has_md5 = any(normalize_checksum(rom_info.get('md5', ''), 'md5') for rom_info in game_info.get('roms', []))
        checksum_order = ('md5', 'crc', 'sha1') if has_md5 else ('crc', 'sha1')

        for checksum_type in checksum_order:
            for rom_info in game_info.get('roms', []):
                checksum_value = normalize_checksum(rom_info.get(checksum_type, ''), checksum_type)
                if checksum_value and checksum_value in signature_index.get(checksum_type, {}):
                    found = True
                    break
            if found:
                break

        if not found:
            missing.append(game_info)

    print(f"Found {len(missing)} missing games")
    return missing


def find_roms_not_in_dat(dat_games: dict, local_roms: set, local_roms_normalized: set,
                         rom_folder: str) -> list:
    """Find local files whose content checksums are not present in the DAT."""
    print("Finding ROMs not in DAT file by checksums...")
    generated_report_prefix = 'rom_downloader_report_'
    files_to_move = []
    rom_path = Path(rom_folder)
    target_signatures = build_target_signature_sets(dat_games)

    if not rom_path.exists():
        return files_to_move

    def signatures_match_dat(signatures: dict) -> bool:
        for checksum_type in ('md5', 'crc', 'sha1'):
            checksum_value = normalize_checksum(signatures.get(checksum_type, ''), checksum_type)
            if checksum_value and checksum_value in target_signatures.get(checksum_type, set()):
                return True
        return False

    for file_path in rom_path.rglob('*'):
        if not file_path.is_file():
            continue
        filename = file_path.name

        if 'ToSort' in file_path.parts:
            continue
        if filename.lower().startswith(generated_report_prefix) and file_path.suffix.lower() == '.txt':
            continue
        if file_path.name.lower() == 'repack_archives_to_individual_zip.bat':
            continue

        file_is_in_dat = False
        if file_path.suffix.lower() in {'.zip', '.7z', '.rar'}:
            try:
                for archive_entry in iter_archive_member_signatures(
                        file_path,
                        target_sizes=target_signatures.get('size', set()),
                        require_hashes=False):
                    if signatures_match_dat(archive_entry):
                        file_is_in_dat = True
                        break
            except Exception as e:
                print(f"  Avertissement: archive ToSort non verifiable ({file_path.name}): {e}")
        else:
            try:
                file_is_in_dat = signatures_match_dat(hash_file_signatures(file_path))
            except Exception as e:
                print(f"  Avertissement: fichier ToSort non verifiable ({file_path.name}): {e}")

        if not file_is_in_dat:
            files_to_move.append(str(file_path))

    print(f"Found {len(files_to_move)} files not in DAT")
    return files_to_move


def move_files_to_tosort(files_to_move: list, rom_folder: str, tosort_folder: str, dry_run: bool = False) -> tuple:
    """Move files to ToSort folder."""
    moved = 0
    failed = 0
    
    # Create ToSort folder if it doesn't exist
    if not dry_run:
        os.makedirs(tosort_folder, exist_ok=True)
    
    for file_path in files_to_move:
        try:
            filename = os.path.basename(file_path)
            dest_path = os.path.join(tosort_folder, filename)
            
            # Handle duplicate names
            if os.path.exists(dest_path):
                base, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(dest_path):
                    dest_path = os.path.join(tosort_folder, f"{base}_{counter}{ext}")
                    counter += 1
            
            if dry_run:
                print(f"  [DRY-RUN] Would move: {filename}")
                moved += 1
            else:
                os.rename(file_path, dest_path)
                print(f"  Moved: {filename}")
                moved += 1
        except Exception as e:
            print(f"  Failed to move {os.path.basename(file_path)}: {e}")
            failed += 1
    
    return moved, failed


def build_dat_md5_lookup(dat_games: dict) -> dict:
    """Indexe les ROMs du DAT par MD5."""
    lookup = {}
    for game_info in dat_games.values():
        for rom_info in game_info.get('roms', []):
            md5_value = normalize_checksum(rom_info.get('md5', ''), 'md5')
            if not md5_value:
                continue
            lookup.setdefault(md5_value, []).append({
                'game_name': game_info.get('game_name', ''),
                'rom_name': Path(rom_info.get('name', '')).name,
                'md5': md5_value,
            })
    return lookup


def find_7z_executable() -> str:
    """Retourne le chemin de 7-Zip si disponible."""
    env_path = os.environ.get('SEVENZIP_EXE') or os.environ.get('SEVEN_ZIP_EXE') or os.environ.get('Z7_EXE')
    candidates = [
        env_path,
        shutil.which('7z'),
        shutil.which('7za'),
        r'C:\Program Files\7-Zip\7z.exe',
        r'C:\Program Files (x86)\7-Zip\7z.exe',
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return ''


def patch_zip_to_torrentzip(zip_path: Path) -> str:
    """Applique les champs TorrentZip/RomVault sur un ZIP existant."""
    data = bytearray(zip_path.read_bytes())
    min_pos = max(0, len(data) - 65557)
    eocd = -1
    for pos in range(len(data) - 22, min_pos - 1, -1):
        if data[pos:pos + 4] == b'PK\x05\x06':
            eocd = pos
            break
    if eocd < 0:
        raise RuntimeError("EOCD ZIP introuvable")

    cd_size = struct.unpack_from('<I', data, eocd + 12)[0]
    cd_offset = struct.unpack_from('<I', data, eocd + 16)[0]
    torrent_flag = 2
    torrent_time = (23 << 11) | (32 << 5)
    torrent_date = ((1996 - 1980) << 9) | (12 << 5) | 24

    ptr = 0
    while ptr < cd_offset:
        if data[ptr:ptr + 4] != b'PK\x03\x04':
            break
        struct.pack_into('<H', data, ptr + 6, torrent_flag)
        struct.pack_into('<H', data, ptr + 10, torrent_time)
        struct.pack_into('<H', data, ptr + 12, torrent_date)
        compressed_size = struct.unpack_from('<I', data, ptr + 18)[0]
        filename_length = struct.unpack_from('<H', data, ptr + 26)[0]
        extra_length = struct.unpack_from('<H', data, ptr + 28)[0]
        ptr += 30 + filename_length + extra_length + compressed_size

    ptr = cd_offset
    cd_end = cd_offset + cd_size
    while ptr < cd_end:
        if data[ptr:ptr + 4] != b'PK\x01\x02':
            break
        struct.pack_into('<H', data, ptr + 4, 0)
        struct.pack_into('<H', data, ptr + 8, torrent_flag)
        struct.pack_into('<H', data, ptr + 12, torrent_time)
        struct.pack_into('<H', data, ptr + 14, torrent_date)
        filename_length = struct.unpack_from('<H', data, ptr + 28)[0]
        extra_length = struct.unpack_from('<H', data, ptr + 30)[0]
        comment_length = struct.unpack_from('<H', data, ptr + 32)[0]
        ptr += 46 + filename_length + extra_length + comment_length

    central_directory = bytes(data[cd_offset:cd_offset + cd_size])
    crc_hex = f"{zlib.crc32(central_directory) & 0xffffffff:08X}"
    comment = f"TORRENTZIPPED-{crc_hex}".encode('ascii')
    struct.pack_into('<H', data, eocd + 20, len(comment))
    patched = bytes(data[:eocd + 22]) + comment
    zip_path.write_bytes(patched)
    return comment.decode('ascii')


def zip_is_torrentzip_compatible(zip_path: Path) -> bool:
    """Verifie les champs TorrentZip que RomVault produit."""
    try:
        data = zip_path.read_bytes()
        eocd = data.rfind(b'PK\x05\x06', max(0, len(data) - 65557))
        if eocd < 0:
            return False
        cd_size = struct.unpack_from('<I', data, eocd + 12)[0]
        cd_offset = struct.unpack_from('<I', data, eocd + 16)[0]
        comment_length = struct.unpack_from('<H', data, eocd + 20)[0]
        comment = data[eocd + 22:eocd + 22 + comment_length].decode('ascii', 'ignore')
        expected = f"TORRENTZIPPED-{zlib.crc32(data[cd_offset:cd_offset + cd_size]) & 0xffffffff:08X}"
        if comment != expected:
            return False

        ptr = cd_offset
        cd_end = cd_offset + cd_size
        while ptr < cd_end:
            if data[ptr:ptr + 4] != b'PK\x01\x02':
                return False
            version_made = struct.unpack_from('<H', data, ptr + 4)[0]
            flag = struct.unpack_from('<H', data, ptr + 8)[0]
            dos_time = struct.unpack_from('<H', data, ptr + 12)[0]
            dos_date = struct.unpack_from('<H', data, ptr + 14)[0]
            if version_made != 0 or flag != 2 or dos_time != 0xbc00 or dos_date != 0x2198:
                return False
            filename_length = struct.unpack_from('<H', data, ptr + 28)[0]
            extra_length = struct.unpack_from('<H', data, ptr + 30)[0]
            entry_comment_length = struct.unpack_from('<H', data, ptr + 32)[0]
            ptr += 46 + filename_length + extra_length + entry_comment_length
        return True
    except Exception:
        return False


def create_torrentzip_single_file(source_file: Path, internal_name: str, output_zip: Path) -> str:
    """Cree un ZIP Deflate maximal puis applique le header TorrentZip/RomVault."""
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    temp_zip = output_zip.with_name(f"{output_zip.stem}.tmp_torrentzip{output_zip.suffix}")
    if temp_zip.exists():
        temp_zip.unlink()

    seven_zip = find_7z_executable()
    with tempfile.TemporaryDirectory(prefix='rom_downloader_torrentzip_') as temp_dir:
        stage_dir = Path(temp_dir)
        staged_file = stage_dir / Path(internal_name).name
        shutil.copyfile(source_file, staged_file)

        if seven_zip:
            args = [
                seven_zip, 'a', '-tzip', '-mm=Deflate', '-mx=9', '-mfb=258',
                '-mpass=15', '-mmt=1', '-mtm=off', '-mtc=off', '-mta=off',
                str(temp_zip), staged_file.name
            ]
            result = subprocess.run(args, cwd=str(stage_dir), stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, check=False)
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout or '7-Zip a echoue').strip())
        else:
            import zipfile
            with zipfile.ZipFile(temp_zip, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
                zf.write(staged_file, arcname=staged_file.name)

    comment = patch_zip_to_torrentzip(temp_zip)
    os.replace(temp_zip, output_zip)
    return comment


def extract_archive_member_to_file(archive_path: Path, member_name: str, output_file: Path):
    """Extrait une entree precise d'une archive supportee vers un fichier."""
    suffix = archive_path.suffix.lower()
    output_file.parent.mkdir(parents=True, exist_ok=True)

    if suffix == '.zip':
        import zipfile
        with zipfile.ZipFile(archive_path, 'r') as zf:
            with zf.open(member_name, 'r') as src, open(output_file, 'wb') as dst:
                shutil.copyfileobj(src, dst)
        return

    if suffix == '.rar':
        rarfile = import_optional_package('rarfile', auto_install=True)
        if rarfile is None:
            raise RuntimeError("rarfile indisponible")
        with rarfile.RarFile(archive_path, 'r') as archive:
            with archive.open(member_name, 'r') as src, open(output_file, 'wb') as dst:
                shutil.copyfileobj(src, dst)
        return

    if suffix == '.7z':
        py7zr = import_optional_package('py7zr', auto_install=True)
        if py7zr is None:
            raise RuntimeError("py7zr indisponible")
        with tempfile.TemporaryDirectory(prefix='rom_downloader_7z_extract_') as temp_dir:
            with py7zr.SevenZipFile(archive_path, mode='r') as archive:
                archive.extractall(path=temp_dir)
            extracted = Path(temp_dir) / member_name
            if not extracted.exists():
                matches = [item for item in Path(temp_dir).rglob('*') if item.is_file() and item.name == Path(member_name).name]
                extracted = matches[0] if matches else extracted
            if not extracted.exists():
                raise RuntimeError(f"entree 7z introuvable: {member_name}")
            shutil.copyfile(extracted, output_file)
        return

    raise RuntimeError(f"archive {suffix} non supportee")


def repack_verified_archives_to_torrentzip(dat_games: dict, rom_folder: str, dry_run: bool = False,
                                           log_func=print, status_callback=None,
                                           is_running=lambda: True) -> dict:
    """Recompresse les archives contenant des ROMs du DAT en ZIP TorrentZip/RomVault."""
    root = Path(rom_folder)
    summary = {'repacked': 0, 'skipped': 0, 'failed': 0, 'deleted': 0, 'items': []}
    if not root.exists():
        return summary

    md5_lookup = build_dat_md5_lookup(dat_games)
    if not md5_lookup:
        log_func("Nettoyage TorrentZip ignore: aucun MD5 dans le DAT")
        return summary

    archive_paths = [
        path for path in root.rglob('*')
        if path.is_file()
        and path.suffix.lower() in {'.zip', '.7z', '.rar'}
        and 'ToSort' not in path.parts
    ]

    total = len(archive_paths)
    log_func(f"Nettoyage TorrentZip: {total} archive(s) a verifier")

    for index, archive_path in enumerate(archive_paths, 1):
        if not is_running():
            log_func("Nettoyage TorrentZip arrete par l'utilisateur.")
            break
        if status_callback:
            status_callback(f"Nettoyage ZIP {index}/{total}: {archive_path.name[:60]}")

        try:
            matches = []
            seen_md5 = set()
            for entry in iter_archive_member_signatures(archive_path):
                md5_value = normalize_checksum(entry.get('md5', ''), 'md5')
                if md5_value in md5_lookup and md5_value not in seen_md5:
                    expected = md5_lookup[md5_value][0]
                    matches.append({
                        'member': entry.get('member') or entry.get('name'),
                        'md5': md5_value,
                        'rom_name': expected['rom_name'] or entry.get('name') or archive_path.stem,
                        'game_name': expected['game_name'],
                    })
                    seen_md5.add(md5_value)

            if not matches:
                summary['skipped'] += 1
                continue

            output_paths = set()
            with tempfile.TemporaryDirectory(prefix='rom_downloader_repack_') as temp_dir:
                temp_root = Path(temp_dir)
                prepared_outputs = []
                for match in matches:
                    rom_name = Path(match['rom_name']).name
                    target_zip = archive_path.parent / f"{Path(rom_name).stem}.zip"
                    output_paths.add(str(target_zip.resolve()).lower())

                    if (archive_path.resolve() == target_zip.resolve()
                            and len(matches) == 1
                            and Path(matches[0]['member']).name == Path(matches[0]['rom_name']).name
                            and zip_is_torrentzip_compatible(archive_path)):
                        summary['skipped'] += 1
                        continue

                    if dry_run:
                        log_func(f"  [DRY-RUN] Recompresserait: {archive_path.name} -> {target_zip.name}")
                        summary['repacked'] += 1
                        continue

                    extracted = temp_root / f"{len(prepared_outputs):04d}_{rom_name}"
                    extract_archive_member_to_file(archive_path, match['member'], extracted)
                    extracted_md5 = hash_file_signatures(extracted).get('md5')
                    if extracted_md5 != match['md5']:
                        raise RuntimeError(f"MD5 extrait incorrect pour {rom_name}")
                    prepared_outputs.append((match, extracted, rom_name, target_zip))

                for match, extracted, rom_name, target_zip in prepared_outputs:
                    comment = create_torrentzip_single_file(extracted, rom_name, target_zip)
                    ok, message = verify_downloaded_md5({'roms': [{'md5': match['md5']}]}, str(target_zip))
                    if not ok:
                        raise RuntimeError(message)
                    log_func(f"  TorrentZip OK: {target_zip.name} ({comment})")
                    summary['repacked'] += 1
                    summary['items'].append({'source': str(archive_path), 'output': str(target_zip), 'game_name': match['game_name']})

            archive_resolved = str(archive_path.resolve()).lower()
            if not dry_run and archive_path.exists() and archive_resolved not in output_paths:
                archive_path.unlink()
                summary['deleted'] += 1

        except Exception as e:
            summary['failed'] += 1
            log_func(f"  Echec nettoyage TorrentZip {archive_path.name}: {e}")

    log_func(
        "Nettoyage TorrentZip termine: "
        f"{summary['repacked']} recompresse(s), {summary['skipped']} ignore(s), "
        f"{summary['deleted']} source(s) supprimee(s), {summary['failed']} echec(s)"
    )
    return summary


def build_report_slug(value: str) -> str:
    """Nettoie une valeur pour un nom de fichier de rapport."""
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', '_', (value or '').strip())
    return cleaned.strip('._-') or 'run'


def write_download_report(output_folder: str, summary: dict) -> str:
    """Écrit un récapitulatif lisible de la session dans le dossier de destination."""
    os.makedirs(output_folder, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    system_slug = build_report_slug(summary.get('system_name', 'systeme'))
    report_path = os.path.join(output_folder, f"rom_downloader_report_{system_slug}_{timestamp}.txt")

    missing_titles = [item['game_name'] for item in summary.get('not_available', [])]
    failed_titles = [item['game_name'] for item in summary.get('failed_items', [])]
    downloaded_titles = [item['game_name'] for item in summary.get('downloaded_items', [])]
    skipped_titles = [item['game_name'] for item in summary.get('skipped_items', [])]

    source_counts = {}
    for item in summary.get('resolved_items', []):
        source_name = item.get('source', 'Inconnu')
        source_counts[source_name] = source_counts.get(source_name, 0) + 1

    lines = [
        "ROM Downloader - Recapitulatif",
        "=" * 72,
        f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"DAT: {summary.get('dat_file', '')}",
        f"Systeme: {summary.get('system_name', '')}",
        f"Profil: {summary.get('dat_profile', '')}",
        f"Dossier de destination: {summary.get('output_folder', '')}",
        f"URL source manuelle: {summary.get('source_url', '') or 'Auto'}",
        f"Sources actives: {', '.join(summary.get('active_sources', [])) or 'Aucune'}",
        "",
        "Resume",
        "-" * 72,
        f"Jeux dans le DAT: {summary.get('total_dat_games', 0)}",
        f"Jeux manquants avant telechargement: {summary.get('missing_before', 0)}",
        f"Jeux resolves sur les providers: {len(summary.get('resolved_items', []))}",
        f"Telecharges: {len(downloaded_titles)}",
        f"Echecs de telechargement: {len(failed_titles)}",
        f"Ignores / deja presents / limite: {len(skipped_titles)}",
        f"Introuvables sur toutes les sources: {len(missing_titles)}",
    ]

    if 'tosort_moved' in summary or 'tosort_failed' in summary:
        lines.extend([
            f"ToSort deplaces: {summary.get('tosort_moved', 0)}",
            f"ToSort echecs: {summary.get('tosort_failed', 0)}",
        ])

    if 'torrentzip_repacked' in summary or 'torrentzip_failed' in summary:
        lines.extend([
            f"TorrentZip recompresse(s): {summary.get('torrentzip_repacked', 0)}",
            f"TorrentZip ignore(s): {summary.get('torrentzip_skipped', 0)}",
            f"TorrentZip sources supprimees: {summary.get('torrentzip_deleted', 0)}",
            f"TorrentZip echecs: {summary.get('torrentzip_failed', 0)}",
        ])

    lines.extend(["", "Resolution par source", "-" * 72])
    if source_counts:
        for source_name, count in sorted(source_counts.items(), key=lambda item: (-item[1], item[0].lower())):
            lines.append(f"- {source_name}: {count}")
    else:
        lines.append("- Aucun jeu resolu")

    lines.extend(["", "Manquants non trouves", "-" * 72])
    if missing_titles:
        lines.extend(f"- {title}" for title in missing_titles)
    else:
        lines.append("- Aucun")

    lines.extend(["", "Echecs de telechargement", "-" * 72])
    if failed_titles:
        lines.extend(f"- {title}" for title in failed_titles)
    else:
        lines.append("- Aucun")

    lines.extend(["", "Telecharges", "-" * 72])
    if downloaded_titles:
        lines.extend(f"- {title}" for title in downloaded_titles)
    else:
        lines.append("- Aucun")

    lines.extend(["", "Ignores", "-" * 72])
    if skipped_titles:
        lines.extend(f"- {title}" for title in skipped_titles)
    else:
        lines.append("- Aucun")

    Path(report_path).write_text("\n".join(lines) + "\n", encoding='utf-8')
    print(f"Rapport ecrit: {report_path}")
    return report_path


def detect_system_name(dat_file_path: str) -> str:
    profile_system_name = finalize_dat_profile(detect_dat_profile(dat_file_path)).get('system_name', '')
    if profile_system_name:
        return profile_system_name

    """
    Tente de détecter le nom du système à partir du nom du fichier DAT.
    Gère les noms complexes (Retool, dates, tags).
    Exemple: 'Nintendo - Game Boy (Retool).dat' -> 'Nintendo - Game Boy'
    """
    try:
        tree = ET.parse(dat_file_path)
        root = tree.getroot()
        header_name = root.findtext('./header/name', default='').strip()
        if header_name:
            return re.sub(r'\s+', ' ', header_name)
    except Exception:
        pass

    filename = os.path.basename(dat_file_path)
    # Retirer l'extension
    name = os.path.splitext(filename)[0]
    # Retirer les parenthèses () et les crochets [] ainsi que leur contenu
    name = re.sub(r'[\(\[].*?[\)\]]', '', name).strip()
    # Normaliser les espaces multiples
    name = re.sub(r'\s+', ' ', name)
    return name


def get_lolroms_session():
    """Retourne une session Cloudflare-compatible pour LoLROMs."""
    global LOLROMS_SESSION

    if LOLROMS_SESSION is None:
        LOLROMS_SESSION = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
        )
        LOLROMS_SESSION.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    return LOLROMS_SESSION


def get_cdromance_session():
    """Retourne une session Cloudflare-compatible pour CDRomance."""
    return get_lolroms_session() # On réutilise la même logique scraper


def get_vimm_session():
    """Retourne une session avec les bons headers pour Vimm's Lair."""
    session = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
    )
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': VIMM_BASE
    })
    return session


def build_lolroms_url(path: str) -> str:
    """Construit une URL LoLROMs depuis un chemin logique avec slashs."""
    segments = [quote(segment) for segment in str(path or '').split('/') if segment]
    return urljoin(LOLROMS_BASE, '/'.join(segments))


def resolve_lolroms_system_path(system_name: str) -> str:
    """Résout le chemin LoLROMs correspondant au système demandé."""
    if not system_name:
        return ''

    mappings = SYSTEM_MAPPINGS.get(system_name, {})
    candidate_paths = []

    mapped_path = mappings.get('lolroms')
    if mapped_path:
        candidate_paths.append(mapped_path)

    candidate_paths.append(system_name.strip())
    candidate_paths.append(re.sub(r'\s*\(Headered\)\s*$', '', system_name).strip())
    candidate_paths.append(re.sub(r'\s*\(Headerless\)\s*$', '', system_name).strip())

    session = get_lolroms_session()
    seen = set()
    for candidate in candidate_paths:
        normalized = candidate.strip().strip('/')
        if not normalized or normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        try:
            response = session.get(build_lolroms_url(normalized), timeout=45)
            if response.status_code == 200 and 'Just a moment...' not in response.text:
                return normalized
        except Exception:
            continue

    return ''


def list_lolroms_directory(system_path: str) -> dict:
    """Scrape LoLROMs pour un système donné et retourne un mapping par nom normalisé."""
    if not system_path:
        return {}

    url = build_lolroms_url(system_path)
    print(f"Scraping LoLROMs: {url}")

    mapping = {}
    try:
        response = get_lolroms_session().get(url, timeout=60)
        if response.status_code != 200 or 'Just a moment...' in response.text:
            print(f"Erreur LoLROMs ({response.status_code}) pour {url}")
            return mapping

        soup = BeautifulSoup(response.text, 'html.parser')
        for link in soup.find_all('a', href=True):
            href = html_module.unescape(link.get('href', '')).strip()
            text = html_module.unescape(link.get_text().strip())

            if not href or not text or text in {'RSS', 'Donate', 'Main', '../'}:
                continue
            if href.endswith('/') or href.lower().endswith('/feed'):
                continue
            if '/.' in href:
                continue

            full_url = urljoin(LOLROMS_BASE, href)
            parsed_name = os.path.basename(unquote(href))
            filename = parsed_name if any(parsed_name.lower().endswith(ext) for ext in ROM_EXTENSIONS) else ''
            if not filename:
                continue

            display_name = strip_rom_extension(filename)
            mapping[display_name.lower()] = {
                'full_name': display_name,
                'filename': filename,
                'url': full_url
            }

        print(f"Found {len(mapping)} files on LoLROMs")
    except Exception as e:
        print(f"Erreur scraping LoLROMs: {e}")

    return mapping


def list_edgeemu_directory(system_slug: str, session: requests.Session) -> dict:
    """Scrape EdgeEmu pour un système donné et retourne un dict {nom_normalisé: url_téléchargement}."""
    if not system_slug:
        return {}
        
    config = ROM_DATABASE.get('config_urls', {})
    url = f"{config.get('edgeemu_browse', '')}{system_slug}"
    print(f"Scraping EdgeEmu: {url}")
    
    mapping = {}
    try:
        response = session.get(url, timeout=30)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # Sur EdgeEmu, les jeux sont dans des balises <details> avec le nom dans <summary>
            # et le lien de téléchargement dans un <a> à l'intérieur
            for details in soup.find_all('details'):
                summary = details.find('summary')
                if not summary: continue
                
                game_name = summary.get_text().strip()
                # On cherche le lien de téléchargement
                a_tag = details.find('a', href=True)
                if a_tag and '/download/' in a_tag['href']:
                    download_url = config.get('edgeemu_base', '') + a_tag['href']
                    mapping[game_name.lower()] = {
                        'full_name': game_name,
                        'url': download_url
                    }
    except Exception as e:
        print(f"Erreur scraping EdgeEmu: {e}")
        
    return mapping


def iter_game_candidate_names(game_info: dict) -> list:
    """Retourne les meilleurs noms candidats pour résoudre un jeu sur une source externe."""
    candidates = []

    primary_rom = strip_rom_extension(game_info.get('primary_rom', '')).strip()
    if primary_rom and primary_rom not in candidates:
        candidates.append(primary_rom)

    for rom_info in game_info.get('roms', []):
        rom_name = strip_rom_extension(rom_info.get('name', '')).strip()
        if rom_name and rom_name not in candidates:
            candidates.append(rom_name)

    game_name = (game_info.get('game_name') or '').strip()
    if game_name and game_name not in candidates:
        candidates.append(game_name)

    return candidates


def resolve_edgeemu_game(game_info: dict, system_slug: str, session: requests.Session) -> dict | None:
    """
    Résout directement une URL EdgeEmu à partir du nom de ROM.
    Le browse EdgeEmu ne retourne qu'un petit sous-ensemble variable de jeux,
    donc on privilégie ici l'URL de téléchargement déterministe.
    """
    if not system_slug:
        return None

    if ROM_DATABASE is None:
        load_rom_database()

    config = ROM_DATABASE.get('config_urls', {})
    edgeemu_base = (config.get('edgeemu_base', '') or '').rstrip('/')
    if not edgeemu_base:
        return None

    for candidate_name in iter_game_candidate_names(game_info):
        filename = f"{candidate_name}.zip"
        download_url = f"{edgeemu_base}/download/{system_slug}/{quote(filename)}"
        try:
            response = session.get(download_url, timeout=30, allow_redirects=True, stream=True)
            status_code = response.status_code
            content_type = (response.headers.get('content-type') or '').lower()
            content_disposition = response.headers.get('content-disposition') or ''
            final_url = response.url
            response.close()

            if status_code == 200 and (
                'application/octet-stream' in content_type
                or 'application/zip' in content_type
                or content_disposition
            ):
                return {
                    'full_name': candidate_name,
                    'filename': filename,
                    'url': final_url
                }
        except Exception:
            continue

    return None


def list_planetemu_directory(system_slug: str, session: requests.Session) -> dict:
    """Scrape PlanetEmu pour un système donné."""
    if not system_slug:
        return {}
        
    config = ROM_DATABASE.get('config_urls', {})
    base = config.get('planetemu_roms', '')
    if not base:
        base = 'https://www.planetemu.net/roms/'
    url = f"{base}{system_slug}"
    print(f"Scraping PlanetEmu: {url}")
    
    mapping = {}
    try:
        # PlanetEmu nécessite souvent plusieurs pages (?page=A, B, etc.)
        # Pour faire simple, on scrape la page principale
        response = session.get(url, timeout=30)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # Les liens vers les ROMs sont dans des <a> pointant vers /rom/
            for a in soup.find_all('a', href=True):
                if '/rom/' in a['href']:
                    game_name = a.get_text().strip()
                    if game_name:
                        # On stocke l'URL de la page du jeu pour extraire l'ID plus tard si besoin
                        page_url = config.get('planetemu_base', '') + a['href']
                        mapping[game_name.lower()] = {
                            'full_name': game_name,
                            'page_url': page_url
                        }
    except Exception as e:
        print(f"Erreur scraping PlanetEmu: {e}")
        
    return mapping


def download_planetemu(page_url: str, dest_path: str, session: requests.Session, progress_callback=None) -> bool:
    """Téléchargement spécifique pour PlanetEmu (POST + Token)."""
    try:
        # Étape 1 : Aller sur la page du jeu pour trouver l'ID
        resp = session.get(page_url, timeout=30)
        html = resp.text
        
        # Chercher l'ID dans le formulaire de téléchargement
        id_match = re.search(r'name="id"\s+value="(\d+)"', html)
        if not id_match:
            print("  [PlanetEmu] ID de ROM introuvable sur la page")
            return False
            
        rom_id = id_match.group(1)
        
        # Étape 2 : Envoyer le POST pour générer le token
        config = ROM_DATABASE.get('config_urls', {})
        download_api = config.get('planetemu_download_api', '')
        if not download_api:
             download_api = 'https://www.planetemu.net/php/roms/download.php'
             
        data = {'id': rom_id, 'download': 'T\u00e9l\u00e9charger'}
        
        # On ne suit pas les redirects automatiquement pour voir le Location
        resp = session.post(download_api, data=data, allow_redirects=False, timeout=30)
        
        token_url = None
        if resp.status_code == 302:
            token_url = resp.headers.get('Location')
            if token_url:
                token_url = urljoin(download_api, token_url)
        
        if not token_url:
            # Essayer de trouver le token dans le HTML si pas de redirect 302
            soup = BeautifulSoup(resp.text, 'html.parser')
            a_token = soup.find('a', href=True)
            if a_token and 'token=' in a_token['href']:
                token_url = urljoin(download_api, a_token['href'])

        if not token_url:
            print("  [PlanetEmu] Échec de génération du token")
            return False
            
        # Étape 3 : Télécharger avec le token
        return download_file(token_url, dest_path, session, progress_callback)
        
    except Exception as e:
        print(f"  [PlanetEmu] Erreur: {e}")
        return False

def resolve_cdromance_game(game_info: dict, session: requests.Session) -> dict | None:
    """Recherche un jeu sur CDRomance via leur moteur de recherche."""
    for candidate_name in iter_game_candidate_names(game_info):
        search_url = f"{CDROMANCE_BASE}?s={quote(candidate_name)}"
        try:
            resp = session.get(search_url, timeout=30)
            if resp.status_code != 200: continue
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            # Les résultats de recherche sont dans des <a> avec la classe 'thumbnail-link' ou similaire
            # On cherche le premier résultat qui ressemble au nom du jeu
            for link in soup.find_all('a', href=True):
                if CDROMANCE_BASE in link['href'] and any(x in link['href'] for x in ['-iso', '-rom', '-roms']):
                    title = link.get('title', '').lower() or link.get_text().strip().lower()
                    # Normalisation basique pour comparaison
                    clean_title = re.sub(r'[^a-z0-9]', '', title)
                    clean_candidate = re.sub(r'[^a-z0-9]', '', candidate_name.lower())
                    
                    if clean_candidate in clean_title or clean_title in clean_candidate:
                        return {
                            'full_name': candidate_name,
                            'page_url': link['href'],
                            'source': 'CDRomance'
                        }
        except Exception as e:
            print(f"  [CDRomance] Erreur recherche: {e}")
            continue
    return None

def download_cdromance(page_url: str, dest_path: str, session: requests.Session, progress_callback=None) -> bool:
    """Télécharge un jeu depuis CDRomance en gérant le système de tickets."""
    try:
        # Étape 1 : Récupérer la page du jeu
        resp = session.get(page_url, timeout=30)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Le ticket est souvent dans un input ou un span avec l'ID cdr_ticket
        ticket = None
        ticket_el = soup.find('input', {'id': 'cdr_ticket_input'}) or soup.find('span', {'id': 'cdr_ticket'})
        if ticket_el:
            ticket = ticket_el.get('value') or ticket_el.get_text().strip()
            
        if not ticket:
            # Essayer de trouver dans le JS si pas trouvé en HTML
            match = re.search(r'cdr_ticket\s*=\s*["\']([^"\']+)["\']', resp.text)
            if match: ticket = match.group(1)

        if not ticket:
            print("  [CDRomance] Ticket introuvable")
            return False
            
        # Étape 2 : Envoyer le ticket pour obtenir les liens
        # CDRomance utilise souvent un POST vers .org/
        post_data = {'cdrTicketInput': ticket}
        resp = session.post(CDROMANCE_BASE, data=post_data, timeout=30)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Chercher les liens de téléchargement
        dl_links = []
        for a in soup.find_all('a', href=True):
            if 'download.php' in a['href']:
                dl_links.append(urljoin(CDROMANCE_BASE, a['href']))
        
        if not dl_links:
            print("  [CDRomance] Aucun lien de téléchargement trouvé après validation du ticket")
            return False
            
        # Prendre le premier lien
        download_url = dl_links[0]
        return download_file(download_url, dest_path, session, progress_callback)
        
    except Exception as e:
        print(f"  [CDRomance] Erreur téléchargement: {e}")
        return False

def resolve_vimm_game(game_info: dict, system_slug: str, session: requests.Session) -> dict | None:
    """Recherche un jeu sur Vimm's Lair."""
    if not system_slug: return None
    
    for candidate_name in iter_game_candidate_names(game_info):
        search_url = f"{VIMM_BASE}vault/?p=list&system={system_slug}&q={quote(candidate_name)}"
        try:
            resp = session.get(search_url, timeout=30)
            if resp.status_code != 200: continue
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            # Les résultats sont dans des <a> à l'intérieur d'un tableau
            for a in soup.find_all('a', href=True):
                if '/vault/' in a['href']:
                    title = a.get_text().strip().lower()
                    if candidate_name.lower() in title or title in candidate_name.lower():
                        return {
                            'full_name': title,
                            'page_url': urljoin(VIMM_BASE, a['href']),
                            'source': 'Vimm\'s Lair'
                        }
        except Exception as e:
            print(f"  [Vimm] Erreur recherche: {e}")
            continue
    return None

def download_vimm(page_url: str, dest_path: str, session: requests.Session, progress_callback=None) -> bool:
    """Télécharge un jeu depuis Vimm's Lair en simulant le formulaire POST."""
    try:
        # Étape 1 : Aller sur la page du jeu pour avoir les cookies et le mediaId
        session.headers.update({'Referer': VIMM_BASE})
        resp = session.get(page_url, timeout=30)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        form = soup.find('form', id='dl_form')
        if not form:
            print("  [Vimm] Formulaire de téléchargement introuvable")
            return False
            
        media_id_input = form.find('input', {'name': 'mediaId'})
        if not media_id_input:
            print("  [Vimm] mediaId introuvable")
            return False
            
        media_id = media_id_input.get('value')
        action = form.get('action')
        download_url = urljoin(page_url, action)
        
        # Étape 2 : POST pour déclencher le téléchargement
        # Note: Vimm est très strict sur le Referer
        session.headers.update({'Referer': page_url})
        payload = {'mediaId': media_id}
        
        # Utiliser download_file mais avec un POST ? 
        # download_file utilise session.get. On va devoir le faire manuellement ici.
        with session.post(download_url, data=payload, stream=True, timeout=120) as r:
            r.raise_for_status()
            
            # Récupérer le nom de fichier
            cd = r.headers.get('content-disposition', '')
            match = re.search(r'filename="?([^";]+)"?', cd)
            if match:
                server_filename = match.group(1)
                dest_path = os.path.join(os.path.dirname(dest_path), server_filename)
                
            total_size = int(r.headers.get('content-length', 0))
            downloaded = 0
            with open(dest_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0 and progress_callback:
                            progress_callback((downloaded / total_size) * 100)
                            
            if progress_callback: progress_callback(100.0)
            return True
            
    except Exception as e:
        print(f"  [Vimm] Erreur téléchargement: {e}")
        return False


RETRO_GAME_SETS_DB = {}
RETRO_GAME_SETS_CACHE_DIR = APP_ROOT / 'rom_db_shards' / 'retrogamesets'

def load_retrogamesets_database(system_slug: str, session: requests.Session) -> list:
    """Charge la base de données JSON pour un système spécifique depuis RetroGameSets."""
    global RETRO_GAME_SETS_DB
    
    if system_slug in RETRO_GAME_SETS_DB:
        return RETRO_GAME_SETS_DB[system_slug]
        
    os.makedirs(RETRO_GAME_SETS_CACHE_DIR, exist_ok=True)
    json_path = RETRO_GAME_SETS_CACHE_DIR / f"{system_slug}.json"
    
    # Si le fichier n'existe pas, on télécharge le games.zip complet
    if not json_path.exists():
        print(f"  [RetroGameSets] Téléchargement de la base de données...")
        try:
            zip_url = urljoin(RETRO_GAME_SETS_BASE, 'softs/games.zip')
            resp = session.get(zip_url, timeout=60)
            if resp.status_code == 200:
                import zipfile
                import io
                with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                    # Extraire tous les JSON dans le dossier cache
                    # Le zip contient un dossier 'games/'
                    for member in z.namelist():
                        if member.endswith('.json'):
                            filename = os.path.basename(member)
                            with open(RETRO_GAME_SETS_CACHE_DIR / filename, 'wb') as f:
                                f.write(z.read(member))
            else:
                print(f"  [RetroGameSets] Erreur téléchargement games.zip: {resp.status_code}")
                return []
        except Exception as e:
            print(f"  [RetroGameSets] Erreur lors de la mise à jour de la base: {e}")
            return []

    # Charger le JSON si présent
    if json_path.exists():
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                RETRO_GAME_SETS_DB[system_slug] = data
                return data
        except Exception as e:
            print(f"  [RetroGameSets] Erreur lecture JSON {system_slug}: {e}")
            
    return []

def resolve_retrogamesets_game(game_info: dict, system_slug: str, session: requests.Session) -> dict | None:
    """Recherche un jeu dans la base RetroGameSets."""
    if not system_slug: return None
    
    db = load_retrogamesets_database(system_slug, session)
    if not db: return None
    
    # Créer un index par nom pour recherche rapide
    if not hasattr(resolve_retrogamesets_game, '_indices'):
        resolve_retrogamesets_game._indices = {}
        
    if system_slug not in resolve_retrogamesets_game._indices:
        index = {}
        for entry in db:
            if not isinstance(entry, list) or len(entry) < 2:
                continue
            # L'entrée est [path, url, size]
            # path: "Nintendo - Game Boy/Tetris (World) (Rev A).zip"
            path = entry[0]
            url = entry[1]
            
            # Extraire le nom du fichier sans extension et sans le préfixe dossier
            filename = os.path.basename(path)
            name_no_ext = strip_rom_extension(filename)
            index[name_no_ext.lower()] = {
                'name': name_no_ext,
                'url': url
            }
        resolve_retrogamesets_game._indices[system_slug] = index
    
    index = resolve_retrogamesets_game._indices[system_slug]
    
    for candidate_name in iter_game_candidate_names(game_info):
        candidate_lower = candidate_name.lower()
        if candidate_lower in index:
            match = index[candidate_lower]
            return {
                'full_name': match.get('name'),
                'url': match.get('url'),
                'source': 'RetroGameSets'
            }
        # Recherche permissive : si le nom candidat est contenu dans un nom de l'index
        for indexed_name_lower, match in index.items():
            if candidate_lower in indexed_name_lower or indexed_name_lower in candidate_lower:
                 return {
                    'full_name': match.get('name'),
                    'url': match.get('url'),
                    'source': 'RetroGameSets'
                }
            
    return None


def list_myrient_directory(myrient_url: str, session: requests.Session) -> set:
    """List all files in a Myrient directory."""
    print(f"Fetching Myrient directory listing: {myrient_url}")

    files = set()
    try:
        response = session.get(myrient_url, timeout=60)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')

            # Chercher spécifiquement dans le tableau de listing
            table = soup.find('table', id='list')
            if table:
                for link in table.find_all('a', href=True):
                    href = link.get('href', '')
                    text = link.get_text().strip()

                    # Filtrer les liens de navigation et éléments non-fichiers
                    if not href or href.startswith('?') or href.startswith('.'):
                        continue
                    if text in ['Parent directory/', './', '../', '']:
                        continue
                    if href.startswith('/') or '://' in href:
                        continue

                    # Utiliser la constante globale des extensions
                    decoded = unquote(href.rstrip('/'))
                    if decoded.lower().endswith(ROM_EXTENSIONS):
                        files.add(decoded)

        print(f"Found {len(files)} files in Myrient directory")
    except Exception as e:
        print(f"Error fetching Myrient directory: {e}")

    return files


def match_myrient_files(missing_games: list, myrient_files: set, source_name: str = 'Myrient') -> tuple:
    """Match missing games with files available on a Myrient-like source."""
    print(f"Matching missing games with {source_name} files...")

    myrient_lookup = {}
    for f in myrient_files:
        name_no_ext = f
        for ext in ROM_EXTENSIONS:
            if f.lower().endswith(ext):
                name_no_ext = f[:-len(ext)]
                break
        myrient_lookup[name_no_ext.lower()] = f

    to_download = []
    not_available = []
    for game_info in missing_games:
        game_name = game_info['game_name']
        matched_file = None
        for rom_info in game_info.get('roms', []):
            rom_name = rom_info.get('name', '')
            rom_name_no_ext = strip_rom_extension(rom_name)
            if rom_name_no_ext.lower() in myrient_lookup:
                matched_file = myrient_lookup[rom_name_no_ext.lower()]
                break

        if not matched_file:
            primary_rom = game_info.get('primary_rom', '')
            primary_rom_no_ext = strip_rom_extension(primary_rom)
            if primary_rom_no_ext.lower() in myrient_lookup:
                matched_file = myrient_lookup[primary_rom_no_ext.lower()]

        if not matched_file:
            game_name_normalized = game_name.lower()
            if game_name_normalized in myrient_lookup:
                matched_file = myrient_lookup[game_name_normalized]

        if matched_file:
            game_info['download_filename'] = matched_file
            game_info['source'] = source_name
            to_download.append(game_info)
        else:
            not_available.append(game_info)

    print(f"Found {len(to_download)} missing games available on {source_name}")
    if not_available:
        print(f"WARNING: {len(not_available)} games NOT found on {source_name}!")

    return to_download, not_available


def search_all_sources_legacy(missing_games: list, sources: list, session: requests.Session, system_name: str = None) -> tuple:
    """
    Search for missing games across all configured sources.
    Utilise la base de données locale (74,189 URLs) + recherche directe + nouveaux scrapers.
    Returns (found_games: list, not_found_games: list)
    """
    print("\n" + "=" * 70)
    print(f"Recherche des jeux manquants pour le système: {system_name or 'Inconnu'}")
    print("=" * 70)
    
    # Charger la base de données
    effective_profile = finalize_dat_profile(dat_profile) if dat_profile else None
    if effective_profile and effective_profile.get('system_name'):
        system_name = effective_profile.get('system_name')

    sources = prepare_sources_for_profile(sources, effective_profile)

    load_rom_database()
    
    if effective_profile:
        print(f"DAT detecte: {describe_dat_profile(effective_profile)}")

    all_found = []
    still_missing = missing_games.copy()
    
    # Mappings pour ce système
    mappings = SYSTEM_MAPPINGS.get(system_name, {}) if system_name else {}
    
    # ========================================================================
    # ÉTAPE 1 : Recherche dans la base de données locale (74,189 URLs)
    # ========================================================================
    print(f"\n{'=' * 70}")
    print("ÉTAPE 1: Recherche dans la base de données locale")
    print(f"{'=' * 70}")
    
    found_in_db = []
    not_in_db = []
    
    for game_info in still_missing:
        game_name = game_info['game_name']
        roms = game_info.get('roms', [])
        
        # Recherche par nom dans la base
        db_results, search_hint = search_database_for_game(game_info)
        
        # Si pas trouvé par nom, essayer par MD5
        if db_results:
            # Prendre le premier résultat (priorité: archive.org > myrient > 1fichier)
            best_result = None
            for result in db_results:
                host = result.get('host', '')
                if 'archive.org' in host:
                    best_result = result
                    break
                elif 'myrient' in host and not best_result:
                    best_result = result
            
            if not best_result:
                best_result = db_results[0]
            
            game_info['download_filename'] = database_result_filename(best_result, game_name)
            game_info['download_url'] = best_result.get('url')
            game_info['source'] = 'database'
            game_info['database_host'] = best_result.get('host')
            found_in_db.append(game_info)
            print(f"  [DB] {game_name} -> {best_result.get('host')}")
        else:
            not_in_db.append(game_info)
    
    all_found.extend(found_in_db)
    still_missing = not_in_db
    
    print(f"\n  Trouvé dans la base: {len(found_in_db)} jeux")
    print(f"  Non trouvé dans la base: {len(still_missing)} jeux")
    
    # ========================================================================
    # ÉTAPE 2 : Recherche via les nouveaux scrapers (EdgeEmu / PlanetEmu)
    # ========================================================================
    if still_missing and system_name:
        for source in sources:
            if source['type'] == 'edgeemu' and source.get('enabled', True) and source.get('compatible', True):
                slug = mappings.get('edgeemu')
                if slug:
                    print(f"\n--- Recherche sur EdgeEmu ({slug}) ---")
                    newly_found = []
                    remaining = []
                    for game_info in still_missing:
                        edge_match = resolve_edgeemu_game(game_info, slug, session)
                        if edge_match:
                            game_info['download_url'] = edge_match['url']
                            game_info['source'] = 'EdgeEmu'
                            game_info['download_filename'] = edge_match['filename']
                            newly_found.append(game_info)
                            print(f"  [EdgeEmu] {game_info['game_name']} trouvé")
                        else:
                            remaining.append(game_info)
                    all_found.extend(newly_found)
                    still_missing = remaining

            elif source['type'] == 'planetemu' and source.get('enabled', True) and source.get('compatible', True):
                slug = mappings.get('planetemu')
                if slug:
                    print(f"\n--- Recherche sur PlanetEmu ({slug}) ---")
                    planet_files = list_planetemu_directory(slug, session)
                    if planet_files:
                        newly_found = []
                        remaining = []
                        for game_info in still_missing:
                            name_lower = game_info['game_name'].lower()
                            if name_lower in planet_files:
                                game_info['page_url'] = planet_files[name_lower]['page_url']
                                game_info['source'] = 'PlanetEmu'
                                game_info['download_filename'] = f"{game_info['game_name']}.zip"
                                newly_found.append(game_info)
                                print(f"  [PlanetEmu] {game_info['game_name']} trouvé")
                            else:
                                remaining.append(game_info)
                        all_found.extend(newly_found)
                        still_missing = remaining

            elif source['type'] == 'cdromance' and source.get('enabled', True):
                print(f"\n--- Recherche sur CDRomance ---")
                cd_session = get_cdromance_session()
                newly_found = []
                remaining = []
                for game_info in still_missing:
                    cd_match = resolve_cdromance_game(game_info, cd_session)
                    if cd_match:
                        game_info['page_url'] = cd_match['page_url']
                        game_info['source'] = 'CDRomance'
                        game_info['download_filename'] = f"{game_info['game_name']}.zip"
                        newly_found.append(game_info)
                        print(f"  [CDRomance] {game_info['game_name']} trouvé")
                    else:
                        remaining.append(game_info)
                all_found.extend(newly_found)
                still_missing = remaining

            elif source['type'] == 'vimm' and source.get('enabled', True):
                slug = mappings.get('vimm')
                if slug:
                    print(f"\n--- Recherche sur Vimm's Lair ({slug}) ---")
                    vimm_session = get_vimm_session()
                    newly_found = []
                    remaining = []
                    for game_info in still_missing:
                        vimm_match = resolve_vimm_game(game_info, slug, vimm_session)
                        if vimm_match:
                            game_info['page_url'] = vimm_match['page_url']
                            game_info['source'] = 'Vimm\'s Lair'
                            game_info['download_filename'] = f"{game_info['game_name']}.zip"
                            newly_found.append(game_info)
                            print(f"  [Vimm] {game_info['game_name']} trouvé")
                        else:
                            remaining.append(game_info)
                    all_found.extend(newly_found)
                    still_missing = remaining

            elif source['type'] == 'retrogamesets' and source.get('enabled', True):
                slug = mappings.get('retrogamesets')
                if slug:
                    print(f"\n--- Recherche sur RetroGameSets ({slug}) ---")
                    newly_found = []
                    remaining = []
                    for game_info in still_missing:
                        rgs_match = resolve_retrogamesets_game(game_info, slug, session)
                        if rgs_match:
                            game_info['download_url'] = rgs_match['url']
                            game_info['source'] = 'RetroGameSets'
                            game_info['download_filename'] = f"{game_info['game_name']}.zip"
                            newly_found.append(game_info)
                            print(f"  [RetroGameSets] {game_info['game_name']} trouvé")
                        else:
                            remaining.append(game_info)
                    all_found.extend(newly_found)
                    still_missing = remaining

    # ÉTAPE 3 : Recherche directe sur Myrient (pour les non-trouvés)
    # ========================================================================
    myrient_sources = [s for s in sources if s['type'] == 'myrient' and s.get('enabled', True)]
    
    if myrient_sources and still_missing:
        for source in myrient_sources:
            print(f"\n--- Recherche directe sur {source['name']} ---")
            
            # Essayer de deviner le dossier Myrient si c'est un lien générique
            base_url = source['base_url']
            if base_url.endswith('/No-Intro/') and system_name:
                base_url = f"{base_url}{quote(system_name)}/"
            
            myrient_files = list_myrient_directory(base_url, session)
            
            if myrient_files:
                found, still_missing = match_myrient_files(still_missing, myrient_files, source['name'])
                for f in found:
                    f['download_url'] = f"{base_url.rstrip('/')}/{quote(f['download_filename'])}"
                all_found.extend(found)
    
    # ========================================================================
    # ETAPE 4 : Recherche archive.org par checksum puis nom avant torrent
    # ========================================================================
    archive_sources = [
        s for s in sources
        if s['type'] == 'archive_org' and s.get('enabled', True) and s.get('compatible', True)
    ]
    
    if archive_sources and still_missing:
        print(f"\n--- Recherche archive.org par MD5 (fallback) ---")
        found, still_missing = search_archive_org_for_games(still_missing)
        all_found.extend(found)
    
    # ========================================================================
    # RÉSUMÉ
    # ========================================================================
    print(f"\n{'=' * 70}")
    print(f"RÉSUMÉ DE LA RECHERCHE")
    print(f"{'=' * 70}")
    print(f"  Jeux trouvés (base locale): {len(found_in_db)}")
    print(f"  Jeux trouvés (Myrient direct): {len(all_found) - len(found_in_db)}")
    print(f"  Total trouvés: {len(all_found)}")
    print(f"  Jeux non trouvés: {len(still_missing)}")
    print(f"{'=' * 70}")
    
    return all_found, still_missing


def search_all_sources(
    missing_games: list,
    sources: list,
    session: requests.Session,
    system_name: str = None,
    dat_profile: dict | None = None,
    excluded_sources: set[str] | None = None
) -> tuple:
    """
    Search for missing games across all configured sources.
    Les liens directs sont prioritaires; Minerva passe ensuite, puis archive.org en dernier recours.
    Returns (found_games: list, not_found_games: list)
    """
    print("\n" + "=" * 70)
    print(f"Recherche des jeux manquants pour le systÃ¨me: {system_name or 'Inconnu'}")
    print("=" * 70)

    load_rom_database()
    excluded_sources = {
        normalize_source_label(source_name)
        for source_name in (excluded_sources or set())
        if source_name
    }

    all_found = []
    still_missing = missing_games.copy()
    direct_found = []
    found_in_db = []
    minerva_found = []
    archive_found = []

    mappings = SYSTEM_MAPPINGS.get(system_name, {}) if system_name else {}

    # ========================================================================
    # ÉTAPE 1 : Recherche dans la base de données locale (shards + fallback)
    # ========================================================================
    print(f"\n{'=' * 70}")
    print("ÉTAPE 1: Recherche dans la base de données locale (MD5 shards + fallback)")
    print(f"{'=' * 70}")

    not_in_db = []
    if 'database' in excluded_sources:
        not_in_db = still_missing
        print("  [DB] ignoree pour ce retry")
    else:
        for game_info in still_missing:
            game_name = game_info['game_name']
            db_results, search_hint = search_database_for_game(game_info)

            best_result = select_database_result(db_results)
            if best_result:
                game_info['download_filename'] = database_result_filename(best_result, game_name)
                game_info['download_url'] = best_result.get('url')
                game_info['source'] = 'database'
                game_info['database_host'] = best_result.get('host')
                found_in_db.append(game_info)
                print(f"  [DB] {game_name} -> {best_result.get('host')}{f' ({search_hint})' if search_hint else ''}")
            else:
                not_in_db.append(game_info)

    all_found.extend(found_in_db)
    still_missing = not_in_db

    print(f"\n  TrouvÃ© dans la base: {len(found_in_db)} jeux")
    print(f"  Non trouvÃ© dans la base: {len(still_missing)} jeux")

    # ========================================================================
    # ETAPE 2 : Recherche directe sur les sources DDL type listing HTML
    # ========================================================================
    print(f"\n{'=' * 70}")
    print("ETAPE 2: Recherche directe sur les sources DDL")
    print(f"{'=' * 70}")

    direct_sources = [
        s for s in sources
        if s.get('enabled', True)
        and s.get('compatible', True)
        and not source_is_excluded(s, excluded_sources)
        and s['type'] in {'myrient'}
    ]

    if direct_sources and still_missing:
        for source in direct_sources:
            if not still_missing:
                break
            print(f"\n--- Recherche directe sur {source['name']} ---")

            if source['type'] == 'minerva':
                base_url = build_minerva_directory_url(source, system_name)
                minerva_files = collect_minerva_files_from_url(base_url, session, source.get('scan_depth', 0))
                if minerva_files:
                    torrent_url = resolve_minerva_torrent_url(source, system_name, session)
                    if not torrent_url:
                        candidates = build_minerva_torrent_urls(source, system_name)
                        probe_url = candidates[0] if candidates else 'aucune URL candidate'
                        print(f"  Avertissement: torrent Minerva introuvable pour {source['name']} ({probe_url})")
                        print("  Bascule vers les sources de fallback pour ce systeme.")
                        continue

                    found, still_missing = match_myrient_files(still_missing, minerva_files, source['name'])
                    for game in found:
                        game['torrent_url'] = torrent_url
                        game['source'] = source['name']
                    direct_found.extend(found)
                    all_found.extend(found)
            else:
                base_url = source['base_url']
                if base_url.endswith('/No-Intro/') and system_name:
                    base_url = f"{base_url}{quote(system_name)}/"

                myrient_files = list_myrient_directory(base_url, session)
                if myrient_files:
                    found, still_missing = match_myrient_files(still_missing, myrient_files, source['name'])
                    for game in found:
                        game['download_url'] = f"{base_url.rstrip('/')}/{quote(game['download_filename'])}"
                    direct_found.extend(found)
                    all_found.extend(found)

    print(f"\n  Trouve via source DDL directe: {len(direct_found)} jeux")
    print(f"  Restants apres DDL direct: {len(still_missing)} jeux")

    # ========================================================================
    # ÉTAPE 3 : Recherche via scrapers secondaires
    # ========================================================================
    if still_missing and system_name:
        for source in sources:
            if not still_missing:
                break
            if source_is_excluded(source, excluded_sources):
                continue

            if source['type'] == 'edgeemu' and source.get('enabled', True):
                slug = mappings.get('edgeemu')
                if slug:
                    print(f"\n--- Recherche sur EdgeEmu ({slug}) ---")
                    newly_found = []
                    if still_missing:
                        remaining = []
                        for game_info in still_missing:
                            edge_match = resolve_edgeemu_game(game_info, slug, session)
                            if edge_match:
                                game_info['download_url'] = edge_match['url']
                                game_info['source'] = 'EdgeEmu'
                                game_info['download_filename'] = edge_match['filename']
                                newly_found.append(game_info)
                                print(f"  [EdgeEmu] {game_info['game_name']} trouvÃ©")
                            else:
                                remaining.append(game_info)
                        all_found.extend(newly_found)
                        still_missing = remaining

            elif source['type'] == 'planetemu' and source.get('enabled', True):
                slug = mappings.get('planetemu')
                if slug:
                    print(f"\n--- Recherche sur PlanetEmu ({slug}) ---")
                    planet_files = list_planetemu_directory(slug, session)
                    if planet_files:
                        newly_found = []
                        remaining = []
                        for game_info in still_missing:
                            name_lower = game_info['game_name'].lower()
                            if name_lower in planet_files:
                                game_info['page_url'] = planet_files[name_lower]['page_url']
                                game_info['source'] = 'PlanetEmu'
                                game_info['download_filename'] = f"{game_info['game_name']}.zip"
                                newly_found.append(game_info)
                                print(f"  [PlanetEmu] {game_info['game_name']} trouvÃ©")
                            else:
                                remaining.append(game_info)
                        all_found.extend(newly_found)
                        still_missing = remaining

            elif source['type'] == 'lolroms' and source.get('enabled', True):
                lolroms_path = resolve_lolroms_system_path(system_name)
                if lolroms_path:
                    print(f"\n--- Recherche sur LoLROMs ({lolroms_path}) ---")
                    lolroms_files = list_lolroms_directory(lolroms_path)
                    if lolroms_files:
                        newly_found = []
                        remaining = []
                        for game_info in still_missing:
                            matched = None
                            for candidate_name in iter_game_candidate_names(game_info):
                                matched = lolroms_files.get(candidate_name.lower())
                                if matched:
                                    break

                            if matched:
                                game_info['download_url'] = matched['url']
                                game_info['source'] = 'LoLROMs'
                                game_info['download_filename'] = matched['filename']
                                newly_found.append(game_info)
                                print(f"  [LoLROMs] {game_info['game_name']} trouvé")
                            else:
                                remaining.append(game_info)

                        all_found.extend(newly_found)
                        still_missing = remaining

            elif source['type'] == 'cdromance' and source.get('enabled', True):
                print(f"\n--- Recherche sur CDRomance ---")
                cd_session = get_cdromance_session()
                newly_found = []
                remaining = []
                for game_info in still_missing:
                    cd_match = resolve_cdromance_game(game_info, cd_session)
                    if cd_match:
                        game_info['page_url'] = cd_match['page_url']
                        game_info['source'] = 'CDRomance'
                        game_info['download_filename'] = f"{game_info['game_name']}.zip"
                        newly_found.append(game_info)
                        print(f"  [CDRomance] {game_info['game_name']} trouvé")
                    else:
                        remaining.append(game_info)
                all_found.extend(newly_found)
                still_missing = remaining

            elif source['type'] == 'vimm' and source.get('enabled', True):
                slug = mappings.get('vimm')
                if slug:
                    print(f"\n--- Recherche sur Vimm's Lair ({slug}) ---")
                    vimm_session = get_vimm_session()
                    newly_found = []
                    remaining = []
                    for game_info in still_missing:
                        vimm_match = resolve_vimm_game(game_info, slug, vimm_session)
                        if vimm_match:
                            game_info['page_url'] = vimm_match['page_url']
                            game_info['source'] = 'Vimm\'s Lair'
                            game_info['download_filename'] = f"{game_info['game_name']}.zip"
                            newly_found.append(game_info)
                            print(f"  [Vimm] {game_info['game_name']} trouvé")
                        else:
                            remaining.append(game_info)
                    all_found.extend(newly_found)
                    still_missing = remaining

            elif source['type'] == 'retrogamesets' and source.get('enabled', True):
                slug = mappings.get('retrogamesets')
                if slug:
                    print(f"\n--- Recherche sur RetroGameSets ({slug}) ---")
                    newly_found = []
                    remaining = []
                    for game_info in still_missing:
                        rgs_match = resolve_retrogamesets_game(game_info, slug, session)
                        if rgs_match:
                            game_info['download_url'] = rgs_match['url']
                            game_info['source'] = 'RetroGameSets'
                            game_info['download_filename'] = f"{game_info['game_name']}.zip"
                            newly_found.append(game_info)
                            print(f"  [RetroGameSets] {game_info['game_name']} trouvé")
                        else:
                            remaining.append(game_info)
                    all_found.extend(newly_found)
                    still_missing = remaining

    # ========================================================================
    # ETAPE 4 : Minerva via torrent avant le fallback archive.org
    # ========================================================================
    minerva_sources = [
        s for s in sources
        if s.get('enabled', True)
        and s.get('compatible', True)
        and not source_is_excluded(s, excluded_sources)
        and s['type'] == 'minerva'
    ]

    if minerva_sources and still_missing:
        print(f"\n{'=' * 70}")
        print("ETAPE 4: Minerva via torrent")
        print(f"{'=' * 70}")

        print("\n--- Recherche Minerva officielle par MD5 DAT ---")
        found, still_missing = search_minerva_hash_database_for_games(still_missing)
        minerva_found.extend(found)
        all_found.extend(found)

        for source in minerva_sources:
            if not still_missing:
                break
            print(f"\n--- Recherche torrent sur {source['name']} ---")
            base_url = build_minerva_directory_url(source, system_name)
            minerva_files = collect_minerva_files_from_url(base_url, session, source.get('scan_depth', 0))
            if not minerva_files:
                continue

            torrent_url = resolve_minerva_torrent_url(source, system_name, session)
            if not torrent_url:
                candidates = build_minerva_torrent_urls(source, system_name)
                probe_url = candidates[0] if candidates else 'aucune URL candidate'
                print(f"  Avertissement: torrent Minerva introuvable pour {source['name']} ({probe_url})")
                continue

            found, still_missing = match_myrient_files(still_missing, minerva_files, source['name'])
            for game in found:
                game['torrent_url'] = torrent_url
                game['source'] = source['name']
            minerva_found.extend(found)
            all_found.extend(found)

    # ========================================================================
    # ETAPE 5 : Dernier recours archive.org par checksum puis nom
    # ========================================================================
    archive_sources = [
        s for s in sources
        if s['type'] == 'archive_org'
        and s.get('enabled', True)
        and not source_is_excluded(s, excluded_sources)
    ]
    if archive_sources and still_missing:
        print(f"\n{'=' * 70}")
        print("ETAPE 5: Dernier recours archive.org")
        print(f"{'=' * 70}")
        print(f"\n--- Recherche archive.org par checksum puis nom ---")
        found, still_missing = search_archive_org_for_games(still_missing)
        archive_found.extend(found)
        all_found.extend(found)

    print(f"\n{'=' * 70}")
    print("RÃ‰SUMÃ‰ DE LA RECHERCHE")
    print(f"{'=' * 70}")
    print(f"  Jeux trouves (DDL direct): {len(direct_found)}")
    print(f"  Jeux trouves (base locale): {len(found_in_db)}")
    print(f"  Jeux trouves (Minerva torrent): {len(minerva_found)}")
    print(f"  Jeux trouves (archive.org dernier recours): {len(archive_found)}")
    print(f"  Total trouvÃ©s: {len(all_found)}")
    print(f"  Jeux non trouvÃ©s: {len(still_missing)}")
    print(f"{'=' * 70}")

    return all_found, still_missing


def search_archive_org_for_games(not_available: list) -> tuple:
    """Recherche archive.org avec priorite md5 -> crc -> sha1 -> nom."""
    found_on_archive = []
    still_not_available = []
    total_games = len(not_available)

    for index, game_info in enumerate(not_available, start=1):
        game_name = game_info['game_name']
        roms = game_info.get('roms', [])
        archive_result = None
        print(f"  [{index}/{total_games}] Fallback archive.org pour: {game_name}")

        checksum_plan = (
            ('md5', search_archive_org_by_md5),
            ('crc', search_archive_org_by_crc),
            ('sha1', search_archive_org_by_sha1)
        )

        for checksum_type, resolver in checksum_plan:
            if archive_result:
                break

            for rom_info in roms:
                checksum_value = normalize_checksum(rom_info.get(checksum_type, ''), checksum_type)
                rom_name = rom_info.get('name', '')
                if not checksum_value:
                    continue

                result = resolver(checksum_value, rom_name)
                if result.get('found'):
                    archive_result = result
                    archive_result['rom_name'] = rom_name
                    break

        if not archive_result:
            rom_names = []
            primary_rom = game_info.get('primary_rom', '')
            if primary_rom:
                rom_names.append(primary_rom)
            for rom_info in roms:
                rom_name = rom_info.get('name', '')
                if rom_name and rom_name not in rom_names:
                    rom_names.append(rom_name)
            if game_name not in rom_names:
                rom_names.append(game_name)

            for rom_name in rom_names:
                result = search_archive_org_by_name(rom_name)
                if result.get('found'):
                    archive_result = result
                    archive_result['rom_name'] = rom_name
                    break

        if archive_result:
            game_info['download_filename'] = archive_result['filename']
            game_info['archive_org_identifier'] = archive_result['identifier']
            game_info['archive_org_filename'] = archive_result['filename']
            game_info['archive_org_md5'] = archive_result.get('md5', '')
            game_info['archive_org_crc'] = archive_result.get('crc', '')
            game_info['archive_org_sha1'] = archive_result.get('sha1', '')
            game_info['archive_org_checksum_type'] = archive_result.get('checksum_type', '')
            game_info['source'] = 'archive_org'
            found_on_archive.append(game_info)
            checksum_label = archive_result.get('checksum_type') or 'name'
            print(f"  [TROUVE] {game_name} sur archive.org ({checksum_label})")
        else:
            still_not_available.append(game_info)

    return found_on_archive, still_not_available


def download_file(url: str, dest_path: str, session: requests.Session, progress_callback=None) -> bool:
    """Download a file from URL to destination path with retry support."""
    max_retries = 3
    retry_delay = 5

    for attempt in range(max_retries):
        try:
            request_kwargs = {
                'stream': True,
                'timeout': 120,
                'allow_redirects': True,
            }
            archive_hosts = ('archive.org', '.archive.org')
            if any(host in (url or '').lower() for host in archive_hosts):
                access_key = os.environ.get('IAS3_ACCESS_KEY', '')
                secret_key = os.environ.get('IAS3_SECRET_KEY', '')
                if access_key and secret_key:
                    from requests.auth import HTTPBasicAuth
                    request_kwargs['auth'] = HTTPBasicAuth(access_key, secret_key)

            with session.get(url, **request_kwargs) as response:
                response.raise_for_status()

                # Get the filename from the server's response
                server_filename = ''
                cd = response.headers.get('content-disposition', '')
                import re
                match = re.search(r'filename=(?:"([^"]+)"|([^;]+))', cd, re.IGNORECASE)
                if match:
                    server_filename = match.group(1) or match.group(2)
                
                if not server_filename:
                    from urllib.parse import unquote
                    server_filename = os.path.basename(unquote(response.url.split('?')[0]))
                
                # If we couldn't find a filename, fallback to original dest_path
                if server_filename:
                    # Clean up the filename from illegal characters
                    server_filename = re.sub(r'[\\/*?:"<>|]', "", server_filename)
                    dest_path = os.path.join(os.path.dirname(dest_path), server_filename)

                total_size = int(response.headers.get('content-length', 0))
                block_size = 8192
                downloaded = 0

                with open(dest_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=block_size):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)

                            if total_size > 0 and progress_callback:
                                progress = (downloaded / total_size) * 100
                                progress_callback(progress)

                if progress_callback:
                    progress_callback(100.0)
                return True

        except Exception as e:
            print(f"  Tentative {attempt + 1}/{max_retries} échouée: {e}")
            if os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                except:
                    pass
            if attempt < max_retries - 1:
                print(f"  Nouvelle tentative dans {retry_delay} secondes...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Backoff exponentiel

    return False


def download_from_archive_org(identifier: str, filename: str, dest_path: str, progress_callback=None) -> bool:
    """Download a file from archive.org using the internetarchive library."""
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            print(f"  Téléchargement depuis archive.org: {identifier}/{filename}")
            
            item = internetarchive.get_item(identifier)
            file_obj = item.get_file(filename)
            
            if file_obj is None:
                print(f"  Fichier non trouvé: {filename}")
                return False
            
            # Download the file
            response = file_obj.download()
            
            # Get the file content
            if hasattr(response, 'iter_content'):
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                
                with open(dest_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            if total_size > 0 and progress_callback:
                                progress = (downloaded / total_size) * 100
                                progress_callback(progress)
            else:
                # If response is not a standard response object, try direct download
                file_obj.download(dest_path)
            
            if progress_callback:
                progress_callback(100.0)
                
            print(f"  Téléchargement terminé: {dest_path}")
            return True
            
        except Exception as e:
            print(f"  Tentative {attempt + 1}/{max_retries} échouée: {e}")
            if os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                except:
                    pass
            if attempt < max_retries - 1:
                time.sleep(2)
    
    return False


def download_from_archive_org(identifier: str, filename: str, dest_path: str, progress_callback=None) -> bool:
    """Download a file from archive.org using internetarchive, then authenticated HTTP fallback."""
    max_retries = 3

    for attempt in range(max_retries):
        try:
            print(f"  TÃ©lÃ©chargement depuis archive.org: {identifier}/{filename}")

            item = internetarchive.get_item(identifier)
            file_obj = item.get_file(filename)

            if file_obj is None:
                print(f"  Fichier non trouvÃ©: {filename}")
                return False

            response = file_obj.download()

            if hasattr(response, 'iter_content'):
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0

                with open(dest_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0 and progress_callback:
                                progress_callback((downloaded / total_size) * 100)
            else:
                file_obj.download(dest_path)

            if progress_callback:
                progress_callback(100.0)

            print(f"  TÃ©lÃ©chargement terminÃ©: {dest_path}")
            return True

        except Exception as e:
            print(f"  [WARN] Tentative internetarchive {attempt + 1}/{max_retries} Ã©chouÃ©e: {e}")
            if os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                except Exception:
                    pass

            try:
                download_url = f"https://archive.org/download/{identifier}/{quote(filename)}"
                print(f"  Fallback HTTP direct: {download_url}")
                session = requests.Session()
                session.headers.update({'User-Agent': 'Mozilla/5.0'})

                auth = None
                access_key = os.environ.get('IAS3_ACCESS_KEY', '')
                secret_key = os.environ.get('IAS3_SECRET_KEY', '')
                if access_key and secret_key:
                    from requests.auth import HTTPBasicAuth
                    auth = HTTPBasicAuth(access_key, secret_key)

                with session.get(download_url, stream=True, allow_redirects=True, timeout=120, auth=auth) as response:
                    response.raise_for_status()
                    total_size = int(response.headers.get('content-length', 0))
                    downloaded = 0

                    with open(dest_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if total_size > 0 and progress_callback:
                                    progress_callback((downloaded / total_size) * 100)

                if progress_callback:
                    progress_callback(100.0)

                if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
                    print(f"  TÃ©lÃ©chargement HTTP archive.org terminÃ©: {dest_path}")
                    return True
            except Exception as http_error:
                print(f"  [WARN] Fallback HTTP archive.org Ã©chouÃ©: {http_error}")
                if os.path.exists(dest_path):
                    try:
                        os.remove(dest_path)
                    except Exception:
                        pass

            if attempt < max_retries - 1:
                time.sleep(2)

    return False


# ============================================================================
# Mode interactif (console)
# ============================================================================

def clean_path_input(path: str) -> str:
    """Remove surrounding quotes from path."""
    path = path.strip()
    if path.startswith('"') and path.endswith('"'):
        path = path[1:-1]
    elif path.startswith("'") and path.endswith("'"):
        path = path[1:-1]
    return path


def get_input(prompt: str) -> str:
    """Get user input with quote cleaning."""
    result = input(prompt).strip()
    return clean_path_input(result)


def create_download_session() -> requests.Session:
    """Cree une session HTTP isolee pour un thread de telechargement."""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    return session


def interactive_mode():
    """Run in interactive console mode."""
    print("=" * 60)
    print("ROM Downloader - Mode Interactif")
    print("=" * 60)
    print()

    dat_file = get_input("Chemin vers le fichier DAT: ")
    rom_folder = get_input("Chemin vers le dossier des ROMs: ")
    myrient_url = get_input("URL source optionnelle (laisser vide pour l'auto Minerva): ")
    print()
    
    tosort_input = get_input("Deplacer les ROMs non presentes dans le DAT vers ToSort ? (o/n): ")
    move_to_tosort = tosort_input.lower() in ['o', 'oui', 'y', 'yes']
    clean_input = get_input("Recompresser les archives validees en ZIP TorrentZip/RomVault ? (o/n): ")
    clean_torrentzip = clean_input.lower() in ['o', 'oui', 'y', 'yes']
    print()

    # Validate
    if not os.path.exists(dat_file):
        print(f"Erreur: Fichier DAT introuvable: {dat_file}")
        return
    if not os.path.exists(rom_folder):
        print(f"Erreur: Dossier ROMs introuvable: {rom_folder}")
        return

    run_download(dat_file, rom_folder, myrient_url, rom_folder, False, None, move_to_tosort, clean_torrentzip)


def file_exists_in_folder(folder: str, filename: str) -> tuple:
    """
    Check if a file exists in folder, handling variations in extensions.
    Returns (exists: bool, actual_path: str)
    """
    # Check exact filename
    exact_path = os.path.join(folder, filename)
    if os.path.exists(exact_path):
        return True, exact_path

    # Check without extension (for .zip vs no extension)
    name_no_ext = filename
    for ext in ROM_EXTENSIONS:
        if filename.lower().endswith(ext):
            name_no_ext = filename[:-len(ext)]
            break

    # Scan folder for matching files
    if os.path.exists(folder):
        for f in os.listdir(folder):
            f_no_ext = f
            for ext in ROM_EXTENSIONS:
                if f.lower().endswith(ext):
                    f_no_ext = f[:-len(ext)]
                    break
            # Compare normalized names
            if f_no_ext.lower() == name_no_ext.lower():
                return True, os.path.join(folder, f)

    return False, None


def snapshot_folder_files(folder: str) -> dict:
    """Capture l'etat des fichiers avant un telechargement."""
    snapshot = {}
    folder_path = Path(folder)
    if not folder_path.exists():
        return snapshot

    for file_path in folder_path.glob('*'):
        if not file_path.is_file():
            continue
        try:
            stat = file_path.stat()
            snapshot[str(file_path.resolve())] = (stat.st_mtime_ns, stat.st_size)
        except Exception:
            continue

    return snapshot


def resolve_downloaded_file_path(dest_path: str, folder: str, before_snapshot: dict) -> str:
    """Retrouve le fichier reel ecrit, meme si le serveur impose un nom different."""
    expected = Path(dest_path)
    if expected.exists():
        return str(expected)

    folder_path = Path(folder)
    if not folder_path.exists():
        return ''

    changed_files = []
    for file_path in folder_path.glob('*'):
        if not file_path.is_file():
            continue
        try:
            resolved = str(file_path.resolve())
            stat = file_path.stat()
            state = (stat.st_mtime_ns, stat.st_size)
        except Exception:
            continue
        if before_snapshot.get(resolved) != state:
            changed_files.append((state[0], str(file_path)))

    if not changed_files:
        return ''

    changed_files.sort(reverse=True)
    return changed_files[0][1]


def expected_game_md5_values(game_info: dict) -> set:
    """Retourne les MD5 attendus par le DAT pour ce jeu."""
    expected = set()
    for rom_info in game_info.get('roms', []):
        md5_value = normalize_checksum(rom_info.get('md5', ''), 'md5')
        if md5_value:
            expected.add(md5_value)
    return expected


def cleanup_invalid_download(path: str):
    """Supprime un telechargement qui ne correspond pas au MD5 du DAT."""
    if not path:
        return
    try:
        file_path = Path(path)
        if file_path.exists() and file_path.is_file():
            file_path.unlink()
    except Exception:
        pass


def cleanup_failed_download_outputs(dest_path: str, folder: str, before_snapshot: dict):
    """Supprime les sorties creees ou modifiees par une tentative ratee."""
    candidates = set()
    resolved_dest = resolve_downloaded_file_path(dest_path, folder, before_snapshot)
    if resolved_dest:
        candidates.add(resolved_dest)
    if dest_path:
        candidates.add(dest_path)

    for candidate in candidates:
        cleanup_invalid_download(candidate)


def verify_downloaded_md5(game_info: dict, downloaded_path: str) -> tuple[bool, str]:
    """
    Verifie le MD5 du fichier telecharge contre le DAT.
    Pour un ZIP, on verifie les entrees internes, car les DAT No-Intro
    reference souvent la ROM contenue plutot que le conteneur ZIP.
    """
    expected_md5 = expected_game_md5_values(game_info)
    if not expected_md5:
        return True, "MD5 DAT absent: validation MD5 ignoree"

    if not downloaded_path or not os.path.exists(downloaded_path):
        return False, "Validation MD5 impossible: fichier telecharge introuvable"

    file_path = Path(downloaded_path)
    suffix = file_path.suffix.lower()

    if suffix in {'.zip', '.7z', '.rar'}:
        try:
            for archive_entry in iter_archive_member_signatures(file_path):
                if archive_entry.get('md5') in expected_md5:
                    return True, f"MD5 OK: {archive_entry.get('member') or archive_entry.get('name')}"
            return False, f"MD5 KO: aucune entree {suffix} ne correspond au DAT"
        except Exception as e:
            return False, f"MD5 KO: archive {suffix} illisible ou non verifiable ({e})"

    try:
        signatures = hash_file_signatures(file_path)
    except Exception as e:
        return False, f"MD5 KO: impossible de lire le fichier ({e})"

    actual_md5 = signatures.get('md5', '')
    if actual_md5 in expected_md5:
        return True, f"MD5 OK: {actual_md5}"

    expected_display = ', '.join(sorted(expected_md5))
    return False, f"MD5 KO: {actual_md5 or 'absent'} != {expected_display}"


DOWNLOAD_RESOLUTION_KEYS = {
    'download_filename',
    'download_url',
    'torrent_url',
    'torrent_target_filename',
    'source',
    'database_host',
    'page_url',
    'archive_org_identifier',
    'archive_org_filename',
    'archive_org_md5',
    'archive_org_crc',
    'archive_org_sha1',
    'archive_org_checksum_type',
    'downloaded_path',
    'attempted_sources',
}


def clean_download_resolution(game_info: dict) -> dict:
    """Copie un jeu DAT sans les champs de provider deja resolus."""
    cleaned = game_info.copy()
    for key in DOWNLOAD_RESOLUTION_KEYS:
        cleaned.pop(key, None)
    return cleaned


def resolve_next_provider(game_info: dict, sources: list, session: requests.Session, system_name: str,
                          dat_profile: dict | None, attempted_sources: list[str]) -> dict | None:
    """Retrouve un provider alternatif pour le meme jeu en excluant ceux deja testes."""
    retry_game = clean_download_resolution(game_info)
    found, _not_available = search_all_sources(
        [retry_game],
        sources,
        session,
        system_name,
        dat_profile,
        excluded_sources={normalize_source_label(source) for source in attempted_sources}
    )
    return found[0] if found else None


def attempt_download_from_resolved_provider(game_info: dict, output_folder: str, sources: list,
                                            session: requests.Session, myrient_url: str = '',
                                            progress_callback=None, log_func=print) -> tuple[bool, str]:
    """Telecharge une resolution provider deja choisie, puis valide son MD5 DAT."""
    source = game_info.get('source', 'unknown')
    filename = game_info.get('download_filename', game_info.get('game_name', ''))
    dest_path = os.path.join(output_folder, filename)
    download_url = game_info.get('download_url')
    torrent_url = game_info.get('torrent_url')
    before_download = snapshot_folder_files(output_folder)
    success = False

    if source == 'archive_org':
        identifier = game_info.get('archive_org_identifier', '')
        if identifier and filename:
            success = download_from_archive_org(identifier, filename, dest_path, progress_callback)

    elif source == 'EdgeEmu' and download_url:
        success = download_file(download_url, dest_path, session, progress_callback)

    elif source == 'PlanetEmu':
        page_url = game_info.get('page_url')
        if page_url:
            success = download_planetemu(page_url, dest_path, session, progress_callback)

    elif source == 'LoLROMs' and download_url:
        success = download_file(download_url, dest_path, get_lolroms_session(), progress_callback)

    elif source == 'CDRomance':
        page_url = game_info.get('page_url')
        if page_url:
            success = download_cdromance(page_url, dest_path, get_cdromance_session(), progress_callback)

    elif source == 'Vimm\'s Lair':
        page_url = game_info.get('page_url')
        if page_url:
            success = download_vimm(page_url, dest_path, get_vimm_session(), progress_callback)

    elif source == 'RetroGameSets' and download_url:
        if is_1fichier_url(download_url):
            success = download_from_premium_source('1fichier', download_url, dest_path, load_api_keys(), progress_callback)
        else:
            log_func(f"  URL: {download_url[:80]}...")
            success = download_file(download_url, dest_path, session, progress_callback)

    elif source.startswith('Minerva') and torrent_url:
        log_func(f"  Torrent: {torrent_url[:80]}...")
        torrent_target = game_info.get('torrent_target_filename') or filename
        success = download_from_minerva_torrent(torrent_url, torrent_target, dest_path, progress_callback)

    elif source in ['myrient', 'Myrient', 'Myrient No-Intro', 'Myrient Redump', 'Myrient TOSEC', 'Source Custom'] and download_url:
        log_func(f"  URL: {download_url[:80]}...")
        success = download_file(download_url, dest_path, session, progress_callback)

    elif source == 'database' and download_url:
        log_func(f"  URL: {download_url[:80]}...")
        if '1fichier.com' in download_url:
            success = download_from_premium_source('1fichier', download_url, dest_path, load_api_keys(), progress_callback)
        elif 'myrient' in download_url:
            log_func("  URL Myrient ignoree (source fermee)")
            success = False
        else:
            success = download_file(download_url, dest_path, session, progress_callback)

    else:
        source_info = next((item for item in sources if item['name'] == source), None)
        base_url = source_info['base_url'] if source_info else myrient_url
        if base_url:
            download_url = f"{base_url.rstrip('/')}/{quote(filename)}"
            log_func(f"  URL: {download_url[:80]}...")
            success = download_file(download_url, dest_path, session, progress_callback)

    downloaded_path = ''
    if success:
        downloaded_path = resolve_downloaded_file_path(dest_path, output_folder, before_download)
        md5_ok, md5_message = verify_downloaded_md5(game_info, downloaded_path)
        log_func(f"  {md5_message}")
        if not md5_ok:
            cleanup_invalid_download(downloaded_path)
            success = False
    else:
        cleanup_failed_download_outputs(dest_path, output_folder, before_download)

    return success, downloaded_path


def download_with_provider_retries(game_info: dict, sources: list, session: requests.Session,
                                   system_name: str, dat_profile: dict | None, output_folder: str,
                                   myrient_url: str = '', dry_run: bool = False,
                                   progress_callback=None, log_func=print,
                                   is_running=lambda: True) -> tuple[str, dict]:
    """Essaie les providers un par un jusqu'a obtenir un fichier valide MD5 DAT."""
    original_game = clean_download_resolution(game_info)
    current_game = game_info.copy()
    attempted_sources = []
    attempted_source_labels = set()

    while current_game and is_running():
        source = current_game.get('source', 'unknown')
        source_label = normalize_source_label(source)
        if source_label in attempted_source_labels:
            log_func(f"  Provider deja teste: {source}")
            break
        attempted_source_labels.add(source_label)
        filename = current_game.get('download_filename', current_game.get('game_name', ''))
        attempted_sources.append(source)
        log_func(f"  Provider: {source}")

        if dry_run:
            if current_game.get('torrent_url'):
                log_func(f"  Serait telecharge via torrent Minerva vers: {output_folder}")
            else:
                log_func(f"  Serait telecharge vers: {output_folder}")
            item_copy = current_game.copy()
            item_copy['attempted_sources'] = attempted_sources.copy()
            return 'dry_run', item_copy

        exists, existing_path = file_exists_in_folder(output_folder, filename)
        if exists:
            md5_ok, md5_message = verify_downloaded_md5(current_game, existing_path)
            log_func(f"  Fichier existant: {os.path.basename(existing_path)}")
            log_func(f"  {md5_message}")
            if md5_ok:
                item_copy = current_game.copy()
                item_copy['downloaded_path'] = existing_path
                item_copy['attempted_sources'] = attempted_sources.copy()
                return 'skipped', item_copy
            cleanup_invalid_download(existing_path)
            log_func("  Fichier existant supprime: MD5 incorrect")

        success, downloaded_path = attempt_download_from_resolved_provider(
            current_game,
            output_folder,
            sources,
            session,
            myrient_url,
            progress_callback,
            log_func
        )
        if success:
            item_copy = current_game.copy()
            item_copy['downloaded_path'] = downloaded_path
            item_copy['attempted_sources'] = attempted_sources.copy()
            return 'downloaded', item_copy

        log_func(f"  Provider {source} invalide ou en echec, recherche d'un autre provider...")
        current_game = resolve_next_provider(
            original_game,
            sources,
            session,
            system_name,
            dat_profile,
            attempted_sources
        )
        if current_game:
            log_func(f"  Retry avec: {current_game.get('source', 'unknown')}")

    item_copy = (current_game or game_info).copy()
    item_copy['attempted_sources'] = attempted_sources.copy()
    return ('stopped' if not is_running() else 'failed'), item_copy


def download_missing_games_sequentially(
    missing_games: list,
    sources: list,
    session: requests.Session,
    system_name: str,
    dat_profile: dict | None,
    output_folder: str,
    myrient_url: str = '',
    dry_run: bool = False,
    limit: int | None = None,
    progress_callback=None,
    log_func=print,
    status_callback=None,
    is_running=lambda: True,
    parallel_downloads: int = 1
) -> dict:
    """
    Traite les jeux un par un: resolution DDL, telechargement, validation MD5,
    fallback provider, puis passage au jeu suivant.
    """
    resolved_items = []
    downloaded_items = []
    failed_items = []
    skipped_items = []
    not_available = []
    downloaded = 0
    failed = 0
    skipped = 0
    handled = 0
    parallel_downloads = max(1, int(parallel_downloads or 1))

    total = len(missing_games)
    if parallel_downloads > 1 and not dry_run:
        log_lock = threading.Lock()

        def safe_log(message=""):
            with log_lock:
                log_func(message)

        def worker_download(first_resolution: dict) -> tuple[str, dict]:
            worker_session = create_download_session()
            return download_with_provider_retries(
                first_resolution,
                sources,
                worker_session,
                system_name,
                dat_profile,
                output_folder,
                myrient_url,
                dry_run,
                None,
                safe_log,
                is_running=is_running
            )

        futures = {}
        max_workers = min(parallel_downloads, limit or total)
        log_func(f"Telechargements paralleles: {max_workers}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            for index, original_game in enumerate(missing_games, 1):
                if not is_running():
                    log_func("Arrete par l'utilisateur.")
                    break

                if limit and handled >= limit:
                    log_func(f"\nLimite atteinte ({limit} jeu(x) traite(s)).")
                    break

                game_name = original_game.get('game_name', 'Jeu inconnu')
                log_func(f"\n[{index}/{total}] Recherche: {game_name}")
                if status_callback:
                    status_callback(f"Recherche {index}/{total}: {game_name[:60]}")

                found, unavailable = search_all_sources(
                    [clean_download_resolution(original_game)],
                    sources,
                    session,
                    system_name,
                    dat_profile
                )

                handled += 1
                if not found:
                    log_func("  Aucun provider disponible")
                    not_available.append((unavailable[0] if unavailable else original_game).copy())
                    continue

                first_resolution = found[0]
                resolved_items.append(first_resolution.copy())
                log_func(f"  Soumis: {game_name} [{first_resolution.get('source', 'unknown')}]")
                future = executor.submit(worker_download, first_resolution)
                futures[future] = game_name

            for future in concurrent.futures.as_completed(futures):
                game_name = futures[future]
                if status_callback:
                    status_callback(f"Validation: {game_name[:60]}")
                try:
                    status, result_item = future.result()
                except Exception as e:
                    status = 'failed'
                    result_item = {'game_name': game_name, 'error': str(e)}

                if status == 'downloaded':
                    safe_log(f"  Telecharge: {result_item.get('download_filename', game_name)}")
                    downloaded += 1
                    downloaded_items.append(result_item.copy())
                elif status == 'skipped':
                    skipped += 1
                    skipped_items.append(result_item.copy())
                elif status == 'stopped':
                    safe_log("Arrete par l'utilisateur.")
                    break
                else:
                    safe_log(f"  Echec du telechargement: {game_name}")
                    failed += 1
                    failed_items.append(result_item.copy())

        return {
            'resolved_items': resolved_items,
            'downloaded_items': downloaded_items,
            'failed_items': failed_items,
            'skipped_items': skipped_items,
            'not_available': not_available,
            'downloaded': downloaded,
            'failed': failed,
            'skipped': skipped,
        }

    for index, original_game in enumerate(missing_games, 1):
        if not is_running():
            log_func("Arrete par l'utilisateur.")
            break

        if limit and handled >= limit:
            log_func(f"\nLimite atteinte ({limit} jeu(x) traite(s)).")
            break

        game_name = original_game.get('game_name', 'Jeu inconnu')
        log_func(f"\n[{index}/{total}] {game_name}")
        if status_callback:
            status_callback(f"Recherche {index}/{total}: {game_name[:60]}")

        found, unavailable = search_all_sources(
            [clean_download_resolution(original_game)],
            sources,
            session,
            system_name,
            dat_profile
        )

        if not found:
            log_func("  Aucun provider disponible")
            not_available.append((unavailable[0] if unavailable else original_game).copy())
            handled += 1
            continue

        first_resolution = found[0]
        log_func(f"  Provider initial: {first_resolution.get('source', 'unknown')}")
        if status_callback:
            status_callback(f"Telechargement {index}/{total}: {game_name[:60]}")

        status, result_item = download_with_provider_retries(
            first_resolution,
            sources,
            session,
            system_name,
            dat_profile,
            output_folder,
            myrient_url,
            dry_run,
            progress_callback,
            log_func,
            is_running=is_running
        )

        if status == 'downloaded':
            log_func(f"  Telecharge: {result_item.get('download_filename', game_name)}")
            downloaded += 1
            downloaded_items.append(result_item.copy())
            resolved_items.append(result_item.copy())
            time.sleep(0.5)
        elif status == 'skipped':
            skipped += 1
            skipped_items.append(result_item.copy())
            resolved_items.append(result_item.copy())
        elif status == 'dry_run':
            resolved_items.append(result_item.copy())
            handled += 1
        elif status == 'stopped':
            log_func("Arrete par l'utilisateur.")
            break
        else:
            log_func("  Echec du telechargement")
            failed += 1
            failed_items.append(result_item.copy())
            handled += 1
            continue

        if status in {'downloaded', 'skipped'}:
            handled += 1

    return {
        'resolved_items': resolved_items,
        'downloaded_items': downloaded_items,
        'failed_items': failed_items,
        'skipped_items': skipped_items,
        'not_available': not_available,
        'downloaded': downloaded,
        'failed': failed,
        'skipped': skipped,
    }


def build_custom_source(source_url: str) -> dict:
    """Détecte et construit une source personnalisée Minerva ou legacy."""
    normalized_url = (source_url or '').strip()
    lower_url = normalized_url.lower()

    if 'minerva-archive.org/browse/' in lower_url:
        if '/browse/no-intro' in lower_url:
            fixed_directory = '/browse/no-intro/' in lower_url and not lower_url.endswith('/browse/no-intro/')
            return {
                'name': 'Minerva Custom',
                'base_url': normalized_url if normalized_url.endswith('/') else normalized_url + '/',
                'type': 'minerva',
                'enabled': True,
                'description': 'Source personnalisée Minerva',
                'collection': 'No-Intro',
                'minerva_path_mode': 'single',
                'scan_depth': 0,
                'fixed_directory': fixed_directory,
                'torrent_scope': 'system',
                'priority': 0
            }
        if '/browse/redump' in lower_url:
            fixed_directory = '/browse/redump/' in lower_url and not lower_url.endswith('/browse/redump/')
            return {
                'name': 'Minerva Custom',
                'base_url': normalized_url if normalized_url.endswith('/') else normalized_url + '/',
                'type': 'minerva',
                'enabled': True,
                'description': 'Source personnalisée Minerva',
                'collection': 'Redump',
                'minerva_path_mode': 'single',
                'scan_depth': 0,
                'fixed_directory': fixed_directory,
                'torrent_scope': 'system',
                'priority': 0
            }
        if '/browse/tosec' in lower_url:
            fixed_directory = '/browse/tosec/' in lower_url and not lower_url.endswith('/browse/tosec/')
            return {
                'name': 'Minerva Custom',
                'base_url': normalized_url if normalized_url.endswith('/') else normalized_url + '/',
                'type': 'minerva',
                'enabled': True,
                'description': 'Source personnalisée Minerva',
                'collection': 'TOSEC',
                'minerva_path_mode': 'split',
                'scan_depth': 2,
                'fixed_directory': fixed_directory,
                'torrent_scope': 'vendor',
                'priority': 0
            }

    return {
        'name': 'Source Custom',
        'base_url': normalized_url,
        'type': 'myrient',
        'enabled': True,
        'priority': 0
    }


def run_download_legacy(dat_file, rom_folder, myrient_url, output_folder, dry_run, limit, move_to_tosort=False, custom_sources=None):
    """Run the download process."""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })

    # Parse DAT
    dat_games = parse_dat_file(dat_file)

    # Scan local ROMs
    local_roms, local_roms_normalized, local_game_names, signature_index = scan_local_roms(rom_folder, dat_games)

    # Find missing games
    missing_games = find_missing_games(dat_games, local_roms, local_roms_normalized, local_game_names, signature_index)

    # Détection du système
    system_name = dat_profile.get('system_name') or detect_system_name(dat_file)
    print(f"Système détecté : {system_name}")

    print(f"DAT detecte : {describe_dat_profile(dat_profile)}")

    if not missing_games:
        print("\nAucun jeu manquant trouvé !")
    else:
        # Use custom sources if provided, otherwise use default sources
        sources = custom_sources if custom_sources else get_default_sources().copy()
        
        # If a custom source URL is provided, add it as first source
        if myrient_url and myrient_url not in [s['base_url'] for s in sources]:
            sources.insert(0, build_custom_source(myrient_url))
        
        # Search across all sources
        to_download, not_available = search_all_sources(missing_games, sources, session, system_name)

        # Display games not found
        if not_available:
            print("\n" + "=" * 60)
            print("Jeux NON trouvés sur aucune source:")
            print("=" * 60)
            for game_info in not_available:
                print(f"  - {game_info['game_name']}")
            print()

        if to_download:
            # Download
            print(f"\n{'Téléchargement' if not dry_run else 'Simulation'} de {len(to_download)} jeu(x)...")

            downloaded = 0
            failed = 0
            skipped = 0

            for i, game_info in enumerate(to_download, 1):
                game_name = game_info['game_name']
                source = game_info.get('source', 'unknown')

                print(f"\n[{i}/{len(to_download)}] {game_name} [{source}]")

                if limit and downloaded >= limit:
                    print("  Ignoré (limite atteinte)")
                    skipped += 1
                    continue

                # Check if file already exists (with better duplicate detection)
                exists, existing_path = file_exists_in_folder(output_folder, filename)
                if exists:
                    print(f"  Déjà présent: {os.path.basename(existing_path)}")
                    skipped += 1
                    continue

                if dry_run:
                    print(f"  Serait téléchargé vers: {output_folder}")
                    continue

                # Download based on source
                dest_path = os.path.join(output_folder, filename)
                success = False
                
                # Get download URL
                download_url = game_info.get('download_url')
                torrent_url = game_info.get('torrent_url')
                
                if source == 'archive_org':
                    identifier = game_info.get('archive_org_identifier', '')
                    if identifier and filename:
                        success = download_from_archive_org(identifier, filename, dest_path)

                elif source == 'EdgeEmu':
                    success = download_file(download_url, dest_path, session)

                elif source == 'PlanetEmu':
                    page_url = game_info.get('page_url')
                    if page_url:
                        success = download_planetemu(page_url, dest_path, session)

                elif source == 'LoLROMs' and download_url:
                    success = download_file(download_url, dest_path, get_lolroms_session())

                elif source == 'CDRomance':
                    page_url = game_info.get('page_url')
                    if page_url:
                        success = download_cdromance(page_url, dest_path, get_cdromance_session())

                elif source == 'Vimm\'s Lair':
                    page_url = game_info.get('page_url')
                    if page_url:
                        success = download_vimm(page_url, dest_path, get_vimm_session())

                elif source == 'RetroGameSets' and download_url:
                    api_keys = load_api_keys()
                    success = download_from_premium_source('1fichier', download_url, dest_path, api_keys)

                elif source.startswith('Minerva') and torrent_url:
                    print(f"  Torrent: {torrent_url[:80]}...")
                    success = download_from_minerva_torrent(torrent_url, filename, dest_path)

                elif source in ['myrient', 'Myrient', 'Myrient No-Intro', 'Myrient Redump', 'Myrient TOSEC', 'Myrient Custom'] and download_url:
                    # Télécharger depuis Myrient
                    print(f"  URL: {download_url[:80]}...")
                    success = download_file(download_url, dest_path, session)

                elif source == 'database' and download_url:
                    # URL directe depuis la base de données
                    print(f"  URL: {download_url[:80]}...")

                    # Vérifier si c'est un lien 1fichier
                    if '1fichier.com' in download_url:
                        api_keys = load_api_keys()
                        success = download_from_premium_source('1fichier', download_url, dest_path, api_keys)
                    elif 'archive.org' in download_url:
                        # Télécharger depuis archive.org
                        success = download_file(download_url, dest_path, session)
                    elif 'myrient' in download_url:
                        # Télécharger depuis Myrient
                        success = download_file(download_url, dest_path, session)
                    else:
                        # URL générique
                        success = download_file(download_url, dest_path, session)

                else:
                    # Get base URL for the source
                    source_info = next((s for s in sources if s['name'] == source), None)
                    base_url = source_info['base_url'] if source_info else myrient_url
                    download_url = f"{base_url.rstrip('/')}/{quote(filename)}"
                    print(f"  URL: {download_url[:80]}...")
                    success = download_file(download_url, dest_path, session)

                if success:
                    print(f"  Téléchargé: {filename}")
                    downloaded += 1
                    time.sleep(0.5)
                else:
                    failed += 1

            # Summary
            print("\n" + "=" * 60)
            print("Résumé:")
            print(f"  Téléchargés: {downloaded}")
            print(f"  Échecs: {failed}")
            print(f"  Ignorés: {skipped}")
            if dry_run:
                print("\n(Simulation - aucun fichier téléchargé)")

    # Move files not in DAT to ToSort
    if move_to_tosort and missing_games:
        print("\n" + "=" * 60)
        print("Recherche des fichiers à déplacer vers ToSort...")
        print("=" * 60)
        
        # Determine ToSort folder (in parent of rom_folder)
        tosort_folder = os.path.join(rom_folder, "ToSort")
        
        files_to_move = find_roms_not_in_dat(dat_games, local_roms, local_roms_normalized, rom_folder)
        
        if files_to_move:
            print(f"\n{len(files_to_move)} fichiers à déplacer vers: {tosort_folder}")
            moved, failed = move_files_to_tosort(files_to_move, rom_folder, tosort_folder, dry_run)
            print(f"\nRésumé ToSort:")
            print(f"  Déplacés: {moved}")
            print(f"  Échecs: {failed}")
        else:
            print("\nAucun fichier à déplacer.")


def run_download(dat_file, rom_folder, myrient_url, output_folder, dry_run, limit,
                 move_to_tosort=False, clean_torrentzip=False, custom_sources=None,
                 parallel_downloads: int | None = None):
    """Run the download process with archive.org as the final fallback."""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })

    dat_games = parse_dat_file(dat_file)
    local_roms, local_roms_normalized, local_game_names, signature_index = scan_local_roms(rom_folder, dat_games)
    missing_games = find_missing_games(dat_games, local_roms, local_roms_normalized, local_game_names, signature_index)
    dat_profile = finalize_dat_profile(detect_dat_profile(dat_file))
    report_active_sources = []
    to_download = []
    not_available = []
    downloaded_items = []
    failed_items = []
    skipped_items = []
    tosort_moved = 0
    tosort_failed = 0
    torrentzip_summary = {'repacked': 0, 'skipped': 0, 'failed': 0, 'deleted': 0}

    system_name = dat_profile.get('system_name') or detect_system_name(dat_file)
    print(f"SystÃ¨me dÃ©tectÃ© : {system_name}")

    if not missing_games:
        print("\nAucun jeu manquant trouvÃ© !")
    else:
        sources = [source.copy() for source in (custom_sources if custom_sources else get_default_sources())]

        if myrient_url and myrient_url not in [s['base_url'] for s in sources]:
            sources.insert(0, build_custom_source(myrient_url))

        sources = prepare_sources_for_profile(sources, dat_profile)
        report_active_sources = [source['name'] for source in sources if source.get('enabled', True)]

        if parallel_downloads is None:
            parallel_downloads = int(os.environ.get('ROM_DOWNLOADER_PARALLEL_DOWNLOADS', DEFAULT_PARALLEL_DOWNLOADS))

        result = download_missing_games_sequentially(
            missing_games,
            sources,
            session,
            system_name,
            dat_profile,
            output_folder,
            myrient_url,
            dry_run,
            limit,
            None,
            print,
            parallel_downloads=parallel_downloads
        )
        to_download = result['resolved_items']
        not_available = result['not_available']
        downloaded_items = result['downloaded_items']
        failed_items = result['failed_items']
        skipped_items = result['skipped_items']

        if not_available:
            print("\n" + "=" * 60)
            print("Jeux NON trouvÃ©s sur aucune source:")
            print("=" * 60)
            for game_info in not_available:
                print(f"  - {game_info['game_name']}")
            print()

        if False and to_download:
            print(f"\n{'TÃ©lÃ©chargement' if not dry_run else 'Simulation'} de {len(to_download)} jeu(x)...")

            downloaded = 0
            failed = 0
            skipped = 0

            for i, game_info in enumerate(to_download, 1):
                game_name = game_info['game_name']
                source = game_info.get('source', 'unknown')
                filename = game_info.get('download_filename', game_name)

                print(f"\n[{i}/{len(to_download)}] {game_name} [{source}]")

                if limit and downloaded >= limit:
                    print("  IgnorÃ© (limite atteinte)")
                    skipped += 1
                    skipped_items.append(game_info.copy())
                    continue

                status, result_item = download_with_provider_retries(
                    game_info,
                    sources,
                    session,
                    system_name,
                    dat_profile,
                    output_folder,
                    myrient_url,
                    dry_run,
                    None,
                    print
                )

                if status == 'downloaded':
                    print(f"  Telecharge: {result_item.get('download_filename', game_name)}")
                    downloaded += 1
                    downloaded_items.append(result_item.copy())
                    time.sleep(0.5)
                elif status == 'skipped':
                    skipped += 1
                    skipped_items.append(result_item.copy())
                elif status == 'dry_run':
                    pass
                else:
                    failed += 1
                    failed_items.append(result_item.copy())
                continue

            print("\n" + "=" * 60)
            print("RÃ©sumÃ©:")
            print(f"  TÃ©lÃ©chargÃ©s: {downloaded}")
            print(f"  Ã‰checs: {failed}")
            print(f"  IgnorÃ©s: {skipped}")
            if dry_run:
                print("\n(Simulation - aucun fichier tÃ©lÃ©chargÃ©)")

    if missing_games:
        print("\n" + "=" * 60)
        print("Resume:")
        print(f"  Telecharges: {result['downloaded']}")
        print(f"  Echecs: {result['failed']}")
        print(f"  Ignores: {result['skipped']}")
        print(f"  Non trouves: {len(not_available)}")
        if dry_run:
            print("\n(Simulation - aucun fichier telecharge)")

    if move_to_tosort:
        print("\n" + "=" * 60)
        print("Recherche des fichiers Ã  dÃ©placer vers ToSort...")
        print("=" * 60)

        tosort_folder = os.path.join(rom_folder, "ToSort")

        files_to_move = find_roms_not_in_dat(dat_games, local_roms, local_roms_normalized, rom_folder)

        if files_to_move:
            print(f"\n{len(files_to_move)} fichiers Ã  dÃ©placer vers: {tosort_folder}")
            moved, failed = move_files_to_tosort(files_to_move, rom_folder, tosort_folder, dry_run)
            tosort_moved = moved
            tosort_failed = failed
            print(f"\nRÃ©sumÃ© ToSort:")
            print(f"  DÃ©placÃ©s: {moved}")
            print(f"  Ã‰checs: {failed}")
        else:
            print("\nAucun fichier Ã  dÃ©placer.")

    if clean_torrentzip:
        print("\n" + "=" * 60)
        print("Nettoyage des archives validees en ZIP TorrentZip/RomVault...")
        print("=" * 60)
        torrentzip_summary = repack_verified_archives_to_torrentzip(
            dat_games,
            output_folder,
            dry_run,
            print
        )

    report_path = write_download_report(output_folder, {
        'dat_file': dat_file,
        'system_name': system_name,
        'dat_profile': describe_dat_profile(dat_profile),
        'output_folder': output_folder,
        'source_url': myrient_url,
        'active_sources': report_active_sources,
        'total_dat_games': len(dat_games),
        'missing_before': len(missing_games),
        'resolved_items': to_download,
        'downloaded_items': downloaded_items,
        'failed_items': failed_items,
        'skipped_items': skipped_items,
        'not_available': not_available,
        'tosort_moved': tosort_moved,
        'tosort_failed': tosort_failed,
        'torrentzip_repacked': torrentzip_summary.get('repacked', 0),
        'torrentzip_skipped': torrentzip_summary.get('skipped', 0),
        'torrentzip_deleted': torrentzip_summary.get('deleted', 0),
        'torrentzip_failed': torrentzip_summary.get('failed', 0),
    })
    return report_path


def cli_mode(args):
    """Run in command-line mode."""
    output_folder = args.output if args.output else args.rom_folder
    os.makedirs(output_folder, exist_ok=True)

    run_download(
        args.dat_file,
        args.rom_folder,
        args.myrient_url,
        output_folder,
        args.dry_run,
        args.limit,
        args.tosort,
        args.clean_torrentzip,
        parallel_downloads=args.parallel
    )


# ============================================================================
# Interface Graphique (GUI)
# ============================================================================

def legacy_gui_mode_unused():
    """Run in GUI mode."""
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox, scrolledtext
        import threading
        
        # Try tkinterdnd2 for drag & drop.
        tkinterdnd2 = import_optional_package('tkinterdnd2', auto_install=True)
        HAS_DND = tkinterdnd2 is not None
        
        class ROMDownloaderGUI:
            def __init__(self, root, use_dnd=False):
                self.root = root
                self.root.title("ROM Downloader")
                self.root.geometry("900x750")
                self.root.minsize(800, 650)

                self.dat_file = tk.StringVar()
                self.rom_folder = tk.StringVar()
                self.myrient_url = tk.StringVar()
                self.clean_torrentzip_var = tk.BooleanVar(value=False)
                self.running = False
                self.session = requests.Session()
                self.session.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })

                self.use_dnd = use_dnd
                self.source_vars = {}  # Store checkbox variables for sources
                self.setup_ui()
                if self.use_dnd:
                    self.setup_drag_drop()

            def setup_ui(self):
                main_frame = ttk.Frame(self.root, padding="10")
                main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
                self.root.columnconfigure(0, weight=1)
                self.root.rowconfigure(0, weight=1)

                title_label = ttk.Label(main_frame, text="ROM Downloader", font=('Segoe UI', 16, 'bold'))
                title_label.grid(row=0, column=0, columnspan=3, pady=(0, 20))

                ttk.Label(main_frame, text="Fichier DAT:").grid(row=1, column=0, sticky=tk.W, pady=5)
                self.dat_entry = ttk.Entry(main_frame, textvariable=self.dat_file, width=80)
                self.dat_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=5, padx=5)
                if self.use_dnd:
                    self.dat_entry.drop_target_register(tkinterdnd2.DND_FILES)
                ttk.Button(main_frame, text="Parcourir...", command=self.browse_dat).grid(row=1, column=2, pady=5)

                ttk.Label(main_frame, text="Dossier ROMs:").grid(row=2, column=0, sticky=tk.W, pady=5)
                self.rom_entry = ttk.Entry(main_frame, textvariable=self.rom_folder, width=80)
                self.rom_entry.grid(row=2, column=1, sticky=(tk.W, tk.E), pady=5, padx=5)
                if self.use_dnd:
                    self.rom_entry.drop_target_register(tkinterdnd2.DND_FILES)
                ttk.Button(main_frame, text="Parcourir...", command=self.browse_rom).grid(row=2, column=2, pady=5)

                ttk.Label(main_frame, text="URL source (optionnel):").grid(row=3, column=0, sticky=tk.W, pady=5)
                self.url_entry = ttk.Entry(main_frame, textvariable=self.myrient_url, width=80)
                self.url_entry.grid(row=3, column=1, sticky=(tk.W, tk.E), pady=5, padx=5)
                ttk.Button(main_frame, text="Defaut GB", command=self.set_default_gb).grid(row=3, column=2, pady=5)

                # Sources section
                ttk.Separator(main_frame, orient='horizontal').grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=15)
                ttk.Label(main_frame, text="Sources de téléchargement:", font=('Segoe UI', 11, 'bold')).grid(row=5, column=0, sticky=tk.W, pady=5)
                
                sources_frame = ttk.Frame(main_frame)
                sources_frame.grid(row=6, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
                
                ttk.Label(
                    sources_frame,
                    text="Toutes les sources disponibles sont utilisees automatiquement. archive.org passe en dernier recours.",
                    wraplength=760
                ).grid(row=0, column=0, sticky=tk.W, padx=10, pady=2)
                ttk.Label(
                    sources_frame,
                    text=", ".join(source['name'] for source in get_default_sources()),
                    wraplength=760
                ).grid(row=1, column=0, sticky=tk.W, padx=10, pady=2)

                self.move_to_tosort_var = tk.BooleanVar(value=False)
                ttk.Checkbutton(main_frame, text="Deplacer les ROMs non presentes dans le DAT vers ToSort",
                               variable=self.move_to_tosort_var).grid(row=7, column=0, columnspan=3, sticky=tk.W, pady=5)
                ttk.Checkbutton(main_frame, text="Apres verification MD5, recompresser les archives en ZIP TorrentZip/RomVault",
                               variable=self.clean_torrentzip_var).grid(row=8, column=0, columnspan=3, sticky=tk.W, pady=5)

                ttk.Separator(main_frame, orient='horizontal').grid(row=9, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=20)

                ttk.Label(main_frame, text="Progression:").grid(row=10, column=0, sticky=tk.W, pady=5)
                self.progress_var = tk.DoubleVar()
                self.progress_bar = ttk.Progressbar(main_frame, variable=self.progress_var, maximum=100, mode='determinate')
                self.progress_bar.grid(row=10, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=5)

                self.status_var = tk.StringVar(value="Pret")
                ttk.Label(main_frame, textvariable=self.status_var).grid(row=11, column=0, columnspan=3, pady=5)

                ttk.Label(main_frame, text="Journal:").grid(row=12, column=0, sticky=tk.W, pady=5)
                self.log_text = scrolledtext.ScrolledText(main_frame, height=20, width=100, wrap=tk.WORD)
                self.log_text.grid(row=13, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
                main_frame.columnconfigure(1, weight=1)
                main_frame.rowconfigure(13, weight=1)

                button_frame = ttk.Frame(main_frame)
                button_frame.grid(row=14, column=0, columnspan=3, pady=10)

                self.start_button = ttk.Button(button_frame, text="Demarrer", command=self.start_download, width=15)
                self.start_button.grid(row=0, column=0, padx=5)

                self.stop_button = ttk.Button(button_frame, text="Arreter", command=self.stop_download, width=15, state=tk.DISABLED)
                self.stop_button.grid(row=0, column=1, padx=5)
                
                ttk.Button(button_frame, text="Quitter", command=self.root.quit, width=15).grid(row=0, column=2, padx=5)
            
            def setup_drag_drop(self):
                if not self.use_dnd:
                    return
                self.dat_entry.dnd_bind('<<Drop>>', self.on_dat_drop)
                self.rom_entry.dnd_bind('<<Drop>>', self.on_rom_drop)
                self.url_entry.bind('<Control-v>', self.handle_paste)
            
            def on_dat_drop(self, event):
                path = self.clean_path(event.data)
                self.dat_file.set(path)
                return event.action
            
            def on_rom_drop(self, event):
                path = self.clean_path(event.data)
                self.rom_folder.set(path)
                return event.action
            
            def clean_path(self, path: str) -> str:
                path = path.strip()
                if path.startswith('"') and path.endswith('"'):
                    path = path[1:-1]
                if path.startswith('{') and path.endswith('}'):
                    path = path[1:-1]
                if '\n' in path:
                    path = path.split('\n')[0]
                return path.strip()
            
            def handle_paste(self, event):
                self.root.after(10, lambda: self.myrient_url.set(self.myrient_url.get().strip()))
            
            def browse_dat(self):
                filename = filedialog.askopenfilename(title="Selectionner le fichier DAT", filetypes=[("DAT files", "*.dat"), ("All files", "*.*")])
                if filename:
                    self.dat_file.set(filename)
            
            def browse_rom(self):
                folder = filedialog.askdirectory(title="Selectionner le dossier des ROMs")
                if folder:
                    self.rom_folder.set(folder)
            
            def set_default_gb(self):
                self.myrient_url.set(f"{MINERVA_BROWSE_BASE}No-Intro/Nintendo%20-%20Game%20Boy/")
            
            def log(self, message: str):
                self.log_text.insert(tk.END, message + "\n")
                self.log_text.see(tk.END)
                self.root.update_idletasks()
            
            def validate_inputs(self) -> bool:
                if not self.dat_file.get():
                    messagebox.showerror("Erreur", "Veuillez selectionner un fichier DAT")
                    return False
                if not os.path.exists(self.dat_file.get()):
                    messagebox.showerror("Erreur", f"Fichier DAT introuvable: {self.dat_file.get()}")
                    return False
                if not self.rom_folder.get():
                    messagebox.showerror("Erreur", "Veuillez selectionner un dossier de ROMs")
                    return False
                if not os.path.exists(self.rom_folder.get()):
                    messagebox.showerror("Erreur", f"Dossier ROMs introuvable: {self.rom_folder.get()}")
                    return False
                return True
            
            def start_download(self):
                if not self.validate_inputs():
                    return
                self.running = True
                self.start_button.config(state=tk.DISABLED)
                self.stop_button.config(state=tk.NORMAL)
                self.progress_var.set(0)
                self.log_text.delete(1.0, tk.END)
                thread = threading.Thread(target=self.run_download)
                thread.daemon = True
                thread.start()
            
            def stop_download(self):
                self.running = False
                self.status_var.set("Arret en cours...")
            
            def run_download(self):
                try:
                    dat_path = self.dat_file.get()
                    rom_folder = self.rom_folder.get()
                    myrient_url = self.myrient_url.get()
                    output_folder = rom_folder

                    sources = [source.copy() for source in get_default_sources()]
                    
                    # Add custom URL if provided
                    if myrient_url and myrient_url not in [s['base_url'] for s in sources]:
                        sources.insert(0, build_custom_source(myrient_url))

                    self.log(f"Parsing DAT file: {dat_path}")
                    self.status_var.set("Analyse du fichier DAT...")
                    dat_games = parse_dat_file(dat_path)

                    self.log(f"Scanning ROM folder: {rom_folder}")
                    self.status_var.set("Analyse des ROMs locales...")
                    local_roms, local_roms_normalized, local_game_names, signature_index = scan_local_roms(rom_folder, dat_games)

                    self.status_var.set("Recherche des jeux manquants...")
                    missing_games = find_missing_games(dat_games, local_roms, local_roms_normalized, local_game_names, signature_index)
                    system_name = detect_system_name(dat_path)

                    if not missing_games:
                        self.log("Aucun jeu manquant trouve !")
                        self.status_var.set("Termine - Aucun jeu manquant")
                        messagebox.showinfo("Termine", "Tous les jeux du DAT sont presents localement !")
                        self.reset_ui()
                        return

                    self.log(f"{len(missing_games)} jeux manquants trouves")
                    self.log(f"Sources actives: {', '.join([s['name'] for s in sources])}")

                    # Search across all sources
                    self.status_var.set("Recherche sur les sources...")
                    to_download, not_available = search_all_sources(missing_games, sources, self.session, system_name)

                    if not_available:
                        self.log(f"\n{len(not_available)} jeux NON disponibles sur aucune source:")
                        for game in not_available[:20]:
                            self.log(f"  - {game['game_name']}")
                        if len(not_available) > 20:
                            self.log(f"  ... et {len(not_available) - 20} autres")

                    if not to_download:
                        self.status_var.set("Aucun jeu trouve")
                        messagebox.showwarning("Attention", "Aucun jeu manquant n'a ete trouve sur les sources.")
                        self.reset_ui()
                        return

                    self.log(f"\nTelechargement de {len(to_download)} jeu(x)...")
                    downloaded = 0
                    failed = 0
                    skipped = 0

                    for i, game_info in enumerate(to_download, 1):
                        if not self.running:
                            self.log("Arrete par l'utilisateur")
                            break

                        game_name = game_info['game_name']
                        source = game_info.get('source', 'unknown')
                        filename = game_info.get('download_filename', game_name)

                        self.log(f"\n[{i}/{len(to_download)}] {game_name} [{source}]")
                        self.status_var.set(f"Telechargement: {i}/{len(to_download)} - {game_name[:50]}...")

                        # Check if file already exists (with better duplicate detection)
                        exists, existing_path = file_exists_in_folder(output_folder, filename)
                        if exists:
                            self.log(f"  Deja present: {os.path.basename(existing_path)}")
                            skipped += 1
                            continue

                        def update_progress(p):
                            self.progress_var.set(p)

                        # Download based on source
                        dest_path = os.path.join(output_folder, filename)
                        success = False
                        download_url = game_info.get('download_url')
                        torrent_url = game_info.get('torrent_url')
                        
                        if source == 'archive_org':
                            identifier = game_info.get('archive_org_identifier', '')
                            if identifier and filename:
                                success = download_from_archive_org(identifier, filename, dest_path, update_progress)
                        elif source == 'EdgeEmu' and download_url:
                            success = download_file(download_url, dest_path, self.session, update_progress)
                        elif source == 'PlanetEmu':
                            page_url = game_info.get('page_url')
                            if page_url:
                                success = download_planetemu(page_url, dest_path, self.session, update_progress)
                        elif source == 'LoLROMs' and download_url:
                            success = download_file(download_url, dest_path, get_lolroms_session(), update_progress)

                        elif source == 'CDRomance':
                            page_url = game_info.get('page_url')
                            if page_url:
                                success = download_cdromance(page_url, dest_path, get_cdromance_session(), update_progress)

                        elif source == 'Vimm\'s Lair':
                            page_url = game_info.get('page_url')
                            if page_url:
                                success = download_vimm(page_url, dest_path, get_vimm_session(), update_progress)

                        elif source == 'RetroGameSets' and download_url:
                            api_keys = load_api_keys()
                            success = download_from_premium_source('1fichier', download_url, dest_path, api_keys, update_progress)

                        elif source.startswith('Minerva') and torrent_url:

                            success = download_from_minerva_torrent(torrent_url, filename, dest_path, update_progress)
                        elif source == 'database' and download_url:
                            if '1fichier.com' in download_url:
                                api_keys = load_api_keys()
                                success = download_from_premium_source('1fichier', download_url, dest_path, api_keys, update_progress)
                            elif 'myrient' in download_url:
                                self.log("  URL Myrient ignorée (source fermée)")
                                success = False
                            else:
                                success = download_file(download_url, dest_path, self.session, update_progress)
                        else:
                            source_info = next((s for s in sources if s['name'] == source), None)
                            base_url = source_info['base_url'] if source_info else myrient_url
                            if base_url:
                                download_url = f"{base_url.rstrip('/')}/{quote(filename)}"
                                success = download_file(download_url, dest_path, self.session, update_progress)
                        
                        if success:
                            self.log(f"  Telecharge: {filename}")
                            downloaded += 1
                            time.sleep(0.5)
                        else:
                            self.log("  Echec du telechargement")
                            failed += 1
                    
                    self.log("\n" + "=" * 60)
                    self.log(f"Resume:")
                    self.log(f"  Telecharges: {downloaded}")
                    self.log(f"  Echecs: {failed}")
                    self.log(f"  Ignores: {skipped}")

                    # Move files not in DAT to ToSort if checkbox is checked
                    if self.move_to_tosort_var.get():
                        self.log("\n" + "=" * 60)
                        self.log("Recherche des fichiers a deplacer vers ToSort...")
                        tosort_folder = os.path.join(rom_folder, "ToSort")
                        
                        files_to_move = find_roms_not_in_dat(dat_games, local_roms, local_roms_normalized, rom_folder)
                        
                        if files_to_move:
                            self.log(f"{len(files_to_move)} fichiers a deplacer vers: {tosort_folder}")
                            moved, move_failed = move_files_to_tosort(files_to_move, rom_folder, tosort_folder, False)
                            self.log(f"\nResume ToSort:")
                            self.log(f"  Deplaces: {moved}")
                            self.log(f"  Echecs: {move_failed}")
                        else:
                            self.log("Aucun fichier a deplacer.")

                    if self.clean_torrentzip_var.get():
                        self.log("\nNettoyage des archives validees en ZIP TorrentZip/RomVault...")
                        repack_verified_archives_to_torrentzip(
                            dat_games,
                            rom_folder,
                            False,
                            self.log,
                            lambda message: self.status_var.set(message),
                            is_running=lambda: self.running
                        )

                    self.status_var.set(f"Termine - {downloaded} telecharge(s)")
                    messagebox.showinfo("Termine", f"Telechargement termine !\n\nTelecharges: {downloaded}\nEchecs: {failed}\nIgnores: {skipped}")
                    
                except Exception as e:
                    self.log(f"ERREUR: {e}")
                    self.status_var.set("Erreur")
                    messagebox.showerror("Erreur", f"Une erreur est survenue:\n{e}")
                
                finally:
                    self.reset_ui()
            
            def reset_ui(self):
                self.running = False
                self.start_button.config(state=tk.NORMAL)
                self.stop_button.config(state=tk.DISABLED)
                self.progress_var.set(0)
        
        # Start GUI
        if HAS_DND:
            root = tkinterdnd2.TkinterDnD.Tk()
            app = ROMDownloaderGUI(root, use_dnd=True)
        else:
            root = tk.Tk()
            app = ROMDownloaderGUI(root, use_dnd=False)
            # Show info after a short delay so window is visible
            root.after(500, lambda: messagebox.showinfo("Info", "Note: Le drag & drop n'est pas disponible.\nInstallez tkinterdnd2 pour l'activer:\n  pip install tkinterdnd2\n\nVous pouvez copier/coller les chemins avec Ctrl+V"))
        
        # Handle window close properly
        root.protocol("WM_DELETE_WINDOW", root.quit)
        root.mainloop()
        root.destroy()

    except Exception as e:
        print(f"Erreur GUI: {e}")
        print("Bascule vers le mode interactif...")
        interactive_mode()


# ============================================================================
# Point d'entrée principal
# ============================================================================

def detect_system_name(dat_file_path: str) -> str:
    """Retourne le nom de systeme normalise a partir du profil DAT."""
    return finalize_dat_profile(detect_dat_profile(dat_file_path)).get('system_name', '')


def tkinterdnd_backend_responds(timeout_seconds: int = 3) -> bool:
    """Teste tkdnd hors processus pour eviter de bloquer le demarrage GUI."""
    if os.environ.get('ROM_DOWNLOADER_DISABLE_DND', '').strip().lower() in {'1', 'true', 'yes', 'oui'}:
        return False

    probe = (
        "import tkinter as tk\n"
        "import tkinterdnd2\n"
        "root = tk.Tk()\n"
        "root.withdraw()\n"
        "tkinterdnd2.TkinterDnD._require(root)\n"
        "root.destroy()\n"
    )
    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    process = None
    try:
        process = subprocess.Popen(
            [sys.executable, '-c', probe],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags
        )
        return process.wait(timeout=timeout_seconds) == 0
    except subprocess.TimeoutExpired:
        if process is not None:
            try:
                process.kill()
            except Exception:
                pass
        return False
    except Exception:
        return False


def enable_tkinterdnd(root) -> object | None:
    """Active les methodes drop_target_register/dnd_bind sur une racine Tk."""
    if not tkinterdnd_backend_responds():
        return None
    try:
        tkinterdnd2 = import_optional_package('tkinterdnd2', auto_install=False)
        if tkinterdnd2 is None:
            return None
        tkinterdnd2.TkinterDnD._require(root)
        return tkinterdnd2
    except Exception:
        return None


def gui_mode():
    """GUI sombre inspiree de la charte Balrog Toolkit."""
    try:
        import tkinter as tk
        import tkinter.font as tkfont
        from tkinter import filedialog, messagebox, scrolledtext, ttk
        import threading

        tkinterdnd2 = None
        has_dnd = False

        class App:
            def __init__(self, root, use_dnd=False):
                self.root = root
                self.use_dnd = use_dnd
                self.font = "Roboto" if "Roboto" in tkfont.families() else "Segoe UI"
                self.session = requests.Session()
                self.session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
                self.default_sources = [source.copy() for source in get_default_sources()]
                self.source_vars = {}
                self.source_widgets = {}
                self.images = {}
                self.running = False
                self.dat_profile = finalize_dat_profile({'family': 'unknown', 'family_label': 'Inconnu', 'system_name': '', 'is_retool': False, 'retool_label': 'DAT brut'})
                self.dat_file = tk.StringVar()
                self.rom_folder = tk.StringVar()
                self.myrient_url = tk.StringVar()
                self.progress_var = tk.DoubleVar(value=0)
                self.clean_torrentzip_var = tk.BooleanVar(value=False)
                self.status_var = tk.StringVar(value="Pret a telecharger les jeux manquants")
                self.hint_var = tk.StringVar(value="Laisse vide pour essayer les DDL, puis Minerva, puis archive.org en dernier recours.")
                self.root.title("ROM Downloader")
                self.root.geometry("1040x760")
                self.root.minsize(940, 660)
                self.root.configure(bg=UI_COLOR_BG)
                self.root.columnconfigure(0, weight=1)
                self.root.rowconfigure(0, weight=1)
                self.style = ttk.Style(self.root)
                try:
                    self.style.theme_use('clam')
                except Exception:
                    pass
                self.style.configure('Balrog.Horizontal.TProgressbar', troughcolor=UI_COLOR_INPUT_BG, background=UI_COLOR_ACCENT, bordercolor=UI_COLOR_CARD_BORDER, lightcolor=UI_COLOR_ACCENT, darkcolor=UI_COLOR_ACCENT)
                try:
                    if BALROG_WINDOW_ICON.exists():
                        self.root.iconbitmap(str(BALROG_WINDOW_ICON))
                except Exception:
                    pass
                self.images['hero'] = self.load_photo(BALROG_1G1R_ICON, 16)
                self.images['folder'] = None
                self.build_ui()
                self.dat_file.trace_add('write', lambda *_: self.root.after(120, self.refresh_profile))
                if self.use_dnd:
                    self.dat_entry.drop_target_register(tkinterdnd2.DND_FILES)
                    self.rom_entry.drop_target_register(tkinterdnd2.DND_FILES)
                    self.dat_entry.dnd_bind('<<Drop>>', lambda e: self._drop(self.dat_file, e))
                    self.rom_entry.dnd_bind('<<Drop>>', lambda e: self._drop(self.rom_folder, e))
                self.url_entry.bind('<Control-v>', lambda _e: self.root.after(10, lambda: self.myrient_url.set(self.myrient_url.get().strip())))
                self.refresh_profile()
                self.root.after_idle(self.fit_window_to_content)

            def load_photo(self, path, subsample):
                if not path.exists():
                    return None
                try:
                    image = tk.PhotoImage(file=str(path))
                    return image.subsample(subsample, subsample) if subsample > 1 else image
                except Exception:
                    return None

            def fit_window_to_content(self):
                """Ajuste la taille initiale de la fenetre au contenu visible."""
                self.root.update_idletasks()

                extra_width = 48
                extra_height = 56
                target_width = max(self.root.winfo_reqwidth() + extra_width, 940)
                target_height = max(self.root.winfo_reqheight() + extra_height, 660)

                screen_width = self.root.winfo_screenwidth()
                screen_height = self.root.winfo_screenheight()

                target_width = min(target_width, max(screen_width - 80, 940))
                target_height = min(target_height, max(screen_height - 80, 660))

                self.root.geometry(f"{target_width}x{target_height}")

            def card(self, parent, row, expand=False):
                outer = tk.Frame(parent, bg=UI_COLOR_CARD_BG, highlightbackground=UI_COLOR_CARD_BORDER, highlightthickness=1)
                outer.grid(row=row, column=0, sticky='nsew' if expand else 'ew', padx=18, pady=(18 if row == 0 else 0, 12))
                inner = tk.Frame(outer, bg=UI_COLOR_CARD_BG)
                inner.pack(fill='both', expand=True, padx=16, pady=16)
                return inner

            def entry(self, parent, var):
                return tk.Entry(parent, textvariable=var, bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_TEXT_MAIN, insertbackground=UI_COLOR_TEXT_MAIN, relief='flat', bd=0, highlightthickness=1, highlightbackground=UI_COLOR_INPUT_BORDER, highlightcolor=UI_COLOR_ACCENT, font=(self.font, 11))

            def button(self, parent, text, command, kind='ghost', width=14, image=None):
                palette = {'accent': (UI_COLOR_ACCENT, UI_COLOR_ACCENT_HOVER), 'danger': (UI_COLOR_ERROR, '#c0392b'), 'ghost': (UI_COLOR_GHOST, UI_COLOR_GHOST_HOVER)}
                bg, active = palette[kind]
                btn = tk.Button(parent, text=text, command=command, bg=bg, fg=UI_COLOR_TEXT_MAIN, activebackground=active, activeforeground=UI_COLOR_TEXT_MAIN, relief='flat', bd=0, padx=14, pady=10, width=width, font=(self.font, 10, 'bold'), cursor='hand2')
                if image:
                    btn.configure(image=image, compound='left')
                return btn

            def toggle(self, parent, text, var):
                return tk.Checkbutton(parent, text=text, variable=var, bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_MAIN, activebackground=UI_COLOR_CARD_BG, activeforeground=UI_COLOR_TEXT_MAIN, selectcolor=UI_COLOR_INPUT_BG, anchor='w', font=(self.font, 10), disabledforeground=UI_COLOR_TEXT_SUB)

            def build_ui(self):
                main = tk.Frame(self.root, bg=UI_COLOR_BG)
                main.grid(row=0, column=0, sticky='nsew')
                main.columnconfigure(0, weight=1)
                main.rowconfigure(3, weight=0)

                header = self.card(main, 0)
                header.columnconfigure(1, weight=1)
                tk.Frame(header, bg=UI_COLOR_ACCENT, width=6).grid(row=0, column=0, rowspan=2, sticky='ns', padx=(0, 14))
                tk.Label(header, text="ROM Downloader", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 18, 'bold')).grid(row=0, column=1, sticky='w')
                tk.Label(header, text="Charge un DAT No-Intro ou Redump retraite avec Retool, compare le dossier cible et telecharge les ROMs manquantes en DDL, puis via Minerva, puis archive.org si besoin.", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_SUB, justify='left', wraplength=760, font=(self.font, 10)).grid(row=1, column=1, sticky='w', pady=(2, 0))
                self.family_badge = None
                self.mode_badge = None
                if self.images.get('hero'):
                    tk.Label(header, image=self.images['hero'], bg=UI_COLOR_CARD_BG).grid(row=0, column=2, rowspan=2, sticky='e')

                fields = self.card(main, 1)
                fields.columnconfigure(1, weight=1)
                field_specs = [
                    (0, "Fichier DAT", self.dat_file, self.browse_dat),
                    (1, "Dossier de sortie", self.rom_folder, self.browse_rom),
                    (2, "URL source (optionnelle)", self.myrient_url, None)
                ]
                for row, label, var, action in field_specs:
                    tk.Label(fields, text=label, bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 11, 'bold')).grid(row=row, column=0, sticky='w', pady=(0 if row == 0 else 14, 0))
                    widget = self.entry(fields, var)
                    if action:
                        widget.grid(row=row, column=1, sticky='ew', padx=(14, 12), pady=(0 if row == 0 else 14, 0), ipady=10)
                        self.button(fields, "Parcourir", action, kind='ghost', width=12).grid(row=row, column=2, sticky='e', pady=(0 if row == 0 else 14, 0))
                    else:
                        widget.grid(row=row, column=1, columnspan=2, sticky='ew', padx=(14, 0), pady=(14, 0), ipady=10)
                    if row == 0:
                        self.dat_entry = widget
                    elif row == 1:
                        self.rom_entry = widget
                    else:
                        self.url_entry = widget
                tk.Label(fields, textvariable=self.hint_var, bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_SUB, justify='left', wraplength=860, font=(self.font, 9)).grid(row=3, column=0, columnspan=3, sticky='w', pady=(10, 0))

                sources = self.card(main, 2)
                tk.Label(sources, text="Sources de telechargement", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 13, 'bold')).grid(row=0, column=0, sticky='w')
                source_names = ', '.join(source['name'] for source in self.default_sources)
                tk.Label(sources, text="Toutes les sources disponibles sont utilisees automatiquement. Les DDL passent avant Minerva, et archive.org reste le dernier recours.", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_SUB, justify='left', wraplength=880, font=(self.font, 9)).grid(row=1, column=0, sticky='w', pady=(6, 8))
                tk.Label(sources, text=source_names, bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_SUB, justify='left', wraplength=880, font=(self.font, 9)).grid(row=2, column=0, sticky='w')
                self.move_to_tosort_var = tk.BooleanVar(value=False)
                self.toggle(sources, "Deplacer les ROMs hors DAT dans un sous-dossier ToSort", self.move_to_tosort_var).grid(row=3, column=0, sticky='w', pady=(14, 0))
                self.toggle(sources, "Apres verification MD5, recompresser les archives en ZIP TorrentZip/RomVault", self.clean_torrentzip_var).grid(row=4, column=0, sticky='w', pady=(8, 0))

                progress = self.card(main, 3)
                progress.columnconfigure(0, weight=1)
                tk.Label(progress, text="Telechargement", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 13, 'bold')).grid(row=0, column=0, sticky='w')
                ttk.Progressbar(progress, variable=self.progress_var, maximum=100, mode='determinate', style='Balrog.Horizontal.TProgressbar').grid(row=1, column=0, sticky='ew', pady=(10, 8))
                tk.Label(progress, textvariable=self.status_var, bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_SUB, font=(self.font, 10), justify='left', wraplength=980).grid(row=2, column=0, sticky='w')
                actions = tk.Frame(progress, bg=UI_COLOR_CARD_BG)
                actions.grid(row=3, column=0, sticky='ew', pady=(16, 0))
                actions.columnconfigure(0, weight=1)
                self.start_button = self.button(actions, "Lancer le telechargement", self.start, kind='accent', width=24)
                self.start_button.grid(row=0, column=1, padx=(0, 10))
                self.stop_button = self.button(actions, "Arreter", self.stop, kind='danger', width=12)
                self.stop_button.grid(row=0, column=2, padx=(0, 10))
                self.stop_button.configure(state=tk.DISABLED)
                self.button(actions, "Quitter", self.root.quit, width=12).grid(row=0, column=3)

            def _drop(self, variable, event):
                variable.set(self._clean(event.data))
                return event.action

            def _clean(self, path):
                path = path.strip()
                if path.startswith('"') and path.endswith('"'):
                    path = path[1:-1]
                if path.startswith('{') and path.endswith('}'):
                    path = path[1:-1]
                return path.split('\n')[0].strip()

            def _ui(self, callback):
                if threading.current_thread() is threading.main_thread():
                    callback()
                else:
                    self.root.after(0, callback)

            def browse_dat(self):
                filename = filedialog.askopenfilename(title="Selectionner le fichier DAT", filetypes=[("DAT files", "*.dat"), ("All files", "*.*")])
                if filename:
                    self.dat_file.set(filename)

            def browse_rom(self):
                folder = filedialog.askdirectory(title="Selectionner le dossier de sortie")
                if folder:
                    self.rom_folder.set(folder)

            def auto_source(self):
                default_url = self.dat_profile.get('default_source_url', '')
                if default_url:
                    self.myrient_url.set(default_url)
                    self.status_var.set("URL Minerva renseignee depuis le DAT")
                else:
                    messagebox.showwarning("DAT", "Impossible de proposer une URL auto pour ce DAT.")

            def refresh_profile(self):
                path = self.dat_file.get().strip()
                profile = finalize_dat_profile(detect_dat_profile(path)) if path and os.path.exists(path) else finalize_dat_profile({'family': 'unknown', 'family_label': 'Inconnu', 'system_name': '', 'is_retool': False, 'retool_label': 'DAT brut'})
                self.dat_profile = profile
                self.hint_var.set("Laisse vide pour essayer les DDL, puis Minerva, puis archive.org en dernier recours." if profile.get('system_name') else "Tu peux laisser l'URL vide pour la detection automatique, ou en saisir une manuellement.")
                if self.family_badge:
                    self.family_badge.configure(text=profile.get('family_label') if profile.get('family') != 'unknown' else "Profil manuel", bg={'no-intro': UI_COLOR_ACCENT, 'redump': UI_COLOR_SUCCESS, 'tosec': UI_COLOR_WARNING}.get(profile.get('family'), UI_COLOR_WARNING))
                if self.mode_badge:
                    self.mode_badge.configure(text="Retool / 1G1R" if profile.get('is_retool') else "DAT brut", bg=UI_COLOR_SUCCESS if profile.get('is_retool') else UI_COLOR_GHOST_HOVER)

            def selected_sources(self):
                sources = []
                for source in self.default_sources:
                    item = source.copy()
                    item['enabled'] = True
                    sources.append(item)
                custom_url = self.myrient_url.get().strip()
                if custom_url and custom_url.rstrip('/').lower() not in {s.get('base_url', '').rstrip('/').lower() for s in sources if s.get('base_url')}:
                    sources.insert(0, build_custom_source(custom_url))
                return prepare_sources_for_profile(sources, self.dat_profile)

            def log(self, message):
                print(message, flush=True)

            def start(self):
                if not self.dat_file.get() or not os.path.exists(self.dat_file.get()):
                    messagebox.showerror("Erreur", "Veuillez selectionner un fichier DAT valide")
                    return
                if not self.rom_folder.get() or not os.path.exists(self.rom_folder.get()):
                    messagebox.showerror("Erreur", "Veuillez selectionner un dossier de sortie valide")
                    return
                self.running = True
                self.start_button.configure(state=tk.DISABLED)
                self.stop_button.configure(state=tk.NORMAL)
                self.progress_var.set(0)
                self.status_var.set("Preparation de l'analyse du DAT...")
                threading.Thread(target=self.run_download, daemon=True).start()

            def stop(self):
                self.running = False
                self.status_var.set("Arret en cours...")

            def run_download(self):
                try:
                    dat_path = self.dat_file.get().strip()
                    rom_folder = self.rom_folder.get().strip()
                    source_url = self.myrient_url.get().strip()
                    dat_profile = finalize_dat_profile(detect_dat_profile(dat_path))
                    system_name = dat_profile.get('system_name') or detect_system_name(dat_path)
                    sources = self.selected_sources()
                    dat_games = parse_dat_file(dat_path)
                    local_roms, local_roms_normalized, local_game_names, signature_index = scan_local_roms(rom_folder, dat_games)
                    missing_games = find_missing_games(dat_games, local_roms, local_roms_normalized, local_game_names, signature_index)
                    downloaded_items = []
                    failed_items = []
                    skipped_items = []
                    to_download = []
                    not_available = []
                    moved = move_failed = 0
                    torrentzip_summary = {'repacked': 0, 'skipped': 0, 'failed': 0, 'deleted': 0}
                    if not missing_games:
                        if self.move_to_tosort_var.get():
                            tosort_folder = os.path.join(rom_folder, "ToSort")
                            files_to_move = find_roms_not_in_dat(dat_games, local_roms, local_roms_normalized, rom_folder)
                            if files_to_move:
                                moved, move_failed = move_files_to_tosort(files_to_move, rom_folder, tosort_folder, False)
                                self.log(f"ToSort -> deplaces: {moved}, echecs: {move_failed}")
                        if self.clean_torrentzip_var.get():
                            torrentzip_summary = repack_verified_archives_to_torrentzip(
                                dat_games,
                                rom_folder,
                                False,
                                self.log,
                                lambda message: self._ui(lambda msg=message: self.status_var.set(msg)),
                                is_running=lambda: self.running
                            )
                        report_path = write_download_report(rom_folder, {
                            'dat_file': dat_path,
                            'system_name': system_name,
                            'dat_profile': describe_dat_profile(dat_profile),
                            'output_folder': rom_folder,
                            'source_url': source_url,
                            'active_sources': [s['name'] for s in sources if s.get('enabled', True)],
                            'total_dat_games': len(dat_games),
                            'missing_before': 0,
                            'resolved_items': [],
                            'downloaded_items': [],
                            'failed_items': [],
                            'skipped_items': [],
                            'not_available': [],
                            'tosort_moved': moved,
                            'tosort_failed': move_failed,
                            'torrentzip_repacked': torrentzip_summary.get('repacked', 0),
                            'torrentzip_skipped': torrentzip_summary.get('skipped', 0),
                            'torrentzip_deleted': torrentzip_summary.get('deleted', 0),
                            'torrentzip_failed': torrentzip_summary.get('failed', 0),
                        })
                        self.status_var.set("Termine - dossier deja complet")
                        self._ui(lambda path=report_path: messagebox.showinfo("Termine", f"Tous les jeux du DAT sont deja presents localement.\n\nRapport:\n{path}"))
                        return
                    self.log(f"DAT detecte: {describe_dat_profile(dat_profile)}")
                    self.log(f"Sources actives: {', '.join([s['name'] for s in sources if s.get('enabled', True)])}")
                    progress = lambda value: self._ui(lambda: self.progress_var.set(value))
                    status_callback = lambda message: self._ui(lambda msg=message: self.status_var.set(msg))
                    result = download_missing_games_sequentially(
                        missing_games,
                        sources,
                        self.session,
                        system_name,
                        dat_profile,
                        rom_folder,
                        source_url,
                        False,
                        None,
                        progress,
                        self.log,
                        status_callback,
                        is_running=lambda: self.running,
                        parallel_downloads=int(os.environ.get('ROM_DOWNLOADER_PARALLEL_DOWNLOADS', DEFAULT_PARALLEL_DOWNLOADS))
                    )
                    to_download = result['resolved_items']
                    not_available = result['not_available']
                    downloaded_items = result['downloaded_items']
                    failed_items = result['failed_items']
                    skipped_items = result['skipped_items']
                    if not_available:
                        self.log(f"{len(not_available)} jeux non disponibles:")
                        for game in not_available[:20]:
                            self.log(f"  - {game['game_name']}")
                    if not to_download and not not_available:
                        self.status_var.set("Aucun jeu trouve sur les sources")
                        self._ui(lambda: messagebox.showwarning("Attention", "Aucun jeu manquant n'a ete trouve sur les sources actives."))
                        return
                    downloaded = result['downloaded']
                    failed = result['failed']
                    skipped = result['skipped']
                    if self.move_to_tosort_var.get():
                        tosort_folder = os.path.join(rom_folder, "ToSort")
                        files_to_move = find_roms_not_in_dat(dat_games, local_roms, local_roms_normalized, rom_folder)
                        if files_to_move:
                            moved, move_failed = move_files_to_tosort(files_to_move, rom_folder, tosort_folder, False)
                            self.log(f"ToSort -> deplaces: {moved}, echecs: {move_failed}")
                    if self.clean_torrentzip_var.get():
                        torrentzip_summary = repack_verified_archives_to_torrentzip(
                            dat_games,
                            rom_folder,
                            False,
                            self.log,
                            status_callback,
                            is_running=lambda: self.running
                        )
                    report_path = write_download_report(rom_folder, {
                        'dat_file': dat_path,
                        'system_name': system_name,
                        'dat_profile': describe_dat_profile(dat_profile),
                        'output_folder': rom_folder,
                        'source_url': source_url,
                        'active_sources': [s['name'] for s in sources if s.get('enabled', True)],
                        'total_dat_games': len(dat_games),
                        'missing_before': len(missing_games),
                        'resolved_items': to_download,
                        'downloaded_items': downloaded_items,
                        'failed_items': failed_items,
                        'skipped_items': skipped_items,
                        'not_available': not_available,
                        'tosort_moved': moved,
                        'tosort_failed': move_failed,
                        'torrentzip_repacked': torrentzip_summary.get('repacked', 0),
                        'torrentzip_skipped': torrentzip_summary.get('skipped', 0),
                        'torrentzip_deleted': torrentzip_summary.get('deleted', 0),
                        'torrentzip_failed': torrentzip_summary.get('failed', 0),
                    })
                    self.status_var.set(f"Termine - {downloaded} telecharge(s)")
                    self._ui(lambda path=report_path: messagebox.showinfo("Termine", f"Telechargement termine.\n\nTelecharges: {downloaded}\nEchecs: {failed}\nIgnores: {skipped}\n\nRapport:\n{path}"))
                except Exception as e:
                    error_message = str(e)
                    self.log(f"ERREUR: {error_message}")
                    self.status_var.set("Erreur")
                    self._ui(lambda msg=error_message: messagebox.showerror("Erreur", f"Une erreur est survenue:\n{msg}"))
                finally:
                    self.running = False
                    self._ui(lambda: (self.start_button.configure(state=tk.NORMAL), self.stop_button.configure(state=tk.DISABLED), self.progress_var.set(0)))

        root = tk.Tk()
        tkinterdnd2 = enable_tkinterdnd(root)
        has_dnd = tkinterdnd2 is not None
        app = App(root, use_dnd=has_dnd)
        if not has_dnd:
            app.status_var.set("Pret - glisser-deposer indisponible, boutons Parcourir actifs")
        root.protocol("WM_DELETE_WINDOW", root.quit)
        root.mainloop()
        root.destroy()
    except Exception as e:
        error_message = f"Erreur GUI: {e}"
        log_path = APP_ROOT / "rom_downloader_gui_error.log"
        try:
            with open(log_path, "w", encoding="utf-8") as log_file:
                log_file.write(error_message + "\n")
        except Exception:
            pass
        print(error_message)
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("ROM Downloader", f"{error_message}\n\nDetail ecrit dans:\n{log_path}")
            root.destroy()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(
        description='ROM Downloader - Compare un DAT 1G1R a un dossier cible et telecharge les jeux manquants',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=r'''
Exemples:
  python rom_downloader.py --gui
  python rom_downloader.py "Dat\Nintendo - Game Boy (Retool).dat" "Roms\Game Boy"
  python rom_downloader.py "Dat\Sony - PlayStation 2 (Retool).dat" "Roms\PS2" --limit 10
  python rom_downloader.py  (mode interactif)
  python rom_downloader.py --sources  (afficher les sources disponibles)
        '''
    )
    parser.add_argument('dat_file', nargs='?', help='Chemin vers le fichier DAT')
    parser.add_argument('rom_folder', nargs='?', help='Chemin vers le dossier de sortie ou de ROMs existantes')
    parser.add_argument('myrient_url', nargs='?', help='URL source optionnelle (laisser vide pour la selection Minerva auto)')
    parser.add_argument('-o', '--output', help='Dossier de sortie (defaut: rom_folder)')
    parser.add_argument('--dry-run', action='store_true', help='Simulation sans telechargement')
    parser.add_argument('--limit', type=int, help='Limite de telechargements')
    parser.add_argument('--gui', action='store_true', help='Mode interface graphique')
    parser.add_argument('--tosort', action='store_true', help='Deplacer les ROMs non presentes dans le DAT vers un sous-dossier ToSort')
    parser.add_argument('--clean-torrentzip', action='store_true', help='Recompresser les archives validees MD5 en ZIP TorrentZip/RomVault')
    parser.add_argument('--parallel', type=int, default=DEFAULT_PARALLEL_DOWNLOADS, help=f'Nombre de telechargements simultanes (defaut: {DEFAULT_PARALLEL_DOWNLOADS})')
    parser.add_argument('--sources', action='store_true', help='Afficher les sources de telechargement')

    args = parser.parse_args()

    # Show sources
    if args.sources:
        print_sources_info()
        return

    # GUI mode
    if args.gui:
        gui_mode()
        return

    # GUI mode by default (no arguments)
    if not args.dat_file and not args.rom_folder and not args.myrient_url:
        gui_mode()
        return

    # CLI mode (dat_file and rom_folder provided)
    if args.dat_file and args.rom_folder:
        cli_mode(args)
        return

    # Partial arguments - show help
    parser.print_help()


if __name__ == '__main__':
    main()
