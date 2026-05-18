"""Compatibilite base ROM via SQLite locale unique, sans shards."""

from __future__ import annotations

from pathlib import Path

from .env import RESOURCE_ROOT
from .local_database import open_local_database


ROM_DATABASE_FILE = RESOURCE_ROOT / "rom_database.zip"
ROM_DATABASE_SHARDS_DIR = RESOURCE_ROOT / "db"
DEFAULT_CONFIG_URLS = {
    "archive_org": "https://archive.org/download/",
    "edgeemu_base": "https://edgeemu.net",
    "edgeemu_browse": "https://edgeemu.net/browse-",
    "planetemu_base": "https://www.planetemu.net",
    "planetemu_roms": "https://www.planetemu.net/roms/",
    "planetemu_download_api": "https://www.planetemu.net/php/roms/download.php",
    "1fichier_free": "https://1fichier.com/",
    "1fichier_apikeys": "https://1fichier.com/console/params.pl",
    "alldebrid_apikeys": "https://alldebrid.com/apikeys/",
    "alldebrid_unlock": "https://api.alldebrid.com/v4/link/unlock",
    "realdebrid_apikeys": "https://real-debrid.com/apitoken",
    "realdebrid_unlock": "https://api.real-debrid.com/rest/1.0/unrestrict/link",
}
ROM_DATABASE = None
ROM_DB_SHARD_CONNECTIONS = {}
ROM_DB_SHARD_CONNECTIONS_LOCK = None


def load_rom_database():
    """Charge uniquement la configuration runtime; les shards sont ignores."""
    global ROM_DATABASE
    if ROM_DATABASE is None:
        ROM_DATABASE = {
            "urls": [],
            "sources": {},
            "config_urls": DEFAULT_CONFIG_URLS.copy(),
            "storage": "sqlite",
            "shard_count": 0,
        }
    return ROM_DATABASE


def load_rom_db_shard(shard_char: str):
    """Compat: les shards ne sont plus ouverts."""
    return None, set()


def build_minerva_torrent_url_from_path(torrent_path: str) -> str:
    from urllib.parse import quote, urljoin

    torrent_path = (torrent_path or "").replace("\\", "/").lstrip("./")
    if not torrent_path:
        return ""
    if torrent_path.startswith(("http://", "https://")):
        return torrent_path
    return urljoin("https://minerva-archive.org/assets/", quote(torrent_path, safe="/"))


def is_minerva_database_result(result: dict) -> bool:
    host = (result.get("host") or "").lower()
    url = (result.get("url") or "").lower()
    torrent_url = (result.get("torrent_url") or "").lower()
    return (
        "minerva-torrent" in host
        or "minerva" in host
        or "minerva-archive.org" in url
        or "minerva-archive.org" in torrent_url
        or bool(result.get("torrent_path"))
    )


def _success_row_to_result(row) -> dict:
    host = row["provider"] or ""
    url = row["download_url"] or row["torrent_url"] or ""
    if "1fichier.com" in url:
        host = "1fichier"
    if row["torrent_url"] and "minerva" in row["torrent_url"].lower():
        host = "minerva-torrent"
    if "archive.org" in url:
        host = "archive.org"
    return {
        "md5": row["md5"] or "",
        "crc": row["crc"] or "",
        "sha1": row["sha1"] or "",
        "url": url,
        "download_url": row["download_url"] or "",
        "torrent_url": row["torrent_url"] or "",
        "host": host,
        "filename": row["download_filename"] or row["game_name"],
        "file_name": row["download_filename"] or row["game_name"],
        "full_name": row["download_filename"] or row["game_name"],
        "full_path": row["download_filename"] or row["game_name"],
        "game_name": row["game_name"],
        "size": row["size"],
    }


def _search_successes(column: str, value: str) -> list:
    value = (value or "").lower().strip()
    if not value:
        return []
    with open_local_database() as conn:
        rows = conn.execute(
            f"SELECT * FROM provider_successes WHERE {column} = ? ORDER BY created_at DESC",
            (value,),
        ).fetchall()
    return [_success_row_to_result(row) for row in rows]


def search_by_md5(md5_hash: str) -> list:
    """Recherche uniquement les providers deja valides MD5."""
    return _search_successes("md5", md5_hash)


def search_by_crc(crc_hash: str) -> list:
    return _search_successes("crc", crc_hash)


def search_by_sha1(sha1_hash: str) -> list:
    return _search_successes("sha1", sha1_hash)


def search_by_name(game_name: str) -> list:
    value = (game_name or "").lower().strip()
    if not value:
        return []
    with open_local_database() as conn:
        rows = conn.execute(
            """
            SELECT * FROM provider_successes
            WHERE lower(game_name) = ? OR lower(download_filename) = ? OR lower(game_name) LIKE ?
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (value, value, f"%{value}%"),
        ).fetchall()
    return [_success_row_to_result(row) for row in rows]


def database_result_filename(entry: dict, fallback: str = "") -> str:
    return entry.get("filename") or entry.get("full_name") or entry.get("game_name") or fallback


def add_to_shard(md5_hash: str, entry: dict, url: str = ""):
    """Compat: aucune ecriture avant succes MD5, donc rien a faire ici."""
    return False


__all__ = [
    "ROM_DATABASE_FILE",
    "ROM_DATABASE_SHARDS_DIR",
    "DEFAULT_CONFIG_URLS",
    "ROM_DATABASE",
    "ROM_DB_SHARD_CONNECTIONS",
    "ROM_DB_SHARD_CONNECTIONS_LOCK",
    "load_rom_database",
    "load_rom_db_shard",
    "build_minerva_torrent_url_from_path",
    "is_minerva_database_result",
    "search_by_md5",
    "add_to_shard",
    "search_by_crc",
    "search_by_sha1",
    "search_by_name",
    "database_result_filename",
]
