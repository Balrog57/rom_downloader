"""Circuit-breaker pour exclure runtime les sources defaillantes."""

from __future__ import annotations

import threading
import time


class SourceCircuitBreaker:
    """Circuit-breaker en memoire par session (threshold=10, recovery=300s)."""

    def __init__(
        self,
        failure_threshold: int = 10,
        recovery_timeout: float = 300.0,
    ):
        self.threshold = max(1, failure_threshold)
        self.recovery = max(1.0, recovery_timeout)
        self._failures: dict[str, int] = {}
        self._last_failure_time: dict[str, float] = {}
        self._lock = threading.Lock()

    def is_open(self, source_name: str) -> bool:
        with self._lock:
            failures = self._failures.get(source_name, 0)
            if failures >= self.threshold:
                last = self._last_failure_time.get(source_name, 0)
                if time.time() - last < self.recovery:
                    return True
                self._failures[source_name] = 0
        return False

    def record_failure(self, source_name: str) -> None:
        with self._lock:
            self._failures[source_name] = self._failures.get(source_name, 0) + 1
            self._last_failure_time[source_name] = time.time()

    def record_success(self, source_name: str) -> None:
        with self._lock:
            self._failures[source_name] = 0
            self._last_failure_time.pop(source_name, None)

    def status(self) -> dict[str, dict]:
        with self._lock:
            return {
                name: {
                    "failures": count,
                    "open": count >= self.threshold,
                    "last_failure": self._last_failure_time.get(name),
                }
                for name, count in self._failures.items()
            }


__all__ = ["SourceCircuitBreaker"]
