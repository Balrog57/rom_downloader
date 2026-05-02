import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .constants import SOURCE_FAMILY_MAP
from .sources import ONEFICHIER_SOURCE_TYPES, normalize_source_label


WINDOWS_RESERVED_NAMES = {
    'CON', 'PRN', 'AUX', 'NUL',
    'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
    'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9',
}


def normalize_system_name(system_name: str) -> str:
    import unicodedata as _ucd
    cleaned = re.sub(r'\s+', ' ', (system_name or '')).strip()
    cleaned = _ucd.normalize('NFKD', cleaned).encode('ascii', 'ignore').decode('ascii')
    cleaned = re.sub(r'\s+NeoGeo\s+', ' Neo Geo ', cleaned)
    cleaned = re.sub(r'\s+NeoGeo$', ' Neo Geo', cleaned)
    cleaned = re.sub(r'^NeoGeo\s+', 'Neo Geo ', cleaned)
    cleaned = re.sub(r'(?<=TurboGrafx)-(?=1[6-9]|CD)', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if not cleaned:
        return ''

    cleanup_patterns = [
        r'\s*[\(\[]\s*(?:retool|1g1r)[^\)\]]*[\)\]]\s*$',
        r'\s*[\(\[]\s*(?:fds|bin|j64|lyx|lzx|a2r|bigendian|headered|headerless|decrypted|encrypted|wip|deprecated|digital|steam|desura|groupees|dlc|theme|update|avatar|content|crypte|flux|waveform|kryoflux|mame|cardimage|cdn|psn|psn minis|psp eboot|psx2psp|umd|nonpdrm|vpk|wad|cia|noscan|hentai|dev|pre-install|spotpass|lotcheck|starlight)[^\)\]]*[\)\]]\s*$',
        r'\s*-\s*datfile\b.*$',
        r'\s+datfile\b.*$',
        r'\s*-\s*retool\s*$',
        r'\s+retool\s*$'
    ]

    previous = None
    while cleaned and cleaned != previous:
        previous = cleaned
        for pattern in cleanup_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE).strip()

    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    aliases = {
        'Atari - Jaguar CD': 'Atari - Jaguar CD Interactive Multimedia System',
        'Atari - Atari Jaguar CD': 'Atari - Jaguar CD Interactive Multimedia System',
        'Atari - Jaguar CD Interactive Multimedia': 'Atari - Jaguar CD Interactive Multimedia System',
        'Nintendo - GameCube - Discs': 'Nintendo - GameCube',
        'Nintendo - GameCube Datfile': 'Nintendo - GameCube',
        'Sega - Dreamcast - Discs': 'Sega - Dreamcast',
        'Sony - PlayStation - Discs': 'Sony - PlayStation',
    }
    return aliases.get(cleaned, cleaned)


def safe_dat_folder_name(dat_file_path: str) -> str:
    """Construit un nom de dossier Windows depuis le nom du DAT."""
    stem = Path(dat_file_path or '').stem or 'DAT'
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', ' ', stem)
    sanitized = re.sub(r'\s+', ' ', sanitized).strip(' .')
    if not sanitized:
        sanitized = 'DAT'
    if sanitized.upper() in WINDOWS_RESERVED_NAMES:
        sanitized = f"_{sanitized}"
    return sanitized


def resolve_dat_output_folder(dat_file_path: str, root_folder: str, use_dat_subfolder: bool = False) -> str:
    """Retourne le dossier effectif selon l'option de sous-dossier DAT."""
    root = os.path.normpath(str(root_folder or '').strip())
    if not use_dat_subfolder:
        return root
    return os.path.join(root, safe_dat_folder_name(dat_file_path))


