"""Utilitaires purs sans dependances externes lourdes."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path


def load_json_file(path: Path, default):
    """Charge un JSON local en tolerant les fichiers absents ou corrompus."""
    try:
        if not path.exists():
            return default
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
        return data if isinstance(data, type(default)) else default
    except Exception:
        return default


def save_json_file(path: Path, data) -> bool:
    """Ecrit un JSON local de facon atomique."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        with open(tmp_path, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
        for attempt in range(3):
            try:
                os.replace(tmp_path, path)
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.15 * (attempt + 1))
        return True
    except Exception as e:
        try:
            if 'tmp_path' in locals() and tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        print(f"Avertissement: impossible d'ecrire {path.name}: {e}")
        return False


def format_bytes(size: int | float | None) -> str:
    """Formate une taille en unite lisible."""
    try:
        value = float(size or 0)
    except Exception:
        value = 0.0
    units = ('o', 'Ko', 'Mo', 'Go', 'To')
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != 'o' else f"{int(value)} {unit}"
        value /= 1024


__all__ = [
    "load_json_file",
    "save_json_file",
    "format_bytes",
]
