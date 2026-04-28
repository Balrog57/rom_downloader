import os
import re
import xml.etree.ElementTree as ET

from .constants import SOURCE_FAMILY_MAP
from .sources import normalize_source_label


def normalize_system_name(system_name: str) -> str:
    cleaned = re.sub(r'\s+', ' ', (system_name or '')).strip()
    if not cleaned:
        return ''

    cleanup_patterns = [
        r'\s*[\(\[]\s*(?:retool|1g1r)[^\)\]]*[\)\]]\s*$',
        r'\s*-\s*retool\s*$',
        r'\s+retool\s*$'
    ]

    previous = None
    while cleaned and cleaned != previous:
        previous = cleaned
        for pattern in cleanup_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE).strip()

    return re.sub(r'\s+', ' ', cleaned).strip()


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

    family = 'unknown'
    family_label = 'Inconnu'
    if 'redump.org' in header_url_lower or 'redump' in header_name_lower:
        family = 'redump'
        family_label = 'Redump'
    elif 'no-intro.org' in header_url_lower or 'no-intro' in header_name_lower:
        family = 'no-intro'
        family_label = 'No-Intro'
    elif 'tosec' in header_url_lower or 'tosec' in header_name_lower:
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

    if family == 'redump' and source_type in {'edgeemu', 'planetemu', 'lolroms'}:
        return False

    if source_type == 'edgeemu':
        return False

    return True


def prepare_sources_for_profile(sources: list, dat_profile: dict | None, prefer_1fichier: bool = False) -> list:
    from .api_keys import load_api_keys
    prepared = []
    for source in sources:
        source_copy = source.copy()
        compatible = is_source_compatible_with_profile(source_copy, dat_profile)
        source_copy['compatible'] = compatible

        source_copy['enabled'] = True

        if prefer_1fichier and source_copy.get('type') in ('retrogamesets', 'startgame'):
            source_copy['priority'] = 0
        elif not prefer_1fichier and source_copy.get('type') in ('retrogamesets', 'startgame'):
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
    'detect_dat_profile',
    'build_profile_default_source_url',
    'finalize_dat_profile',
    'get_source_family',
    'is_source_compatible_with_profile',
    'prepare_sources_for_profile',
    'describe_dat_profile',
]