import html as html_module
import json
import os
import re
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
    select_database_result,
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
        LOLROMS_SESSION = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
        )
        LOLROMS_SESSION.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    return LOLROMS_SESSION


def get_cdromance_session():
    """Retourne une session Cloudflare-compatible pour CDRomance."""
    return get_lolroms_session()


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
    from . import _facade
    cache = _facade.load_listing_cache()
    cache_key = f"lolroms:{url}"
    cached = _facade.listing_cache_get(cache, cache_key)
    if cached:
        print("  Listing LoLROMs depuis le cache")
        return dict(cached)

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
        _facade.listing_cache_set(cache, cache_key, mapping)
        _facade.save_listing_cache(cache)
    except Exception as e:
        print(f"Erreur scraping LoLROMs: {e}")

    return mapping


def list_edgeemu_directory(system_slug: str, session: requests.Session) -> dict:
    """Scrape EdgeEmu pour un système donné et retourne un dict {nom_normalisé: url_téléchargement}."""
    if not system_slug:
        return {}
        
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

def resolve_cdromance_game(game_info: dict, session: requests.Session) -> dict | None:
    """Recherche un jeu sur CDRomance via leur moteur de recherche."""
    for candidate_name in iter_game_candidate_names(game_info):
        search_url = f"{CDROMANCE_BASE}?s={quote(candidate_name)}"
        try:
            resp = session.get(search_url, timeout=30)
            if resp.status_code != 200: continue
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            for link in soup.find_all('a', href=True):
                if CDROMANCE_BASE in link['href'] and any(x in link['href'] for x in ['-iso', '-rom', '-roms']):
                    title = link.get('title', '').lower() or link.get_text().strip().lower()
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
        resp = session.get(page_url, timeout=30)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        ticket = None
        ticket_el = soup.find('input', {'id': 'cdr_ticket_input'}) or soup.find('span', {'id': 'cdr_ticket'})
        if ticket_el:
            ticket = ticket_el.get('value') or ticket_el.get_text().strip()
            
        if not ticket:
            match = re.search(r'cdr_ticket\s*=\s*["\']([^"\']+)["\']', resp.text)
            if match: ticket = match.group(1)

        if not ticket:
            print("  [CDRomance] Ticket introuvable")
            return False
            
        post_data = {'cdrTicketInput': ticket}
        resp = session.post(CDROMANCE_BASE, data=post_data, timeout=30)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        dl_links = []
        for a in soup.find_all('a', href=True):
            if 'download.php' in a['href']:
                dl_links.append(urljoin(CDROMANCE_BASE, a['href']))
        
        if not dl_links:
            print("  [CDRomance] Aucun lien de téléchargement trouvé après validation du ticket")
            return False
            
        download_url = dl_links[0]
        from .downloads import download_file
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


__all__ = [
    'get_lolroms_session',
    'get_cdromance_session',
    'get_vimm_session',
    'build_lolroms_url',
    'resolve_lolroms_system_path',
    'list_lolroms_directory',
    'list_edgeemu_directory',
    'iter_game_candidate_names',
    'resolve_edgeemu_game',
    'list_planetemu_directory',
    'download_planetemu',
    'resolve_cdromance_game',
    'download_cdromance',
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
]