"""Base SQLite locale unique pour catalogue, providers valides et historique."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .env import APP_ROOT


LOCAL_DATABASE_FILE = APP_ROOT / ".rom_downloader.sqlite"


def local_database_path(path: str | Path | None = None) -> Path:
    """Retourne le chemin SQLite local, avec compat dossier pour les tests."""
    if path is None:
        return LOCAL_DATABASE_FILE
    target = Path(path)
    if target.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
        return target
    return target / LOCAL_DATABASE_FILE.name


@contextmanager
def open_local_database(path: str | Path | None = None):
    """Ouvre une connexion SQLite initialisee."""
    target = local_database_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    init_local_database(target, conn=conn)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_local_database(path: str | Path | None = None, conn: sqlite3.Connection | None = None) -> None:
    """Cree le schema SQLite local si necessaire."""
    own_conn = None
    if conn is None:
        target = local_database_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        own_conn = sqlite3.connect(target, timeout=30, check_same_thread=False)
        conn = own_conn
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS systems (
            system_id TEXT PRIMARY KEY,
            dat_path TEXT NOT NULL UNIQUE,
            dat_label TEXT NOT NULL,
            dat_section TEXT NOT NULL,
            system_name TEXT NOT NULL,
            family TEXT NOT NULL,
            family_label TEXT NOT NULL,
            is_retool INTEGER NOT NULL DEFAULT 0,
            game_count INTEGER NOT NULL DEFAULT 0,
            total_size INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS games (
            game_id TEXT PRIMARY KEY,
            system_id TEXT NOT NULL,
            game_name TEXT NOT NULL,
            primary_rom TEXT NOT NULL,
            md5 TEXT,
            crc TEXT,
            sha1 TEXT,
            size INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL,
            UNIQUE(system_id, game_name),
            FOREIGN KEY(system_id) REFERENCES systems(system_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS roms (
            rom_id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            system_id TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            name TEXT NOT NULL,
            size INTEGER NOT NULL DEFAULT 0,
            crc TEXT,
            md5 TEXT,
            sha1 TEXT,
            FOREIGN KEY(game_id) REFERENCES games(game_id) ON DELETE CASCADE,
            FOREIGN KEY(system_id) REFERENCES systems(system_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_games_system_name ON games(system_id, game_name);
        CREATE INDEX IF NOT EXISTS idx_roms_md5 ON roms(md5);
        CREATE INDEX IF NOT EXISTS idx_roms_crc ON roms(crc);
        CREATE INDEX IF NOT EXISTS idx_roms_sha1 ON roms(sha1);
        CREATE INDEX IF NOT EXISTS idx_roms_name ON roms(name);
        CREATE TABLE IF NOT EXISTS provider_successes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            system_id TEXT,
            game_name TEXT NOT NULL,
            provider TEXT NOT NULL,
            source_type TEXT,
            download_url TEXT,
            torrent_url TEXT,
            page_url TEXT,
            archive_org_identifier TEXT,
            archive_org_filename TEXT,
            download_filename TEXT,
            file_path TEXT,
            size INTEGER NOT NULL DEFAULT 0,
            md5 TEXT,
            crc TEXT,
            sha1 TEXT,
            duration_seconds REAL NOT NULL DEFAULT 0,
            average_speed REAL NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL,
            UNIQUE(game_id, provider, download_url, torrent_url, archive_org_identifier, archive_org_filename)
        );
        CREATE INDEX IF NOT EXISTS idx_provider_successes_game ON provider_successes(game_id);
        CREATE INDEX IF NOT EXISTS idx_provider_successes_md5 ON provider_successes(md5);
        CREATE TABLE IF NOT EXISTS download_jobs (
            job_id TEXT PRIMARY KEY,
            system_id TEXT,
            output_folder TEXT NOT NULL,
            status TEXT NOT NULL,
            total INTEGER NOT NULL DEFAULT 0,
            completed INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS download_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT,
            game_id TEXT,
            system_id TEXT,
            game_name TEXT NOT NULL,
            provider TEXT,
            status TEXT NOT NULL,
            detail TEXT,
            duration_seconds REAL NOT NULL DEFAULT 0,
            file_path TEXT,
            size INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_download_attempts_created ON download_attempts(created_at);
        CREATE TABLE IF NOT EXISTS provider_metrics (
            provider TEXT PRIMARY KEY,
            attempts INTEGER NOT NULL DEFAULT 0,
            downloaded INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0,
            skipped INTEGER NOT NULL DEFAULT 0,
            dry_run INTEGER NOT NULL DEFAULT 0,
            quota_skipped INTEGER NOT NULL DEFAULT 0,
            seconds REAL NOT NULL DEFAULT 0,
            bytes INTEGER NOT NULL DEFAULT 0,
            average_speed REAL NOT NULL DEFAULT 0,
            last_success_at REAL NOT NULL DEFAULT 0,
            last_failure_at REAL NOT NULL DEFAULT 0
        );
        """
    )
    conn.commit()
    if own_conn is not None:
        own_conn.close()


