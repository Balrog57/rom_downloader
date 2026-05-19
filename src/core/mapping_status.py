"""Diagnostic de couverture des mappings DAT vers providers."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .dat_profile import detect_dat_profile, finalize_dat_profile
from .env import RESOURCE_ROOT
from .sources import get_default_sources, resolve_system_mapping


def _provider_types(provider_types: list[str] | None = None) -> list[str]:
    if provider_types:
        return list(dict.fromkeys(provider_types))
    types = []
    for source in get_default_sources():
        source_type = source.get("type")
        if source_type and source_type not in types:
            types.append(source_type)
    return types


def build_mapping_status(dat_root: str | Path | None = None,
                         provider_types: list[str] | None = None) -> dict:
    """Calcule la couverture des mappings provider pour les DAT locaux."""
    root = Path(dat_root or (RESOURCE_ROOT / "dat"))
    providers = _provider_types(provider_types)
    dat_files = sorted(root.rglob("*.dat"), key=lambda path: str(path).lower()) if root.exists() else []
    systems_by_name: dict[str, dict] = {}

    for dat_path in dat_files:
        try:
            profile = finalize_dat_profile(detect_dat_profile(str(dat_path)))
            system_name = profile.get("system_name") or dat_path.stem
        except Exception:
            system_name = dat_path.stem
        item = systems_by_name.setdefault(system_name, {"system_name": system_name, "dat_files": []})
        item["dat_files"].append(str(dat_path))

    provider_rows = {}
    for provider in providers:
        covered = []
        missing = []
        for system_name in sorted(systems_by_name, key=str.lower):
            mapping = resolve_system_mapping(system_name, provider)
            if mapping:
                covered.append({"system_name": system_name, "mapping": mapping})
            else:
                missing.append(system_name)
        provider_rows[provider] = {
            "covered": len(covered),
            "missing": len(missing),
            "covered_systems": covered,
            "missing_systems": missing,
        }

    without_any_provider = []
    for system_name in sorted(systems_by_name, key=str.lower):
        if not any(resolve_system_mapping(system_name, provider) for provider in providers):
            without_any_provider.append(system_name)

    return {
        "dat_root": str(root),
        "dat_files": len(dat_files),
        "unique_systems": len(systems_by_name),
        "providers": provider_rows,
        "without_any_provider": without_any_provider,
    }


def format_mapping_status_report(status: dict, missing_limit: int = 20) -> str:
    """Formate le diagnostic mapping pour la CLI."""
    lines = [
        "Couverture mappings DAT/providers",
        "=" * 40,
        f"DAT: {status.get('dat_files', 0)}",
        f"Systemes uniques: {status.get('unique_systems', 0)}",
        "",
        "Providers:",
    ]
    for provider, row in (status.get("providers") or {}).items():
        lines.append(f"  - {provider}: {row.get('covered', 0)} couvert(s), {row.get('missing', 0)} manquant(s)")
        missing = row.get("missing_systems") or []
        for system_name in missing[:max(0, missing_limit)]:
            lines.append(f"      manquant: {system_name}")
        if missing_limit and len(missing) > missing_limit:
            lines.append(f"      ... {len(missing) - missing_limit} autre(s)")

    without_any = status.get("without_any_provider") or []
    lines.extend(["", f"Sans aucun provider mappe: {len(without_any)}"])
    for system_name in without_any[:max(0, missing_limit)]:
        lines.append(f"  - {system_name}")
    if missing_limit and len(without_any) > missing_limit:
        lines.append(f"  ... {len(without_any) - missing_limit} autre(s)")
    return "\n".join(lines)


def export_mapping_status(status: dict, output_path: str | Path) -> str:
    """Exporte le diagnostic mapping en JSON ou CSV selon l'extension."""
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() == ".csv":
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["provider", "system_name", "status", "mapping"])
            writer.writeheader()
            for provider, row in (status.get("providers") or {}).items():
                for item in row.get("covered_systems") or []:
                    writer.writerow({
                        "provider": provider,
                        "system_name": item.get("system_name", ""),
                        "status": "covered",
                        "mapping": item.get("mapping", ""),
                    })
                for system_name in row.get("missing_systems") or []:
                    writer.writerow({
                        "provider": provider,
                        "system_name": system_name,
                        "status": "missing",
                        "mapping": "",
                    })
    else:
        target.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(target)


__all__ = [
    "build_mapping_status",
    "format_mapping_status_report",
    "export_mapping_status",
]
