"""Helpers testables pour le pipeline resolution/telechargement."""

from __future__ import annotations


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
            })
            status = attempt.get("status") or "failed"
            metric["attempts"] += 1
            metric[status] = metric.get(status, 0) + 1
            try:
                metric["seconds"] += float(attempt.get("duration_seconds", 0) or 0)
            except (TypeError, ValueError):
                pass
    return metrics


def failure_cause_counts(failed_items: list[dict], not_available: list[dict]) -> dict[str, int]:
    """Classe les echecs en causes stables pour rapport/statistiques."""
    causes: dict[str, int] = {}
    for _item in not_available or []:
        causes["not_found"] = causes.get("not_found", 0) + 1
    for item in failed_items or []:
        cause = "download_failed"
        attempts = item.get("provider_attempts") or []
        if attempts:
            last = attempts[-1]
            status = last.get("status") or "failed"
            detail = (last.get("detail") or item.get("error") or "").lower()
            if status == "quota_skipped":
                cause = "quota"
            elif "md5" in detail or "taille" in detail or "checksum" in detail:
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
                target[key] = target.get(key, 0) + value
    return merged