def reset_local_database(path: str | Path | None = None) -> None:
    """Supprime la base locale et ses fichiers WAL/SHM."""
    target = local_database_path(path)
    for candidate in [target, target.with_name(target.name + "-wal"), target.with_name(target.name + "-shm")]:
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass


def create_download_job(system_id: str | None, game_ids: list[str] | None, output_folder: str,
                        path: str | Path | None = None) -> str:
    """Cree un job de telechargement dans l'historique SQLite."""
    now = time.time()
    job_id = uuid.uuid4().hex
    with open_local_database(path) as conn:
        conn.execute(
            """
            INSERT INTO download_jobs (job_id, system_id, output_folder, status, total, completed, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, system_id or "", output_folder, "running", len(game_ids or []), 0, now, now),
        )
    return job_id


def run_download_job(job_id: str, workers: int = 3, stop_event=None,
                     path: str | Path | None = None) -> dict:
    """
    Compat API: retourne l'etat d'un job cree dans SQLite.
    L'execution effective reste geree par download_missing_games_sequentially.
    """
    with open_local_database(path) as conn:
        row = conn.execute("SELECT * FROM download_jobs WHERE job_id = ?", (job_id,)).fetchone()
        attempts = conn.execute(
            "SELECT status, COUNT(*) AS count FROM download_attempts WHERE job_id = ? GROUP BY status",
            (job_id,),
        ).fetchall()
    if not row:
        return {"job_id": job_id, "status": "missing", "workers": workers, "attempts": {}}
    return {
        "job_id": row["job_id"],
        "system_id": row["system_id"],
        "output_folder": row["output_folder"],
        "status": row["status"],
        "total": row["total"],
        "completed": row["completed"],
        "workers": workers,
        "attempts": {item["status"]: item["count"] for item in attempts},
    }


def update_download_job(job_id: str, status: str | None = None, completed: int | None = None,
                        path: str | Path | None = None) -> None:
    """Met a jour un job de telechargement."""
    if not job_id:
        return
    updates = ["updated_at = ?"]
    params: list = [time.time()]
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if completed is not None:
        updates.append("completed = ?")
        params.append(completed)
    params.append(job_id)
    with open_local_database(path) as conn:
        conn.execute(f"UPDATE download_jobs SET {', '.join(updates)} WHERE job_id = ?", params)


def record_download_attempt(item: dict, path: str | Path | None = None) -> None:
    """Ajoute une tentative ou un resultat de telechargement dans SQLite."""
    now = time.time()
    with open_local_database(path) as conn:
        conn.execute(
            """
            INSERT INTO download_attempts
            (job_id, game_id, system_id, game_name, provider, status, detail, duration_seconds, file_path, size, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.get("job_id") or "",
                item.get("game_id") or "",
                item.get("system_id") or "",
                item.get("game_name") or "",
                item.get("provider") or item.get("source") or "",
                item.get("status") or "",
                item.get("detail") or item.get("error") or "",
                float(item.get("duration_seconds") or 0),
                item.get("file_path") or item.get("downloaded_path") or "",
                int(item.get("size") or 0),
                float(item.get("created_at") or now),
            ),
        )


