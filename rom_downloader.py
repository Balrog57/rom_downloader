#!/usr/bin/env python3
r"""
ROMVault Missing ROM Downloader

Compare un fichier DAT avec des ROMs locales et télécharge les manquantes depuis plusieurs sources.

Sources supportées:
    GRATUITES:
    - Myrient No-Intro
    - Myrient Redump
    - Myrient TOSEC
    - archive.org: Recherche par signature MD5
    
    PREMIUM (nécessitent une clé API):
    - 1fichier: Téléchargement via API
    - AllDebrid: Service debrid multi-hébergeurs
    - RealDebrid: Service debrid multi-hébergeurs

Usage en ligne de commande:
    python rom_downloader.py <dat_file> <rom_folder> <myrient_url> [--dry-run] [--limit N] [--tosort]

Usage interactif (sans arguments):
    python rom_downloader.py
    (Pose des questions pour les chemins)

Usage GUI (interface graphique):
    python rom_downloader.py --gui

Options:
    --dry-run         Simulation sans téléchargement
    --limit N         Limite le nombre de téléchargements
    --tosort          Déplace les ROMs non présentes dans le DAT vers le dossier ToSort
    --gui             Lance l'interface graphique
    --sources         Affiche la liste des sources de téléchargement
    --configure-api   Configure les clés API pour les services premium
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, unquote

try:
    import requests
    from bs4 import BeautifulSoup
    import internetarchive
except ImportError:
    print("Installation des packages requis (requests, beautifulsoup4, internetarchive)...")
    os.system("pip install requests beautifulsoup4 internetarchive -q")
    import requests
    from bs4 import BeautifulSoup
    import internetarchive

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

# ============================================================================
# Base de données locale des URLs (extrait de RGSX games.zip)
# 74,189 URLs - 100% autonome, ne dépend plus de RGSX
# ============================================================================

ROM_DATABASE_FILE = 'rom_database.zip'
ROM_DATABASE = None


def load_rom_database():
    """Charge la base de données des URLs en mémoire."""
    global ROM_DATABASE
    
    if ROM_DATABASE is not None:
        return ROM_DATABASE
    
    try:
        import zipfile
        # Charger la base complète
        if os.path.exists(ROM_DATABASE_FILE):
            with zipfile.ZipFile(ROM_DATABASE_FILE, 'r') as zf:
                with zf.open('rom_database.json') as f:
                    ROM_DATABASE = json.load(f)
            print(f"Base de données chargée : {ROM_DATABASE.get('total_urls', 0):,} URLs")
        else:
            print(f"ATTENTION: {ROM_DATABASE_FILE} non trouvé!")
            print("Exécutez create_rom_database.py pour créer la base puis zippez le fichier.")
            ROM_DATABASE = {'urls': [], 'sources': {}}
            
        return ROM_DATABASE
        
    except Exception as e:
        print(f"Erreur chargement base de données: {e}")
        ROM_DATABASE = {'urls': [], 'sources': {}}
        return ROM_DATABASE


def search_by_md5(md5_hash: str) -> list:
    """
    Recherche une ROM par son hash MD5.
    Note : La recherche locale par MD5 est désactivée car md5_lookup.json a été supprimé.
    Elle sera effectuée via Archive.org (fallback).
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
    
    # Recherche dans la base
    results = []
    game_normalized = game_name.lower().strip()
    
    # On parcourt les URLs de la base pour trouver une correspondance sur le nom
    # Note: C'est plus lent que le lookup mais évite le fichier de 20MB
    urls = ROM_DATABASE.get('urls', [])
    for entry in urls:
        full_name = entry.get('full_name', '').lower()
        if game_normalized in full_name:
            results.append(entry)
            if len(results) >= 50:
                break
                
    return results

# ============================================================================
# Configuration des sources de téléchargement
# ============================================================================

# Sources extraites de games.zip RGSX (74,189 URLs analysées)
# Ces sources sont utilisées indépendamment de RGSX

def get_default_sources():
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
            'name': '1fichier (API)',
            'base_url': config.get('1fichier_api_base', ''),
            'type': 'premium_api',
            'enabled': False,
            'description': 'Téléchargement via API',
            'api_key_required': True,
            'priority': 3
        },
        {
            'name': '1fichier (Gratuit)',
            'base_url': config.get('1fichier_free', ''),
            'type': 'free_host',
            'enabled': True,
            'description': 'Mode gratuit avec attente (si lien détecté)',
            'priority': 3
        },
        {
            'name': 'AllDebrid (API)',
            'base_url': config.get('alldebrid_api_base', ''),
            'type': 'debrid_api',
            'enabled': False,
            'description': 'Service debrid multi-hébergeurs',
            'api_key_required': True,
            'priority': 3
        },
        {
            'name': 'RealDebrid (API)',
            'base_url': config.get('realdebrid_api_base', ''),
            'type': 'debrid_api',
            'enabled': False,
            'description': 'Service debrid multi-hébergeurs',
            'api_key_required': True,
            'priority': 3
        }
    ]

