"""Version applicative de ROM Downloader."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _candidate_version_files() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    candidates = [root / "VERSION"]
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / "VERSION")
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
