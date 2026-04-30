import html as html_module
import csv
import json
import os
import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import quote, unquote, urljoin

import cloudscraper
import requests
from bs4 import BeautifulSoup

from .constants import *
from .env import *
from .dependencies import *
from .dat_parser import strip_rom_extension, normalize_checksum
from . import rom_database as _rom_db
from .rom_database import load_rom_database, database_result_filename
from .sources import SYSTEM_MAPPINGS, normalize_source_label, source_is_excluded, source_order_key
from .minerva import (
    search_minerva_hash_database_for_games,
    build_minerva_directory_url,
    collect_minerva_files_from_url,
    resolve_minerva_torrent_url,
    build_minerva_torrent_urls,
    search_database_for_game,
    select_ddl_result,
    select_torrent_result,
    select_archive_result,
)
from .dat_profile import (
    finalize_dat_profile,
    prepare_sources_for_profile,
    describe_dat_profile,
)
from .archive_org import (
    search_archive_org_by_md5,
    search_archive_org_by_crc,
    search_archive_org_by_sha1,
    search_archive_org_by_name,
)


LOLROMS_SESSION = None


def get_lolroms_session():
    """Retourne une session Cloudflare-compatible pour LoLROMs."""
    global LOLROMS_SESSION

    if LOLROMS_SESSION is None:
        user_agent = os.environ.get(
            'LOLROMS_USER_AGENT',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        )
        LOLROMS_SESSION = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
            delay=10,
        )
        LOLROMS_SESSION.headers.update({
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Cache-Control': 'no-cache',
            'DNT': '1',
            'Upgrade-Insecure-Requests': '1',
        })
        cookie = os.environ.get('LOLROMS_COOKIE', '').strip()
        if cookie:
            LOLROMS_SESSION.headers['Cookie'] = cookie
            for pair in cookie.split(';'):
                if '=' in pair:
                    key, val = pair.split('=', 1)
                    LOLROMS_SESSION.cookies.set(key.strip(), val.strip(), domain='lolroms.com')

    return LOLROMS_SESSION


def download_lolroms_file(url: str, dest_path: str, progress_callback=None,
                          timeout_seconds: int = 120, progress_detail_callback=None) -> bool:
    """Telecharge un fichier LoLROMs avec les en-tetes attendus par Cloudflare."""
    from .downloads import download_file

    session = get_lolroms_session()
    directory_url = url.rsplit('/', 1)[0] + '/' if '/' in url else LOLROMS_BASE
    headers = {
        'Accept': 'application/octet-stream,application/x-7z-compressed,application/zip,*/*;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': directory_url,
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-User': '?1',
        'Connection': 'keep-alive',
    }
    return download_file(
        url,
        dest_path,
        session,
        progress_callback,
        timeout_seconds,
        progress_detail_callback,
        extra_headers=headers,
    )



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


LOLROMS_SUBDIR_ALIASES = {
    'Nintendo - Game Boy Advance': {
        'multiboot': 'Multi-Boot',
        'ereader': 'eReader',
        'play-yan': 'Play-Yan',
        'video': 'Video',
        'hacks (color)': 'Hacks (Color)',
        't-en': 'T-En',
    },
    'Nintendo - Game Boy': {},
    'Nintendo - Game Boy Color': {},
    'Nintendo - Nintendo Entertainment System': {},
    'Nintendo - Super Nintendo Entertainment System': {},
    'Nintendo - Nintendo 64': {},
    'Sega - Mega Drive - Genesis': {},
    'Sega - Master System - Mark III': {},
    'Sega - Game Gear': {},
    'SNK - Neo Geo Pocket Color': {},
    'Sony - PlayStation': {},
    'Sony - PlayStation Portable': {},
    'Nintendo - DS': {},
    'Nintendo - 3DS': {},
    'Nintendo - GameCube': {},
    'Nintendo - Wii': {},
    'Nintendo - Wii U': {},
    'Nintendo - Virtual Boy': {},
    'Nintendo - Pokémon Mini': {},
}


def _lolroms_subdir_for_system(system_name: str) -> str | None:
    """Extrait le sous-repertoire LoLROMs si le nom du systeme contient un qualificateur de sous-ensemble."""
    base = re.sub(r'\s*\(.+?\)\s*$', '', system_name).strip()
    qualifier_match = re.search(r'\(([^)]+)\)\s*$', system_name)
    if not qualifier_match:
        return None
    qualifier = qualifier_match.group(1).strip().lower()
    aliases = LOLROMS_SUBDIR_ALIASES.get(base, {})
    return aliases.get(qualifier)


