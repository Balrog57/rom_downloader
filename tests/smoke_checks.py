"""Smoke checks that avoid network downloads."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.dat import discover_dat_menu_items
from src.config import build_diagnostic_report
from src.providers import build_provider_registry


def main() -> None:
    items = discover_dat_menu_items()
    sections = {item["label"].lower() for item in items if item.get("type") == "section"}
    required = {"no-intro", "redump", "retool"}
    missing = required - sections
    if missing:
        raise SystemExit(f"missing DAT sections: {sorted(missing)}")

    dat_files = [item for item in items if item.get("type") == "file"]
    if not dat_files:
        raise SystemExit("no DAT files discovered")

    report = build_diagnostic_report()
    if report["db_shards"] <= 0:
        raise SystemExit("db shards missing")

    providers = build_provider_registry()
    provider_names = {provider.name for provider in providers}
    for expected in ("Minerva No-Intro", "archive.org"):
        if expected not in provider_names:
            raise SystemExit(f"provider missing: {expected}")

    if not Path("main.py").exists():
        raise SystemExit("main.py missing")

    print(f"smoke ok: {len(dat_files)} DAT files, {len(providers)} providers")


if __name__ == "__main__":
    main()
