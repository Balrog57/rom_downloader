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
            status TEXT NOT NULL DEFAULT 'resolved',
            error_code TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            last_checked_at REAL NOT NULL,
            expires_at REAL NOT NULL DEFAULT 0,
            UNIQUE(game_id, provider, download_url, torrent_url, page_url, archive_org_identifier, archive_org_filename),
            FOREIGN KEY(game_id) REFERENCES games(game_id) ON DELETE CASCADE,
            FOREIGN KEY(system_id) REFERENCES systems(system_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_provider_candidates_game ON provider_candidates(game_id, status, last_checked_at);
        CREATE INDEX IF NOT EXISTS idx_provider_candidates_provider ON provider_candidates(provider, status);
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
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_download_attempts_created ON download_attempts(created_at);
        CREATE INDEX IF NOT EXISTS idx_download_attempts_status ON download_attempts(status);
        CREATE INDEX IF NOT EXISTS idx_download_attempts_job ON download_attempts(job_id);
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_download_attempts_error_code ON download_attempts(error_code)")
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
            system_id or item.get("system_id") or "",
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


def list_provider_metrics(path: str | Path | None = None) -> dict[str, dict]:
    """Retourne les metriques providers stockees en SQLite."""
    with open_local_database(path) as conn:
        rows = conn.execute("SELECT * FROM provider_metrics ORDER BY provider COLLATE NOCASE").fetchall()
    return {row["provider"]: dict(row) for row in rows}


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
             next_retry_at, detail, duration_seconds, file_path, size, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def record_provider_candidates(game_id: str, candidates: list[dict], status: str = "resolved",
                               error_code: str = "", ttl_seconds: int | None = None,
                               path: str | Path | None = None) -> int:
    """Persiste les providers candidats avant validation du fichier."""
    if not game_id or not candidates:
        return 0
    now = time.time()
    expires_at = now + ttl_seconds if ttl_seconds else 0
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
            conn.execute(
                """
                INSERT INTO provider_candidates
                (game_id, system_id, game_name, provider, source_type, confidence,
                 download_url, torrent_url, page_url, archive_org_identifier, archive_org_filename,
                 download_filename, status, error_code, metadata_json, last_checked_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id, provider, download_url, torrent_url, page_url, archive_org_identifier, archive_org_filename)
                DO UPDATE SET
                    source_type = excluded.source_type,
                    confidence = excluded.confidence,
                    download_filename = excluded.download_filename,
                    status = excluded.status,
                    error_code = excluded.error_code,
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
                    status,
                    error_code,
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
        "source_type": row["source_type"],
        "confidence": row["confidence"],
        "download_url": row["download_url"],
        "torrent_url": row["torrent_url"],
        "page_url": row["page_url"],
        "archive_org_identifier": row["archive_org_identifier"],
        "archive_org_filename": row["archive_org_filename"],
        "download_filename": row["download_filename"],
        "status": row["status"],
        "error_code": row["error_code"],
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
            "provider_candidates": conn.execute("SELECT COUNT(*) FROM provider_candidates").fetchone()[0],
            "download_jobs": conn.execute("SELECT COUNT(*) FROM download_jobs").fetchone()[0],
            "download_queue_items": conn.execute("SELECT COUNT(*) FROM download_queue_items").fetchone()[0],
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
    "update_download_queue_item",
    "list_download_queue_items",
    "record_provider_metric",
    "list_provider_metrics",
    "record_download_attempt",
    "record_provider_success",
    "record_provider_candidates",
    "list_provider_candidates",
    "list_validated_providers",
    "list_download_history",
    "database_status",
]