def detect_dat_profile(dat_file_path: str) -> dict:
    header_name = ''
    header_url = ''
    header_description = ''
    retool_marker = ''

    try:
        tree = ET.parse(dat_file_path)
        root = tree.getroot()
        header_name = root.findtext('./header/name', default='').strip()
        header_url = root.findtext('./header/url', default='').strip()
        header_description = root.findtext('./header/description', default='').strip()
        retool_marker = (
            root.findtext('./header/retool', default='').strip()
            or root.findtext('.//retool', default='').strip()
        )
    except Exception:
        pass

    fallback_name = os.path.splitext(os.path.basename(dat_file_path))[0]
    fallback_name = re.sub(r'[\(\[].*?[\)\]]', '', fallback_name).strip()
    fallback_name = re.sub(r'\s+', ' ', fallback_name)

    raw_system_name = header_name or fallback_name
    system_name = normalize_system_name(raw_system_name) or fallback_name

    header_url_lower = header_url.lower()
    header_name_lower = header_name.lower()
    header_description_lower = header_description.lower()
    fallback_name_lower = fallback_name.lower()
    dat_path_lower = dat_file_path.replace('\\', '/').lower()

    family = 'unknown'
    family_label = 'Inconnu'
    if (
        'redump.org' in header_url_lower
        or 'redump' in header_name_lower
        or '/redump/' in dat_path_lower
        or re.search(r'\bredump\b', fallback_name_lower)
    ):
        family = 'redump'
        family_label = 'Redump'
    elif (
        'no-intro.org' in header_url_lower
        or 'no-intro' in header_name_lower
        or '/no-intro/' in dat_path_lower
        or re.search(r'\bno-intro\b', fallback_name_lower)
    ):
        family = 'no-intro'
        family_label = 'No-Intro'
    elif (
        'tosec' in header_url_lower
        or 'tosec' in header_name_lower
        or '/tosec/' in dat_path_lower
        or re.search(r'\btosec\b', fallback_name_lower)
    ):
        family = 'tosec'
        family_label = 'TOSEC'

    is_retool = bool(
        retool_marker
        or re.search(r'\bretool\b', header_name_lower)
        or re.search(r'\bretool\b', header_description_lower)
    )

    return {
        'path': dat_file_path,
        'raw_system_name': raw_system_name,
        'system_name': system_name,
        'header_name': header_name,
        'header_url': header_url,
        'family': family,
        'family_label': family_label,
        'is_retool': is_retool,
        'retool_label': 'Retool / 1G1R' if is_retool else 'DAT brut',
        'default_source_url': ''
    }


def build_profile_default_source_url(dat_profile: dict) -> str:
    from .minerva import build_minerva_directory_url
    from .sources import get_default_sources
    family = (dat_profile or {}).get('family', 'unknown')
    system_name = (dat_profile or {}).get('system_name')
    collection = next(
        (name for name, mapped_family in SOURCE_FAMILY_MAP.items() if mapped_family == family),
        ''
    )
    if not collection or not system_name:
        return ''

    source = next(
        (item for item in get_default_sources() if item.get('collection') == collection),
        None
    )
    if not source:
        return ''
    return build_minerva_directory_url(source, system_name)


def finalize_dat_profile(dat_profile: dict) -> dict:
    profile = (dat_profile or {}).copy()
    profile['default_source_url'] = build_profile_default_source_url(profile)
    return profile


def get_source_family(source: dict) -> str:
    if source.get('fixed_directory') or source.get('name') == 'Minerva Custom':
        return 'custom'
    return SOURCE_FAMILY_MAP.get(source.get('collection', '').strip(), '')


def is_source_compatible_with_profile(source: dict, dat_profile: dict | None) -> bool:
    if not dat_profile:
        return True

    family = dat_profile.get('family', 'unknown')
    if family == 'unknown':
        return True

    source_type = source.get('type')
    if source_type == 'minerva':
        source_family = get_source_family(source)
        return source_family in {'', 'custom', family}

    return True


def prepare_sources_for_profile(sources: list, dat_profile: dict | None, prefer_1fichier: bool = False) -> list:
    from .api_keys import load_api_keys
    prepared = []
    for source in sources:
        source_copy = source.copy()
        compatible = is_source_compatible_with_profile(source_copy, dat_profile)
        source_copy['compatible'] = compatible

        source_copy['enabled'] = bool(source_copy.get('enabled', True))

        source_type = source_copy.get('type')
        if prefer_1fichier and source_type in ONEFICHIER_SOURCE_TYPES:
            source_copy['priority'] = 0
            source_copy['order'] = 10 if source_type == 'retrogamesets' else 11
        elif not prefer_1fichier and source_type in ONEFICHIER_SOURCE_TYPES:
            source_copy['order'] = 78 if source_type == 'retrogamesets' else 79
            api_keys = load_api_keys()
            has_deblocker = api_keys.get('alldebrid') or api_keys.get('realdebrid') or api_keys.get('1fichier')
            if not has_deblocker:
                source_copy['compatible'] = False

        prepared.append(source_copy)

    return prepared


def describe_dat_profile(dat_profile: dict | None) -> str:
    if not dat_profile:
        return "DAT inconnu"

    parts = []
    system_name = dat_profile.get('system_name')
    if system_name:
        parts.append(system_name)

    family_label = dat_profile.get('family_label')
    if family_label and family_label != 'Inconnu':
        parts.append(family_label)

    retool_label = dat_profile.get('retool_label')
    if retool_label:
        parts.append(retool_label)

    return " | ".join(parts) if parts else "DAT inconnu"


__all__ = [
    'normalize_system_name',
    'safe_dat_folder_name',
    'resolve_dat_output_folder',
    'detect_dat_profile',
    'build_profile_default_source_url',
    'finalize_dat_profile',
    'get_source_family',
    'is_source_compatible_with_profile',
    'prepare_sources_for_profile',
    'describe_dat_profile',
]