def list_lolroms_directory(system_path: str, include_subdirs: bool = True) -> dict:
    """Scrape LoLROMs pour un systeme donne et retourne un mapping par nom normalise.
    Si include_subdirs=True, scrape aussi les sous-repertoires (Multi-Boot, eReader, etc.)
    et fusionne leurs fichiers dans le listing principal.
    """
    if not system_path:
        return {}

    url = build_lolroms_url(system_path)
    print(f"Scraping LoLROMs: {url}")
    from . import _facade
    cache = _facade.load_listing_cache()
    cache_key = f"lolroms:{url}"
    cached = _facade.listing_cache_get(cache, cache_key)
    if cached:
        print("  Listing LoLROMs depuis le cache")
        return dict(cached)

    mapping = {}
    subdirs = []
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
            if href.lower().endswith('/feed'):
                continue
            if '/.' in href:
                continue

            if href.endswith('/'):
                subdir_name = text.strip()
                if subdir_name and subdir_name not in {'/', './', '../'} and include_subdirs:
                    subdirs.append(subdir_name)
                continue

            full_url = urljoin(url.rstrip('/') + '/', href)
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

        if subdirs:
            print(f"  Sous-repertoires LoLROMs detectes: {', '.join(subdirs)}")
            for subdir_name in subdirs:
                subdir_path = f"{system_path}/{subdir_name}"
                subdir_url = build_lolroms_url(subdir_path)
                subdir_cache_key = f"lolroms:{subdir_url}"
                subdir_cached = _facade.listing_cache_get(cache, subdir_cache_key)
                if subdir_cached:
                    print(f"  Sous-repertoire {subdir_name} depuis le cache ({len(subdir_cached)} fichiers)")
                    mapping.update(subdir_cached)
                    continue
                try:
                    subdir_resp = get_lolroms_session().get(subdir_url, timeout=60)
                    if subdir_resp.status_code != 200 or 'Just a moment...' in subdir_resp.text:
                        continue
                    subdir_soup = BeautifulSoup(subdir_resp.text, 'html.parser')
                    subdir_count = 0
                    for link in subdir_soup.find_all('a', href=True):
                        href = html_module.unescape(link.get('href', '')).strip()
                        text = html_module.unescape(link.get_text().strip())
                        if not href or not text or text in {'RSS', 'Donate', 'Main', '../'}:
                            continue
                        if href.endswith('/') or href.lower().endswith('/feed'):
                            continue
                        if '/.' in href:
                            continue
                        full_url = urljoin(subdir_url.rstrip('/') + '/', href)
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
                        subdir_count += 1
                    if subdir_count:
                        print(f"  Sous-repertoire {subdir_name}: {subdir_count} fichiers")
                        subdir_mapping = {
                            k: v for k, v in mapping.items()
                            if v['url'].startswith(subdir_url)
                        }
                        _facade.listing_cache_set(cache, subdir_cache_key, subdir_mapping)
                except Exception as e:
                    print(f"  Erreur sous-repertoire LoLROMs {subdir_name}: {e}")

        print(f"Found {len(mapping)} files on LoLROMs")
        _facade.listing_cache_set(cache, cache_key, mapping)
        _facade.save_listing_cache(cache)
    except Exception as e:
        print(f"Erreur scraping LoLROMs: {e}")

    return mapping


def list_edgeemu_directory(system_slug: str, session: requests.Session) -> dict:
    """Scrape EdgeEmu pour un système donné et retourne un dict {nom_normalisé: url_téléchargement}."""
    if not system_slug:
        return {}
    if _rom_db.ROM_DATABASE is None:
        load_rom_database()
    config = _rom_db.ROM_DATABASE.get('config_urls', {})
    url = f"{config.get('edgeemu_browse', '')}{system_slug}"
    print(f"Scraping EdgeEmu: {url}")
    from . import _facade
    cache = _facade.load_listing_cache()
    cache_key = f"edgeemu:{url}"
    cached = _facade.listing_cache_get(cache, cache_key)
    if cached:
        print("  Listing EdgeEmu depuis le cache")
        return dict(cached)
    
    mapping = {}
    try:
        response = session.get(url, timeout=30)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            for details in soup.find_all('details'):
                summary = details.find('summary')
                if not summary: continue
                
                game_name = summary.get_text().strip()
                a_tag = details.find('a', href=True)
                if a_tag and '/download/' in a_tag['href']:
                    download_url = config.get('edgeemu_base', '') + a_tag['href']
                    mapping[game_name.lower()] = {
                        'full_name': game_name,
                        'url': download_url
                    }
            _facade.listing_cache_set(cache, cache_key, mapping)
            _facade.save_listing_cache(cache)
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


