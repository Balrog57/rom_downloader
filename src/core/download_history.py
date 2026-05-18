"""Historique local des telechargements stocke dans SQLite."""

from __future__ import annotations

from pathlib import Path

from .local_database import (
    LOCAL_DATABASE_FILE,
    record_download_attempt,
    list_download_history as _list_download_history,
)


DOWNLOAD_HISTORY_FILE = LOCAL_DATABASE_FILE


def record_download_history(item: dict, path: str | Path | None = None) -> None:
    """Ajoute une entree d'historique locale dans SQLite."""
    record_download_attempt(item, path)


def list_download_history(filters: dict | None = None, limit: int = 500,
                          path: str | Path | None = None) -> list[dict]:
    """Retourne l'historique filtre depuis SQLite."""
    return _list_download_history(filters, limit, path)


__all__ = [
    "DOWNLOAD_HISTORY_FILE",
    "record_download_history",
    "list_download_history",
]
