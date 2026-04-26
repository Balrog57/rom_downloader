"""Orchestration des telechargements paralleles et robustes."""

from __future__ import annotations

import concurrent.futures
import os
import time
from typing import Callable

from .sessions import (
    create_optimized_session,
    get_chunk_size,
    safe_stream_write,
    timed_request,
    DEFAULT_TIMEOUT_SECONDS,
)
from .circuits import SourceCircuitBreaker
from .cache_runtime import RuntimeCache
from .exceptions import ChecksumMismatchError
from .metrics import record_provider_attempt


class ParallelDownloadPool:
    """Pool de workers pour telecharger N fichiers en parallele."""

    def __init__(
        self,
        max_workers: int = 3,
        circuit_breaker: SourceCircuitBreaker | None = None,
        runtime_cache: RuntimeCache | None = None,
        metrics: dict[str, dict] | None = None,
    ):
        self.max_workers = max(1, max_workers)
        self.circuit = circuit_breaker or SourceCircuitBreaker()
        self.cache = runtime_cache or RuntimeCache()
        self.metrics = metrics or {}
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="download_worker_",
        )
        self._shutdown = False

    def download_game(
        self,
        game_info: dict,
        dest_folder: str,
        source_attempts: list[dict] | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        dry_run: bool = False,
        progress_callback=None,
        md5_validator: Callable[[str, dict], tuple[bool, str]] | None = None,
    ) -> dict:
        """Telecharge un jeu en essayant chaque source. Retourne dict resultat."""
        result = {
            "game_name": game_info.get("game_name", "unknown"),
            "success": False,
            "path": "",
            "source": "",
            "error": "",
            "provider_attempts": [],
        }

        for attempt in (source_attempts or []):
            source_name = attempt.get("source", "")
            source_url = attempt.get("download_url", "")
            torrent_url = attempt.get("torrent_url", "")

            if not source_name or self.circuit.is_open(source_name):
                result["provider_attempts"].append(
                    {"source": source_name, "status": "skipped", "detail": "circuit_open"}
                )
                continue

            start = time.time()
            dest_path = os.path.join(
                dest_folder, attempt.get("download_filename", "rom.zip")
            )

            if dry_run:
                duration = time.time() - start
                record_provider_attempt(self.metrics, source_name, "dry_run", duration)
                result["provider_attempts"].append(
                    {
                        "source": source_name,
                        "status": "dry_run",
                        "duration_seconds": duration,
                        "path": dest_path,
                    }
                )
                result["success"] = True
                result["path"] = dest_path
                result["source"] = source_name
                return result

            try:
                ok = False
                if torrent_url:
                    ok = self._download_torrent(torrent_url, dest_path, timeout_seconds, progress_callback)
                elif source_url:
                    ok = self._download_http(source_url, dest_path, timeout_seconds, progress_callback)

                if ok and md5_validator:
                    valid, msg = md5_validator(dest_path, game_info)
                    if not valid:
                        raise ChecksumMismatchError(msg)

                duration = time.time() - start
                record_provider_attempt(self.metrics, source_name, "downloaded", duration)
                result["provider_attempts"].append(
                    {
                        "source": source_name,
                        "status": "downloaded",
                        "duration_seconds": duration,
                        "path": dest_path,
                    }
                )
                result["success"] = True
                result["path"] = dest_path
                result["source"] = source_name
                self.circuit.record_success(source_name)
                return result

            except Exception as exc:
                duration = time.time() - start
                status = "quota_skipped" if "quota" in str(exc).lower() else "failed"
                record_provider_attempt(self.metrics, source_name, status, duration)
                result["provider_attempts"].append(
                    {
                        "source": source_name,
                        "status": status,
                        "duration_seconds": duration,
                        "detail": str(exc),
                    }
                )
                if not isinstance(exc, ChecksumMismatchError):
                    self.circuit.record_failure(source_name)
                continue

        result["error"] = "Toutes les sources ont echoue"
        return result

    def submit_download(self, game_info: dict, dest_folder: str, **kwargs):
        return self.executor.submit(self.download_game, game_info, dest_folder, **kwargs)

    def shutdown(self, wait: bool = True) -> None:
        if not self._shutdown:
            self.executor.shutdown(wait=wait)
            self._shutdown = True

    def _download_http(
        self,
        url: str,
        dest_path: str,
        timeout_seconds: int,
        progress_callback=None,
    ) -> bool:
        """Telechargement HTTP robuste avec resume et retry."""
        import re
        from urllib.parse import unquote

        session = create_optimized_session()
        max_retries = 3
        retry_delay = 3
        part_path = dest_path + ".part"

        for attempt in range(max_retries):
            try:
                resume_from = os.path.getsize(part_path) if os.path.exists(part_path) else 0
                request_kwargs = {
                    "stream": True,
                    "timeout": timeout_seconds,
                    "allow_redirects": True,
                }
                if resume_from > 0:
                    request_kwargs["headers"] = {"Range": f"bytes={resume_from}-"}

                response = timed_request(session, "GET", url, **request_kwargs)
                response.raise_for_status()

                server_filename = ""
                cd = response.headers.get("content-disposition", "")
                match = re.search(
                    r'filename=(?:"([^"]+)"|([^;]+))',
                    cd,
                    re.IGNORECASE,
                )
                if match:
                    server_filename = match.group(1) or match.group(2)
                if not server_filename:
                    server_filename = os.path.basename(
                        unquote(response.url.split("?")[0])
                    )
                current_dest = dest_path
                if server_filename:
                    server_filename = re.sub(r'[\\/*?:"<>|]', "", server_filename)
                    current_dest = os.path.join(os.path.dirname(dest_path), server_filename)
                    part_path = current_dest + ".part"
                    resume_from = os.path.getsize(part_path) if os.path.exists(part_path) else 0

                content_length = int(response.headers.get("content-length", 0))
                content_range = response.headers.get("content-range", "")
                total_size = content_length
                if content_range and "/" in content_range:
                    try:
                        total_size = int(content_range.rsplit("/", 1)[1])
                    except Exception:
                        total_size = content_length + resume_from
                elif resume_from and response.status_code == 206:
                    total_size = content_length + resume_from

                if resume_from and response.status_code != 206:
                    try:
                        os.remove(part_path)
                    except FileNotFoundError:
                        pass
                    resume_from = 0

                downloaded = resume_from
                mode = "ab" if resume_from and response.status_code == 206 else "wb"

                with open(part_path, mode) as handle:
                    downloaded = safe_stream_write(
                        response,
                        handle,
                        downloaded=downloaded,
                        total_size=total_size,
                        progress_callback=progress_callback,
                    )

                os.replace(part_path, current_dest)
                return True

            except Exception:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
                continue

        return False

    def _download_torrent(self, torrent_url, dest_path, timeout_seconds, progress_callback=None) -> bool:
        """Placeholder: delegue au legacy core.py pour l'instant."""
        return False


__all__ = ["ParallelDownloadPool", "record_provider_attempt"]