def normalize_external_game_name(name: str) -> str:
    """Normalise un titre pour comparer DAT et listings web."""
    value = html_module.unescape(str(name or ''))
    value = os.path.basename(unquote(value))
    value = strip_rom_extension(value)
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = value.lower().replace('&', ' and ')
    value = re.sub(r'\b(?:rev|version|v)\s*(\d+(?:\.\d+)*)\b', r'rev \1', value)
    value = re.sub(r'\b(?:disc|disk|cd)\s*(\d+(?:\.\d+)*)\b', r'disc \1', value)
    value = re.sub(r'\b(?:demo|sample|prototype|proto|beta|alpha|unl|unlicensed|debug|press[-\s]?kit|promo)\b', '', value)
    value = re.sub(r'[^a-z0-9]+', ' ', value)
    value = re.sub(r'\s+', ' ', value).strip()
    value = re.sub(r'\bdisc\s', ' disc ', value)
    return re.sub(r'\s+', ' ', value).strip()


def find_listing_match(game_info: dict, listing: dict, min_score: float = 0.92) -> tuple[str, dict] | tuple[None, None]:
    """Trouve le meilleur resultat d'un listing avec exact + normalisation + fuzzy + containment."""
    if not listing:
        return None, None

    raw_index = {str(key).lower(): entry for key, entry in listing.items()}
    normalized_index = {}
    normalized_names = []
    for key, entry in listing.items():
        display_name = entry.get('full_name') or key
        for value in (key, display_name):
            normalized = normalize_external_game_name(value)
            current = normalized_index.get(normalized)
            current_name = current.get('full_name', '') if current else ''
            if normalized and (current is None or len(str(display_name)) < len(str(current_name))):
                normalized_index[normalized] = entry
                if normalized not in normalized_names:
                    normalized_names.append(normalized)

    candidates = iter_game_candidate_names(game_info)

    for candidate_name in candidates:
        raw = candidate_name.lower()
        if raw in raw_index:
            return candidate_name, raw_index[raw]

        normalized_candidate = normalize_external_game_name(candidate_name)
        if not normalized_candidate:
            continue

        entry = normalized_index.get(normalized_candidate)
        if entry:
            return candidate_name, entry

        best_name = ''
        best_score = 0.0
        for normalized_name in normalized_names:
            score = SequenceMatcher(None, normalized_candidate, normalized_name).ratio()
            if score > best_score:
                best_name = normalized_name
                best_score = score

        if best_score >= min_score:
            return candidate_name, normalized_index[best_name]

    for candidate_name in candidates:
        normalized_candidate = normalize_external_game_name(candidate_name)
        if not normalized_candidate:
            continue
        for normalized_name in normalized_names:
            shorter, longer = sorted([normalized_candidate, normalized_name], key=len)
            if len(shorter) >= 8 and (shorter in longer or longer in shorter):
                return candidate_name, normalized_index[normalized_name]

    return None, None


def resolve_edgeemu_game(game_info: dict, system_slug: str, session: requests.Session) -> dict | None:
    """
    Résout directement une URL EdgeEmu à partir du nom de ROM.
    Le browse EdgeEmu ne retourne qu'un petit sous-ensemble variable de jeux,
    donc on privilégie ici l'URL de téléchargement déterministe.
    """
    if not system_slug:
        return None

    if _rom_db.ROM_DATABASE is None:
        load_rom_database()

    config = _rom_db.ROM_DATABASE.get('config_urls', {})
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
    if _rom_db.ROM_DATABASE is None:
        load_rom_database()
    config = _rom_db.ROM_DATABASE.get('config_urls', {})
    base = config.get('planetemu_roms', '')
    if not base:
        base = 'https://www.planetemu.net/roms/'
    url = f"{base}{system_slug}"
    print(f"Scraping PlanetEmu: {url}")
    from . import _facade
    cache = _facade.load_listing_cache()
    cache_key = f"planetemu:{url}"
    cached = _facade.listing_cache_get(cache, cache_key)
    if cached:
        print("  Listing PlanetEmu depuis le cache")
        return dict(cached)

    mapping = {}
    try:
        response = session.get(url, timeout=30)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            for a in soup.find_all('a', href=True):
                if '/rom/' in a['href']:
                    game_name = a.get_text().strip()
                    if game_name:
                        page_url = config.get('planetemu_base', '') + a['href']
                        mapping[game_name.lower()] = {
                            'full_name': game_name,
                            'page_url': page_url
                        }
            _facade.listing_cache_set(cache, cache_key, mapping)
            _facade.save_listing_cache(cache)
    except Exception as e:
        print(f"Erreur scraping PlanetEmu: {e}")
        
    return mapping


