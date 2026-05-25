"""Inspection pragmatique des capacites et contraintes d'un DAT."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path


def _text(root, path: str) -> str:
    value = root.findtext(path, default="")
    return (value or "").strip()


def analyze_dat_capabilities(dat_path: str) -> dict:
    """Retourne un resume exploitable des formats et metadonnees DAT avances."""
    tree = ET.parse(dat_path)
    root = tree.getroot()
    games = root.findall(".//game")
    roms = root.findall(".//rom")
    disks = root.findall(".//disk")

    header_name = _text(root, "./header/name")
    header_type = _text(root, "./header/type") or _text(root, "./header/category")
    chd_roms = [rom for rom in roms if (rom.get("name") or "").lower().endswith(".chd")]
    chd_disks = [disk for disk in disks if (disk.get("name") or "").strip()]
    merged_roms = [rom for rom in roms if rom.get("merge")]
    clone_games = [game for game in games if game.get("cloneof") or game.get("romof") or game.get("sampleof")]
    bios_games = [game for game in games if (game.get("isbios") or "").lower() in {"yes", "true", "1"}]
    device_games = [game for game in games if (game.get("isdevice") or "").lower() in {"yes", "true", "1"}]
    headered = bool(header_type or _text(root, "./header/headers") or _text(root, "./header/header"))
    merge_mode = "simple"
    if clone_games and merged_roms:
        merge_mode = "split/merged detecte"
    elif clone_games:
        merge_mode = "clones detectes"
    elif merged_roms:
        merge_mode = "rom merge detecte"

    return {
        "dat_path": str(dat_path),
        "dat_name": header_name or Path(dat_path).stem,
        "header_name": header_name,
        "header_type": header_type,
        "headered": headered,
        "games": len(games),
        "roms": len(roms),
        "disks": len(disks),
        "chd_roms": len(chd_roms),
        "chd_disks": len(chd_disks),
        "chd_supported": True,
        "clone_games": len(clone_games),
        "bios_games": len(bios_games),
        "device_games": len(device_games),
        "merged_roms": len(merged_roms),
        "merge_mode": merge_mode,
        "rebuild_strategy": "non-merged/simple",
        "notes": [
            "CHD: validation hash/taille uniquement, aucune conversion.",
            "Headers/merge: detection et reporting, pas de reconstruction arcade complete.",
        ],
    }


def format_dat_capabilities_report(capabilities: dict) -> str:
    """Formate le resume DAT pour la CLI."""
    lines = [
        "Capacites DAT",
        "=" * 60,
        f"DAT: {capabilities.get('dat_name', '')}",
        f"Fichier: {capabilities.get('dat_path', '')}",
        f"Jeux: {capabilities.get('games', 0)}",
        f"ROMs: {capabilities.get('roms', 0)}",
        f"Disks: {capabilities.get('disks', 0)}",
        f"CHD ROMs: {capabilities.get('chd_roms', 0)}",
        f"CHD disks: {capabilities.get('chd_disks', 0)}",
        f"Header detecte: {'oui' if capabilities.get('headered') else 'non'}",
        f"Type header: {capabilities.get('header_type') or '-'}",
        f"Clones/parents: {capabilities.get('clone_games', 0)}",
        f"BIOS: {capabilities.get('bios_games', 0)}",
        f"Devices: {capabilities.get('device_games', 0)}",
        f"ROMs merge: {capabilities.get('merged_roms', 0)}",
        f"Mode merge suppose: {capabilities.get('merge_mode', 'simple')}",
        f"Strategie rebuild: {capabilities.get('rebuild_strategy', 'non-merged/simple')}",
        "",
        "Notes:",
    ]
    for note in capabilities.get("notes") or []:
        lines.append(f"- {note}")
    return "\n".join(lines)


__all__ = ["analyze_dat_capabilities", "format_dat_capabilities_report"]
