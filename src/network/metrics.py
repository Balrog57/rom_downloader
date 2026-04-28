"""Metriques providers et reordonnancement dynamique."""

from __future__ import annotations

import json
from pathlib import Path


METRICS_FILE = Path(".rom_downloader_provider_metrics.json")


def load_provider_metrics(path: Path | str | None = None) -> dict[str, dict]:
    """Charge les metriques persistantes des providers."""
    target = Path(path or METRICS_FILE)
    if not target.exists():
        return {}
    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_provider_metrics(metrics: dict, path: Path | str | None = None) -> bool:
    """Persiste les metriques providers sur disque."""
    target = Path(path or METRICS_FILE)
    try:
        with open(target, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def compute_provider_score(metric: dict) -> float:
    """Score pour reordonnancement (higher=better)."""
    attempts = metric.get("attempts", 0)
    downloaded = metric.get("downloaded", 0)
    failed = metric.get("failed", 0)
    seconds = metric.get("seconds", 0.0)

    if attempts == 0:
        return 1.0

    success_rate = downloaded / attempts
    penalty = (failed / attempts) * 0.5 + (seconds / max(attempts, 1)) * 0.01
    return max(0.0, success_rate - penalty)


def prioritize_sources(
    sources: list[dict],
    metrics: dict[str, dict] | None = None,
) -> list[dict]:
    """Reordonne les sources selon les metriques historiques."""
    metrics = metrics or load_provider_metrics()

    def sort_key(src: dict) -> tuple:
        name = src.get("name", "")
        metric = metrics.get(name, {})
        score = compute_provider_score(metric)
        base_priority = int(src.get("priority", 50))
        order = int(src.get("order", base_priority))
        return (order, -score, base_priority, name.lower())

    return sorted(sources, key=sort_key)


def record_provider_attempt(
    metrics: dict,
    source_name: str,
    status: str,
    duration_seconds: float = 0.0,
) -> dict:
    """Enregistre une tentative provider dans les metriques."""
    metric = metrics.setdefault(
        source_name,
        {
            "attempts": 0,
            "downloaded": 0,
            "failed": 0,
            "skipped": 0,
            "dry_run": 0,
            "quota_skipped": 0,
            "seconds": 0.0,
        },
    )
    metric["attempts"] += 1
    metric[status] = metric.get(status, 0) + 1
    metric["seconds"] += duration_seconds
    return metric


__all__ = [
    "load_provider_metrics",
    "save_provider_metrics",
    "compute_provider_score",
    "prioritize_sources",
    "record_provider_attempt",
    "METRICS_FILE",
]