def download_planetemu(page_url: str, dest_path: str, session: requests.Session, progress_callback=None) -> bool:
    """Téléchargement spécifique pour PlanetEmu (POST + Token)."""
    try:
        resp = session.get(page_url, timeout=30)
        html = resp.text
        
        id_match = re.search(r'name="id"\s+value="(\d+)"', html)
        if not id_match:
            print("  [PlanetEmu] ID de ROM introuvable sur la page")
            return False
            
        rom_id = id_match.group(1)
        
        if _rom_db.ROM_DATABASE is None:
            load_rom_database()
        config = _rom_db.ROM_DATABASE.get('config_urls', {})
        download_api = config.get('planetemu_download_api', '')
        if not download_api:
             download_api = 'https://www.planetemu.net/php/roms/download.php'
             
        data = {'id': rom_id, 'download': 'T\u00e9l\u00e9charger'}
        
        resp = session.post(download_api, data=data, allow_redirects=False, timeout=30)
        
        token_url = None
        if resp.status_code == 302:
            token_url = resp.headers.get('Location')
            if token_url:
                token_url = urljoin(download_api, token_url)
        
        if not token_url:
            soup = BeautifulSoup(resp.text, 'html.parser')
            a_token = soup.find('a', href=True)
            if a_token and 'token=' in a_token['href']:
                token_url = urljoin(download_api, a_token['href'])

        if not token_url:
            print("  [PlanetEmu] Échec de génération du token")
            return False
            
        from .downloads import download_file
        return download_file(token_url, dest_path, session, progress_callback)
        
    except Exception as e:
        print(f"  [PlanetEmu] Erreur: {e}")
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
        
        session.headers.update({'Referer': page_url})
        payload = {'mediaId': media_id}
        
        with session.post(download_url, data=payload, stream=True, timeout=120) as r:
            r.raise_for_status()
            
            cd = r.headers.get('content-disposition', '')
            match = re.search(r'filename="?([^";]+)"?', cd)
            if match:
                server_filename = match.group(1)
                dest_path = os.path.join(os.path.dirname(dest_path), server_filename)
                
            total_size = int(r.headers.get('content-length', 0))
            downloaded = 0
            with open(dest_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
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
RETRO_GAME_SETS_CACHE_DIR = APP_ROOT / 'db' / 'retrogamesets'

def load_retrogamesets_database(system_slug: str, session: requests.Session) -> list:
    """Charge la base de données JSON pour un système spécifique depuis RetroGameSets."""
    global RETRO_GAME_SETS_DB
    
    if system_slug in RETRO_GAME_SETS_DB:
        return RETRO_GAME_SETS_DB[system_slug]
        
    os.makedirs(RETRO_GAME_SETS_CACHE_DIR, exist_ok=True)
    json_path = RETRO_GAME_SETS_CACHE_DIR / f"{system_slug}.json"
    
    if not json_path.exists():
        print(f"  [RetroGameSets] Téléchargement de la base de données...")
        try:
            zip_url = urljoin(RETRO_GAME_SETS_BASE, 'softs/games.zip')
            resp = session.get(zip_url, timeout=60)
            if resp.status_code == 200:
                import zipfile
                import io
                with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
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
    
    if not hasattr(resolve_retrogamesets_game, '_indices'):
        resolve_retrogamesets_game._indices = {}
        
    if system_slug not in resolve_retrogamesets_game._indices:
        index = {}
        for entry in db:
            if not isinstance(entry, list) or len(entry) < 2:
                continue
            path = entry[0]
            url = entry[1]
            
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

            table = soup.find('table', id='list')
            if table:
                for link in table.find_all('a', href=True):
                    href = link.get('href', '')
                    text = link.get_text().strip()

                    if not href or href.startswith('?') or href.startswith('.'):
                        continue
                    if text in ['Parent directory/', './', '../', '']:
                        continue
                    if href.startswith('/') or '://' in href:
                        continue

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


def search_archive_org_for_games(not_available: list) -> tuple:
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


# ── RomHustler ──────────────────────────────────────────────────────────

def _romhustler_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml',
    })
    return session


