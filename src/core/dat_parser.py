import xml.etree.ElementTree as ET
from pathlib import Path

from .constants import ROM_EXTENSIONS


def parse_dat_file(dat_path: str) -> dict:
    """Parse a No-Intro DAT XML file and extract ROM information."""
    print(f"Parsing DAT file: {dat_path}")

    tree = ET.parse(dat_path)
    root = tree.getroot()

    games = {}
    game_elements = root.findall('.//game')

    for game in game_elements:
        game_name = game.get('name', '')
        if not game_name:
            continue

        rom_elements = game.findall('rom')
        rom_files = []
        for rom_elem in rom_elements:
            rom_info = {
                'name': rom_elem.get('name', ''),
                'size': rom_elem.get('size', '0'),
                'crc': rom_elem.get('crc', ''),
                'md5': rom_elem.get('md5', ''),
                'sha1': rom_elem.get('sha1', '')
            }
            if rom_info['name']:
                rom_files.append(rom_info)

        if rom_files:
            games[game_name] = {
                'game_name': game_name,
                'roms': rom_files,
                'primary_rom': rom_files[0]['name'] if rom_files else ''
            }

    print(f"Found {len(games)} games in DAT file")
    return games


def normalize_checksum(value: str, checksum_type: str) -> str:
    """Normalise un hash pour les comparaisons."""
    normalized = (value or '').strip().lower()
    if not normalized:
        return ''
    if checksum_type == 'crc':
        return normalized.zfill(8)
    return normalized


def parse_rom_size(value) -> int | None:
    """Convertit une taille de ROM DAT en entier si possible."""
    try:
        size = int(str(value).strip())
        return size if size >= 0 else None
    except Exception:
        return None


def strip_rom_extension(filename: str) -> str:
    """Retire l'extension ROM reconnue d'un nom de fichier."""
    name_no_ext = filename
    for ext in sorted(ROM_EXTENSIONS, key=len, reverse=True):
        if name_no_ext.lower().endswith(ext):
            return name_no_ext[:-len(ext)]
    return name_no_ext


def add_local_name_reference(filename: str, local_roms: set, local_roms_normalized: set, local_game_names: set):
    """Ajoute un nom de fichier dans les index de comparaison locale."""
    if not filename:
        return
    basename = Path(filename).name
    name_no_ext = strip_rom_extension(basename)
    local_roms.add(basename)
    local_roms_normalized.add(name_no_ext.lower())
    local_game_names.add(name_no_ext.lower())


__all__ = [
    'parse_dat_file',
    'normalize_checksum',
    'parse_rom_size',
    'strip_rom_extension',
    'add_local_name_reference',
]
