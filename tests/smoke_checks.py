"""Smoke checks that avoid network downloads."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.dat import discover_dat_menu_items
from src.config import build_diagnostic_report
from src.providers import build_provider_registry
from src.core.config_profiles import CONFIG_PROFILES


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def main() -> None:
    items = discover_dat_menu_items()
    sections = {item["label"].lower() for item in items if item.get("type") == "section"}
    required = {"no-intro", "redump", "retool - french no unl"}
    missing = required - sections
    if missing:
        raise SystemExit(f"missing DAT sections: {sorted(missing)}")

    dat_files = [item for item in items if item.get("type") == "file"]
    if not dat_files:
        raise SystemExit("no DAT files discovered")

    report = build_diagnostic_report()
    if "local_database" not in report:
        raise SystemExit("local database status missing")

    providers = build_provider_registry()
    provider_names = {provider.name for provider in providers}
    for expected in ("Minerva No-Intro", "archive.org"):
        if expected not in provider_names:
            raise SystemExit(f"provider missing: {expected}")
    for provider in providers:
        if "myrient" in provider.name.lower() or provider.type == "myrient":
            raise SystemExit(f"obsolete Myrient provider exposed: {provider.name}")

    readme = _read_text("README.md")
    roadmap = _read_text("docs/ROADMAP.md")
    for label, text in (("README", readme), ("ROADMAP", roadmap)):
        lowered = text.lower()
        if "minerva torrent et archive.org restent les derniers recours" not in lowered:
            raise SystemExit(f"{label}: Minerva/archive.org fallback policy missing")
        if "dat retool/1g1r deja filtre" not in lowered and "dat deja filtre" not in lowered:
            raise SystemExit(f"{label}: external 1G1R DAT policy missing")

    goal_path = Path("goal.md")
    if goal_path.exists():
        goal_text = goal_path.read_text(encoding="utf-8")
        goal_lower = goal_text.lower()
        if ("provider myrient" in goal_lower and "http" in goal_lower) or "1g1r fr" in goal_lower:
            raise SystemExit("goal.md still contains obsolete Myrient/1G1R wording")

    for profile_key, profile in CONFIG_PROFILES.items():
        label = str(profile.get("label", "")).lower()
        if "1g1r" in profile_key.lower() or "1g1r" in label:
            raise SystemExit(f"internal 1G1R profile exposed: {profile_key}")

    if not Path("main.py").exists():
        raise SystemExit("main.py missing")

    print(f"smoke ok: {len(dat_files)} DAT files, {len(providers)} providers")


if __name__ == "__main__":
    main()