ROMHUSTLER_MAX_PAGES = 8


def list_romhustler_directory(system_slug: str, session: requests.Session) -> dict:
    if not system_slug:
        return {}
    url = f"{ROMHUSTLER_BASE}roms/{system_slug}"
    print(f"Scraping RomHustler: {url}")
    from . import _facade
    cache = _facade.load_listing_cache()
    cache_key = f"romhustler:{url}"
    cached = _facade.listing_cache_get(cache, cache_key)
    if cached:
        print("  Listing RomHustler depuis le cache")
        return dict(cached)

    mapping = {}
    try:
        page = 1
        while True:
            page_url = f"{ROMHUSTLER_BASE}roms/{system_slug}" if page == 1 else f"{ROMHUSTLER_BASE}roms/{system_slug}/{page}"
            resp = session.get(page_url, timeout=30)
            if resp.status_code != 200:
                break
            soup = BeautifulSoup(resp.text, 'html.parser')
            table = soup.find('table', class_='roms-table')
            if not table:
                break

            rows = table.find_all('tr')
            page_count = 0
            for row in rows:
                link = row.find('a', href=True)
                if not link:
                    continue
                href = link['href']
                text = link.get_text().strip()
                if not text:
                    continue
                if ROMHUSTLER_BASE in href:
                    if '/rom/' not in href:
                        continue
                elif not href.startswith('/rom/'):
                    continue
                name_no_ext = strip_rom_extension(text)
                game_page_url = href if href.startswith('http') else urljoin(ROMHUSTLER_BASE, href)
                mapping[name_no_ext.lower()] = {
                    'full_name': name_no_ext,
                    'page_url': game_page_url,
                }
                page_count += 1

            if page_count == 0:
                break

            next_link = soup.find('a', href=True, string=re.compile(r'Next', re.IGNORECASE))
            rel_next = soup.find('link', rel='next')
            has_next = bool(next_link or rel_next)
            if not has_next:
                pagination = soup.find('ul', class_='pagination') or soup.find('nav', class_='pagination')
                if pagination:
                    for a in pagination.find_all('a', href=True):
                        href = a.get('href', '')
                        if f'/roms/{system_slug}/{page + 1}' in href:
                            has_next = True
                            break
            if not has_next:
                break
            page += 1
            if page > ROMHUSTLER_MAX_PAGES:
                print(f"  [RomHustler] Pagination limitee a {ROMHUSTLER_MAX_PAGES} pages")
                break

        _facade.listing_cache_set(cache, cache_key, mapping)
        _facade.save_listing_cache(cache)
        print(f"Found {len(mapping)} files on RomHustler")
    except Exception as e:
        print(f"Erreur scraping RomHustler: {e}")
    return mapping


def resolve_romhustler_game(game_info: dict, system_slug: str, session: requests.Session) -> dict | None:
    if not system_slug:
        return None
    listing = list_romhustler_directory(system_slug, session)
    if not listing:
        return None
    candidate_name, entry = find_listing_match(game_info, listing)
    if entry:
            game_page_url = entry.get('page_url', '')
            if not game_page_url:
                return None
            try:
                resp = session.get(game_page_url, timeout=30)
                if resp.status_code != 200:
                    return None
                soup = BeautifulSoup(resp.text, 'html.parser')
                dl_link = soup.find('a', href=True, string=re.compile(r'(download|télécharger)', re.IGNORECASE))
                if not dl_link:
                    for a in soup.find_all('a', href=True):
                        if '/download/' in a.get('href', ''):
                            dl_link = a
                            break
                if dl_link:
                    href = dl_link['href']
                    dl_url = urljoin(ROMHUSTLER_BASE, href)
                    return {
                        'full_name': entry.get('full_name') or candidate_name,
                        'page_url': game_page_url,
                        'url': dl_url,
                        'filename': f"{candidate_name}.zip",
                    }
                return {
                    'full_name': entry.get('full_name') or candidate_name,
                    'page_url': game_page_url,
                    'filename': f"{candidate_name}.zip",
                }
            except Exception:
                return None
    return None


# ── CoolROM ─────────────────────────────────────────────────────────────

_COOLROM_NINTENDO_SYSTEMS = {
    'nes', 'snes', 'n64', 'nds', 'gbc', 'gba', 'gamecube', 'wii', 'vb',
}

def _coolrom_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': COOLROM_BASE,
    })
    return session


