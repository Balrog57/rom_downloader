import json
import os
import re
import sqlite3
import threading
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import quote, urljoin

from .env import RESOURCE_ROOT


ROM_DATABASE_FILE = RESOURCE_ROOT / 'rom_database.zip'
ROM_DATABASE_SHARDS_DIR = RESOURCE_ROOT / 'db'
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
ROM_DB_SHARD_CONNECTIONS_LOCK = threading.Lock()


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
                print("Ajoutez les fichiers db/shard_*.zip au depot pour activer la recherche locale.")

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

    with ROM_DB_SHARD_CONNECTIONS_LOCK:
        cached = ROM_DB_SHARD_CONNECTIONS.get(shard_char)
        if cached:
            return cached['conn'], cached['columns']

        shard_zip = ROM_DATABASE_SHARDS_DIR / f"shard_{shard_char}.zip"
        shard_db_name = f"shard_{shard_char}.db"
        if not shard_zip.exists():
            return None, set()

        try:
            import zipfile as zipfile_mod

            with zipfile_mod.ZipFile(shard_zip, 'r') as zf:
                with zf.open(shard_db_name) as db_file:
                    with NamedTemporaryFile(delete=False, suffix='.db') as tmp:
                        tmp.write(db_file.read())
                        tmp_path = tmp.name

            conn = sqlite3.connect(tmp_path, check_same_thread=False)
            lock = threading.RLock()
            with lock:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(roms)").fetchall()}
            ROM_DB_SHARD_CONNECTIONS[shard_char] = {
                'conn': conn,
                'columns': columns,
                'tmp_path': tmp_path,
                'lock': lock,
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


def _get_normalize_checksum():
    from ._facade import normalize_checksum
    return normalize_checksum


def search_by_md5(md5_hash: str) -> list:
    """Recherche une ROM par MD5 dans les shards SQLite zippes."""
    normalize_checksum = _get_normalize_checksum()
    md5_hash = normalize_checksum(md5_hash, 'md5')
    if not md5_hash:
        return []

    conn, columns = load_rom_db_shard(md5_hash[0])
    if not conn:
        return []

    try:
        shard_cache = ROM_DB_SHARD_CONNECTIONS.get(md5_hash[0]) or {}
        shard_lock = shard_cache.get('lock') or threading.RLock()
        with shard_lock:
            cursor = conn.cursor()
            if 'entries' in columns:
                cursor.execute("SELECT entries, urls FROM roms WHERE md5 = ?", (md5_hash,))
                row = cursor.fetchone()
            else:
                cursor.execute("SELECT urls FROM roms WHERE md5 = ?", (md5_hash,))
                row = cursor.fetchone()

        if 'entries' in columns:
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
    """Retourne le meilleur nom de fichier disponible pour une entree de base locale."""
    return (
        entry.get('filename')
        or entry.get('full_name')
        or entry.get('game_name')
        or fallback
    )


def add_to_shard(md5_hash: str, entry: dict, url: str = ''):
    """Ajoute ou met a jour une entree ROM dans le shard correspondant.
    Permet d'enrichir la base incrementalement quand une ROM est trouvee."""
    import time
    md5_hash = (md5_hash or '').lower().strip()
    if not md5_hash or len(md5_hash) != 32:
        return False

    shard_char = md5_hash[0]
    conn, columns = load_rom_db_shard(shard_char)
    if not conn:
        return False

    shard_cache = ROM_DB_SHARD_CONNECTIONS.get(shard_char)
    if not shard_cache:
        return False
    shard_lock = shard_cache.get('lock') or threading.RLock()

    try:
        with shard_lock:
            cursor = conn.cursor()

            existing_entries = []
            existing_urls = []
            cursor.execute("SELECT entries, urls FROM roms WHERE md5 = ?", (md5_hash,))
            row = cursor.fetchone()
            if row:
                try:
                    existing_entries = json.loads(row[0] or '[]')
                except (json.JSONDecodeError, TypeError):
                    existing_entries = []
                try:
                    existing_urls = json.loads(row[1] or '[]')
                except (json.JSONDecodeError, TypeError):
                    existing_urls = []

            new_entry = {
                'host': entry.get('host', 'unknown'),
                'file_name': entry.get('file_name') or entry.get('filename') or entry.get('full_name', ''),
                'full_path': entry.get('full_path', ''),
                'size': str(entry['size']) if entry.get('size') else '',
                'crc32': entry.get('crc32') or entry.get('crc', ''),
                'sha1': entry.get('sha1', ''),
                'torrent_path': entry.get('torrent_path', ''),
                'torrent_url': entry.get('torrent_url', url),
            }

            host_lower = new_entry['host'].lower()
            duplicate = False
            for existing in existing_entries:
                if (existing.get('torrent_url') or existing.get('url', '')).lower() == (new_entry['torrent_url'] or new_entry.get('url', url)).lower():
                    duplicate = True
                    break
                if existing.get('file_name', '').lower() == new_entry['file_name'].lower() and existing.get('host', '').lower() == host_lower:
                    duplicate = True
                    break

            if not duplicate:
                existing_entries.append(new_entry)
                if url:
                    existing_urls.append(url)

            entries_json = json.dumps(existing_entries, ensure_ascii=False, separators=(',', ':'))
            urls_json = json.dumps(existing_urls, ensure_ascii=False, separators=(',', ':'))
            cursor.execute(
                "INSERT OR REPLACE INTO roms (md5, entries, urls) VALUES (?, ?, ?)",
                (md5_hash, entries_json, urls_json)
            )
            conn.commit()
        return True
    except Exception as e:
        print(f"Erreur ajout shard {shard_char}: {e}")
        return False


def search_by_crc(crc_hash: str) -> list:
    """
    Recherche une ROM par CRC dans la base locale.
    La base actuelle ne contient pas d'index CRC dedie.
    """
    return []


def search_by_sha1(sha1_hash: str) -> list:
    """
    Recherche une ROM par SHA1 dans la base locale.
    La base actuelle ne contient pas d'index SHA1 dedie.
    """
    return []


def search_by_name(game_name: str) -> list:
    """
    Recherche une ROM par son nom dans la base de donnees locale.
    """
    from ._facade import strip_rom_extension

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

__all__ = [
    'ROM_DATABASE_FILE',
    'ROM_DATABASE_SHARDS_DIR',
    'DEFAULT_CONFIG_URLS',
    'ROM_DATABASE',
    'ROM_DB_SHARD_CONNECTIONS',
    'ROM_DB_SHARD_CONNECTIONS_LOCK',
    'load_rom_database',
    'load_rom_db_shard',
    'build_minerva_torrent_url_from_path',
    'is_minerva_database_result',
    'search_by_md5',
    'database_result_filename',
    'add_to_shard',
    'search_by_crc',
    'search_by_sha1',
    'search_by_name',
]