# Mappings des systèmes pour les scrapers
# Permet de traduire le nom du système (extrait du DAT) en slug pour le site
SYSTEM_MAPPINGS = {
    'Nintendo - Game Boy': {
        'edgeemu': 'nintendo-gameboy',
        'planetemu': 'nintendo-game-boy'
    },
    'Nintendo - Game Boy Color': {
        'edgeemu': 'nintendo-gameboycolor',
        'planetemu': 'nintendo-game-boy-color'
    },
    'Nintendo - Game Boy Advance': {
        'edgeemu': 'nintendo-gba',
        'planetemu': 'nintendo-game-boy-advance'
    },
    'Nintendo - Nintendo Entertainment System': {
        'edgeemu': 'nintendo-nes',
        'planetemu': 'nintendo-entertainment-system'
    },
    'Nintendo - Super Nintendo Entertainment System': {
        'edgeemu': 'nintendo-snes',
        'planetemu': 'nintendo-super-nintendo-entertainment-system'
    },
    'Nintendo - Nintendo 64': {
        'edgeemu': 'nintendo-n64',
        'planetemu': 'nintendo-64'
    },
    'Sega - Mega Drive - Genesis': {
        'edgeemu': 'sega-genesis',
        'planetemu': 'sega-mega-drive'
    },
    'Sega - Master System - Mark III': {
        'edgeemu': 'sega-mastersystem',
        'planetemu': 'sega-master-system'
    },
    'Sega - Game Gear': {
        'edgeemu': 'sega-gamegear',
        'planetemu': 'sega-game-gear'
    },
    'NEC - PC Engine - TurboGrafx 16': {
        'edgeemu': 'nec-pcengine',
        'planetemu': 'nec-pc-engine-turbografx-16-entertainment-super-system'
    },
    'SNK - Neo Geo Pocket Color': {
        'edgeemu': 'snk-neogeopocketcolor',
        'planetemu': 'snk-neo-geo-pocket-color'
    }
}


# ============================================================================
# Configuration des clés API
# ============================================================================

API_CONFIG_FILE = 'api_keys.json'


def load_api_keys() -> dict:
    """Load API keys from configuration file."""
    default_keys = {
        '1fichier': '',
        'alldebrid': '',
        'realdebrid': ''
    }
    
    if os.path.exists(API_CONFIG_FILE):
        try:
            with open(API_CONFIG_FILE, 'r', encoding='utf-8') as f:
                keys = json.load(f)
                # Merge with defaults
                for key in default_keys:
                    if key not in keys:
                        keys[key] = default_keys[key]
                return keys
        except Exception as e:
            print(f"Erreur lors du chargement des clés API: {e}")
    
    return default_keys