def list_coolrom_directory(system_slug: str, session: requests.Session) -> dict:
    if not system_slug:
        return {}
    if system_slug in _COOLROM_NINTENDO_SYSTEMS:
        print(f"  [CoolROM] Systeme Nintendo ({system_slug}) supprime pour droits d'auteur")
        return {}
    url = f"{COOLROM_BASE}roms/{system_slug}/"
    print(f"Scraping CoolROM: {url}")
    from . import _facade
    cache = _facade.load_listing_cache()
    cache_key = f"coolrom:{url}"
    cached = _facade.listing_cache_get(cache, cache_key)
    if cached:
        print("  Listing CoolROM depuis le cache")
        return dict(cached)

    mapping = {}
    try:
        all_url = f"{COOLROM_BASE}roms/{system_slug}/all/"
        resp = session.get(all_url, timeout=30)
        if resp.status_code != 200:
            resp = session.get(url, timeout=30)
        if resp.status_code != 200:
            print(f"Erreur CoolROM ({resp.status_code}) pour {url}")
            return mapping
        if 'removed.php' in resp.text.lower():
            print(f"  [CoolROM] Systeme {system_slug} supprime pour droits d'auteur")
            return mapping
        soup = BeautifulSoup(resp.text, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/roms/' not in href:
                continue
            if f'/roms/{system_slug}/' not in href:
                continue
            if href.endswith('/'):
                continue
            parts = href.strip('/').split('/')
            if len(parts) < 4:
                continue
            if not parts[-1].endswith('.php'):
                continue
            text = a.get_text().strip()
            if not text:
                continue
            name_no_ext = strip_rom_extension(text)
            page_url = urljoin(COOLROM_BASE, href)
            game_id_match = re.search(r'/roms/[^/]+/(\d+)/', href)
            game_id = game_id_match.group(1) if game_id_match else ''
            mapping[name_no_ext.lower()] = {
                'full_name': name_no_ext,
                'page_url': page_url,
                'game_id': game_id,
            }
        _facade.listing_cache_set(cache, cache_key, mapping)
        _facade.save_listing_cache(cache)
        print(f"Found {len(mapping)} files on CoolROM")
    except Exception as e:
        print(f"Erreur scraping CoolROM: {e}")
    return mapping


def resolve_coolrom_game(game_info: dict, system_slug: str, session: requests.Session) -> dict | None:
    if not system_slug:
        return None
    if system_slug in _COOLROM_NINTENDO_SYSTEMS:
        return None
    listing = list_coolrom_directory(system_slug, session)
    if not listing:
        return None
    candidate_name, entry = find_listing_match(game_info, listing)
    if entry:
        return {
            'full_name': entry.get('full_name') or candidate_name,
            'page_url': entry.get('page_url', ''),
            'game_id': entry.get('game_id', ''),
            'filename': f"{candidate_name}.zip",
        }
    return None


# ── NoPayStation ────────────────────────────────────────────────────────

_NPS_TSV_CACHE = {}


def _load_nopaystation_tsv(tsv_name: str, session: requests.Session) -> list:
    if tsv_name in _NPS_TSV_CACHE:
        return _NPS_TSV_CACHE[tsv_name]
    tsv_url = f"{NOPAYSTATION_BASE}tsv/{tsv_name}.tsv"
    print(f"Chargement NoPayStation TSV: {tsv_url}")
    try:
        resp = session.get(tsv_url, timeout=60)
        if resp.status_code != 200:
            print(f"  [NoPayStation] Erreur ({resp.status_code}) pour {tsv_url}")
            return []
        rows = []
        reader = csv.DictReader(resp.text.splitlines(), delimiter='\t')
        for item in reader:
            title_id = (item.get('Title ID') or '').strip()
            title = (item.get('Name') or item.get('Original Name') or '').strip()
            region = (item.get('Region') or '').strip()
            url = (item.get('PKG direct link') or item.get('URL') or '').strip()
            size = (item.get('File Size') or '').strip()
            if url.lower().startswith(('http://', 'https://')) and title:
                rows.append({
                    'title_id': title_id,
                    'title': title,
                    'region': region,
                    'url': url,
                    'size': size,
                })
        _NPS_TSV_CACHE[tsv_name] = rows
        print(f"  [NoPayStation] {len(rows)} entrees dans {tsv_name}")
        return rows
    except Exception as e:
        print(f"  [NoPayStation] Erreur chargement TSV: {e}")
        return []


def resolve_nopaystation_game(game_info: dict, tsv_name: str, session: requests.Session) -> dict | None:
    if not tsv_name:
        return None
    rows = _load_nopaystation_tsv(tsv_name, session)
    if not rows:
        return None
    listing = {}
    for row in rows:
        title = row.get('title', '').strip()
        if not title:
            continue
        listing[title.lower()] = {
            'full_name': title,
            'url': row.get('url', ''),
            'region': row.get('region', ''),
        }
    _candidate_name, entry = find_listing_match(game_info, listing, min_score=0.95)
    if entry and entry.get('url'):
        return {
            'full_name': entry.get('full_name', ''),
            'url': entry['url'],
            'filename': os.path.basename(unquote(entry['url'])),
        }
    return None


# ── StartGame.world ─────────────────────────────────────────────────────

def _startgame_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    })
    return session


