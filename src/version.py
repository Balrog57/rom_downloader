"""Version applicative de ROM Downloader."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _candidate_version_files() -> list[Path]:
    bundle_root = getattr(sys, "_MEIPASS", None)
    resource_root = Path(bundle_root).resolve() if bundle_root else Path(__file__).resolve().parents[1]
    app_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else resource_root
    candidates = [resource_root / "VERSION"]
    if app_root != resource_root:
        candidates.append(app_root / "VERSION")
    return candidates


def read_version() -> str:
    env_version = os.environ.get("ROM_DOWNLOADER_VERSION", "").strip()
    if env_version:
        return env_version.lstrip("v")
    for path in _candidate_version_files():
        try:
            version = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if version:
            return version.lstrip("v")
    return "0.0.0"


APP_VERSION = read_version()