def save_api_keys(keys: dict) -> bool:
    """Save API keys to configuration file."""
    try:
        with open(API_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(keys, f, indent=2)
        return True
    except Exception as e:
        print(f"Erreur lors de la sauvegarde des clés API: {e}")
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
        print("\nClés API sauvegardées avec succès!")
    else:
        print("\nErreur lors de la sauvegarde des clés API.")
    
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
    For 1fichier: tries API first, falls back to free mode if no API key.
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
        
        # Fallback to free mode
        print("  Bascule en mode gratuit (sans API key)...")
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
    # Load API keys to show status
    api_keys = load_api_keys()
    
    print("\n" + "=" * 70)
    print("SOURCES DE TÉLÉCHARGEMENT DISPONIBLES")
    print("Extrait de games.zip RGSX (74,189 URLs analysées)")
    print("=" * 70)
    
    print("\n--- Source Principale ---")
    for i, source in enumerate(get_default_sources(), 1):
        if source['type'] != 'archive_org':
            continue
        print(f"\n{i}. {source['name']}")
        print(f"   Type: {source['type']}")
        print(f"   Description: {source.get('description', 'N/A')}")
        print(f"   Priorité: {source.get('priority', 'N/A')}")
    
    print("\n--- Sources Secondaires ---")
    for i, source in enumerate(get_default_sources(), 1):
        if source['type'] != 'myrient':
            continue
        print(f"\n{i}. {source['name']}")
        print(f"   Type: {source['type']}")
        if source['base_url']:
            print(f"   URL: Masquée")
        print(f"   Description: {source.get('description', 'N/A')}")
        print(f"   Priorité: {source.get('priority', 'N/A')}")
    
    print("\n--- 1fichier ---")
    for i, source in enumerate(get_default_sources(), 1):
        if source['type'] not in ('premium_api', 'free_host'):
            continue
        
        if source.get('api_key_required', False):
            api_key = api_keys.get('1fichier', '')
            key_status = "CONFIGURÉE" if api_key else "NON CONFIGURÉE"
            print(f"\n{i}. {source['name']} [{key_status}]")
        else:
            print(f"\n{i}. {source['name']} [TOUJOURS DISPONIBLE]")
        
        print(f"   Type: {source['type']}")
        if source['base_url']:
            print(f"   URL: Masquée")
        print(f"   Description: {source.get('description', 'N/A')}")
        print(f"   Priorité: {source.get('priority', 'N/A')}")
    
    print("\n--- Services Debrid (Premium) ---")
    for i, source in enumerate(get_default_sources(), 1):
        if source['type'] != 'debrid_api':
            continue
        
        service_name = source['name'].split(' ')[0].lower()
        api_key = api_keys.get(service_name, '')
        key_status = "CONFIGURÉE" if api_key else "NON CONFIGURÉE"
        
        print(f"\n{i}. {source['name']} [{key_status}]")
        print(f"   Type: {source['type']}")
        if source['base_url']:
            print(f"   URL: {source['base_url']}")
        print(f"   Description: {source.get('description', 'N/A')}")
        print(f"   Priorité: {source.get('priority', 'N/A')}")
    
    print("\n--- Sources Supplémentaires ---")
    for i, source in enumerate(ADDITIONAL_SOURCES, 1):
        status = "ACTIVABLE" if not source.get('enabled', False) else "ACTIVE"
        print(f"\n{i}. {source['name']} [{status}]")
        print(f"   Type: {source['type']}")
        if source['base_url']:
            print(f"   URL: {source['base_url']}")
        print(f"   Description: {source.get('description', 'N/A')}")
    
    print("\n" + "=" * 70)
    print("Pour configurer les clés API premium :")
    print("  python rom_downloader.py --configure-api")
    print("=" * 70)

# ============================================================================
# Fonctions de traitement
# ============================================================================

def search_archive_org_by_md5(md5_hash: str, rom_name: str) -> dict:
    """
    Search for a ROM on archive.org using MD5 hash with multiple strategies.
    NOTE: archive.org a des limitations pour les ROMs No-Intro.
    Cette fonction est un dernier recours après Myrient.
    """
    if not md5_hash:
        return {'found': False}

    print(f"  Recherche archive.org par MD5: {md5_hash}")

    strategies_tried = []

    # Stratégie 1: Recherche directe par MD5
    try:
        query = f'md5:{md5_hash}'
        print(f"    → Recherche: {query}")
        results = internetarchive.search_items(query)

        for result in results:
            identifier = result.get('identifier', '')
            if identifier:
                try:
                    item = internetarchive.get_item(identifier)
                    files = item.get_files()

                    for file_info in files:
                        file_name = file_info.get('name', '')
                        file_md5 = file_info.get('md5', '')

                        if file_md5 and file_md5.lower() == md5_hash.lower():
                            print(f"    ✓ Trouvé: {identifier}/{file_name}")
                            return {
                                'found': True,
                                'identifier': identifier,
                                'filename': file_name,
                                'md5': md5_hash,
                                'source': 'archive_org_md5'
                            }
                except Exception as e:
                    continue

        strategies_tried.append('md5_direct')
    except Exception as e:
        print(f"    ✗ Erreur recherche MD5: {e}")
        strategies_tried.append(f'md5_error: {e}')

    # Stratégie 2: Recherche par nom de ROM avec différentes collections
    if rom_name:
        collections_to_try = [
            'softwarelibrary',
            'retrogames',
            'classicgames',
            'gameboy',
            ''  # No filter (all archive.org)
        ]
        
        clean_name = rom_name.split('(')[0].strip()
        
        for collection in collections_to_try:
            try:
                if collection:
                    query = f'{clean_name} AND collection:{collection}'
                else:
                    query = clean_name
                
                print(f"    → Recherche nom: {query[:50]}...")
                results = list(internetarchive.search_items(query))[:15]

                for result in results:
                    identifier = result.get('identifier', '')
                    if not identifier:
                        continue

                    try:
                        item = internetarchive.get_item(identifier)
                        files = item.get_files()

                        for file_info in files:
                            file_name = file_info.get('name', '')
                            file_md5 = file_info.get('md5', '')

                            # Vérifier correspondance nom
                            if (rom_name.lower() in file_name.lower() or 
                                clean_name.lower() in file_name.lower()):
                                
                                if file_name.endswith(('.zip', '.gb', '.gbc', '.7z', '.rar')):
                                    # Si on a un MD5, le vérifier
                                    if file_md5 and file_md5.lower() == md5_hash.lower():
                                        print(f"    ✓ Trouvé (nom+MD5): {identifier}/{file_name}")
                                        return {
                                            'found': True,
                                            'identifier': identifier,
                                            'filename': file_name,
                                            'md5': md5_hash,
                                            'source': 'archive_org_name'
                                        }
                                    elif not file_md5:
                                        # Pas de MD5 disponible, on prend quand même en dernier recours
                                        print(f"    ✓ Trouvé (nom seulement): {identifier}/{file_name}")
                                        return {
                                            'found': True,
                                            'identifier': identifier,
                                            'filename': file_name,
                                            'md5': md5_hash,
                                            'source': 'archive_org_name'
                                        }
                    except Exception as e:
                        continue

                strategies_tried.append(f'name_{collection or "all"}')
            except Exception as e:
                strategies_tried.append(f'name_error_{collection}: {e}')

    print(f"  ✗ Non trouvé sur archive.org (stratégies: {', '.join(strategies_tried)})")
    return {'found': False, 'strategies_tried': strategies_tried}


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
                        print(f"  ✓ Téléchargé via internetarchive ({size:,} octets)")
                        if progress_callback:
                            progress_callback(100.0)
                        return True
            except Exception as e:
                print(f"  ⚠ Erreur internetarchive: {e}, tentative HTTP directe...")
            
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
                print(f"  ✓ Téléchargé via HTTP direct ({size:,} octets)")
                return True
            else:
                print(f"  ✗ Fichier non créé")
                return False
                
        except Exception as e:
            print(f"  ✗ Tentative {attempt + 1}/{max_retries} échouée: {e}")
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
        query = f'{rom_name} AND collection:No-Intro'
        results = list(internetarchive.search_items(query))[:20]

        for result in results:
            identifier = result.get('identifier', '')
            if not identifier:
                continue

            try:
                item = internetarchive.get_item(identifier)
                files = item.get_files()

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
        query = rom_name
        results = list(internetarchive.search_items(query))[:10]

        for result in results:
            identifier = result.get('identifier', '')
            if not identifier:
                continue

            try:
                item = internetarchive.get_item(identifier)
                files = item.get_files()

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


def scan_local_roms(rom_folder: str) -> tuple:
    """Scan a folder for local ROM files."""
    print(f"Scanning local ROMs folder: {rom_folder}")

    local_roms = set()
    local_roms_normalized = set()
    local_game_names = set()
    rom_path = Path(rom_folder)

    if not rom_path.exists():
        print(f"Warning: ROM folder does not exist: {rom_folder}")
        return local_roms, local_roms_normalized, local_game_names

    # Utiliser la constante globale
    archive_extensions = ('.zip', '.7z', '.rar', '.gz', '.z')

    for file_path in rom_path.rglob('*'):
        if file_path.is_file():
            filename = file_path.name
            local_roms.add(filename)

            name_no_ext = filename
            for ext in ROM_EXTENSIONS:
                if name_no_ext.lower().endswith(ext):
                    name_no_ext = name_no_ext[:-len(ext)]
                    break
            local_roms_normalized.add(name_no_ext.lower())
            local_game_names.add(name_no_ext.lower())

            if file_path.suffix.lower() in archive_extensions:
                try:
                    import zipfile
                    if file_path.suffix.lower() == '.zip':
                        with zipfile.ZipFile(file_path, 'r') as zf:
                            for zip_info in zf.infolist():
                                if not zip_info.is_dir():
                                    internal_name = zip_info.filename
                                    local_roms.add(internal_name)
                                    for ext in ROM_EXTENSIONS:
                                        if internal_name.lower().endswith(ext):
                                            internal_name = internal_name[:-len(ext)]
                                            break
                                    local_roms_normalized.add(internal_name.lower())
                except Exception:
                    pass

    print(f"Found {len(local_roms)} local ROM files")
    return local_roms, local_roms_normalized, local_game_names


def find_missing_games(dat_games: dict, local_roms: set, local_roms_normalized: set, local_game_names: set) -> list:
    """Compare DAT games with local ROMs and return missing ones."""
    print("Comparing DAT games with local ROMs...")

    missing = []
    for game_name, game_info in dat_games.items():
        found = False

        game_name_normalized = game_name.lower()
        if game_name_normalized in local_game_names:
            found = True

        if not found:
            for rom_info in game_info['roms']:
                rom_name = rom_info['name']
                rom_name_no_ext = rom_name
                for ext in ROM_EXTENSIONS:
                    if rom_name.lower().endswith(ext):
                        rom_name_no_ext = rom_name[:-len(ext)]
                        break

                if rom_name in local_roms or rom_name_no_ext.lower() in local_roms_normalized:
                    found = True
                    break

        if not found:
            missing.append(game_info)

    print(f"Found {len(missing)} missing games")
    return missing


def find_roms_not_in_dat(dat_games: dict, local_roms: set, local_roms_normalized: set,
                         rom_folder: str) -> list:
    """Find ROM files that are not in the DAT file."""
    print("Finding ROMs not in DAT file...")

    # Build sets for DAT game names with different normalization strategies
    dat_game_names_exact = set()  # Exact normalized names
    dat_game_names_base = set()   # Base names (before first parenthesis)
    
    for game_name in dat_games.keys():
        name_lower = game_name.lower()
        dat_game_names_exact.add(name_lower)
        
        # Extract base name (before first parenthesis)
        if '(' in name_lower:
            base_name = name_lower.split('(')[0].strip()
            # Also try without trailing dash or spaces
            base_name_clean = base_name.rstrip(' -')
            dat_game_names_base.add(base_name)
            dat_game_names_base.add(base_name_clean)
        else:
            dat_game_names_base.add(name_lower)

    # Also add ROM names from DAT
    for game_info in dat_games.values():
        for rom_info in game_info.get('roms', []):
            rom_name = rom_info.get('name', '')
            rom_name_no_ext = rom_name
            for ext in ROM_EXTENSIONS:
                if rom_name.lower().endswith(ext):
                    rom_name_no_ext = rom_name[:-len(ext)]
                    break

            name_lower = rom_name_no_ext.lower()
            dat_game_names_exact.add(name_lower)
            
            # Extract base name
            if '(' in name_lower:
                base_name = name_lower.split('(')[0].strip()
                base_name_clean = base_name.rstrip(' -')
                dat_game_names_base.add(base_name)
                dat_game_names_base.add(base_name_clean)
            else:
                dat_game_names_base.add(name_lower)

    def is_name_in_dat(name_to_check: str) -> bool:
        """Check if a name matches any DAT game using multiple strategies."""
        name_lower = name_to_check.lower()
        
        # Strategy 1: Exact match
        if name_lower in dat_game_names_exact:
            return True
        
        # Strategy 2: Base name match
        if '(' in name_lower:
            base_name = name_lower.split('(')[0].strip()
            base_name_clean = base_name.rstrip(' -')
            if base_name in dat_game_names_base or base_name_clean in dat_game_names_base:
                return True
        else:
            if name_lower in dat_game_names_base:
                return True
        
        # Strategy 3: Check if any DAT name contains the base name
        base_name = name_lower.split('(')[0].strip().rstrip(' -') if '(' in name_lower else name_lower
        for dat_name in dat_game_names_base:
            if base_name and base_name in dat_name and len(base_name) > 5:
                return True
            if dat_name and dat_name in base_name and len(dat_name) > 5:
                return True
        
        return False

    # Find files not in DAT
    files_to_move = []
    rom_path = Path(rom_folder)

    archive_extensions = ('.zip', '.7z', '.rar', '.gz', '.z')
    all_extensions = list(ROM_EXTENSIONS) + ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.mp4', '.avi', '.mkv', '.pdf', '.txt', '.nfo']

    if not rom_path.exists():
        return files_to_move

    for file_path in rom_path.rglob('*'):
        if file_path.is_file():
            filename = file_path.name

            # Skip if already in ToSort folder
            if 'ToSort' in file_path.parts:
                continue

            # Check if file matches a DAT game
            name_no_ext = filename
            for ext in all_extensions:
                if name_no_ext.lower().endswith(ext):
                    name_no_ext = name_no_ext[:-len(ext)]
                    break

            if not is_name_in_dat(name_no_ext):
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


def detect_system_name(dat_file_path: str) -> str:
    """
    Tente de détecter le nom du système à partir du nom du fichier DAT.
    Gère les noms complexes (Retool, dates, tags).
    Exemple: 'Nintendo - Game Boy (Retool).dat' -> 'Nintendo - Game Boy'
    """
    filename = os.path.basename(dat_file_path)
    # Retirer l'extension
    name = os.path.splitext(filename)[0]
    # Retirer les parenthèses () et les crochets [] ainsi que leur contenu
    name = re.sub(r'[\(\[].*?[\)\]]', '', name).strip()
    # Normaliser les espaces multiples
    name = re.sub(r'\s+', ' ', name)
    return name


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


def list_planetemu_directory(system_slug: str, session: requests.Session) -> dict:
    """Scrape PlanetEmu pour un système donné."""
    if not system_slug:
        return {}
        
    config = ROM_DATABASE.get('config_urls', {})
    url = f"{config.get('planetemu_roms', '')}{system_slug}"
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
        data = {'id': rom_id, 'download': 'T\u00e9l\u00e9charger'}
        
        # On ne suit pas les redirects automatiquement pour voir le Location
        resp = session.post(download_api, data=data, allow_redirects=False, timeout=30)
        
        token_url = None
        if resp.status_code == 302:
            token_url = resp.headers.get('Location')
            if token_url:
                from urllib.parse import urljoin
                token_url = urljoin(download_api, token_url)
        
        if not token_url:
            print("  [PlanetEmu] Échec de génération du token")
            return False
            
        # Étape 3 : Télécharger avec le token
        return download_file(token_url, dest_path, session, progress_callback)
        
    except Exception as e:
        print(f"  [PlanetEmu] Erreur: {e}")
        return False


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
        game_name_normalized = game_name.lower()

        matched_file = None
        if game_name_normalized in myrient_lookup:
            matched_file = myrient_lookup[game_name_normalized]

        if not matched_file:
            primary_rom = game_info.get('primary_rom', '')
            primary_rom_no_ext = primary_rom
            for ext in ROM_EXTENSIONS:
                if primary_rom.lower().endswith(ext):
                    primary_rom_no_ext = primary_rom[:-len(ext)]
                    break
            if primary_rom_no_ext.lower() in myrient_lookup:
                matched_file = myrient_lookup[primary_rom_no_ext.lower()]

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


def search_all_sources(missing_games: list, sources: list, session: requests.Session, system_name: str = None) -> tuple:
    """
    Search for missing games across all configured sources.
    Utilise la base de données locale (74,189 URLs) + recherche directe + nouveaux scrapers.
    Returns (found_games: list, not_found_games: list)
    """
    print("\n" + "=" * 70)
    print(f"Recherche des jeux manquants pour le système: {system_name or 'Inconnu'}")
    print("=" * 70)
    
    # Charger la base de données
    load_rom_database()
    
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
        db_results = search_by_name(game_name)
        
        # Si pas trouvé par nom, essayer par MD5
        if not db_results:
            for rom_info in roms:
                md5_hash = rom_info.get('md5', '')
                if md5_hash:
                    db_results = search_by_md5(md5_hash)
                    if db_results:
                        print(f"  [DB] {game_name} trouvé par MD5: {md5_hash}")
                        break
        
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
            
            game_info['download_filename'] = best_result.get('full_name', game_name)
            game_info['download_url'] = best_result.get('url')
            game_info['source'] = 'database'
            game_info['database_host'] = best_result.get('host')
            found_in_db.append(game_info)
            print(f"  [DB] {game_name} → {best_result.get('host')}")
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
            if source['type'] == 'edgeemu' and source.get('enabled', True):
                slug = mappings.get('edgeemu')
                if slug:
                    print(f"\n--- Recherche sur EdgeEmu ({slug}) ---")
                    edge_files = list_edgeemu_directory(slug, session)
                    if edge_files:
                        newly_found = []
                        remaining = []
                        for game_info in still_missing:
                            name_lower = game_info['game_name'].lower()
                            if name_lower in edge_files:
                                game_info['download_url'] = edge_files[name_lower]['url']
                                game_info['source'] = 'EdgeEmu'
                                game_info['download_filename'] = game_info['game_name']
                                newly_found.append(game_info)
                                print(f"  [EdgeEmu] {game_info['game_name']} trouvé")
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
                                game_info['download_filename'] = game_info['game_name']
                                newly_found.append(game_info)
                                print(f"  [PlanetEmu] {game_info['game_name']} trouvé")
                            else:
                                remaining.append(game_info)
                        all_found.extend(newly_found)
                        still_missing = remaining
    
    # ========================================================================
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
    # ÉTAPE 4 : Recherche archive.org par MD5 (fallback final)
    # ========================================================================
    archive_sources = [s for s in sources if s['type'] == 'archive_org' and s.get('enabled', True)]
    
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


def search_archive_org_for_games(not_available: list) -> tuple:
    """
    Search for games not available on other sources using archive.org by MD5 hash or name.
    Returns (found_on_archive: list, still_not_available: list)
    """
    found_on_archive = []
    still_not_available = []

    for game_info in not_available:
        game_name = game_info['game_name']
        roms = game_info.get('roms', [])

        archive_result = None

        # Try to find ROM by MD5 hash first
        for rom_info in roms:
            md5_hash = rom_info.get('md5', '')
            if md5_hash:
                result = search_archive_org_by_md5(md5_hash, rom_info.get('name', ''))
                if result['found']:
                    archive_result = result
                    archive_result['rom_name'] = rom_info.get('name', '')
                    break

        # Fallback: search by name if MD5 search failed
        if not archive_result:
            result = search_archive_org_by_name(game_name)
            if result['found']:
                archive_result = result
                archive_result['rom_name'] = game_name

        if archive_result:
            game_info['download_filename'] = archive_result['filename']
            game_info['archive_org_identifier'] = archive_result['identifier']
            game_info['archive_org_filename'] = archive_result['filename']
            game_info['archive_org_md5'] = archive_result.get('md5', '')
            game_info['source'] = 'archive_org'
            found_on_archive.append(game_info)
            print(f"  [TROUVÉ] {game_name} sur archive.org")
        else:
            still_not_available.append(game_info)

    return found_on_archive, still_not_available


def download_file(url: str, dest_path: str, session: requests.Session, progress_callback=None) -> bool:
    """Download a file from URL to destination path with retry support."""
    max_retries = 3
    retry_delay = 5

    for attempt in range(max_retries):
        try:
            with session.get(url, stream=True, timeout=120) as response:
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


def interactive_mode():
    """Run in interactive console mode."""
    print("=" * 60)
    print("ROM Downloader - Mode Interactif")
    print("=" * 60)
    print()

    dat_file = get_input("Chemin vers le fichier DAT: ")
    rom_folder = get_input("Chemin vers le dossier des ROMs: ")
    myrient_url = get_input("URL Myrient: ")
    print()
    
    tosort_input = get_input("Deplacer les ROMs non presentes dans le DAT vers ToSort ? (o/n): ")
    move_to_tosort = tosort_input.lower() in ['o', 'oui', 'y', 'yes']
    print()

    # Validate
    if not os.path.exists(dat_file):
        print(f"Erreur: Fichier DAT introuvable: {dat_file}")
        return
    if not os.path.exists(rom_folder):
        print(f"Erreur: Dossier ROMs introuvable: {rom_folder}")
        return

    run_download(dat_file, rom_folder, myrient_url, rom_folder, False, None, move_to_tosort)


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


def run_download(dat_file, rom_folder, myrient_url, output_folder, dry_run, limit, move_to_tosort=False, custom_sources=None):
    """Run the download process."""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })

    # Parse DAT
    dat_games = parse_dat_file(dat_file)

    # Scan local ROMs
    local_roms, local_roms_normalized, local_game_names = scan_local_roms(rom_folder)

    # Find missing games
    missing_games = find_missing_games(dat_games, local_roms, local_roms_normalized, local_game_names)

    # Détection du système
    system_name = detect_system_name(dat_file)
    print(f"Système détecté : {system_name}")

    if not missing_games:
        print("\nAucun jeu manquant trouvé !")
    else:
        # Use custom sources if provided, otherwise use default sources
        sources = custom_sources if custom_sources else get_default_sources().copy()
        
        # If a custom myrient_url is provided, add it as first source
        if myrient_url and myrient_url not in [s['base_url'] for s in sources]:
            sources.insert(0, {
                'name': 'Myrient Custom',
                'base_url': myrient_url,
                'type': 'myrient',
                'enabled': True
            })
        
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
                filename = game_info.get('download_filename', game_name)

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
                
                if source == 'archive_org':
                    identifier = game_info.get('archive_org_identifier', '')
                    if identifier and filename:
                        success = download_from_archive_org(identifier, filename, dest_path, session)

                elif source == 'EdgeEmu':
                    success = download_file(download_url, dest_path, session)

                elif source == 'PlanetEmu':
                    page_url = game_info.get('page_url')
                    if page_url:
                        success = download_planetemu(page_url, dest_path, session)

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
        parent_folder = os.path.dirname(rom_folder)
        tosort_folder = os.path.join(parent_folder, "ToSort")
        
        files_to_move = find_roms_not_in_dat(dat_games, local_roms, local_roms_normalized, rom_folder)
        
        if files_to_move:
            print(f"\n{len(files_to_move)} fichiers à déplacer vers: {tosort_folder}")
            moved, failed = move_files_to_tosort(files_to_move, rom_folder, tosort_folder, dry_run)
            print(f"\nRésumé ToSort:")
            print(f"  Déplacés: {moved}")
            print(f"  Échecs: {failed}")
        else:
            print("\nAucun fichier à déplacer.")


