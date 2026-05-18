"""Catalogue local des systemes DAT et des jeux dans SQLite."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .dat_parser import parse_dat_file
from .dat_profile import detect_dat_profile, finalize_dat_profile
from .env import RESOURCE_ROOT
from .local_database import (
    open_local_database,
    init_local_database,
    record_provider_success,
    list_validated_providers,
)


def _system_id(dat_path: str, dat_root: Path | None = None) -> str:
    path = Path(dat_path)
    try:
        key = str(path.resolve().relative_to((dat_root or RESOURCE_ROOT).resolve()))
    except Exception:
        key = str(path.resolve())
    return hashlib.sha1(key.replace("\\", "/").lower().encode("utf-8")).hexdigest()


def _game_id(system_id: str, game_name: str) -> str:
    return hashlib.sha1(f"{system_id}:{game_name}".lower().encode("utf-8")).hexdigest()


def _rom_size(roms: list[dict]) -> int:
    total = 0
    for rom in roms or []:
        try:
            total += max(0, int(str(rom.get("size", "0")).strip() or 0))
        except (TypeError, ValueError):
            pass
    return total


def _dat_section(dat_path: Path, dat_root: Path) -> str:
    try:
        relative = dat_path.relative_to(dat_root)
        if len(relative.parts) > 1:
            return relative.parts[0]
    except Exception:
        pass
    return "dat"


def _dat_section_from_label(label: str, fallback: str = "dat") -> str:
    normalized = (label or "").replace("\\", "/").strip("/")
    if "/" in normalized:
        return normalized.split("/", 1)[0] or fallback
    return fallback or "dat"


def _dat_label_without_section(label: str, section: str) -> str:
    normalized = (label or "").replace("\\", "/")
    prefix = (section or "").strip("/\\")
    if prefix and normalized.lower().startswith(prefix.lower() + "/"):
        return normalized[len(prefix) + 1:]
    return label or ""


def _primary_signature(roms: list[dict]) -> dict:
    primary = (roms or [{}])[0]
    return {
        "md5": (primary.get("md5") or "").lower(),
        "crc": (primary.get("crc") or "").lower(),
        "sha1": (primary.get("sha1") or "").lower(),
        "size": _rom_size([primary]),
    }


def _row_to_system(row) -> dict:
    section = _dat_section_from_label(row["dat_label"], row["dat_section"])
    return {
        "system_id": row["system_id"],
        "dat_path": row["dat_path"],
        "dat_label": _dat_label_without_section(row["dat_label"], section),
        "dat_label_full": row["dat_label"],
        "dat_section": section,
        "system_name": row["system_name"],
        "family": row["family"],
        "family_label": row["family_label"],
        "is_retool": bool(row["is_retool"]),
        "game_count": row["game_count"],
        "games_count": row["game_count"],
        "total_size": row["total_size"],
        "updated_at": row["updated_at"],
    }


def _row_to_game(row, providers: list[dict], roms: list[dict]) -> dict:
    return {
        "game_id": row["game_id"],
        "system_id": row["system_id"],
        "game_name": row["game_name"],
        "primary_rom": row["primary_rom"],
        "roms": roms,
        "md5": row["md5"] or "",
        "crc": row["crc"] or "",
        "sha1": row["sha1"] or "",
        "size": row["size"],
        "providers": providers,
        "updated_at": row["updated_at"],
    }


def build_catalog_index(dat_root: str | Path | None = None, force: bool = False,
                        catalog_dir: str | Path | None = None) -> dict:
    """Construit ou met a jour l'index local des DAT dans SQLite."""
    root = Path(dat_root or (RESOURCE_ROOT / "dat"))
    init_local_database(catalog_dir)
    if not root.exists():
        return {"systems": 0, "games": 0, "dat_root": str(root)}

    if force:
        with open_local_database(catalog_dir) as conn:
            conn.execute("DELETE FROM roms")
            conn.execute("DELETE FROM games")
            conn.execute("DELETE FROM systems")

    dat_files = sorted(root.rglob("*.dat"), key=lambda path: str(path).lower())
    systems_count = 0
    games_count = 0
    now = time.time()

    with open_local_database(catalog_dir) as conn:
        for dat_path in dat_files:
            try:
                dat_games = parse_dat_file(str(dat_path))
                profile = finalize_dat_profile(detect_dat_profile(str(dat_path)))
            except Exception:
                continue

            system_id = _system_id(str(dat_path), root)
            total_size = sum(_rom_size(game.get("roms", [])) for game in dat_games.values())
            dat_label = str(dat_path.relative_to(root)) if dat_path.is_relative_to(root) else dat_path.name
            conn.execute(
                """
                INSERT OR REPLACE INTO systems
                (system_id, dat_path, dat_label, dat_section, system_name, family, family_label,
                 is_retool, game_count, total_size, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    system_id,
                    str(dat_path),
                    dat_label,
                    _dat_section(dat_path, root),
                    profile.get("system_name") or dat_path.stem,
                    profile.get("family") or "unknown",
                    profile.get("family_label") or "Inconnu",
                    1 if profile.get("is_retool") else 0,
                    len(dat_games),
                    total_size,
                    now,
                ),
            )
            conn.execute("DELETE FROM roms WHERE system_id = ?", (system_id,))
            conn.execute("DELETE FROM games WHERE system_id = ?", (system_id,))
            for game_name, game in sorted(dat_games.items(), key=lambda item: item[0].lower()):
                roms = game.get("roms", [])
                sig = _primary_signature(roms)
                game_id = _game_id(system_id, game_name)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO games
                    (game_id, system_id, game_name, primary_rom, md5, crc, sha1, size, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        game_id,
                        system_id,
                        game_name,
                        game.get("primary_rom") or "",
                        sig["md5"],
                        sig["crc"],
                        sig["sha1"],
                        _rom_size(roms),
                        now,
                    ),
                )
                for index, rom in enumerate(roms):
                    conn.execute(
                        """
                        INSERT INTO roms (game_id, system_id, position, name, size, crc, md5, sha1)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            game_id,
                            system_id,
                            index,
                            rom.get("name") or "",
                            int(str(rom.get("size", "0")).strip() or 0),
                            (rom.get("crc") or "").lower(),
                            (rom.get("md5") or "").lower(),
                            (rom.get("sha1") or "").lower(),
                        ),
                    )
            systems_count += 1
            games_count += len(dat_games)

    return {"systems": systems_count, "games": games_count, "dat_root": str(root)}


