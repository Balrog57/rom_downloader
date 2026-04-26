"""Helpers de progression et durees pour les transferts."""

from __future__ import annotations

import time


def format_duration(seconds: int | float | None) -> str:
    """Formate une duree courte pour les logs de progression."""
    try:
        total = max(0, int(seconds or 0))
    except Exception:
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


class DownloadProgressMeter:
    """Calcule debit, ETA et cadence de logs pour un transfert."""

    def __init__(self, total_size: int, resume_from: int = 0, report_interval: float = 5.0):
        self.total_size = max(0, int(total_size or 0))
        self.resume_from = max(0, int(resume_from or 0))
        self.report_interval = max(0.1, float(report_interval or 5.0))
        self.started_at = time.time()
        self.last_report_at = self.started_at

    def snapshot(self, downloaded: int):
        """Retourne les metriques si un nouveau log doit etre emis."""
        if self.total_size <= 0:
            return None
        now = time.time()
        if now - self.last_report_at < self.report_interval:
            return None
        elapsed = max(0.001, now - self.started_at)
        transferred = max(0, int(downloaded or 0) - self.resume_from)
        speed = max(0.0, transferred / elapsed)
        remaining = max(0, self.total_size - int(downloaded or 0))
        eta = remaining / speed if speed > 0 else 0
        self.last_report_at = now
        return {
            "percent": (int(downloaded or 0) / self.total_size) * 100,
            "speed": speed,
            "eta": eta,
        }
