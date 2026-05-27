"""Mappage des noms de systemes DAT vers les noms de dossiers des frontends.

Support: Batocera, RetroBat, EmulationStation (ES-DE), LaunchBox.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .sources import SYSTEM_MAPPINGS
from .dat_profile import normalize_system_name


_FRONTEND_SYSTEM_MAPPINGS: dict[str, dict[str, str]] = {}


def _build_batocera_map() -> dict[str, str]:
    """Construit le mapping DAT -> dossier Batocera/ES-DE depuis SYSTEM_MAPPINGS.

    La convention Batocera utilise generalement le meme slug que Vimm ou PlanetEmu.
    On derive le dossier depuis les entrees SYSTEM_MAPPINGS existantes.
    """
    mapping: dict[str, str] = {}
    overrides = {
        "Nintendo - Game Boy Advance": "gba",
        "Nintendo - Nintendo DS": "nds",
        "Nintendo - Nintendo 64": "n64",
        "Nintendo - Super Nintendo Entertainment System": "snes",
        "Nintendo - Nintendo Entertainment System": "nes",
        "Nintendo - Game Boy": "gb",
        "Nintendo - Game Boy Color": "gbc",
        "Nintendo - Nintendo 3DS": "3ds",
        "Nintendo - Wii": "wii",
        "Nintendo - Wii U": "wiiu",
        "Nintendo - GameCube": "gc",
        "Sony - PlayStation": "psx",
        "Sony - PlayStation 2": "ps2",
        "Sony - PlayStation 3": "ps3",
        "Sony - PlayStation Portable": "psp",
        "Sony - PlayStation Vita": "psvita",
        "Sega - Mega Drive - Genesis": "megadrive",
        "Sega - Master System - Mark III": "mastersystem",
        "Sega - Game Gear": "gamegear",
        "Sega - Saturn": "saturn",
        "Sega - Dreamcast": "dreamcast",
        "Sega - 32X": "sega32x",
        "Sega - CD": "segacd",
        "NEC - PC Engine - TurboGrafx 16": "pcengine",
        "NEC - PC Engine CD - TurboGrafx CD": "pcenginecd",
        "NEC - PC Engine SuperGrafx": "supergrafx",
        "Atari - 2600": "atari2600",
        "Atari - 5200": "atari5200",
        "Atari - 7800": "atari7800",
        "Atari - Jaguar": "atarijaguar",
        "Atari - Lynx": "atarilynx",
        "Microsoft - Xbox": "xbox",
        "Microsoft - Xbox 360": "xbox360",
        "Commodore - 64": "c64",
        "Commodore - Amiga": "amiga",
        "Commodore - Amiga CD32": "amigacd32",
        "Bandai - WonderSwan": "wonderswan",
        "Bandai - WonderSwan Color": "wonderswancolor",
        "SNK - Neo Geo AES": "neogeo",
        "SNK - Neo Geo CD": "neogeocd",
        "SNK - Neo Geo Pocket": "ngp",
        "SNK - Neo Geo Pocket Color": "ngpc",
        "Panasonic - 3DO": "3do",
        "Philips - CD-i": "cdi",
        "Coleco - ColecoVision": "coleco",
        "Mattel - Intellivision": "intellivision",
        "Magnavox - Odyssey2": "odyssey2",
        "Fairchild - Channel F": "channelf",
    }
    mapping.update(overrides)

    for dat_name, provider_slugs in SYSTEM_MAPPINGS.items():
        if dat_name in mapping:
            continue
        slug = (provider_slugs.get("vimm") or provider_slugs.get("planetemu") or "").lower()
        slug = re.sub(r"[^a-z0-9]+", "", slug)
        if slug:
            mapping[dat_name] = slug

    return mapping


def get_frontend_mapping(frontend: str = "batocera") -> dict[str, str]:
    global _FRONTEND_SYSTEM_MAPPINGS
    if not _FRONTEND_SYSTEM_MAPPINGS:
        _FRONTEND_SYSTEM_MAPPINGS = {
            "batocera": _build_batocera_map(),
            "retrobat": _build_batocera_map(),
            "es-de": _build_batocera_map(),
            "launchbox": {},
        }
    return _FRONTEND_SYSTEM_MAPPINGS.get(frontend, _FRONTEND_SYSTEM_MAPPINGS["batocera"])


def frontend_folder_for_system(system_name: str, frontend: str = "batocera") -> str:
    """Retourne le nom de dossier attendu par un frontend pour un systeme donne."""
    mapping = get_frontend_mapping(frontend)
    normalized = normalize_system_name(system_name)
    result = mapping.get(normalized) or mapping.get(system_name)
    if result:
        return result

    slug = re.sub(r"[^a-zA-Z0-9]+", "", system_name).lower()
    return slug or "unknown"


def build_frontend_output_path(system_name: str, rom_filename: str,
                                output_root: str, frontend: str = "batocera") -> str:
    """Construit le chemin de sortie organise par frontend.

    Exemple: output_root/gba/rom.gba
    """
    folder = frontend_folder_for_system(system_name, frontend)
    return os.path.join(output_root, folder, rom_filename)


def generate_es_gamelist_xml(games: list[dict], system_name: str) -> str:
    """Genere un gamelist.xml minimal avec quelques infos DAT utiles."""
    import xml.etree.ElementTree as ET
    from xml.dom import minidom

    root = ET.Element("gameList")
    for game in games:
        gname = game.get("game_name", "")
        roms = game.get("roms") or []
        primary = game.get("download_filename") or game.get("primary_rom", "")
        if not primary and roms:
            primary = roms[0].get("name", "")
        chd = any((rom.get("name") or "").lower().endswith(".chd") for rom in roms)
        flags = []
        if chd:
            flags.append("CHD")
        if str(game.get("isbios") or "").lower() in {"yes", "true", "1"}:
            flags.append("BIOS")
        if str(game.get("isdevice") or "").lower() in {"yes", "true", "1"}:
            flags.append("Device DAT")
        if game.get("cloneof"):
            flags.append(f"Clone de {game.get('cloneof')}")
        if game.get("romof"):
            flags.append(f"ROM de {game.get('romof')}")
        game_el = ET.SubElement(root, "game")
        ET.SubElement(game_el, "path").text = f"./{primary}"
        ET.SubElement(game_el, "name").text = gname
        ET.SubElement(game_el, "desc").text = " | ".join(flags)
        ET.SubElement(game_el, "image").text = ""
        ET.SubElement(game_el, "rating").text = ""

    rough = ET.tostring(root, encoding="unicode")
    dom = minidom.parseString(rough.encode("utf-8"))
    return dom.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


def generate_missing_txt(games: list[dict]) -> str:
    """Genere une liste lisible des jeux absents/echec pour frontend ou RomVault."""
    lines = []
    for game in games:
        name = game.get("game_name") or game.get("name") or ""
        status = game.get("status") or game.get("error_code") or "missing"
        provider = game.get("source") or game.get("provider") or ""
        roms = game.get("roms") or []
        flags = []
        if any((rom.get("name") or "").lower().endswith(".chd") for rom in roms):
            flags.append("CHD")
        if str(game.get("isbios") or "").lower() in {"yes", "true", "1"}:
            flags.append("BIOS")
        if str(game.get("isdevice") or "").lower() in {"yes", "true", "1"}:
            flags.append("DEVICE")
        suffix = f" [{', '.join(flags)}]" if flags else ""
        provider_part = f" ({provider})" if provider else ""
        if name:
            lines.append(f"{name}{suffix} - {status}{provider_part}")
    return "\n".join(lines) + ("\n" if lines else "")


__all__ = [
    "get_frontend_mapping",
    "frontend_folder_for_system",
    "build_frontend_output_path",
    "generate_es_gamelist_xml",
    "generate_missing_txt",
]