def list_startgame_directory(system_slug: str, session: requests.Session) -> dict:
    if not system_slug:
        return {}
    url = f"{STARTGAME_BASE}{quote(system_slug)}/"
    print(f"Scraping StartGame: {url}")
    from . import _facade
    cache = _facade.load_listing_cache()
    cache_key = f"startgame:{url}"
    cached = _facade.listing_cache_get(cache, cache_key)
    if cached:
        print("  Listing StartGame depuis le cache")
        return dict(cached)

    mapping = {}
    try:
        resp = session.get(url, timeout=30)
        if resp.status_code != 200:
            print(f"Erreur StartGame ({resp.status_code}) pour {url}")
            return mapping
        if 'connexion-inscription' in resp.url or 'redirect_to=' in resp.url:
            print("  [StartGame] Connexion requise, listing ignore")
            return mapping
        soup = BeautifulSoup(resp.text, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href']
            text = a.get_text().strip()
            if not text or '1fichier.com' not in href:
                continue
            if '?af=' in href.lower():
                continue
            name_no_ext = strip_rom_extension(text)
            mapping[name_no_ext.lower()] = {
                'full_name': name_no_ext,
                'url': href,
            }
        _facade.listing_cache_set(cache, cache_key, mapping)
        _facade.save_listing_cache(cache)
        print(f"Found {len(mapping)} fichiers sur StartGame")
    except Exception as e:
        print(f"Erreur scraping StartGame: {e}")
    return mapping


def resolve_startgame_game(game_info: dict, system_slug: str, session: requests.Session) -> dict | None:
    if not system_slug:
        return None
    listing = list_startgame_directory(system_slug, session)
    if not listing:
        return None
    candidate_name, entry = find_listing_match(game_info, listing)
    if entry:
        return {
            'full_name': entry.get('full_name') or candidate_name,
            'url': entry['url'],
            'filename': f"{candidate_name}.zip",
        }
    return None


# ── hShop (3DS) ─────────────────────────────────────────────────────────

def _hshop_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    })
    return session


def resolve_hshop_game(game_info: dict, category: str, session: requests.Session) -> dict | None:
    if not category:
        return None
    for candidate_name in iter_game_candidate_names(game_info):
        search_url = f"{HSHOP_BASE}search?q={quote(candidate_name)}"
        try:
            resp = session.get(search_url, timeout=30)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a['href']
                text = a.get_text().strip().lower()
                candidate_lower = candidate_name.lower()
                if candidate_lower in text or text in candidate_lower:
                    page_url = urljoin(HSHOP_BASE, href)
                    return {
                        'full_name': candidate_name,
                        'page_url': page_url,
                        'filename': f"{candidate_name}.cia",
                    }
        except Exception:
            continue
    return None


# ── RomsXISOs (GitHub Pages) ────────────────────────────────────────────

_ROMSXISOS_JS_BASE = 'https://romsxisos.github.io/web/js_games/'

_romsxisos_js_cache: dict[str, list] = {}


def _romsxisos_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    })
    return session


def _gdrive_viewer_to_direct(url: str) -> str:
    """Convertit une URL Google Drive viewer en URL de telechargement direct."""
    m = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url)
    if m:
        file_id = m.group(1)
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    m = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', url)
    if m:
        file_id = m.group(1)
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url