def cli_mode(args):
    """Run in command-line mode."""
    output_folder = args.output if args.output else args.rom_folder
    os.makedirs(output_folder, exist_ok=True)

    run_download(args.dat_file, args.rom_folder, args.myrient_url, output_folder, args.dry_run, args.limit, args.tosort)


# ============================================================================
# Interface Graphique (GUI)
# ============================================================================

def gui_mode():
    """Run in GUI mode."""
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox, scrolledtext
        import threading
        
        # Try tkinterdnd2 for drag & drop
        try:
            import tkinterdnd2
            HAS_DND = True
        except ImportError:
            HAS_DND = False
        
        class ROMDownloaderGUI:
            def __init__(self, root, use_dnd=False):
                self.root = root
                self.root.title("ROM Downloader")
                self.root.geometry("900x750")
                self.root.minsize(800, 650)

                self.dat_file = tk.StringVar()
                self.rom_folder = tk.StringVar()
                self.myrient_url = tk.StringVar()
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

                ttk.Label(main_frame, text="URL Myrient (optionnel):").grid(row=3, column=0, sticky=tk.W, pady=5)
                self.url_entry = ttk.Entry(main_frame, textvariable=self.myrient_url, width=80)
                self.url_entry.grid(row=3, column=1, sticky=(tk.W, tk.E), pady=5, padx=5)
                ttk.Button(main_frame, text="Defaut GB", command=self.set_default_gb).grid(row=3, column=2, pady=5)

                # Sources section
                ttk.Separator(main_frame, orient='horizontal').grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=15)
                ttk.Label(main_frame, text="Sources de téléchargement:", font=('Segoe UI', 11, 'bold')).grid(row=5, column=0, sticky=tk.W, pady=5)
                
                sources_frame = ttk.Frame(main_frame)
                sources_frame.grid(row=6, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
                
                # Initialize source checkboxes
                self.source_vars = {}
                for i, source in enumerate(get_default_sources()):
                    var = tk.BooleanVar(value=source.get('enabled', True))
                    self.source_vars[source['name']] = var
                    chk = ttk.Checkbutton(sources_frame, text=source['name'], variable=var)
                    chk.grid(row=i // 2, column=i % 2, sticky=tk.W, padx=10, pady=2)

                self.move_to_tosort_var = tk.BooleanVar(value=False)
                ttk.Checkbutton(main_frame, text="Deplacer les ROMs non presentes dans le DAT vers ToSort",
                               variable=self.move_to_tosort_var).grid(row=7, column=0, columnspan=3, sticky=tk.W, pady=5)

                ttk.Separator(main_frame, orient='horizontal').grid(row=8, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=20)

                ttk.Label(main_frame, text="Progression:").grid(row=9, column=0, sticky=tk.W, pady=5)
                self.progress_var = tk.DoubleVar()
                self.progress_bar = ttk.Progressbar(main_frame, variable=self.progress_var, maximum=100, mode='determinate')
                self.progress_bar.grid(row=9, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=5)

                self.status_var = tk.StringVar(value="Pret")
                ttk.Label(main_frame, textvariable=self.status_var).grid(row=10, column=0, columnspan=3, pady=5)

                ttk.Label(main_frame, text="Journal:").grid(row=11, column=0, sticky=tk.W, pady=5)
                self.log_text = scrolledtext.ScrolledText(main_frame, height=20, width=100, wrap=tk.WORD)
                self.log_text.grid(row=12, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
                main_frame.columnconfigure(1, weight=1)
                main_frame.rowconfigure(12, weight=1)

                button_frame = ttk.Frame(main_frame)
                button_frame.grid(row=13, column=0, columnspan=3, pady=10)

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
                if ROM_DATABASE is None:
                    load_rom_database()
                config = ROM_DATABASE.get('config_urls', {})
                self.myrient_url.set(config.get('myrient_no_intro', '') + "Nintendo%20-%20Game%20Boy/")
            
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
                if not self.myrient_url.get():
                    messagebox.showerror("Erreur", "Veuillez entrer une URL Myrient")
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

                    # Build sources list from checkboxes
                    sources = []
                    for source in get_default_sources():
                        if self.source_vars.get(source['name'], tk.BooleanVar(value=True)).get():
                            sources.append(source.copy())
                    
                    # Add custom URL if provided
                    if myrient_url and myrient_url not in [s['base_url'] for s in sources]:
                        sources.insert(0, {
                            'name': 'Myrient Custom',
                            'base_url': myrient_url,
                            'type': 'myrient',
                            'enabled': True
                        })

                    self.log(f"Parsing DAT file: {dat_path}")
                    self.status_var.set("Analyse du fichier DAT...")
                    dat_games = parse_dat_file(dat_path)

                    self.log(f"Scanning ROM folder: {rom_folder}")
                    self.status_var.set("Analyse des ROMs locales...")
                    local_roms, local_roms_normalized, local_game_names = scan_local_roms(rom_folder)

                    self.status_var.set("Recherche des jeux manquants...")
                    missing_games = find_missing_games(dat_games, local_roms, local_roms_normalized, local_game_names)

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
                    to_download, not_available = search_all_sources(missing_games, sources, self.session)

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
                        
                        if source == 'archive_org':
                            identifier = game_info.get('archive_org_identifier', '')
                            if identifier and filename:
                                success = download_from_archive_org(identifier, filename, dest_path, self.session, update_progress)
                        else:
                            source_info = next((s for s in sources if s['name'] == source), None)
                            base_url = source_info['base_url'] if source_info else myrient_url
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
                        
                        parent_folder = os.path.dirname(rom_folder)
                        tosort_folder = os.path.join(parent_folder, "ToSort")
                        
                        files_to_move = find_roms_not_in_dat(dat_games, local_roms, local_roms_normalized, rom_folder)
                        
                        if files_to_move:
                            self.log(f"{len(files_to_move)} fichiers a deplacer vers: {tosort_folder}")
                            moved, move_failed = move_files_to_tosort(files_to_move, rom_folder, tosort_folder, False)
                            self.log(f"\nResume ToSort:")
                            self.log(f"  Deplaces: {moved}")
                            self.log(f"  Echecs: {move_failed}")
                        else:
                            self.log("Aucun fichier a deplacer.")

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

def main():
    parser = argparse.ArgumentParser(
        description='ROM Downloader - Compare DAT avec ROMs locales et telecharge depuis plusieurs sources',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=r'''
Exemples:
  python rom_downloader.py --gui
  python rom_downloader.py "Dat\Nintendo - Game Boy.dat" "Roms\GB"
  python rom_downloader.py "Dat\PS1.dat" "Roms\PS1" --limit 10
  python rom_downloader.py  (mode interactif)
  python rom_downloader.py --sources  (afficher les sources disponibles)
  python rom_downloader.py --configure-api  (configurer les clés API)
        '''
    )
    parser.add_argument('dat_file', nargs='?', help='Chemin vers le fichier DAT')
    parser.add_argument('rom_folder', nargs='?', help='Chemin vers le dossier des ROMs')
    parser.add_argument('myrient_url', nargs='?', help='URL Myrient')
    parser.add_argument('-o', '--output', help='Dossier de sortie (defaut: rom_folder)')
    parser.add_argument('--dry-run', action='store_true', help='Simulation sans telechargement')
    parser.add_argument('--limit', type=int, help='Limite de telechargements')
    parser.add_argument('--gui', action='store_true', help='Mode interface graphique')
    parser.add_argument('--tosort', action='store_true', help='Deplacer les ROMs non presentes dans le DAT vers ToSort')
    parser.add_argument('--sources', action='store_true', help='Afficher les sources de telechargement')
    parser.add_argument('--configure-api', action='store_true', help='Configurer les cles API premium')

    args = parser.parse_args()

    # Configure API keys
    if args.configure_api:
        configure_api_keys()
        return

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