def list_catalog_systems(filters: dict | None = None, catalog_dir: str | Path | None = None) -> list[dict]:
    """Liste les systemes indexes."""
    filters = filters or {}
    query = (filters.get("query") or "").strip().lower()
    family = (filters.get("family") or "all").strip().lower()
    section = (filters.get("section") or family or "all").strip().lower()
    systems = []
    with open_local_database(catalog_dir) as conn:
        rows = conn.execute("SELECT * FROM systems ORDER BY system_name COLLATE NOCASE").fetchall()
    for row in rows:
        item = _row_to_system(row)
        if query and query not in f"{item['system_name']} {item['dat_label']}".lower():
            continue
        if section != "all" and item["dat_section"].lower() != section:
            continue
        systems.append(item)
    return sorted(systems, key=lambda item: (item["dat_section"].lower(), item["system_name"].lower(), item["dat_label"].lower()))


def list_catalog_sections(catalog_dir: str | Path | None = None) -> list[str]:
    """Liste les categories issues des dossiers sous dat/."""
    sections = {item["dat_section"] for item in list_catalog_systems(catalog_dir=catalog_dir)}
    return sorted(sections, key=str.lower)


def get_catalog_system(system_id: str, catalog_dir: str | Path | None = None) -> dict | None:
    with open_local_database(catalog_dir) as conn:
        row = conn.execute("SELECT * FROM systems WHERE system_id = ?", (system_id,)).fetchone()
    return _row_to_system(row) if row else None


def list_catalog_games(system_id: str, query: str = "", letter: str = "all",
                       catalog_dir: str | Path | None = None) -> list[dict]:
    """Liste les jeux d'un systeme indexe."""
    query = (query or "").strip().lower()
    letter = (letter or "all").strip().lower()
    games = []
    with open_local_database(catalog_dir) as conn:
        rows = conn.execute(
            "SELECT * FROM games WHERE system_id = ? ORDER BY game_name COLLATE NOCASE",
            (system_id,),
        ).fetchall()
        for row in rows:
            rom_rows = conn.execute(
                "SELECT name, size, crc, md5, sha1 FROM roms WHERE game_id = ? ORDER BY position",
                (row["game_id"],),
            ).fetchall()
            provider_rows = conn.execute(
                "SELECT * FROM provider_successes WHERE game_id = ? ORDER BY created_at DESC",
                (row["game_id"],),
            ).fetchall()
            providers = []
            for provider in provider_rows:
                metadata = {}
                try:
                    metadata = json.loads(provider["metadata_json"] or "{}")
                except Exception:
                    metadata = {}
                item = dict(metadata)
                item.update({
                    "source": provider["provider"],
                    "download_url": provider["download_url"],
                    "torrent_url": provider["torrent_url"],
                    "page_url": provider["page_url"],
                    "archive_org_identifier": provider["archive_org_identifier"],
                    "archive_org_filename": provider["archive_org_filename"],
                    "download_filename": provider["download_filename"],
                    "downloaded_path": provider["file_path"],
                    "created_at": provider["created_at"],
                })
                providers.append(item)
            roms = [dict(rom) for rom in rom_rows]
            item = _row_to_game(row, providers, roms)
            name = item["game_name"].lower()
            if query and query not in name:
                continue
            if letter not in {"", "all"}:
                first = name[:1]
                if letter == "#" and (not first or first.isalpha()):
                    continue
                if letter != "#" and first != letter:
                    continue
            games.append(item)
    return games


def update_catalog_game_providers(system_id: str, game_name: str, providers: list[dict],
                                  catalog_dir: str | Path | None = None) -> bool:
    """
    Compat: n'enregistre plus les providers candidats.
    Utiliser record_provider_success apres validation MD5 pour persister un lien.
    """
    return False


def refresh_catalog_providers(system_id: str, limit: int | None = None,
                              catalog_dir: str | Path | None = None) -> dict:
    """Compat: l'enrichissement manuel provider est desactive."""
    return {"resolved": 0, "missing": 0, "skipped": 0, "disabled": True}


__all__ = [
    "build_catalog_index",
    "list_catalog_systems",
    "list_catalog_sections",
    "get_catalog_system",
    "list_catalog_games",
    "update_catalog_game_providers",
    "refresh_catalog_providers",
    "record_provider_success",
    "list_validated_providers",
]
