"""Base SQLite locale unique pour catalogue, providers valides et historique."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .env import APP_ROOT
from .error_codes import classify_error, error_is_retryable, retry_delay_seconds


LOCAL_DATABASE_FILE = APP_ROOT / ".rom_downloader.sqlite"
QUEUE_TERMINAL_STATUSES = {"completed", "failed", "skipped", "not_found", "cancelled", "dry_run"}


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
            dat_mtime REAL NOT NULL DEFAULT 0,
            dat_file_size INTEGER NOT NULL DEFAULT 0,
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
        CREATE INDEX IF NOT EXISTS idx_provider_successes_provider ON provider_successes(provider);
        CREATE TABLE IF NOT EXISTS provider_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            system_id TEXT,
            game_name TEXT NOT NULL,
            provider TEXT NOT NULL,
            source_type TEXT,
            confidence REAL NOT NULL DEFAULT 0,
            download_url TEXT,
            torrent_url TEXT,
            page_url TEXT,
            archive_org_identifier TEXT,
            archive_org_filename TEXT,
            download_filename TEXT,
            size INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'resolved',
            error_code TEXT NOT NULL DEFAULT '',
            http_status INTEGER NOT NULL DEFAULT 0,
            content_type TEXT NOT NULL DEFAULT '',
            announced_size INTEGER NOT NULL DEFAULT 0,
            hash_final TEXT NOT NULL DEFAULT '',
            html_snippet TEXT NOT NULL DEFAULT '',
            provider_rank INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            last_checked_at REAL NOT NULL,
            expires_at REAL NOT NULL DEFAULT 0,
            UNIQUE(game_id, provider, download_url, torrent_url, page_url, archive_org_identifier, archive_org_filename),
            FOREIGN KEY(game_id) REFERENCES games(game_id) ON DELETE CASCADE,
            FOREIGN KEY(system_id) REFERENCES systems(system_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_provider_candidates_game ON provider_candidates(game_id, status, last_checked_at);
        CREATE INDEX IF NOT EXISTS idx_provider_candidates_provider ON provider_candidates(provider, status);
        CREATE INDEX IF NOT EXISTS idx_provider_candidates_system_provider ON provider_candidates(system_id, provider);
        CREATE INDEX IF NOT EXISTS idx_provider_candidates_expires ON provider_candidates(expires_at);
        CREATE TABLE IF NOT EXISTS download_jobs (
            job_id TEXT PRIMARY KEY,
            system_id TEXT,
            output_folder TEXT NOT NULL,
            status TEXT NOT NULL,
            total INTEGER NOT NULL DEFAULT 0,
            completed INTEGER NOT NULL DEFAULT 0,
            priority INTEGER NOT NULL DEFAULT 0,
            paused_at REAL NOT NULL DEFAULT 0,
            started_at REAL NOT NULL DEFAULT 0,
            finished_at REAL NOT NULL DEFAULT 0,
            error_count INTEGER NOT NULL DEFAULT 0,
            bytes_total INTEGER NOT NULL DEFAULT 0,
            bytes_done INTEGER NOT NULL DEFAULT 0,
            settings_json TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS download_queue_items (
            item_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            game_id TEXT,
            system_id TEXT,
            game_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            priority INTEGER NOT NULL DEFAULT 0,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            next_retry_at REAL NOT NULL DEFAULT 0,
            locked_by TEXT NOT NULL DEFAULT '',
            locked_at REAL NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            UNIQUE(job_id, game_id),
            FOREIGN KEY(job_id) REFERENCES download_jobs(job_id) ON DELETE CASCADE,
            FOREIGN KEY(game_id) REFERENCES games(game_id) ON DELETE SET NULL,
            FOREIGN KEY(system_id) REFERENCES systems(system_id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_download_queue_job_status ON download_queue_items(job_id, status, priority, created_at);
        CREATE INDEX IF NOT EXISTS idx_download_queue_game ON download_queue_items(game_id);
        CREATE TABLE IF NOT EXISTS download_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT,
            game_id TEXT,
            system_id TEXT,
            game_name TEXT NOT NULL,
            provider TEXT,
            status TEXT NOT NULL,
            error_code TEXT NOT NULL DEFAULT '',
            retryable INTEGER NOT NULL DEFAULT 0,
            next_retry_at REAL NOT NULL DEFAULT 0,
            detail TEXT,
            duration_seconds REAL NOT NULL DEFAULT 0,
            file_path TEXT,
            size INTEGER NOT NULL DEFAULT 0,
            candidate_url TEXT NOT NULL DEFAULT '',
            http_status INTEGER NOT NULL DEFAULT 0,
            content_type TEXT NOT NULL DEFAULT '',
            announced_size INTEGER NOT NULL DEFAULT 0,
            hash_final TEXT NOT NULL DEFAULT '',
            html_snippet TEXT NOT NULL DEFAULT '',
            provider_rank INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_download_attempts_created ON download_attempts(created_at);
        CREATE INDEX IF NOT EXISTS idx_download_attempts_status ON download_attempts(status);
        CREATE INDEX IF NOT EXISTS idx_download_attempts_job ON download_attempts(job_id);
        CREATE INDEX IF NOT EXISTS idx_download_attempts_game ON download_attempts(game_id);
        CREATE INDEX IF NOT EXISTS idx_download_attempts_system ON download_attempts(system_id);
        CREATE INDEX IF NOT EXISTS idx_download_jobs_status ON download_jobs(status, updated_at);
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
        CREATE TABLE IF NOT EXISTS provider_system_metrics (
            provider TEXT NOT NULL,
            system_id TEXT NOT NULL,
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
            last_failure_at REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (provider, system_id)
        );
        CREATE TABLE IF NOT EXISTS circuit_states (
            source_name TEXT PRIMARY KEY,
            failures INTEGER NOT NULL DEFAULT 0,
            last_failure_time REAL NOT NULL DEFAULT 0,
            typed_failures_json TEXT NOT NULL DEFAULT '{}',
            last_typed_failure_json TEXT NOT NULL DEFAULT '{}'
        );
        """
    )
    _ensure_column(conn, "download_jobs", "priority", "priority INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "systems", "dat_mtime", "dat_mtime REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "systems", "dat_file_size", "dat_file_size INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "download_jobs", "paused_at", "paused_at REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "download_jobs", "started_at", "started_at REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "download_jobs", "finished_at", "finished_at REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "download_jobs", "error_count", "error_count INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "download_jobs", "bytes_total", "bytes_total INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "download_jobs", "bytes_done", "bytes_done INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "download_jobs", "settings_json", "settings_json TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "download_attempts", "error_code", "error_code TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "download_attempts", "retryable", "retryable INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "download_attempts", "next_retry_at", "next_retry_at REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "download_attempts", "candidate_url", "candidate_url TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "download_attempts", "http_status", "http_status INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "download_attempts", "content_type", "content_type TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "download_attempts", "announced_size", "announced_size INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "download_attempts", "hash_final", "hash_final TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "download_attempts", "html_snippet", "html_snippet TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "download_attempts", "provider_rank", "provider_rank INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "provider_candidates", "size", "size INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "provider_candidates", "http_status", "http_status INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "provider_candidates", "content_type", "content_type TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "provider_candidates", "announced_size", "announced_size INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "provider_candidates", "hash_final", "hash_final TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "provider_candidates", "html_snippet", "html_snippet TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "provider_candidates", "provider_rank", "provider_rank INTEGER NOT NULL DEFAULT 0")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_download_attempts_error_code ON download_attempts(error_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_provider_successes_provider ON provider_successes(provider)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_provider_candidates_game ON provider_candidates(game_id, status, last_checked_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_provider_candidates_provider ON provider_candidates(provider, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_provider_candidates_system_provider ON provider_candidates(system_id, provider)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_provider_candidates_expires ON provider_candidates(expires_at)")
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS game_search_fts USING fts5("
        "game_id UNINDEXED, system_id UNINDEXED, game_name, primary_rom, "
        "content='games', content_rowid='rowid'"
        ")"
    )
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS system_search_fts USING fts5("
        "system_id UNINDEXED, system_name, "
        "content='systems', content_rowid='rowid'"
        ")"
    )
    conn.commit()
    if own_conn is not None:
        own_conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """Ajoute une colonne manquante pour migrer les bases locales existantes."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if column not in {row[1] for row in rows}:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def reset_local_database(path: str | Path | None = None) -> None:
    """Supprime la base locale et ses fichiers WAL/SHM."""
    target = local_database_path(path)
    for candidate in [target, target.with_name(target.name + "-wal"), target.with_name(target.name + "-shm")]:
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass


def _normalize_queue_item(item) -> dict:
    if isinstance(item, dict):
        return {
            "game_id": item.get("game_id") or "",
            "system_id": item.get("system_id") or "",
            "game_name": item.get("game_name") or item.get("name") or item.get("primary_rom") or "",
            "priority": int(item.get("priority") or 0),
        }
    return {"game_id": str(item or ""), "system_id": "", "game_name": "", "priority": 0}


def create_download_job(system_id: str | None, game_ids: list | None, output_folder: str,
                        path: str | Path | None = None, settings: dict | None = None,
                        priority: int = 0) -> str:
    """Cree un job de telechargement dans l'historique SQLite."""
    now = time.time()
    job_id = uuid.uuid4().hex
    queue_items = [_normalize_queue_item(item) for item in (game_ids or [])]
    with open_local_database(path) as conn:
        conn.execute(
            """
            INSERT INTO download_jobs
            (job_id, system_id, output_folder, status, total, completed, priority,
             started_at, settings_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                system_id or "",
                output_folder,
                "running",
                len(queue_items),
                0,
                int(priority or 0),
                now,
                json.dumps(settings or {}, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        for item in queue_items:
            _insert_download_queue_item(conn, job_id, system_id or item.get("system_id") or "", item, now)
    return job_id


def _insert_download_queue_item(conn: sqlite3.Connection, job_id: str, system_id: str,
                                item: dict, now: float) -> None:
    game_id = item.get("game_id") or None
    system_ref = system_id or item.get("system_id") or None
    game_name = item.get("game_name") or game_id or "Jeu inconnu"
    conn.execute(
        """
        INSERT OR IGNORE INTO download_queue_items
        (item_id, job_id, game_id, system_id, game_name, status, priority,
         attempt_count, next_retry_at, locked_by, locked_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            job_id,
            game_id,
            system_ref,
            game_name,
            "pending",
            int(item.get("priority") or 0),
            0,
            0,
            "",
            0,
            now,
            now,
        ),
    )


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
        queue = conn.execute(
            "SELECT status, COUNT(*) AS count FROM download_queue_items WHERE job_id = ? GROUP BY status",
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
        "queue": {item["status"]: item["count"] for item in queue},
    }


def list_download_jobs(status: str = "all", limit: int = 100,
                       path: str | Path | None = None) -> list[dict]:
    """Liste les jobs de telechargement persistants avec resume de queue."""
    clauses = []
    params: list = []
    normalized_status = (status or "all").strip().lower()
    if normalized_status not in {"", "all"}:
        clauses.append("LOWER(status) = ?")
        params.append(normalized_status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    jobs = []
    with open_local_database(path) as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM download_jobs
            {where}
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            [*params, max(1, int(limit or 100))],
        ).fetchall()
        for row in rows:
            queue_rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM download_queue_items WHERE job_id = ? GROUP BY status",
                (row["job_id"],),
            ).fetchall()
            item = dict(row)
            item["queue"] = {queue_row["status"]: queue_row["count"] for queue_row in queue_rows}
            jobs.append(item)
    return jobs


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
        if status in {"completed", "failed", "stopped", "cancelled"}:
            updates.append("finished_at = ?")
            params.append(time.time())
        elif status == "paused":
            updates.append("paused_at = ?")
            params.append(time.time())
    if completed is not None:
        updates.append("completed = ?")
        params.append(completed)
    params.append(job_id)
    with open_local_database(path) as conn:
        conn.execute(f"UPDATE download_jobs SET {', '.join(updates)} WHERE job_id = ?", params)


def update_download_queue_item(job_id: str, game_id: str | None = None, game_name: str | None = None,
                               status: str | None = None, priority: int | None = None,
                               next_retry_at: float | None = None, locked_by: str | None = None,
                               increment_attempts: bool = False,
                               path: str | Path | None = None) -> bool:
    """Met a jour l'etat persistant d'un jeu dans la file."""
    if not job_id or (not game_id and not game_name):
        return False
    updates = ["updated_at = ?"]
    params: list = [time.time()]
    if status is not None:
        updates.append("status = ?")
        params.append(status)
        if status in QUEUE_TERMINAL_STATUSES:
            updates.extend(["locked_by = ?", "locked_at = ?"])
            params.extend(["", 0])
    if priority is not None:
        updates.append("priority = ?")
        params.append(int(priority))
    if next_retry_at is not None:
        updates.append("next_retry_at = ?")
        params.append(float(next_retry_at))
    if locked_by is not None:
        updates.append("locked_by = ?")
        params.append(locked_by)
        updates.append("locked_at = ?")
        params.append(time.time() if locked_by else 0)
    if increment_attempts:
        updates.append("attempt_count = attempt_count + 1")

    where = ["job_id = ?"]
    params.append(job_id)
    if game_id:
        where.append("game_id = ?")
        params.append(game_id)
    else:
        where.append("game_name = ?")
        params.append(game_name or "")
    with open_local_database(path) as conn:
        cursor = conn.execute(
            f"UPDATE download_queue_items SET {', '.join(updates)} WHERE {' AND '.join(where)}",
            params,
        )
        return cursor.rowcount > 0


def pause_download_job(job_id: str, path: str | Path | None = None) -> bool:
    """Met en pause un job en cours (statut 'running' -> 'paused')."""
    with open_local_database(path) as conn:
        row = conn.execute("SELECT status FROM download_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row or row["status"] != "running":
            return False
        now = time.time()
        conn.execute(
            "UPDATE download_jobs SET status='paused', paused_at=?, updated_at=? WHERE job_id = ?",
            (now, now, job_id),
        )
        return True


def resume_download_job(job_id: str, path: str | Path | None = None) -> bool:
    """Reprend un job en pause (statut 'paused' -> 'running')."""
    with open_local_database(path) as conn:
        row = conn.execute("SELECT status FROM download_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row or row["status"] != "paused":
            return False
        now = time.time()
        conn.execute(
            "UPDATE download_jobs SET status='running', paused_at=0, updated_at=? WHERE job_id = ?",
            (now, job_id),
        )
        return True


def cancel_download_job(job_id: str, path: str | Path | None = None) -> bool:
    """Annule un job (statut 'running' ou 'paused' -> 'cancelled').
    Les items non termines passent aussi en 'cancelled'."""
    with open_local_database(path) as conn:
        row = conn.execute("SELECT status FROM download_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row or row["status"] not in {"running", "paused", "pending"}:
            return False
        now = time.time()
        conn.execute(
            "UPDATE download_jobs SET status='cancelled', finished_at=?, updated_at=? WHERE job_id = ?",
            (now, now, job_id),
        )
        conn.execute(
            "UPDATE download_queue_items SET status='cancelled', updated_at=? "
            "WHERE job_id = ? AND status NOT IN ('completed', 'failed', 'skipped', 'not_found', 'cancelled')",
            (now, job_id),
        )
        return True


def retry_failed_queue_items(job_id: str, path: str | Path | None = None,
                             error_code: str = "", retryable_only: bool = False) -> int:
    """Remet en file les items echoues ou annules d'un job, avec filtres optionnels."""
    with open_local_database(path) as conn:
        row = conn.execute("SELECT status FROM download_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            return 0
        now = time.time()
        target_error = (error_code or "").strip()
        if target_error or retryable_only:
            candidates = conn.execute(
                "SELECT item_id, game_id, game_name FROM download_queue_items "
                "WHERE job_id = ? AND status IN ('failed', 'cancelled', 'not_found')",
                (job_id,),
            ).fetchall()
            item_ids = []
            for item in candidates:
                latest = conn.execute(
                    """
                    SELECT error_code, retryable FROM download_attempts
                    WHERE job_id = ? AND (game_id = ? OR game_name = ?)
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (job_id, item["game_id"] or "", item["game_name"] or ""),
                ).fetchone()
                if not latest:
                    continue
                if target_error and latest["error_code"] != target_error:
                    continue
                if retryable_only and not latest["retryable"]:
                    continue
                item_ids.append(item["item_id"])
            if not item_ids:
                retried = 0
            else:
                placeholders = ", ".join("?" for _ in item_ids)
                cursor = conn.execute(
                    "UPDATE download_queue_items SET status='pending', updated_at=?, attempt_count=0, next_retry_at=0, locked_by='', locked_at=0 "
                    f"WHERE item_id IN ({placeholders})",
                    [now, *item_ids],
                )
                retried = cursor.rowcount
        else:
            cursor = conn.execute(
                "UPDATE download_queue_items SET status='pending', updated_at=?, attempt_count=0, next_retry_at=0, locked_by='', locked_at=0 "
                "WHERE job_id = ? AND status IN ('failed', 'cancelled', 'not_found')",
                (now, job_id),
            )
            retried = cursor.rowcount
        if retried:
            conn.execute(
                "UPDATE download_jobs SET status=?, completed=0, updated_at=? WHERE job_id = ?",
                ("running", now, job_id),
            )
        return retried


def get_job_status(job_id: str, path: str | Path | None = None) -> str:
    """Retourne le statut actuel d'un job de telechargement."""
    with open_local_database(path) as conn:
        row = conn.execute(
            "SELECT status FROM download_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
    return row["status"] if row else ""


def get_job_config(job_id: str, path: str | Path | None = None) -> dict:
    """Retourne la configuration persistante d'un job (output_folder, settings_json...)."""
    with open_local_database(path) as conn:
        row = conn.execute(
            "SELECT system_id, output_folder, settings_json, created_at FROM download_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    if not row:
        return {}
    settings = {}
    try:
        settings = json.loads(row["settings_json"] or "{}")
    except Exception:
        pass
    return {
        "system_id": row["system_id"],
        "output_folder": row["output_folder"],
        "settings": settings,
        "created_at": row["created_at"],
    }


def get_pending_queue_items_for_job(job_id: str, include_failed: bool = True,
                                    path: str | Path | None = None) -> list[dict]:
    """Retourne les items non terminaux d'un job, ordonnes par priorite."""
    statuses = ["pending"]
    if include_failed:
        statuses.extend(["failed", "cancelled", "not_found"])
    with open_local_database(path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM download_queue_items
            WHERE job_id = ? AND status IN ({})
            ORDER BY priority DESC, created_at ASC
            """.format(", ".join("?" * len(statuses))),
            [job_id, *statuses],
        ).fetchall()
    return [dict(row) for row in rows]


def save_job_progress(job_id: str, last_processed_index: int,
                      path: str | Path | None = None) -> None:
    """Sauvegarde la progression d'un job (index du dernier jeu traite)."""
    if not job_id:
        return
    now = time.time()
    config = get_job_config(job_id, path=path)
    settings = config.get("settings", {})
    settings["last_processed_index"] = last_processed_index
    with open_local_database(path) as conn:
        conn.execute(
            "UPDATE download_jobs SET settings_json = ?, updated_at = ? WHERE job_id = ?",
            (json.dumps(settings, ensure_ascii=False, sort_keys=True), now, job_id),
        )


def cleanup_stale_locks(timeout_seconds: int = 3600,
                        path: str | Path | None = None) -> dict:
    """Debloque les items verrouilles depuis trop longtemps (crash ou abandon).
    Passe les jobs dont tous les items sont terminaux en 'stopped'."""
    now = time.time()
    cutoff = now - int(timeout_seconds or 3600)
    result = {"unlocked_items": 0, "stopped_jobs": 0}
    with open_local_database(path) as conn:
        cursor = conn.execute(
            "UPDATE download_queue_items SET status='pending', locked_by='', locked_at=0, updated_at=? "
            "WHERE locked_at > 0 AND locked_at < ? AND status = 'running'",
            (now, cutoff),
        )
        result["unlocked_items"] = cursor.rowcount
        orphan_rows = conn.execute(
            "SELECT DISTINCT job_id FROM download_jobs WHERE status = 'running' AND job_id NOT IN "
            "(SELECT DISTINCT job_id FROM download_queue_items WHERE status NOT IN ('completed', 'failed', "
            "'skipped', 'not_found', 'cancelled', 'dry_run', 'stopped'))"
        ).fetchall()
        for row in orphan_rows:
            conn.execute(
                "UPDATE download_jobs SET status='stopped', finished_at=?, updated_at=? WHERE job_id = ?",
                (now, now, row["job_id"]),
            )
            result["stopped_jobs"] += 1
    return result


def _provider_metric_status(status: str, error_code: str) -> str:
    normalized = (status or "").strip().lower()
    if normalized in {"completed", "downloaded"}:
        return "downloaded"
    if normalized == "dry_run":
        return "dry_run"
    if normalized == "skipped":
        return "skipped"
    if error_code == "quota_exceeded" or normalized == "quota_skipped":
        return "quota_skipped"
    return "failed"


def record_provider_metric(provider: str, status: str, duration_seconds: float = 0.0,
                           size: int = 0, error_code: str = "",
                           created_at: float | None = None,
                           path: str | Path | None = None) -> None:
    """Met a jour les metriques SQLite d'un provider apres une tentative."""
    provider = (provider or "").strip()
    if not provider:
        return
    now = float(created_at or time.time())
    metric_status = _provider_metric_status(status, error_code)
    seconds = max(0.0, float(duration_seconds or 0))
    transferred = max(0, int(size or 0))
    average_speed = transferred / seconds if transferred and seconds else 0
    success_at = now if metric_status == "downloaded" else 0
    failure_at = now if metric_status in {"failed", "quota_skipped"} else 0
    with open_local_database(path) as conn:
        conn.execute(
            """
            INSERT INTO provider_metrics
            (provider, attempts, downloaded, failed, skipped, dry_run, quota_skipped,
             seconds, bytes, average_speed, last_success_at, last_failure_at)
            VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider) DO UPDATE SET
                attempts = provider_metrics.attempts + 1,
                downloaded = provider_metrics.downloaded + excluded.downloaded,
                failed = provider_metrics.failed + excluded.failed,
                skipped = provider_metrics.skipped + excluded.skipped,
                dry_run = provider_metrics.dry_run + excluded.dry_run,
                quota_skipped = provider_metrics.quota_skipped + excluded.quota_skipped,
                seconds = provider_metrics.seconds + excluded.seconds,
                bytes = provider_metrics.bytes + excluded.bytes,
                average_speed = CASE
                    WHEN provider_metrics.seconds + excluded.seconds > 0
                    THEN (provider_metrics.bytes + excluded.bytes) / (provider_metrics.seconds + excluded.seconds)
                    ELSE 0
                END,
                last_success_at = MAX(provider_metrics.last_success_at, excluded.last_success_at),
                last_failure_at = MAX(provider_metrics.last_failure_at, excluded.last_failure_at)
            """,
            (
                provider,
                1 if metric_status == "downloaded" else 0,
                1 if metric_status == "failed" else 0,
                1 if metric_status == "skipped" else 0,
                1 if metric_status == "dry_run" else 0,
                1 if metric_status == "quota_skipped" else 0,
                seconds,
                transferred,
                average_speed,
                success_at,
                failure_at,
            ),
        )


def record_provider_system_metric(provider: str, system_id: str, status: str,
                                   duration_seconds: float = 0.0, size: int = 0,
                                   path: str | Path | None = None) -> None:
    """Met a jour les metriques SQLite par (provider, system_id)."""
    provider = (provider or "").strip()
    system_id = (system_id or "").strip()
    if not provider or not system_id:
        return
    now = time.time()
    metric_status = _provider_metric_status(status, "")
    seconds = max(0.0, float(duration_seconds or 0))
    transferred = max(0, int(size or 0))
    average_speed = transferred / seconds if transferred and seconds else 0
    success_at = now if metric_status == "downloaded" else 0
    failure_at = now if metric_status in {"failed", "quota_skipped"} else 0
    with open_local_database(path) as conn:
        conn.execute(
            """
            INSERT INTO provider_system_metrics
            (provider, system_id, attempts, downloaded, failed, skipped, dry_run, quota_skipped,
             seconds, bytes, average_speed, last_success_at, last_failure_at)
            VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider, system_id) DO UPDATE SET
                attempts = provider_system_metrics.attempts + 1,
                downloaded = provider_system_metrics.downloaded + excluded.downloaded,
                failed = provider_system_metrics.failed + excluded.failed,
                skipped = provider_system_metrics.skipped + excluded.skipped,
                dry_run = provider_system_metrics.dry_run + excluded.dry_run,
                quota_skipped = provider_system_metrics.quota_skipped + excluded.quota_skipped,
                seconds = provider_system_metrics.seconds + excluded.seconds,
                bytes = provider_system_metrics.bytes + excluded.bytes,
                average_speed = CASE
                    WHEN provider_system_metrics.seconds + excluded.seconds > 0
                    THEN (provider_system_metrics.bytes + excluded.bytes) / (provider_system_metrics.seconds + excluded.seconds)
                    ELSE 0
                END,
                last_success_at = MAX(provider_system_metrics.last_success_at, excluded.last_success_at),
                last_failure_at = MAX(provider_system_metrics.last_failure_at, excluded.last_failure_at)
            """,
            (
                provider, system_id,
                1 if metric_status == "downloaded" else 0,
                1 if metric_status == "failed" else 0,
                1 if metric_status == "skipped" else 0,
                1 if metric_status == "dry_run" else 0,
                1 if metric_status == "quota_skipped" else 0,
                seconds, transferred, average_speed, success_at, failure_at,
            ),
        )


def list_provider_system_metrics(system_id: str = "", path: str | Path | None = None) -> dict[str, dict]:
    """Retourne les metriques SQLite par (provider, system_id), filtrees par systeme si fourni."""
    with open_local_database(path) as conn:
        if system_id:
            rows = conn.execute(
                "SELECT * FROM provider_system_metrics WHERE system_id = ? ORDER BY provider COLLATE NOCASE",
                (system_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM provider_system_metrics ORDER BY provider, system_id").fetchall()
    result: dict[str, dict] = {}
    for row in rows:
        key = f"{row['provider']}::{row['system_id']}"
        result[key] = dict(row)
    return result


def save_circuit_states(circuit_breaker: "SourceCircuitBreaker", path: str | Path | None = None) -> None:
    """Persiste l'etat du circuit-breaker dans SQLite."""
    with open_local_database(path) as conn:
        conn.execute("DELETE FROM circuit_states")
        status = circuit_breaker.status()
        for source_name, state in status.items():
            conn.execute(
                "INSERT INTO circuit_states (source_name, failures, last_failure_time, typed_failures_json, last_typed_failure_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    source_name,
                    state.get("failures", 0),
                    state.get("last_failure", 0.0) or 0.0,
                    json.dumps(state.get("by_type", {}), sort_keys=True),
                    "{}",
                ),
            )


def load_circuit_states(path: str | Path | None = None) -> dict[str, dict]:
    """Charge les etats de circuit-breaker depuis SQLite."""
    with open_local_database(path) as conn:
        rows = conn.execute("SELECT * FROM circuit_states").fetchall()
    result: dict[str, dict] = {}
    for row in rows:
        result[row["source_name"]] = {
            "failures": row["failures"],
            "last_failure": row["last_failure_time"],
            "by_type": json.loads(row["typed_failures_json"] or "{}"),
        }
    return result


def compute_provider_score(metric: dict) -> float:
    """Score pour reordonnancement (higher=better), compatible avec network/metrics.py."""
    import time as _time
    attempts = metric.get("attempts", 0)
    downloaded = metric.get("downloaded", 0)
    failed = metric.get("failed", 0)
    seconds = metric.get("seconds", 0.0)
    average_speed = metric.get("average_speed", 0.0)
    last_failure_at = float(metric.get("last_failure_at", 0) or 0)
    if attempts == 0:
        return 1.0
    success_rate = downloaded / attempts
    avg_seconds = seconds / max(attempts, 1)
    speed_bonus = min(float(average_speed or 0) / (2 * 1024 * 1024), 0.25)
    recent_failure_penalty = 0.0
    if last_failure_at and _time.time() - last_failure_at < 6 * 60 * 60:
        recent_failure_penalty = 0.15
    penalty = (failed / attempts) * 0.5 + avg_seconds * 0.01 + recent_failure_penalty
    return max(0.0, success_rate + speed_bonus - penalty)


def provider_score_breakdown(metric: dict, attempt_summary: dict | None = None) -> dict:
    """Retourne un score provider explicable pour diagnostics et source-health."""
    attempt_summary = attempt_summary or {}
    attempts = int(metric.get("attempts") or attempt_summary.get("attempt_count") or 0)
    downloaded = int(metric.get("downloaded") or attempt_summary.get("completed_count") or 0)
    failed = int(metric.get("failed") or attempt_summary.get("failure_count") or 0)
    cloudflare = int(attempt_summary.get("cloudflare_count") or 0)
    html_count = int(attempt_summary.get("html_count") or 0)
    hash_count = int(attempt_summary.get("hash_count") or 0)
    success_rate = downloaded / attempts if attempts else 0.0
    failure_rate = failed / attempts if attempts else 0.0
    cloudflare_rate = cloudflare / attempts if attempts else 0.0
    html_rate = html_count / attempts if attempts else 0.0
    hash_rate = hash_count / attempts if attempts else 0.0
    if int(metric.get("attempts") or 0):
        score = compute_provider_score(metric or {})
    elif attempts:
        score = max(0.0, success_rate - failure_rate * 0.5)
    else:
        score = 1.0
    score = max(0.0, score - cloudflare_rate * 0.25 - html_rate * 0.2 - hash_rate * 0.2)
    reasons = []
    if not attempts:
        reasons.append("aucune tentative")
    else:
        reasons.append(f"succes {success_rate:.0%}")
        if failure_rate:
            reasons.append(f"echecs {failure_rate:.0%}")
        if cloudflare_rate:
            reasons.append(f"cloudflare {cloudflare_rate:.0%}")
        if html_rate:
            reasons.append(f"html {html_rate:.0%}")
        if hash_rate:
            reasons.append(f"hash KO {hash_rate:.0%}")
        if float(metric.get("average_speed") or 0) > 0:
            reasons.append("vitesse connue")
    return {
        "score": round(score, 4),
        "success_rate": round(success_rate, 4),
        "failure_rate": round(failure_rate, 4),
        "cloudflare_rate": round(cloudflare_rate, 4),
        "html_rate": round(html_rate, 4),
        "hash_mismatch_rate": round(hash_rate, 4),
        "score_reasons": reasons,
    }


def prioritize_sources_by_system(sources: list[dict], system_id: str,
                                  path: str | Path | None = None) -> list[dict]:
    """Reordonne les sources par score SQLite per-systeme, avec fallback global."""
    system_metrics = list_provider_system_metrics(system_id, path=path)
    global_metrics_list = list_provider_metrics(path=path)

    def scored_source(src: dict) -> dict:
        name = src.get("name", "")
        composite = f"{name}::{system_id}"
        if composite in system_metrics:
            score_info = provider_score_breakdown(system_metrics[composite])
        elif name in global_metrics_list:
            score_info = provider_score_breakdown(global_metrics_list[name])
        else:
            score_info = provider_score_breakdown({})
        enriched = dict(src)
        enriched["_provider_score"] = score_info["score"]
        enriched["_provider_score_reasons"] = score_info["score_reasons"]
        return enriched

    def sort_key(src: dict) -> tuple:
        name = src.get("name", "")
        score = float(src.get("_provider_score") or 0)
        base_priority = int(src.get("priority", 50))
        order = int(src.get("order", base_priority))
        return (order, -score, base_priority, name.lower())

    scored = [scored_source(source) for source in sources]
    return sorted(scored, key=sort_key)


def list_provider_metrics(path: str | Path | None = None) -> dict[str, dict]:
    """Retourne les metriques providers stockees en SQLite."""
    with open_local_database(path) as conn:
        rows = conn.execute("SELECT * FROM provider_metrics ORDER BY provider COLLATE NOCASE").fetchall()
    return {row["provider"]: dict(row) for row in rows}


def _health_action(enabled: bool, status: str, cloudflare_count: int, html_count: int,
                   hash_count: int, failure_count: int) -> str:
    if not enabled:
        return "Reactiver la source si necessaire"
    if cloudflare_count:
        return "Tester navigateur/cache Cloudflare"
    if html_count:
        return "Verifier URL et selecteurs HTML"
    if hash_count:
        return "Verifier mapping DAT/provider"
    if status == "degraded" or failure_count:
        return "Relancer un test source"
    if status == "ok":
        return "Aucune action"
    return "Sonder des candidats"


def build_source_health_summary(sources: list[dict] | None = None,
                                path: str | Path | None = None) -> list[dict]:
    """Agrège candidates, succes, tentatives et circuits en un tableau source-health."""
    if sources is None:
        try:
            from .sources import get_default_sources
            sources = get_default_sources()
        except Exception:
            sources = []
    now = time.time()
    source_map = {
        (source.get("name") or source.get("type") or ""): source
        for source in (sources or [])
        if source.get("name") or source.get("type")
    }
    with open_local_database(path) as conn:
        metric_rows = conn.execute("SELECT * FROM provider_metrics").fetchall()
        candidate_rows = conn.execute(
            """
            SELECT provider, source_type,
                   COUNT(*) AS candidate_count,
                   COUNT(DISTINCT game_id) AS covered_games,
                   SUM(CASE WHEN status='resolved' AND (expires_at = 0 OR expires_at > ?) THEN 1 ELSE 0 END) AS active_candidates,
                   SUM(CASE WHEN expires_at > 0 AND expires_at <= ? THEN 1 ELSE 0 END) AS expired_candidates,
                   SUM(CASE WHEN status != 'resolved' OR error_code != '' THEN 1 ELSE 0 END) AS candidate_errors,
                   MAX(last_checked_at) AS last_checked_at
            FROM provider_candidates
            GROUP BY provider, source_type
            """,
            (now, now),
        ).fetchall()
        success_rows = conn.execute(
            """
            SELECT provider, COUNT(*) AS success_count, COUNT(DISTINCT game_id) AS success_games,
                   MAX(created_at) AS last_success_at
            FROM provider_successes
            GROUP BY provider
            """
        ).fetchall()
        attempt_rows = conn.execute(
            """
            SELECT provider, COUNT(*) AS attempt_count,
                   SUM(CASE WHEN status IN ('completed', 'downloaded') THEN 1 ELSE 0 END) AS completed_count,
                   SUM(CASE WHEN status IN ('failed', 'error') THEN 1 ELSE 0 END) AS failure_count,
                   SUM(CASE WHEN error_code='cloudflare_challenge' THEN 1 ELSE 0 END) AS cloudflare_count,
                   SUM(CASE WHEN error_code IN ('unexpected_html', 'html_response') THEN 1 ELSE 0 END) AS html_count,
                   SUM(CASE WHEN error_code IN ('checksum_mismatch', 'hash_mismatch') THEN 1 ELSE 0 END) AS hash_count,
                   MAX(created_at) AS last_attempt_at
            FROM download_attempts
            WHERE provider != ''
            GROUP BY provider
            """
        ).fetchall()
        latest_errors = conn.execute(
            """
            SELECT provider, error_code, detail, created_at
            FROM download_attempts
            WHERE provider != '' AND status IN ('failed', 'error', 'not_found')
            ORDER BY created_at DESC
            """
        ).fetchall()
        circuit_rows = conn.execute("SELECT * FROM circuit_states").fetchall()

    metrics = {row["provider"]: dict(row) for row in metric_rows}
    candidates = {row["provider"]: dict(row) for row in candidate_rows}
    successes = {row["provider"]: dict(row) for row in success_rows}
    attempts = {row["provider"]: dict(row) for row in attempt_rows}
    latest_error_by_provider = {}
    for row in latest_errors:
        provider = row["provider"]
        if provider not in latest_error_by_provider:
            latest_error_by_provider[provider] = dict(row)
    circuits = {row["source_name"]: dict(row) for row in circuit_rows}
    provider_names = set(source_map) | set(metrics) | set(candidates) | set(successes) | set(attempts) | set(circuits)
    rows = []
    for provider in sorted(provider_names, key=lambda value: value.lower()):
        source = source_map.get(provider, {})
        metric = metrics.get(provider, {})
        candidate = candidates.get(provider, {})
        success = successes.get(provider, {})
        attempt = attempts.get(provider, {})
        circuit = circuits.get(provider, {})
        enabled = bool(source.get("enabled", True))
        failure_count = int(metric.get("failed") or attempt.get("failure_count") or 0)
        downloaded = int(metric.get("downloaded") or success.get("success_count") or attempt.get("completed_count") or 0)
        cloudflare_count = int(attempt.get("cloudflare_count") or 0)
        html_count = int(attempt.get("html_count") or 0)
        hash_count = int(attempt.get("hash_count") or 0)
        score_info = provider_score_breakdown(metric, attempt)
        if not enabled:
            status = "disabled"
        elif int(circuit.get("failures") or 0) > 0 or cloudflare_count or html_count or (failure_count > downloaded and failure_count > 0):
            status = "degraded"
        elif downloaded or int(success.get("success_count") or 0):
            status = "ok"
        elif int(candidate.get("active_candidates") or 0):
            status = "candidate"
        else:
            status = "unknown"
        latest_error = latest_error_by_provider.get(provider, {})
        last_success = float(metric.get("last_success_at") or success.get("last_success_at") or 0)
        last_failure = float(metric.get("last_failure_at") or latest_error.get("created_at") or 0)
        last_checked = float(candidate.get("last_checked_at") or 0)
        rows.append({
            "provider": provider,
            "type": source.get("type") or candidate.get("source_type") or "",
            "enabled": enabled,
            "status": status,
            "coverage": int(candidate.get("covered_games") or 0),
            "candidate_count": int(candidate.get("candidate_count") or 0),
            "active_candidates": int(candidate.get("active_candidates") or 0),
            "expired_candidates": int(candidate.get("expired_candidates") or 0),
            "candidate_errors": int(candidate.get("candidate_errors") or 0),
            "success_count": int(success.get("success_count") or downloaded),
            "success_games": int(success.get("success_games") or 0),
            "attempt_count": int(metric.get("attempts") or attempt.get("attempt_count") or 0),
            "failure_count": failure_count,
            "average_speed": float(metric.get("average_speed") or 0),
            "last_success_at": last_success,
            "last_failure_at": last_failure,
            "last_test_at": max(last_success, last_failure, last_checked, float(attempt.get("last_attempt_at") or 0)),
            "last_error_code": latest_error.get("error_code") or "",
            "last_error": latest_error.get("detail") or "",
            "cloudflare_count": cloudflare_count,
            "html_count": html_count,
            "hash_mismatch_count": hash_count,
            **score_info,
            "circuit_state": f"failures={int(circuit.get('failures') or 0)}" if circuit else "ok",
            "recommended_action": _health_action(enabled, status, cloudflare_count, html_count, hash_count, failure_count),
        })
    rows.sort(key=lambda item: (item["status"] == "disabled", -float(item.get("score") or 0), item["provider"].lower()))
    return rows


def list_download_queue_items(filters: dict | None = None, limit: int = 1000,
                              path: str | Path | None = None) -> list[dict]:
    """Liste les jeux en file persistante."""
    filters = filters or {}
    job_id = (filters.get("job_id") or "").strip()
    status = (filters.get("status") or "all").strip().lower()
    query = (filters.get("query") or "").strip().lower()
    clauses = []
    params: list = []
    if job_id:
        clauses.append("job_id = ?")
        params.append(job_id)
    if status not in {"", "all"}:
        clauses.append("LOWER(status) = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = []
    with open_local_database(path) as conn:
        db_rows = conn.execute(
            f"""
            SELECT * FROM download_queue_items
            {where}
            ORDER BY priority DESC, created_at ASC
            LIMIT ?
            """,
            [*params, max(limit or 1000, 1)],
        ).fetchall()
    for row in db_rows:
        item = dict(row)
        if query and query not in f"{item.get('game_name', '')} {item.get('game_id', '')}".lower():
            continue
        rows.append(item)
    return rows


def get_download_job_detail(job_id: str, item_limit: int = 200, attempt_limit: int = 100,
                            path: str | Path | None = None) -> dict:
    """Retourne un detail actionnable de job: config, file et tentatives recentes."""
    if not job_id:
        return {}
    with open_local_database(path) as conn:
        job = conn.execute("SELECT * FROM download_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not job:
            return {}
        queue_rows = conn.execute(
            """
            SELECT * FROM download_queue_items
            WHERE job_id = ?
            ORDER BY
              CASE status
                WHEN 'running' THEN 0
                WHEN 'failed' THEN 1
                WHEN 'not_found' THEN 2
                WHEN 'pending' THEN 3
                ELSE 4
              END,
              priority DESC,
              updated_at DESC
            LIMIT ?
            """,
            (job_id, max(1, int(item_limit or 200))),
        ).fetchall()
        queue_counts = conn.execute(
            "SELECT status, COUNT(*) AS count FROM download_queue_items WHERE job_id = ? GROUP BY status",
            (job_id,),
        ).fetchall()
        attempt_rows = conn.execute(
            """
            SELECT * FROM download_attempts
            WHERE job_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (job_id, max(1, int(attempt_limit or 100))),
        ).fetchall()
        error_rows = conn.execute(
            """
            SELECT error_code, COUNT(*) AS count
            FROM download_attempts
            WHERE job_id = ? AND error_code NOT IN ('', 'skipped', 'dry_run')
            GROUP BY error_code
            ORDER BY count DESC, error_code
            """,
            (job_id,),
        ).fetchall()
    settings = {}
    try:
        settings = json.loads(job["settings_json"] or "{}")
    except Exception:
        settings = {}
    attempts = [dict(row) for row in attempt_rows]
    items = [dict(row) for row in queue_rows]
    retryable_count = sum(1 for attempt in attempts if attempt.get("retryable"))
    last_error = next((attempt for attempt in attempts if attempt.get("error_code") not in {"", "skipped", "dry_run"}), {})
    part_files = []
    part_bytes = 0
    output_folder_value = job["output_folder"] or ""
    output_folder = Path(output_folder_value) if output_folder_value else None
    if output_folder and output_folder.is_dir():
        for part_path in sorted(output_folder.rglob("*.part"))[:50]:
            try:
                size = part_path.stat().st_size
            except OSError:
                size = 0
            part_bytes += size
            part_files.append({"path": str(part_path), "size": size})
    next_retry_values = [
        float(item.get("next_retry_at") or 0)
        for item in items
        if float(item.get("next_retry_at") or 0) > 0
    ]
    now = time.time()
    return {
        "job": dict(job),
        "settings": settings,
        "queue": {row["status"]: row["count"] for row in queue_counts},
        "items": items,
        "attempts": attempts,
        "errors": {row["error_code"]: row["count"] for row in error_rows},
        "parts": {"count": len(part_files), "bytes": part_bytes, "files": part_files},
        "summary": {
            "retryable_recent": retryable_count,
            "next_retry_at": min(next_retry_values) if next_retry_values else 0,
            "seconds_since_update": max(0, now - float(job["updated_at"] or now)),
            "last_error_code": last_error.get("error_code") or "",
            "last_error": last_error.get("detail") or "",
            "last_provider": last_error.get("provider") or "",
        },
    }


def record_download_attempt(item: dict, path: str | Path | None = None) -> None:
    """Ajoute une tentative ou un resultat de telechargement dans SQLite."""
    now = time.time()
    status = item.get("status") or ""
    detail = item.get("detail") or item.get("error") or ""
    error_code = item.get("error_code") or classify_error(status, detail)
    retryable = bool(item.get("retryable")) if "retryable" in item else error_is_retryable(error_code)
    next_retry_at = float(item.get("next_retry_at") or 0)
    if retryable and not next_retry_at:
        next_retry_at = now + retry_delay_seconds(error_code)
    with open_local_database(path) as conn:
        conn.execute(
            """
            INSERT INTO download_attempts
            (job_id, game_id, system_id, game_name, provider, status, error_code, retryable,
             next_retry_at, detail, duration_seconds, file_path, size, candidate_url,
             http_status, content_type, announced_size, hash_final, html_snippet,
             provider_rank, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.get("job_id") or "",
                item.get("game_id") or "",
                item.get("system_id") or "",
                item.get("game_name") or "",
                item.get("provider") or item.get("source") or "",
                status,
                error_code,
                1 if retryable else 0,
                next_retry_at,
                detail,
                float(item.get("duration_seconds") or 0),
                item.get("file_path") or item.get("downloaded_path") or "",
                int(item.get("size") or 0),
                item.get("candidate_url") or item.get("download_url") or item.get("torrent_url") or item.get("page_url") or "",
                int(item.get("http_status") or 0),
                item.get("content_type") or "",
                int(item.get("announced_size") or 0),
                item.get("hash_final") or "",
                str(item.get("html_snippet") or "")[:500],
                int(item.get("provider_rank") or 0),
                float(item.get("created_at") or now),
            ),
        )
    record_provider_metric(
        item.get("provider") or item.get("source") or "",
        status,
        duration_seconds=float(item.get("duration_seconds") or 0),
        size=int(item.get("size") or 0),
        error_code=error_code,
        created_at=float(item.get("created_at") or now),
        path=path,
    )
    record_provider_system_metric(
        item.get("provider") or item.get("source") or "",
        item.get("system_id") or "",
        status,
        duration_seconds=float(item.get("duration_seconds") or 0),
        size=int(item.get("size") or 0),
        path=path,
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


def _candidate_ttl_seconds(status: str, error_code: str = "") -> int:
    """TTL pragmatique des candidates non verifiees."""
    normalized_status = (status or "").strip().lower()
    normalized_error = (error_code or "").strip().lower()
    if normalized_status == "resolved" and not normalized_error:
        return 7 * 86400
    if normalized_error in {"network_timeout", "http_429", "http_5xx", "cloudflare_challenge"}:
        return 2 * 3600
    if normalized_error == "http_404":
        return 24 * 3600
    if normalized_status in {"not_found", "missing"} or normalized_error in {"game_not_found", "provider_not_mapped"}:
        return 24 * 3600
    if normalized_error:
        return 24 * 3600
    return 7 * 86400


def record_provider_candidates(game_id: str, candidates: list[dict], status: str = "resolved",
                               error_code: str = "", ttl_seconds: int | None = None,
                               path: str | Path | None = None) -> int:
    """Persiste les providers candidats avant validation du fichier."""
    if not game_id or not candidates:
        return 0
    now = time.time()
    stored = 0
    with open_local_database(path) as conn:
        row = conn.execute(
            "SELECT game_id, system_id, game_name FROM games WHERE game_id = ?",
            (game_id,),
        ).fetchone()
        if not row:
            return 0
        for candidate in candidates:
            provider = candidate.get("source") or candidate.get("provider") or ""
            if not provider:
                continue
            candidate_status = candidate.get("status") or status or "resolved"
            candidate_error = (
                candidate.get("error_code")
                or error_code
                or classify_error(candidate_status, candidate.get("detail") or candidate.get("error") or "")
            )
            candidate_ttl = ttl_seconds if ttl_seconds is not None else _candidate_ttl_seconds(candidate_status, candidate_error)
            expires_at = now + candidate_ttl if candidate_ttl else 0
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
                    "size",
                    "http_status",
                    "content_type",
                    "announced_size",
                    "hash_final",
                    "html_snippet",
                    "provider_rank",
                }
            }
            conn.execute(
                """
                INSERT INTO provider_candidates
                (game_id, system_id, game_name, provider, source_type, confidence,
                 download_url, torrent_url, page_url, archive_org_identifier, archive_org_filename,
                 download_filename, size, status, error_code, http_status, content_type,
                 announced_size, hash_final, html_snippet, provider_rank, metadata_json, last_checked_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id, provider, download_url, torrent_url, page_url, archive_org_identifier, archive_org_filename)
                DO UPDATE SET
                    source_type = excluded.source_type,
                    confidence = excluded.confidence,
                    download_filename = excluded.download_filename,
                    size = excluded.size,
                    status = excluded.status,
                    error_code = excluded.error_code,
                    http_status = excluded.http_status,
                    content_type = excluded.content_type,
                    announced_size = excluded.announced_size,
                    hash_final = excluded.hash_final,
                    html_snippet = excluded.html_snippet,
                    provider_rank = excluded.provider_rank,
                    metadata_json = excluded.metadata_json,
                    last_checked_at = excluded.last_checked_at,
                    expires_at = excluded.expires_at
                """,
                (
                    game_id,
                    row["system_id"],
                    row["game_name"],
                    provider,
                    candidate.get("type") or "",
                    float(candidate.get("confidence") or 0),
                    candidate.get("download_url") or "",
                    candidate.get("torrent_url") or "",
                    candidate.get("page_url") or "",
                    candidate.get("archive_org_identifier") or "",
                    candidate.get("archive_org_filename") or "",
                    candidate.get("download_filename") or "",
                    int(candidate.get("size") or 0),
                    candidate_status,
                    candidate_error,
                    int(candidate.get("http_status") or 0),
                    candidate.get("content_type") or "",
                    int(candidate.get("announced_size") or 0),
                    candidate.get("hash_final") or "",
                    str(candidate.get("html_snippet") or "")[:500],
                    int(candidate.get("provider_rank") or 0),
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    now,
                    expires_at,
                ),
            )
            stored += 1
    return stored


def list_provider_candidates(game_id: str, status: str = "all",
                             path: str | Path | None = None) -> list[dict]:
    """Liste les providers candidats connus pour un jeu."""
    if not game_id:
        return []
    clauses = ["game_id = ?"]
    params: list = [game_id]
    if status not in {"", "all"}:
        clauses.append("status = ?")
        params.append(status)
    with open_local_database(path) as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM provider_candidates
            WHERE {' AND '.join(clauses)}
            ORDER BY last_checked_at DESC
            """,
            params,
        ).fetchall()
    return [_provider_candidate_row_to_dict(row) for row in rows]


def list_validated_providers(game_id: str, path: str | Path | None = None) -> list[dict]:
    """Liste les providers valides pour un jeu."""
    with open_local_database(path) as conn:
        rows = conn.execute(
            "SELECT * FROM provider_successes WHERE game_id = ? ORDER BY created_at DESC",
            (game_id,),
        ).fetchall()
    return [_provider_row_to_dict(row) for row in rows]


def _provider_candidate_row_to_dict(row: sqlite3.Row) -> dict:
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
        "type": row["source_type"],
        "source_type": row["source_type"],
        "confidence": row["confidence"],
        "download_url": row["download_url"],
        "torrent_url": row["torrent_url"],
        "page_url": row["page_url"],
        "archive_org_identifier": row["archive_org_identifier"],
        "archive_org_filename": row["archive_org_filename"],
        "download_filename": row["download_filename"],
        "size": row["size"],
        "status": row["status"],
        "error_code": row["error_code"],
        "http_status": row["http_status"],
        "content_type": row["content_type"],
        "announced_size": row["announced_size"],
        "hash_final": row["hash_final"],
        "html_snippet": row["html_snippet"],
        "provider_rank": row["provider_rank"],
        "last_checked_at": row["last_checked_at"],
        "expires_at": row["expires_at"],
    })
    return item


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
    error_code = (filters.get("error_code") or "").strip().lower()
    retryable_filter = filters.get("retryable")
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
            "error_code": row["error_code"] or "",
            "retryable": bool(row["retryable"]),
            "next_retry_at": row["next_retry_at"],
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
        if error_code and item["error_code"].lower() != error_code:
            continue
        if retryable_filter is not None and bool(item["retryable"]) != bool(retryable_filter):
            continue
        rows.append(item)
        if limit and len(rows) >= limit:
            break
    return rows


def dashboard_stats(path: str | Path | None = None) -> dict:
    """Retourne les statistiques agregees pour le tableau de bord Accueil."""
    with open_local_database(path) as conn:
        verified = conn.execute(
            "SELECT COUNT(*) FROM provider_successes"
        ).fetchone()[0]
        attempts_24h = conn.execute(
            "SELECT COUNT(*) FROM download_attempts WHERE created_at > ?",
            (time.time() - 86400,),
        ).fetchone()[0]
        avg_speed = conn.execute(
            "SELECT COALESCE(AVG(average_speed), 0) FROM provider_metrics WHERE average_speed > 0"
        ).fetchone()[0]
        jobs_active = conn.execute(
            "SELECT COUNT(*) FROM download_jobs WHERE status IN ('running', 'pending')"
        ).fetchone()[0]
        jobs_paused = conn.execute(
            "SELECT COUNT(*) FROM download_jobs WHERE status='paused'"
        ).fetchone()[0]
        jobs_failed = conn.execute(
            "SELECT COUNT(*) FROM download_jobs WHERE status='failed'"
        ).fetchone()[0]
        jobs_completed = conn.execute(
            "SELECT COUNT(*) FROM download_jobs WHERE status='completed'"
        ).fetchone()[0]
        blocked_rows = conn.execute(
            "SELECT provider FROM download_attempts "
            "WHERE error_code='cloudflare_challenge' AND created_at > ? "
            "GROUP BY provider",
            (time.time() - 300,),
        ).fetchall()
        blocked = [row["provider"] for row in blocked_rows] if blocked_rows else []
        return {
            "systems": conn.execute("SELECT COUNT(*) FROM systems").fetchone()[0],
            "games": conn.execute("SELECT COUNT(*) FROM games").fetchone()[0],
            "verified": verified,
            "valid_providers": conn.execute("SELECT COUNT(*) FROM provider_successes").fetchone()[0],
            "attempts_24h": attempts_24h,
            "average_speed": avg_speed,
            "blocked_sources": blocked,
            "jobs": {
                "active": jobs_active,
                "paused": jobs_paused,
                "failed": jobs_failed,
                "completed": jobs_completed,
            },
        }


def system_coverage_data(path: str | Path | None = None) -> list[dict]:
    """Retourne une liste de stats de couverture par systeme (ID + comptage providers candidats/valides)."""
    with open_local_database(path) as conn:
        provider_counts = {
            "candidates": {},
            "successes": {},
        }
        for kind, table in provider_counts.items():
            if table == "candidates":
                rows = conn.execute(
                    "SELECT s.system_id, COUNT(DISTINCT pc.provider) AS count "
                    "FROM systems s LEFT JOIN provider_candidates pc ON pc.system_id = s.system_id "
                    "WHERE pc.status != 'expired' "
                    "GROUP BY s.system_id"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT s.system_id, COUNT(DISTINCT ps.provider) AS count "
                    "FROM systems s LEFT JOIN provider_successes ps ON ps.system_id = s.system_id "
                    "GROUP BY s.system_id"
                ).fetchall()
            for row in rows:
                provider_counts[kind][row["system_id"]] = row["count"]
        verified = {}
        verified_rows = conn.execute(
            "SELECT s.system_id, COUNT(DISTINCT ps.game_id) AS count "
            "FROM systems s LEFT JOIN provider_successes ps ON ps.system_id = s.system_id "
            "GROUP BY s.system_id"
        ).fetchall()
        for row in verified_rows:
            verified[row["system_id"]] = row["count"]
        system_rows = conn.execute(
            "SELECT system_id, system_name, dat_section, game_count, total_size, dat_mtime FROM systems ORDER BY dat_section, system_name"
        ).fetchall()
        result = []
        for row in system_rows:
            sid = row["system_id"]
            result.append({
                "system_id": sid,
                "system_name": row["system_name"],
                "dat_section": row["dat_section"],
                "game_count": row["game_count"],
                "total_size": row["total_size"],
                "dat_date": time.strftime("%Y-%m-%d", time.localtime(row["dat_mtime"])) if row["dat_mtime"] > 0 else "",
                "candidates": provider_counts["candidates"].get(sid, 0),
                "successes": provider_counts["successes"].get(sid, 0),
                "verified_local": verified.get(sid, 0),
            })
    return result


def search_games_fts(query: str, limit: int = 100, path: str | Path | None = None) -> list[dict]:
    """Recherche plein texte dans les noms de jeux via FTS5."""
    if not query or not query.strip():
        return []
    sanitized = query.strip().replace('"', '').replace('*', '')
    if len(sanitized.split()) <= 1:
        term = f"{sanitized}*" if '*' in query else sanitized
    else:
        term = sanitized
    with open_local_database(path) as conn:
        try:
            rows = conn.execute(
                "SELECT g.* FROM game_search_fts f JOIN games g ON g.rowid = f.rowid "
                "WHERE game_search_fts MATCH ? ORDER BY rank LIMIT ?",
                (term, max(1, int(limit))),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [dict(row) for row in rows]


def search_systems_fts(query: str, limit: int = 100, path: str | Path | None = None) -> list[dict]:
    """Recherche plein texte dans les noms de systemes via FTS5."""
    if not query or not query.strip():
        return []
    sanitized = query.strip().replace('"', '').replace('*', '')
    if len(sanitized.split()) <= 1:
        term = f"{sanitized}*" if '*' in query else sanitized
    else:
        term = sanitized
    with open_local_database(path) as conn:
        try:
            rows = conn.execute(
                "SELECT s.* FROM system_search_fts f JOIN systems s ON s.rowid = f.rowid "
                "WHERE system_search_fts MATCH ? ORDER BY rank LIMIT ?",
                (term, max(1, int(limit))),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [dict(row) for row in rows]


def rebuild_fts_indexes(path: str | Path | None = None) -> dict:
    """Reconstruit les index FTS5 a partir des tables source."""
    with open_local_database(path) as conn:
        conn.execute("INSERT INTO game_search_fts(game_search_fts) VALUES('rebuild')")
        conn.execute("INSERT INTO system_search_fts(system_search_fts) VALUES('rebuild')")
    return {"games": True, "systems": True}


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
            "provider_candidates": conn.execute("SELECT COUNT(*) FROM provider_candidates").fetchone()[0],
            "provider_metrics": conn.execute("SELECT COUNT(*) FROM provider_metrics").fetchone()[0],
            "download_jobs": conn.execute("SELECT COUNT(*) FROM download_jobs").fetchone()[0],
            "download_queue_items": conn.execute("SELECT COUNT(*) FROM download_queue_items").fetchone()[0],
            "download_attempts": conn.execute("SELECT COUNT(*) FROM download_attempts").fetchone()[0],
        }


__all__ = [
    "LOCAL_DATABASE_FILE",
    "QUEUE_TERMINAL_STATUSES",
    "local_database_path",
    "open_local_database",
    "init_local_database",
    "reset_local_database",
    "create_download_job",
    "run_download_job",
    "list_download_jobs",
    "update_download_job",
    "update_download_queue_item",
    "list_download_queue_items",
    "get_download_job_detail",
    "pause_download_job",
    "resume_download_job",
    "cancel_download_job",
    "retry_failed_queue_items",
    "get_job_status",
    "get_job_config",
    "get_pending_queue_items_for_job",
    "save_job_progress",
    "cleanup_stale_locks",
    "record_provider_metric",
    "record_provider_system_metric",
    "compute_provider_score",
    "provider_score_breakdown",
    "list_provider_metrics",
    "list_provider_system_metrics",
    "prioritize_sources_by_system",
    "record_download_attempt",
    "record_provider_success",
    "record_provider_candidates",
    "list_provider_candidates",
    "list_validated_providers",
    "build_source_health_summary",
    "list_download_history",
    "database_status",
    "dashboard_stats",
    "save_circuit_states",
    "load_circuit_states",
    "system_coverage_data",
    "search_games_fts",
    "search_systems_fts",
    "rebuild_fts_indexes",
]
