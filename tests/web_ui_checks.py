"""Checks Web UI REST sans reseau externe."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from urllib.request import Request, urlopen


def assert_true(condition, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def _post(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(url: str) -> dict:
    with urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["ROM_DOWNLOADER_APP_ROOT"] = tmp
        from http.server import ThreadingHTTPServer
        from src.core.web_ui import _WebHandler

        tmp_path = Path(tmp)
        dat_path = tmp_path / "mini.dat"
        rom_dir = tmp_path / "roms"
        rom_dir.mkdir()
        dat_path.write_text("""<?xml version="1.0"?>
<datafile>
  <header><name>Web Test</name></header>
  <game name="Alpha"><rom name="alpha.bin" size="4" md5="e2fc714c4727ee9395f324cd2e7f331f"/></game>
</datafile>
""", encoding="utf-8")

        server = ThreadingHTTPServer(("127.0.0.1", 0), _WebHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            status = _get(base + "/api/status")
            assert_true("path" in status, "status API shape failed")
            source_health = _get(base + "/api/source/health")
            assert_true(isinstance(source_health, list), "source health API shape failed")
            retryable_history = _get(base + "/api/history?status=failed&retryable=1")
            assert_true(isinstance(retryable_history, list), "history retryable API shape failed")
            analysis = _post(base + "/api/analyze", {"dat_path": str(dat_path), "rom_folder": str(rom_dir)})
            assert_true(analysis.get("missing_games") == 1, "analyze API missing count failed")
            created = _post(base + "/api/job/create", {"dat_path": str(dat_path), "rom_folder": str(rom_dir), "output_folder": str(rom_dir)})
            assert_true(created.get("queued") == 1 and created.get("job_id"), "job create API failed")
            job = _get(base + "/api/job/status?id=" + created["job_id"])
            assert_true(job.get("job_id") == created["job_id"], "job status API failed")
            detail = _get(base + "/api/job/detail?id=" + created["job_id"])
            assert_true(detail.get("job", {}).get("job_id") == created["job_id"] and "items" in detail, "job detail API failed")
            paused = _post(base + "/api/job/pause", {"job_id": created["job_id"]})
            assert_true(paused.get("ok") is True, "job pause API failed")
            resumed = _post(base + "/api/job/resume", {"job_id": created["job_id"]})
            assert_true(resumed.get("ok") is True, "job resume API failed")
            retried = _post(base + "/api/job/retry", {"job_id": created["job_id"]})
            assert_true("retried" in retried, "job retry API failed")
            retried_filtered = _post(base + "/api/job/retry", {"job_id": created["job_id"], "retryable_only": True})
            assert_true("retried" in retried_filtered, "job retry filtered API failed")
            orphan_part = rom_dir / "orphan.bin.part"
            orphan_part.write_bytes(b"partial")
            cleaned_parts = _post(base + "/api/job/cleanup-parts", {"job_id": created["job_id"]})
            assert_true(cleaned_parts.get("removed") == 1 and not orphan_part.exists(), "job cleanup parts API failed")
            cancelled = _post(base + "/api/job/cancel", {"job_id": created["job_id"]})
            assert_true(cancelled.get("ok") is True, "job cancel API failed")
            policy = _post(base + "/api/source/policy", {"source": "LoLROMs", "delay_seconds": 9})
            assert_true(policy.get("policy", {}).get("delay_seconds") == 9, "source policy API failed")
            cleared = _post(base + "/api/cache/clear", {})
            assert_true(cleared.get("ok") is True, "cache clear API failed")
        finally:
            server.shutdown()
            server.server_close()
    print("web ui checks ok")


if __name__ == "__main__":
    main()
