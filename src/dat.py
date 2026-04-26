"""Parsing DAT, profils et decouverte des fichiers DAT."""

from .core import (
    describe_dat_profile,
    detect_dat_profile,
    detect_system_name,
    discover_dat_menu_items,
    finalize_dat_profile,
    normalize_system_name,
    parse_dat_file,
)

__all__ = [
    "describe_dat_profile",
    "detect_dat_profile",
    "detect_system_name",
    "discover_dat_menu_items",
    "finalize_dat_profile",
    "normalize_system_name",
    "parse_dat_file",
]