def _parse_romsxisos_js(js_text: str) -> list[dict]:
    """Extrait les entrees ROM depuis un fichier JS RomsXISOs (const roms = [...])."""
    start_idx = js_text.find('const roms = [')
    if start_idx < 0:
        return []
    bracket_start = js_text.find('[', start_idx)
    if bracket_start < 0:
        return []
    depth = 0
    end_idx = -1
    in_string = False
    escape = False
    for i in range(bracket_start, len(js_text)):
        ch = js_text[i]
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                end_idx = i + 1
                break
    if end_idx < 0:
        return []
    raw_array = js_text[bracket_start:end_idx]
    fixed = re.sub(r'(\{|,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', raw_array)
    fixed = re.sub(r',\s*([\]\}])', r'\1', fixed)
    try:
        data = json.loads(fixed)
    except (json.JSONDecodeError, ValueError):
        return []
    results = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = entry.get('name', '').strip()
        link1 = entry.get('link1', '').strip()
        link2 = entry.get('link2', '').strip()
        size = entry.get('size', '').strip()
        if name and (link1 or link2):
            results.append({
                'name': name,
                'link1': link1,
                'link2': link2,
                'size': size,
            })
    return results


def list_romsxisos_directory(system_slug: str, session: requests.Session) -> dict:
    if not system_slug:
        return {}
    js_url = f"{_ROMSXISOS_JS_BASE}{system_slug}_games_es.js"
    print(f"Scraping RomsXISOs: {js_url}")
    from . import _facade
    cache = _facade.load_listing_cache()
    cache_key = f"romsxisos:v3:{js_url}"
    cached = _facade.listing_cache_get(cache, cache_key)
    if cached:
        print("  Listing RomsXISOs depuis le cache")
        return dict(cached)

    mapping = {}
    try:
        resp = session.get(js_url, timeout=30)
        if resp.status_code != 200:
            print(f"Erreur RomsXISOs ({resp.status_code}) pour {js_url}")
            return mapping
        entries = _parse_romsxisos_js(resp.text)
        for entry in entries:
            name_no_ext = strip_rom_extension(entry['name'])
            url = _gdrive_viewer_to_direct(entry['link1'] or entry['link2'])
            if 'myrient.' in url.lower() or 'myrient/' in url.lower():
                continue
            url_filename = os.path.basename(unquote(url.split('?', 1)[0]))
            filename = url_filename if strip_rom_extension(url_filename) != url_filename else f"{name_no_ext}.zip"
            mapping[name_no_ext.lower()] = {
                'full_name': name_no_ext,
                'url': url,
                'filename': filename,
                'size': entry.get('size', ''),
                'is_gdrive': 'drive.google.com' in url,
            }
        _facade.listing_cache_set(cache, cache_key, mapping)
        _facade.save_listing_cache(cache)
        print(f"Found {len(mapping)} fichiers sur RomsXISOs")
    except Exception as e:
        print(f"Erreur scraping RomsXISOs: {e}")
    return mapping


def resolve_romsxisos_game(game_info: dict, system_slug: str, session: requests.Session) -> dict | None:
    if not system_slug:
        return None
    listing = list_romsxisos_directory(system_slug, session)
    if not listing:
        return None
    candidate_name, entry = find_listing_match(game_info, listing)
    if entry:
        return {
            'full_name': entry.get('full_name') or candidate_name,
            'url': entry['url'],
            'filename': entry.get('filename', f"{candidate_name}.zip"),
            'is_gdrive': entry.get('is_gdrive', False),
        }
    return None


__all__ = [
    'get_lolroms_session',
    'download_lolroms_file',
    'get_vimm_session',
    'build_lolroms_url',
    'resolve_lolroms_system_path',
    'LOLROMS_SUBDIR_ALIASES',
    '_lolroms_subdir_for_system',
    'list_lolroms_directory',
    'list_edgeemu_directory',
    'iter_game_candidate_names',
    'normalize_external_game_name',
    'find_listing_match',
    'resolve_edgeemu_game',
    'list_planetemu_directory',
    'download_planetemu',
    'resolve_vimm_game',
    'download_vimm',
    'RETRO_GAME_SETS_DB',
    'RETRO_GAME_SETS_CACHE_DIR',
    'load_retrogamesets_database',
    'resolve_retrogamesets_game',
    'list_myrient_directory',
    'match_myrient_files',
    'LOLROMS_SESSION',
    'search_archive_org_for_games',
    'list_romhustler_directory',
    'resolve_romhustler_game',
    '_COOLROM_NINTENDO_SYSTEMS',
    'list_coolrom_directory',
    'resolve_coolrom_game',
    'resolve_nopaystation_game',
    'list_startgame_directory',
    'resolve_startgame_game',
    'resolve_hshop_game',
    '_ROMSXISOS_JS_BASE',
    '_gdrive_viewer_to_direct',
    '_parse_romsxisos_js',
    '_romsxisos_session',
    'list_romsxisos_directory',
    'resolve_romsxisos_game',
    '_NPS_TSV_CACHE',
]
