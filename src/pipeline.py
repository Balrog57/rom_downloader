"""Helpers testables pour le pipeline resolution/telechargement."""

from __future__ import annotations

from .network.exceptions import ChecksumMismatchError, SourceTimeoutError


def aggregate_source_counts(items: list[dict]) -> dict[str, int]:
    """Compte les jeux resolus par source principale."""
    counts: dict[str, int] = {}
    for item in items or []:
        source_name = item.get("source") or "Inconnu"
        counts[source_name] = counts.get(source_name, 0) + 1
    return counts


def aggregate_provider_metrics(items: list[dict]) -> dict[str, dict]:
    """Agrege les tentatives provider en metriques exploitables par les rapports."""
    metrics: dict[str, dict] = {}
    for item in items or []:
        for attempt in item.get("provider_attempts", []) or []:
            source_name = attempt.get("source") or "Inconnu"
            metric = metrics.setdefault(source_name, {
                "attempts": 0,
                "downloaded": 0,
                "failed": 0,
                "skipped": 0,
                "dry_run": 0,
                "quota_skipped": 0,
                "seconds": 0.0,
                "bytes": 0,
                "average_speed": 0.0,
                "last_success_at": 0.0,
                "last_failure_at": 0.0,
            })
            status = attempt.get("status") or "failed"
            metric["attempts"] += 1
            metric[status] = metric.get(status, 0) + 1
            try:
                duration = float(attempt.get("duration_seconds", 0) or 0)
                metric["seconds"] += duration
            except (TypeError, ValueError):
                duration = 0.0
            try:
                transferred = int(attempt.get("bytes", 0) or 0)
            except (TypeError, ValueError):
                transferred = 0
            if transferred > 0:
                metric["bytes"] += transferred
            if status == "downloaded":
                metric["last_success_at"] = max(metric.get("last_success_at", 0.0), float(attempt.get("created_at", 0) or 0))
            elif status == "failed":
                metric["last_failure_at"] = max(metric.get("last_failure_at", 0.0), float(attempt.get("created_at", 0) or 0))
            if metric.get("seconds", 0) > 0 and metric.get("bytes", 0) > 0:
                metric["average_speed"] = metric["bytes"] / metric["seconds"]
    return metrics


def failure_cause_counts(failed_items: list[dict], not_available: list[dict]) -> dict[str, int]:
    """Classe les echecs en causes stables pour rapport/statistiques."""
    causes: dict[str, int] = {}
    for _item in not_available or []:
        causes["not_found"] = causes.get("not_found", 0) + 1
    for item in failed_items or []:
        cause = "download_failed"
        error_obj = item.get("error")
        if isinstance(error_obj, ChecksumMismatchError):
            cause = "validation"
        elif isinstance(error_obj, SourceTimeoutError):
            cause = "timeout"
        else:
            attempts = item.get("provider_attempts") or []
            if attempts:
                last = attempts[-1]
                status = last.get("status") or "failed"
                detail = (last.get("detail") or item.get("error") or "").lower()
                if status == "quota_skipped":
                    cause = "quota"
                elif "md5" in detail or "taille" in detail or "checksum" in detail or detail == "validation":
                    cause = "validation"
                elif "timeout" in detail:
                    cause = "timeout"
                elif status:
                    cause = status
            elif item.get("error"):
                cause = "exception"
        causes[cause] = causes.get(cause, 0) + 1
    return causes


def build_pipeline_summary(summary: dict) -> dict:
    """Produit un resume testable des resultats runtime."""
    resolved = summary.get("resolved_items", []) or []
    failed = summary.get("failed_items", []) or []
    not_available = summary.get("not_available", []) or []
    return {
        "source_counts": aggregate_source_counts(resolved),
        "provider_metrics": aggregate_provider_metrics(resolved + failed),
        "failure_causes": failure_cause_counts(failed, not_available),
    }


def merge_provider_metrics(existing: dict | None, incoming: dict | None) -> dict:
    """Fusionne des metriques providers en conservant un cumul persistant."""
    merged = {name: dict(values) for name, values in (existing or {}).items()}
    for source_name, values in (incoming or {}).items():
        target = merged.setdefault(source_name, {
            "attempts": 0,
            "downloaded": 0,
            "failed": 0,
            "skipped": 0,
            "dry_run": 0,
            "quota_skipped": 0,
            "seconds": 0.0,
        })
        for key, value in values.items():
            if isinstance(value, (int, float)):
                if key in {"last_success_at", "last_failure_at"}:
                    target[key] = max(target.get(key, 0), value)
                elif key == "average_speed":
                    continue
                else:
                    target[key] = target.get(key, 0) + value
        if target.get("seconds", 0) > 0 and target.get("bytes", 0) > 0:
            target["average_speed"] = target["bytes"] / target["seconds"]
    return merged
