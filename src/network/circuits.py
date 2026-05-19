"""Circuit-breaker pour exclure runtime les sources defaillantes, avec suivi par type d'erreur."""

from __future__ import annotations

import threading
import time

_ERROR_TYPE_THRESHOLDS = {
    "cloudflare_challenge": 5,
    "http_429": 5,
    "quota_exceeded": 3,
    "network_timeout": 10,
}

_ERROR_TYPE_RECOVERIES = {
    "cloudflare_challenge": 600,
    "http_429": 300,
    "quota_exceeded": 600,
    "network_timeout": 300,
}


class SourceCircuitBreaker:
    """Circuit-breaker en memoire par session.

    Supporte deux compteurs :
    - global : toutes les erreurs, threshold=10, recovery=300s
    - par type d'erreur : seuils et recoveries plus fins (cf _ERROR_TYPE_THRESHOLDS)
    """

    def __init__(
        self,
        failure_threshold: int = 10,
        recovery_timeout: float = 300.0,
        typed_thresholds: dict[str, int] | None = None,
        typed_recoveries: dict[str, float] | None = None,
    ):
        self.threshold = max(1, failure_threshold)
        self.recovery = max(1.0, recovery_timeout)
        self._typed_thresholds = dict(_ERROR_TYPE_THRESHOLDS)
        self._typed_recoveries = dict(_ERROR_TYPE_RECOVERIES)
        if typed_thresholds:
            self._typed_thresholds.update(typed_thresholds)
        if typed_recoveries:
            self._typed_recoveries.update(typed_recoveries)
        self._failures: dict[str, int] = {}
        self._last_failure_time: dict[str, float] = {}
        self._typed_failures: dict[tuple[str, str], int] = {}
        self._typed_last_failure: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # API existante (retrocompatible)
    # ------------------------------------------------------------------

    def is_open(self, source_name: str, error_type: str | None = None) -> bool:
        with self._lock:
            if error_type:
                return self._is_open_typed(source_name, error_type)
            return self._is_open_global(source_name)

    def record_failure(self, source_name: str, error_type: str | None = None) -> None:
        with self._lock:
            self._add_global_failure(source_name)
            if error_type:
                self._add_typed_failure(source_name, error_type)

    def record_success(self, source_name: str) -> None:
        with self._lock:
            self._failures.pop(source_name, None)
            self._last_failure_time.pop(source_name, None)
            keys_to_drop = [
                k for k in self._typed_failures if k[0] == source_name
            ]
            for k in keys_to_drop:
                self._typed_failures.pop(k, None)
                self._typed_last_failure.pop(k, None)

    # ------------------------------------------------------------------
    # Interne
    # ------------------------------------------------------------------

    def _is_open_global(self, source_name: str) -> bool:
        failures = self._failures.get(source_name, 0)
        if failures >= self.threshold:
            last = self._last_failure_time.get(source_name, 0)
            if time.time() - last < self.recovery:
                return True
            self._failures[source_name] = 0
        return False

    def _is_open_typed(self, source_name: str, error_type: str) -> bool:
        key = (source_name, error_type)
        failures = self._typed_failures.get(key, 0)
        threshold = self._typed_thresholds.get(error_type, self.threshold)
        recovery = self._typed_recoveries.get(error_type, self.recovery)
        if failures >= threshold:
            last = self._typed_last_failure.get(key, 0)
            if time.time() - last < recovery:
                return True
            self._typed_failures[key] = 0
        return False

    def _add_global_failure(self, source_name: str) -> None:
        self._failures[source_name] = self._failures.get(source_name, 0) + 1
        self._last_failure_time[source_name] = time.time()

    def _add_typed_failure(self, source_name: str, error_type: str) -> None:
        key = (source_name, error_type)
        self._typed_failures[key] = self._typed_failures.get(key, 0) + 1
        self._typed_last_failure[key] = time.time()

    # ------------------------------------------------------------------
    # Diagnostic
    # ------------------------------------------------------------------

    def status(self) -> dict[str, dict]:
        with self._lock:
            result = {}
            all_names = set(self._failures.keys()) | {k[0] for k in self._typed_failures}
            for name in all_names:
                global_failures = self._failures.get(name, 0)
                entry = {
                    "failures": global_failures,
                    "open": global_failures >= self.threshold,
                    "last_failure": self._last_failure_time.get(name),
                    "by_type": {},
                }
                for (src, etype), count in self._typed_failures.items():
                    if src != name:
                        continue
                    threshold = _ERROR_TYPE_THRESHOLDS.get(etype, self.threshold)
                    key = (src, etype)
                    entry["by_type"][etype] = {
                        "failures": count,
                        "open": count >= threshold,
                        "last_failure": self._typed_last_failure.get(key),
                        "threshold": threshold,
                    }
                result[name] = entry
            return result


__all__ = ["SourceCircuitBreaker"]