def record_provider_success(game_id: str, candidate: dict, file_info: dict,
                            path: str | Path | None = None) -> None:
    """Persiste uniquement un provider qui a donne un fichier valide."""
    if not game_id:
        return
    now = time.time()
    metadata = {
        key: value
        for key, value in candidate.items()
        if key not in {
            "provider_candidates",
            "roms",
            "download_url",
            "torrent_url",
            "page_url",
            "archive_org_identifier",
            "archive_org_filename",
        }
    }
    with open_local_database(path) as conn:
        row = conn.execute(
            "SELECT game_id, system_id, game_name, md5, crc, sha1 FROM games WHERE game_id = ?",
            (game_id,),
        ).fetchone()
        if not row:
            return
        conn.execute(
            """
            INSERT OR REPLACE INTO provider_successes
            (game_id, system_id, game_name, provider, source_type, download_url, torrent_url, page_url,
             archive_org_identifier, archive_org_filename, download_filename, file_path, size, md5, crc, sha1,
             duration_seconds, average_speed, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                game_id,
                row["system_id"],
                row["game_name"],
                candidate.get("source") or candidate.get("provider") or "",
                candidate.get("type") or "",
                candidate.get("download_url") or "",
                candidate.get("torrent_url") or "",
                candidate.get("page_url") or "",
                candidate.get("archive_org_identifier") or "",
                candidate.get("archive_org_filename") or "",
                candidate.get("download_filename") or "",
                file_info.get("file_path") or file_info.get("downloaded_path") or "",
                int(file_info.get("size") or 0),
                row["md5"] or candidate.get("md5") or "",
                row["crc"] or candidate.get("crc") or "",
                row["sha1"] or candidate.get("sha1") or "",
                float(file_info.get("duration_seconds") or 0),
                float(file_info.get("average_speed") or 0),
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                now,
            ),
        )


def list_validated_providers(game_id: str, path: str | Path | None = None) -> list[dict]:
    """Liste les providers valides pour un jeu."""
    with open_local_database(path) as conn:
        rows = conn.execute(
            "SELECT * FROM provider_successes WHERE game_id = ? ORDER BY created_at DESC",
            (game_id,),
        ).fetchall()
    return [_provider_row_to_dict(row) for row in rows]


def _provider_row_to_dict(row: sqlite3.Row) -> dict:
    metadata = {}
    try:
        metadata = json.loads(row["metadata_json"] or "{}")
    except Exception:
        metadata = {}
    item = dict(metadata)
    item.update({
        "game_id": row["game_id"],
        "system_id": row["system_id"],
        "game_name": row["game_name"],
        "source": row["provider"],
        "download_url": row["download_url"],
        "torrent_url": row["torrent_url"],
        "page_url": row["page_url"],
        "archive_org_identifier": row["archive_org_identifier"],
        "archive_org_filename": row["archive_org_filename"],
        "download_filename": row["download_filename"],
        "downloaded_path": row["file_path"],
        "size": row["size"],
        "md5": row["md5"],
        "crc": row["crc"],
        "sha1": row["sha1"],
        "created_at": row["created_at"],
    })
    return item


def list_download_history(filters: dict | None = None, limit: int = 500,
                          path: str | Path | None = None) -> list[dict]:
    """Retourne l'historique depuis SQLite."""
    filters = filters or {}
    query = (filters.get("query") or "").strip().lower()
    status = (filters.get("status") or "all").strip().lower()
    system = (filters.get("system_name") or "").strip().lower()
    rows = []
    with open_local_database(path) as conn:
        db_rows = conn.execute(
            """
            SELECT a.*, s.system_name AS system_label, s.dat_path
            FROM download_attempts a
            LEFT JOIN systems s ON s.system_id = a.system_id
            ORDER BY a.created_at DESC
            LIMIT ?
            """,
            (max(limit or 500, 1) * 3,),
        ).fetchall()
    for row in db_rows:
        item = {
            "created_at": row["created_at"],
            "date": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(row["created_at"])),
            "game_name": row["game_name"],
            "system_name": row["system_label"] or row["system_id"] or "",
            "dat_path": row["dat_path"] or "",
            "provider": row["provider"] or "",
            "status": row["status"],
            "size": row["size"],
            "duration_seconds": row["duration_seconds"],
            "average_speed": (row["size"] / row["duration_seconds"]) if row["size"] and row["duration_seconds"] else 0,
            "file_path": row["file_path"] or "",
            "error": row["detail"] or "",
        }
        haystack = f"{item['game_name']} {item['system_name']} {item['provider']}".lower()
        if query and query not in haystack:
            continue
        if status not in {"", "all"} and item["status"].lower() != status:
            continue
        if system and system not in item["system_name"].lower():
            continue
        rows.append(item)
        if limit and len(rows) >= limit:
            break
    return rows


def database_status(path: str | Path | None = None) -> dict:
    """Retourne un resume de la base locale."""
    target = local_database_path(path)
    with open_local_database(path) as conn:
        return {
            "path": str(target),
            "exists": target.exists(),
            "systems": conn.execute("SELECT COUNT(*) FROM systems").fetchone()[0],
            "games": conn.execute("SELECT COUNT(*) FROM games").fetchone()[0],
            "roms": conn.execute("SELECT COUNT(*) FROM roms").fetchone()[0],
            "provider_successes": conn.execute("SELECT COUNT(*) FROM provider_successes").fetchone()[0],
            "download_attempts": conn.execute("SELECT COUNT(*) FROM download_attempts").fetchone()[0],
        }


__all__ = [
    "LOCAL_DATABASE_FILE",
    "local_database_path",
    "open_local_database",
    "init_local_database",
    "reset_local_database",
    "create_download_job",
    "run_download_job",
    "update_download_job",
    "record_download_attempt",
    "record_provider_success",
    "list_validated_providers",
    "list_download_history",
    "database_status",
]
