"""Export FixDAT : genere un DAT No-Intro compatible RomVault/clrmamepro avec les jeux manquants."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from xml.dom import minidom
from pathlib import Path

from .dat_parser import parse_dat_file
from .dat_profile import detect_dat_profile


def _get_header_info(dat_path: str) -> dict:
    profile = detect_dat_profile(dat_path)
    return {
        "name": profile.get("raw_system_name", "Unknown"),
        "family": profile.get("family_label", "Unknown"),
        "is_retool": profile.get("is_retool", False),
    }


def _build_fixdat_xml(dat_games: dict, system_name: str, family: str, is_retool: bool) -> str:
    datafile = ET.Element("datafile", {
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:schemaLocation": "https://datomatic.no-intro.org/stuff https://datomatic.no-intro.org/stuff/schema_nointro_datfile_v3.xsd",
    })
    header = ET.SubElement(datafile, "header")
    ET.SubElement(header, "name").text = f"{system_name} (FixDAT)"
    ET.SubElement(header, "description").text = f"{system_name} - Jeux manquants (FixDAT)"
    ET.SubElement(header, "version").text = "FixDAT"
    if family:
        ET.SubElement(header, "homepage").text = family
    if is_retool:
        ET.SubElement(header, "retool").text = "Filtre FixDAT"
    ET.SubElement(header, "clrmamepro", {"forcenodump": "required"})

    for game_name, game_info in sorted(dat_games.items()):
        game_elem = ET.SubElement(datafile, "game", {"name": game_name})
        ET.SubElement(game_elem, "description").text = game_name
        for rom in game_info.get("roms", []):
            attrs = {"name": rom.get("name", ""), "size": str(rom.get("size", "0"))}
            if rom.get("crc"):
                attrs["crc"] = rom["crc"]
            if rom.get("md5"):
                attrs["md5"] = rom["md5"]
            if rom.get("sha1"):
                attrs["sha1"] = rom["sha1"]
            ET.SubElement(game_elem, "rom", attrs)

    rough = ET.tostring(datafile, encoding="unicode")
    dom = minidom.parseString(rough.encode("utf-8"))
    pretty = dom.toprettyxml(indent="\t", encoding="utf-8").decode("utf-8")
    header_end = pretty.find("</header>")
    if header_end > 0:
        pretty = '<?xml version="1.0"?>\n' + pretty[pretty.find("<datafile"):]
    return pretty


def build_fixdat(dat_path: str, missing_games: dict, output_path: str | None = None) -> str:
    """Genere un DAT des jeux manquants a partir d'un DAT original et d'une liste de jeux absents.

    Args:
        dat_path: Chemin vers le fichier DAT original.
        missing_games: Dict des jeux manquants {game_name: game_info} (format parse_dat_file).
        output_path: Chemin de sortie optionnel. Si omis, retourne le XML.

    Returns:
        Le chemin du fichier FixDAT ecrit, ou le XML si output_path est None.
    """
    if isinstance(missing_games, list):
        missing_games = {g.get("game_name", str(i)): g for i, g in enumerate(missing_games)}

    header = _get_header_info(dat_path)
    xml_content = _build_fixdat_xml(missing_games, header["name"], header["family"], header["is_retool"])

    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(xml_content, encoding="utf-8")
        return str(target)

    return xml_content


def build_fixdat_from_results(dat_path: str, dat_games: dict, not_available: list,
                              output_dir: str) -> str:
    """Genere un FixDAT a partir des resultats d'un run (jeux introuvables et echoues).

    Args:
        dat_path: Chemin du DAT original.
        dat_games: Tous les jeux du DAT {game_name: game_info}.
        not_available: Liste des jeux non trouves (items avec 'game_name').
        output_dir: Dossier de sortie pour le fichier .dat.

    Returns:
        Chemin du FixDAT genere.
    """
    missing = {}
    for item in not_available:
        gname = item.get("game_name") or item.get("name") or ""
        if gname and gname in dat_games:
            missing[gname] = dat_games[gname]

    stem = Path(dat_path).stem
    out_path = os.path.join(output_dir, f"{stem}_FixDAT.dat")
    return build_fixdat(dat_path, missing, out_path)


__all__ = [
    "build_fixdat",
    "build_fixdat_from_results",
]
