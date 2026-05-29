"""Logging structure minimal pour les erreurs silencieuses."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from ..core.env import APP_ROOT

_logger: logging.Logger | None = None
_log_file: Path | None = None


def setup_logging(log_file: str | Path | None = None) -> logging.Logger:
    """Configure le logger applicatif. Appele au demarrage."""
    global _logger, _log_file
    if _logger is not None:
        return _logger

    target = Path(log_file) if log_file else (APP_ROOT / "rom_downloader.log")
    _log_file = target

    _logger = logging.getLogger("rom_downloader")
    _logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(str(target), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    _logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    _logger.addHandler(ch)

    _logger.info("Logging initialise: %s", target)
    return _logger


def get_logger() -> logging.Logger:
    """Retourne le logger applicatif, l'initialise si necessaire."""
    global _logger
    if _logger is None:
        _logger = setup_logging()
    return _logger


def log_exception(module: str, message: str, exc: Exception | None = None):
    """Log une exception avec traceback dans le fichier de log."""
    logger = get_logger()
    if exc:
        logger.error("[%s] %s: %s", module, message, exc, exc_info=True)
    else:
        logger.error("[%s] %s", module, message, exc_info=True)
