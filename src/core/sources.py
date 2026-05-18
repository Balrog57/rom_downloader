import hashlib
import json
import re
import time
from urllib.parse import unquote, urlparse

from .constants import (
    ARCHIVE_ORG_DOWNLOAD_BASE,
    LOLROMS_BASE,
    MINERVA_BROWSE_BASE,
    RETRO_GAME_SETS_BASE,
    ROMHUSTLER_BASE,
    COOLROM_BASE,
    NOPAYSTATION_BASE,
    STARTGAME_BASE,
    HSHOP_BASE,
    ROMSXISOS_BASE,
    SOURCE_FAMILY_MAP,
    VIMM_BASE,
)
from .env import RESOLUTION_CACHE_TTL_SECONDS


def get_default_sources_legacy():
    from . import rom_database as _rom_db
    from .rom_database import load_rom_database, DEFAULT_CONFIG_URLS
    if _rom_db.ROM_DATABASE is None:
        load_rom_database()
    config = _rom_db.ROM_DATABASE.get('config_urls', {})
    return [
        {
            'name': 'archive.org',
            'base_url': config.get('archive_org', ''),
            'type': 'archive_org',
            'enabled': True,
            'description': 'Dernier recours HTTP apres DDL et Minerva',
            'priority': 110,
            'order': 160,
        },
        {
            'name': 'Myrient No-Intro',
            'base_url': config.get('myrient_no_intro', ''),
            'type': 'myrient',
            'enabled': True,
            'description': 'ROMs No-Intro',
            'priority': 2
        },
        {
            'name': 'Myrient Redump',
            'base_url': config.get('myrient_redump', ''),
            'type': 'myrient',
            'enabled': True,
            'description': 'ROMs Redump',
            'priority': 2
        },
        {
            'name': 'Myrient TOSEC',
            'base_url': config.get('myrient_tosec', ''),
            'type': 'myrient',
            'enabled': True,
            'description': 'ROMs TOSEC',
            'priority': 2
        },
        {
            'name': 'EdgeEmu',
            'base_url': config.get('edgeemu_browse', ''),
            'type': 'edgeemu',
            'enabled': False,
            'description': 'Lien direct (Excellent pour le retro)',
            'priority': 2
        },
        {
            'name': 'PlanetEmu',
            'base_url': config.get('planetemu_roms', ''),
            'type': 'planetemu',
            'enabled': False,
            'description': 'Lien direct (POST) - Source FR majeure',
            'priority': 2
        },
        {
            'name': 'Passerelle 1fichier',
            'base_url': config.get('1fichier_free', ''),
            'type': 'free_host',
            'enabled': True,
            'description': 'Hebergeur utilise quand une source fournit un lien 1fichier',
            'priority': 3
        }
    ]


SOURCE_TYPE_ORDER = {
    'planetemu': 20,
    'romhustler': 25,
    'coolrom': 30,
    'romsxisos': 35,
    'nopaystation': 40,
    'hshop': 45,
    'vimm': 50,
    'lolroms': 60,
    'retrogamesets': 70,
    'startgame': 72,
    'free_host': 78,
    'archive_org_collection': 82,
    'edgeemu': 850,
    'minerva': 900,
    'archive_org': 1000,
}

DDL_SOURCE_TYPES = {
    'planetemu',
    'romhustler',
    'coolrom',
    'romsxisos',
    'nopaystation',
    'hshop',
    'vimm',
    'lolroms',
    'retrogamesets',
    'startgame',
    'free_host',
    'archive_org_collection',
}

ONEFICHIER_SOURCE_TYPES = {'retrogamesets', 'startgame'}


ROMGOGETTER_ARCHIVE_ORG_COLLECTION_GROUPS = {
    'ps1_archive': [
        'sony_playstation_part1',
        'sony_playstation_part2',
        'sony_playstation_part3',
        'sony_playstation_part4',
        'sony_playstation_part5',
    ],
    'ps2_archive': [
        'sony_playstation2_numberssymbols',
        'sony_playstation2_a',
        'sony_playstation2_b',
        'sony_playstation2_c',
        'sony_playstation2_d_part1',
        'sony_playstation2_d_part2',
        'sony_playstation2_e',
        'sony_playstation2_f',
        'sony_playstation2_g',
        'sony_playstation2_h',
        'sony_playstation2_i',
        'sony_playstation2_j',
        'sony_playstation2_k',
        'sony_playstation2_l',
        'sony_playstation2_m_part1',
        'sony_playstation2_m_part2',
        'sony_playstation2_n',
        'sony_playstation2_o_part1',
        'sony_playstation2_o_part2',
        'sony_playstation2_p',
        'sony_playstation2_q',
        'sony_playstation2_r',
        'sony_playstation2_s_part1',
        'sony_playstation2_s_part2',
        'sony_playstation2_s_part3',
        'sony_playstation2_s_part4',
        'sony_playstation2_t',
        'sony_playstation2_u',
        'sony_playstation2_v',
        'sony_playstation2_w',
        'sony_playstation2_x',
        'sony_playstation2_z',
    ],
    'ps3_archive': [
        'sony_playstation3_numberssymbols',
        'sony_playstation3_a_part1',
        'sony_playstation3_a_part2',
        'sony_playstation3_a_part3',
        'sony_playstation3_b_part1',
        'sony_playstation3_b_part2',
        'sony_playstation3_b_part3',
        'sony_playstation3_c_part1',
        'sony_playstation3_c_part2',
        'sony_playstation3_c_part3',
        'sony_playstation3_d_part1',
        'sony_playstation3_d_part2',
        'sony_playstation3_d_part3',
        'sony_playstation3_d_part4',
        'sony_playstation3_d_part5',
        'sony_playstation3_e',
        'sony_playstation3_f_part1',
        'sony_playstation3_f_part2',
        'sony_playstation3_f_part3',
        'sony_playstation3_g_part1',
        'sony_playstation3_g_part2',
        'sony_playstation3_g_part3',
        'sony_playstation3_h_part1',
        'sony_playstation3_h_part2',
        'sony_playstation3_i',
        'sony_playstation3_j',
        'sony_playstation3_k',
        'sony_playstation3_l_part1',
        'sony_playstation3_l_part2',
        'sony_playstation3_l_part3',
        'sony_playstation3_m_part1',
        'sony_playstation3_m_part2',
        'sony_playstation3_m_part3',
        'sony_playstation3_m_part4',
        'sony_playstation3_m_part5',
        'sony_playstation3_n_part1',
        'sony_playstation3_n_part2',
        'sony_playstation3_n_part3',
        'sony_playstation3_o_part1',
        'sony_playstation3_o_part2',
        'sony_playstation3_o_part3',
        'sony_playstation3_p_part1',
        'sony_playstation3_p_part2',
        'sony_playstation3_q',
        'sony_playstation3_r_part1',
        'sony_playstation3_r_part2',
        'sony_playstation3_r_part3',
        'sony_playstation3_r_part4',
        'sony_playstation3_s_part1',
        'sony_playstation3_s_part2',
        'sony_playstation3_s_part3',
        'sony_playstation3_s_part4',
        'sony_playstation3_s_part5',
        'sony_playstation3_s_part6',
        'sony_playstation3_t_part1',
        'sony_playstation3_t_part2',
        'sony_playstation3_t_part3',
        'sony_playstation3_t_part4',
        'sony_playstation3_u_part1',
        'sony_playstation3_u_part2',
        'sony_playstation3_v',
        'sony_playstation3_w_part1',
        'sony_playstation3_w_part2',
        'sony_playstation3_x',
        'sony_playstation3_y',
        'sony_playstation3_z',
    ],
    'xbox_archive': [
        'microsoft_xbox_numberssymbols',
        'microsoft_xbox_a',
        'microsoft_xbox_b',
        'microsoft_xbox_c_part1',
        'microsoft_xbox_c_part2',
        'microsoft_xbox_d_part1',
        'microsoft_xbox_d_part2',
        'microsoft_xbox_e',
        'microsoft_xbox_f',
        'microsoft_xbox_g',
        'microsoft_xbox_h',
        'microsoft_xbox_i',
        'microsoft_xbox_j',
        'microsoft_xbox_k',
        'microsoft_xbox_l',
        'microsoft_xbox_m_part1',
        'microsoft_xbox_m_part2',
        'microsoft_xbox_n_part1',
        'microsoft_xbox_n_part2',
        'microsoft_xbox_o_part1',
        'microsoft_xbox_o_part2',
        'microsoft_xbox_p',
        'microsoft_xbox_q',
        'microsoft_xbox_r',
        'microsoft_xbox_s_part1',
        'microsoft_xbox_s_part2',
        'microsoft_xbox_t_part1',
        'microsoft_xbox_t_part2',
        'microsoft_xbox_u',
        'microsoft_xbox_v',
        'microsoft_xbox_w',
        'microsoft_xbox_x',
        'microsoft_xbox_y',
        'microsoft_xbox_z',
    ],
    'xbox360_archive': [
        'microsoft_xbox360_numberssymbols',
        'microsoft_xbox360_a_part1',
        'microsoft_xbox360_a_part2',
        'microsoft_xbox360_b_part1',
        'microsoft_xbox360_b_part2',
        'microsoft_xbox360_c_part1',
        'microsoft_xbox360_c_part2',
        'microsoft_xbox360_d_part1',
        'microsoft_xbox360_d_part2',
        'microsoft_xbox360_d_part3',
        'microsoft_xbox360_e',
        'microsoft_xbox360_f_part1',
        'microsoft_xbox360_f_part2',
        'microsoft_xbox360_g',
        'microsoft_xbox360_h',
        'microsoft_xbox360_i',
        'microsoft_xbox360_j',
        'microsoft_xbox360_k',
        'microsoft_xbox360_l',
        'microsoft_xbox360_m_part1',
        'microsoft_xbox360_m_part2',
        'microsoft_xbox360_n_part1',
        'microsoft_xbox360_n_part2',
        'microsoft_xbox360_o',
        'microsoft_xbox360_p',
        'microsoft_xbox360_q',
        'microsoft_xbox360_r',
        'microsoft_xbox360_r_part1',
        'microsoft_xbox360_s_part1',
        'microsoft_xbox360_s_part2',
        'microsoft_xbox360_t_part1',
        'microsoft_xbox360_t_part2',
        'microsoft_xbox360_u',
        'microsoft_xbox360_v',
        'microsoft_xbox360_w',
        'microsoft_xbox360_x_part1',
        'microsoft_xbox360_x_part2',
        'microsoft_xbox360_y',
        'microsoft_xbox360_z',
    ],
    'nds_decrypted_archive': ['pack-roms-nintendo-ds-eu-usa-jap-rabbits-games'],
    '3ds_encrypted_archive': ['3ds-main-encrypted', '3ds-main-encrypted-p2'],
    'wiiu_archive': ['nointro_wiiu_cdn_nov_2020'],
    'psp_archive': ['psp_20220507', 'psp_20220507_2', 'psp-minis-chd'],
}


def source_order_key(source: dict) -> tuple:
    """Trie les sources avec archive.org en tout dernier recours."""
    return (
        int(source.get('order', SOURCE_TYPE_ORDER.get(source.get('type'), 60))),
        source.get('priority', 50),
        source.get('name', '').lower()
    )


def expand_collection_group(group_name: str) -> list[str]:
    """Retourne les identifiants archive.org d'un groupe RomGoGetter."""
    return list(ROMGOGETTER_ARCHIVE_ORG_COLLECTION_GROUPS.get(group_name, []))


def parse_archive_org_collection_spec(value) -> dict | None:
    """Normalise un identifiant ou une URL archive.org /download en spec cible."""
    if isinstance(value, dict):
        identifier = str(value.get('identifier', '')).strip()
        if not identifier:
            return None
        spec = {'identifier': identifier}
        path_prefix = str(value.get('path_prefix', '') or '').strip().strip('/')
        if path_prefix:
            spec['path_prefix'] = path_prefix
        return spec

    raw = str(value or '').strip()
    if not raw:
        return None

    if raw in ROMGOGETTER_ARCHIVE_ORG_COLLECTION_GROUPS:
        return {'group': raw}

    if raw.startswith(('http://', 'https://')):
        parsed = urlparse(raw)
        parts = [unquote(part) for part in parsed.path.split('/') if part]
        if parsed.netloc.endswith('archive.org') and len(parts) >= 2 and parts[0] in {'download', 'metadata', 'details'}:
            spec = {'identifier': parts[1]}
            if parts[0] == 'download' and len(parts) > 2:
                spec['path_prefix'] = '/'.join(parts[2:]).strip('/')
            return spec
        return None

    return {'identifier': raw}


def parse_archive_org_collection_specs(values) -> list:
    """Aplati des identifiants, groupes ou URLs archive.org en specs dedupliquees."""
    if not values:
        return []
    raw_values = values if isinstance(values, (list, tuple, set)) else [values]
    specs = []
    seen = set()
    for value in raw_values:
        parsed = parse_archive_org_collection_spec(value)
        if not parsed:
            continue
        if parsed.get('group'):
            group_values = expand_collection_group(parsed['group'])
            group_specs = parse_archive_org_collection_specs(group_values)
            for spec in group_specs:
                key = (spec.get('identifier', ''), spec.get('path_prefix', ''))
                if key not in seen:
                    seen.add(key)
                    specs.append(spec)
            continue
        key = (parsed.get('identifier', ''), parsed.get('path_prefix', ''))
        if key not in seen:
            seen.add(key)
            specs.append(parsed)
    return specs


def archive_org_collection_identifiers(values) -> list[str]:
    """Retourne seulement les identifiants archive.org normalises."""
    return [spec['identifier'] for spec in parse_archive_org_collection_specs(values)]


def normalize_source_label(value: str) -> str:
    """Normalise un nom de provider pour les retries."""
    return re.sub(r'\s+', ' ', (value or '').strip().lower())


def active_source_labels(sources: list) -> list[str]:
    """Retourne les labels stables des sources actives."""
    labels = []
    for source in sources or []:
        if source.get('enabled', True) and source.get('compatible', True):
            labels.append(normalize_source_label(source.get('name') or source.get('type', '')))
    return sorted(label for label in labels if label)


def provider_exclusion_labels(provider_item: dict) -> set[str]:
    """Retourne les labels a exclure pour chercher le provider suivant."""
    source = provider_item.get('source', '')
    labels = {normalize_source_label(source)}
    source_type = normalize_source_label(provider_item.get('type', ''))
    if source_type:
        labels.add(source_type)

    source_label = normalize_source_label(source)
    host_label = normalize_source_label(provider_item.get('database_host', ''))
    if source_label.startswith('database'):
        labels.add('database')
    if '1fichier' in source_label or '1fichier' in host_label:
        labels.add('database (1fichier)')
        labels.add('1fichier')
    if 'archive.org' in source_label or 'archive.org' in host_label:
        labels.add('archive.org')
        labels.add('archive_org')
    if 'archive.org cible' in source_label:
        labels.add('archive_org_collection')
    if 'minerva' in source_label or 'minerva' in host_label:
        labels.add('minerva')
        labels.add('minerva official hashes')
    return {label for label in labels if label}


def resolution_cache_key(game_info: dict, sources: list, system_name: str,
                         dat_profile: dict | None, excluded_sources: set[str] | None = None) -> str:
    """Construit une cle de cache pour une resolution provider."""
    from ._facade import normalize_checksum
    roms = game_info.get('roms') or []
    signature_parts = []
    for rom_info in roms:
        signature_parts.extend([
            normalize_checksum(rom_info.get('md5', ''), 'md5'),
            normalize_checksum(rom_info.get('crc', ''), 'crc'),
            normalize_checksum(rom_info.get('sha1', ''), 'sha1'),
            str(rom_info.get('size', '')).strip(),
        ])
    payload = {
        'game': game_info.get('game_name', ''),
        'primary_rom': game_info.get('primary_rom', ''),
        'system': system_name or '',
        'family': (dat_profile or {}).get('family', ''),
        'sources': active_source_labels(sources),
        'source_order': [
            {
                'label': normalize_source_label(source.get('name') or source.get('type', '')),
                'type': source.get('type', ''),
                'order': int(source.get('order', SOURCE_TYPE_ORDER.get(source.get('type'), 60))),
                'priority': source.get('priority', 50),
                'enabled': bool(source.get('enabled', True)),
                'compatible': bool(source.get('compatible', True)),
            }
            for source in sorted(sources or [], key=source_order_key)
        ],
        'excluded': sorted(excluded_sources or []),
        'signatures': [part for part in signature_parts if part],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(encoded.encode('utf-8')).hexdigest()


def resolve_game_sources_with_cache(game_info: dict, sources: list, session,
                                     system_name: str, dat_profile: dict | None,
                                     excluded_sources: set[str] | None = None,
                                     cache: dict | None = None) -> tuple[list, list, bool]:
    """Resout les sources d'un jeu en utilisant un cache persistant court."""
    from ._facade import search_all_sources, clean_download_resolution
    cache = cache or {'entries': {}}
    entries = cache.setdefault('entries', {})
    key = resolution_cache_key(game_info, sources, system_name, dat_profile, excluded_sources)
    now = time.time()
    cached = entries.get(key)
    if cached and now - float(cached.get('created_at', 0)) <= RESOLUTION_CACHE_TTL_SECONDS:
        return [item.copy() for item in cached.get('found', [])], [item.copy() for item in cached.get('unavailable', [])], True

    found = []
    unavailable = []
    seen_sources = set()
    excluded = {
        normalize_source_label(source_name)
        for source_name in (excluded_sources or set())
        if source_name
    }
    max_passes = max(1, len([s for s in sources or [] if s.get('enabled', True)]) + 3)

    for _attempt in range(max_passes):
        try:
            pass_found, pass_unavailable = search_all_sources(
                [clean_download_resolution(game_info)],
                sources,
                session,
                system_name,
                dat_profile,
                excluded_sources=excluded
            )
        except Exception as exc:
            unavailable.append({
                **clean_download_resolution(game_info),
                'source': 'resolution',
                'error': str(exc),
            })
            break

        if pass_unavailable:
            unavailable = [item.copy() for item in pass_unavailable]
        if not pass_found:
            break

        added = False
        for item in pass_found:
            labels = provider_exclusion_labels(item)
            provider_key = (
                normalize_source_label(item.get('source', '')),
                item.get('download_url') or item.get('torrent_url') or item.get('archive_org_identifier') or item.get('page_url') or '',
                item.get('download_filename') or '',
            )
            if provider_key not in seen_sources:
                found.append(item.copy())
                seen_sources.add(provider_key)
                added = True
            excluded.update(labels)
        if not added:
            break

    provider_candidates = [item.copy() for item in found]
    for item in found:
        item['provider_candidates'] = [candidate.copy() for candidate in provider_candidates]
    entries[key] = {
        'created_at': now,
        'sources': active_source_labels(sources),
        'found_sources': sorted({
            normalize_source_label(item.get('source', ''))
            for item in found
            if item.get('source')
        }),
        'found': [item.copy() for item in found],
        'unavailable': [item.copy() for item in unavailable],
    }
    return found, unavailable, False


def source_is_excluded(source: dict, excluded_sources: set[str]) -> bool:
    """Indique si une source est deja exclue pour un retry."""
    if not excluded_sources:
        return False
    labels = {
        normalize_source_label(source.get('name', '')),
        normalize_source_label(source.get('type', '')),
    }
    if source.get('type') == 'archive_org':
        labels.add('archive.org')
        labels.add('archive_org')
    if source.get('type') == 'archive_org_collection':
        labels.add('archive.org cible')
        labels.add('archive_org_collection')
    return bool(labels & excluded_sources)


def source_matches_label(source: dict, source_label: str) -> bool:
    """Compare un label runtime avec une source configuree."""
    normalized = normalize_source_label(source_label)
    if not normalized:
        return False
    labels = {
        normalize_source_label(source.get('name', '')),
        normalize_source_label(source.get('type', '')),
    }
    if source.get('type') == 'archive_org':
        labels.update({'archive.org', 'archive_org'})
    if source.get('type') == 'archive_org_collection':
        labels.update({'archive.org cible', 'archive_org_collection'})
    return normalized in labels


def find_source_config(sources: list, source_label: str) -> dict | None:
    """Retrouve la configuration source associee a un provider resolu."""
    for source in sources:
        if source_matches_label(source, source_label):
            return source
    return None


def optional_positive_int(value, *, minimum: int = 1, maximum: int | None = None) -> int | None:
    """Convertit une valeur de preference en entier positif optionnel."""
    if value in (None, ''):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < minimum:
        return None
    if maximum is not None:
        number = min(number, maximum)
    return number


def parse_candidate_limit(value, missing_count: int | None = None, default: int = 0) -> int:
    """Convertit une limite de pre-analyse; 'all' signifie tous les manquants."""
    if value is None or value == '':
        return default
    if isinstance(value, str) and value.strip().lower() in {'all', 'tout', 'tous', '*'}:
        return max(0, int(missing_count or 0))
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def source_timeout_seconds(source: dict | None, default: int = 120) -> int:
    """Timeout reseau effectif pour une source."""
    return optional_positive_int((source or {}).get('timeout_seconds'), minimum=3, maximum=1800) or default


def source_delay_seconds(source: dict | None, default: float = 0.0) -> float:
    """Delai (secondes) avant chaque telechargement pour eviter le rate-limiting."""
    val = (source or {}).get('delay_seconds')
    if val is None:
        return default
    try:
        f = float(val)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(f, 60.0))


def source_quota_limit(source: dict | None) -> int | None:
    """Quota de tentatives par run pour une source, None = illimite."""
    return optional_positive_int((source or {}).get('quota_per_run'), minimum=1, maximum=100000)


def apply_source_policies(sources: list, policies: dict) -> list:
    """Applique les politiques utilisateur (timeout, quota, delai) aux sources."""
    for source in sources:
        policy = policies.get(source.get('name', ''), {})
        if not policy:
            continue
        timeout = optional_positive_int(policy.get('timeout_seconds'), minimum=3, maximum=1800)
        if timeout is not None:
            source['timeout_seconds'] = timeout
        quota = optional_positive_int(policy.get('quota_per_run'), minimum=1, maximum=100000)
        if quota is not None:
            source['quota_per_run'] = quota
        delay = policy.get('delay_seconds')
        if delay is not None:
            try:
                source['delay_seconds'] = max(0.0, min(float(delay), 60.0))
            except (TypeError, ValueError):
                pass
    return sources


def source_policy_summary(source: dict) -> str:
    """Resume compact d'une politique source pour les logs et diagnostics."""
    parts = []
    if source.get('timeout_seconds'):
        parts.append(f"timeout {source_timeout_seconds(source)}s")
    quota = source_quota_limit(source)
    if quota is not None:
        parts.append(f"quota {quota}/run")
    delay = source_delay_seconds(source, 0.0)
    if delay:
        parts.append(f"delai {delay:g}s")
    return ", ".join(parts)


def reserve_source_quota(source_label: str, sources: list, usage: dict | None, lock=None) -> tuple[bool, str]:
    """Reserve une tentative source si le quota par run le permet."""
    source = find_source_config(sources, source_label)
    limit = source_quota_limit(source)
    if limit is None:
        return True, ''
    normalized = normalize_source_label(source_label)
    if lock:
        lock.acquire()
    try:
        current = int((usage or {}).get(normalized, 0))
        if current >= limit:
            return False, f"quota atteint ({current}/{limit})"
        if usage is not None:
            usage[normalized] = current + 1
        return True, f"{current + 1}/{limit}"
    finally:
        if lock:
            lock.release()


def get_default_sources():
    from . import rom_database as _rom_db
    from .rom_database import load_rom_database
    rom_db = _rom_db.ROM_DATABASE
    if rom_db is None:
        rom_db = load_rom_database()
    config = rom_db.get('config_urls', {})
    sources = [
        {
            'name': 'archive.org',
            'base_url': config.get('archive_org', ''),
            'type': 'archive_org',
            'enabled': True,
            'description': 'Dernier recours HTTP apres DDL et Minerva',
            'priority': 110
        },
        {
            'name': 'Minerva No-Intro',
            'base_url': f'{MINERVA_BROWSE_BASE}No-Intro/',
            'type': 'minerva',
            'enabled': True,
            'description': 'Torrent pour les DAT No-Intro / Retool',
            'collection': 'No-Intro',
            'minerva_path_mode': 'single',
            'scan_depth': 0,
            'torrent_scope': 'system',
            'priority': 90,
            'order': 130,
        },
        {
            'name': 'Minerva Redump',
            'base_url': f'{MINERVA_BROWSE_BASE}Redump/',
            'type': 'minerva',
            'enabled': True,
            'description': 'Torrent pour les DAT Redump / Retool',
            'collection': 'Redump',
            'minerva_path_mode': 'single',
            'scan_depth': 0,
            'torrent_scope': 'system',
            'priority': 90,
            'order': 140,
        },
        {
            'name': 'Minerva TOSEC',
            'base_url': f'{MINERVA_BROWSE_BASE}TOSEC/',
            'type': 'minerva',
            'enabled': True,
            'description': 'Torrent pour la collection TOSEC',
            'collection': 'TOSEC',
            'minerva_path_mode': 'split',
            'scan_depth': 2,
            'torrent_scope': 'vendor',
            'priority': 90,
            'order': 150,
        },
        {
            'name': 'EdgeEmu',
            'base_url': config.get('edgeemu_browse', ''),
            'type': 'edgeemu',
            'enabled': True,
            'description': 'Fallback direct',
            'priority': 3,
            'order': 120,
        },
        {
            'name': 'PlanetEmu',
            'base_url': config.get('planetemu_roms', ''),
            'type': 'planetemu',
            'enabled': True,
            'description': 'Lien direct (POST) - Source FR majeure',
            'priority': 3,
            'order': 30,
        },
        {
            'name': 'LoLROMs',
            'base_url': LOLROMS_BASE,
            'type': 'lolroms',
            'enabled': True,
            'description': 'Fallback direct via Cloudflare-compatible listing',
            'priority': 3,
            'order': 10,
            'delay_seconds': 3,
        },
        {
            'name': 'Vimm\'s Lair',
            'base_url': VIMM_BASE,
            'type': 'vimm',
            'enabled': True,
            'description': 'The Vault - Source de reference historique',
            'priority': 3,
            'order': 20,
        },
        {
            'name': 'RetroGameSets',
            'base_url': RETRO_GAME_SETS_BASE,
            'type': 'retrogamesets',
            'enabled': True,
            'description': 'JSON DB - 1fichier (AllDebrid recommande)',
            'priority': 2,
            'order': 90,
        },
        {
            'name': 'RomHustler',
            'base_url': ROMHUSTLER_BASE,
            'type': 'romhustler',
            'enabled': True,
            'description': 'DDL guest - 500KB/s, jeux populaires bloques',
            'priority': 3,
            'order': 40,
        },
        {
            'name': 'CoolROM',
            'base_url': COOLROM_BASE,
            'type': 'coolrom',
            'enabled': True,
            'description': 'DDL token - Nintendo supprime, autres OK',
            'priority': 3,
            'order': 50,
        },
        {
            'name': 'NoPayStation',
            'base_url': NOPAYSTATION_BASE,
            'type': 'nopaystation',
            'enabled': True,
            'description': 'Index TSV - PS1/PS2/PS3/PSP/Vita (.pkg expirants)',
            'priority': 2,
            'order': 70,
        },
        {
            'name': 'StartGame',
            'base_url': STARTGAME_BASE,
            'type': 'startgame',
            'enabled': True,
            'description': 'Sets No-Intro/Redump via 1fichier (AllDebrid recommande)',
            'priority': 2,
            'order': 100,
        },
        {
            'name': 'hShop',
            'base_url': HSHOP_BASE,
            'type': 'hshop',
            'enabled': True,
            'description': '3DS uniquement - .cia cryptes, partiel',
            'priority': 3,
            'order': 80,
        },
        {
            'name': 'RomsXISOs',
            'base_url': ROMSXISOS_BASE,
            'type': 'romsxisos',
            'enabled': True,
            'description': 'GitHub Pages - Google Drive / directs non-Myrient',
            'priority': 3,
            'order': 60,
        },
        {
            'name': 'archive.org cible',
            'base_url': ARCHIVE_ORG_DOWNLOAD_BASE,
            'type': 'archive_org_collection',
            'enabled': True,
            'description': 'Collections archive.org fixes par systeme (RomGoGetter, Redump, No-Intro)',
            'priority': 90,
            'order': 110,
        },
    ]
    return sorted(sources, key=source_order_key)


SYSTEM_MAPPINGS = {
    # ── Nintendo ──
    'Nintendo - Game Boy': {
        'edgeemu': 'nintendo-gameboy',
        'planetemu': 'nintendo-game-boy',
        'lolroms': 'Nintendo/Game Boy',
        'retrogamesets': 'Game Boy (Archive)',
        'romhustler': 'gbc',
        'coolrom': 'gb',
        'romsxisos': 'gameboy',
        'startgame': 'nintendo-game-boy',
        'vimm': 'GB',
    },
    'Nintendo - Game Boy Color': {
        'edgeemu': 'nintendo-gameboycolor',
        'planetemu': 'nintendo-game-boy-color',
        'lolroms': 'Nintendo/Game Boy Color',
        'retrogamesets': 'Game Boy Color (Archive)',
        'romhustler': 'gbc',
        'coolrom': 'gbc',
        'romsxisos': 'gameboycolor',
        'vimm': 'GBC',
    },
    'Nintendo - Game Boy Advance': {
        'edgeemu': 'nintendo-gba',
        'planetemu': 'nintendo-game-boy-advance',
        'lolroms': 'Nintendo/Game Boy Advance',
        'retrogamesets': 'Game Boy Advance (Archive)',
        'romhustler': 'gba',
        'coolrom': 'gba',
        'romsxisos': 'gba',
        'vimm': 'GBA',
    },
    'Nintendo - Game Boy Advance (Multiboot)': {
        'lolroms': 'Nintendo/Game Boy Advance/Multiboot',
    },
    'Nintendo - Game Boy Advance (eReader)': {
        'lolroms': 'Nintendo/Game Boy Advance/e-Reader',
    },
    'Nintendo - Nintendo Entertainment System': {
        'edgeemu': 'nintendo-nes',
        'planetemu': 'nintendo-entertainment-system',
        'lolroms': 'Nintendo/Nintendo Entertainment System/Headerless',
        'retrogamesets': 'NES (Archive)',
        'romhustler': 'nes',
        'coolrom': 'nes',
        'romsxisos': 'nes',
        'vimm': 'NES',
    },
    'Nintendo - Nintendo Entertainment System (Headered)': {
        'edgeemu': 'nintendo-nes',
        'planetemu': 'nintendo-entertainment-system',
        'lolroms': 'Nintendo/Nintendo Entertainment System',
        'romhustler': 'nes',
        'coolrom': 'nes',
        'vimm': 'NES',
    },
    'Nintendo - Super Nintendo Entertainment System': {
        'edgeemu': 'nintendo-snes',
        'planetemu': 'nintendo-super-nintendo-entertainment-system',
        'lolroms': 'Nintendo/Super Nintendo Entertainment System',
        'retrogamesets': 'SNES (Archive)',
        'romhustler': 'snes',
        'coolrom': 'snes',
        'romsxisos': 'snes',
        'vimm': 'SNES',
    },
    'Nintendo - Nintendo 64': {
        'edgeemu': 'nintendo-n64',
        'planetemu': 'nintendo-64',
        'lolroms': 'Nintendo/Nintendo 64',
        'retrogamesets': 'Nintendo 64 (Archive)',
        'romhustler': 'n64',
        'coolrom': 'n64',
        'romsxisos': 'n64',
        'vimm': 'N64',
    },
    'Nintendo - DS': {
        'lolroms': 'Nintendo/DS',
        'planetemu': 'nintendo-ds',
        'retrogamesets': 'Nintendo DS (LolRoms)',
        'romhustler': 'nds',
        'coolrom': 'nds',
        'vimm': 'DS',
        'archive_org_collection': expand_collection_group('nds_decrypted_archive'),
    },
    'Nintendo - 3DS': {
        'lolroms': 'Nintendo/3DS',
        'planetemu': 'nintendo-3ds',
        'retrogamesets': '3DS (Archive)',
        'coolrom': '3ds',
        'hshop': 'games',
        'vimm': '3DS',
        'archive_org_collection': expand_collection_group('3ds_encrypted_archive'),
    },
    'Nintendo - GameCube': {
        'edgeemu': 'nintendo-gamecube',
        'lolroms': 'Nintendo/GameCube',
        'planetemu': 'nintendo-gamecube',
        'retrogamesets': 'Game Cube (Archive)',
        'romhustler': 'gamecube',
        'coolrom': 'gamecube',
        'romsxisos': 'gamecube',
        'startgame': 'nintendo-gamecube',
        'vimm': 'GameCube',
        'archive_org_collection': ['GCRedumpNKitPart1', 'GCRedumpNKitPart2'],
    },
    'Nintendo - Wii': {
        'lolroms': 'Nintendo/Wii',
        'planetemu': 'nintendo-wii',
        'retrogamesets': 'Wii (Archive)',
        'romhustler': 'wii',
        'coolrom': 'wii',
        'romsxisos': 'wii',
        'vimm': 'Wii',
    },
    'Nintendo - Wii U': {
        'lolroms': 'Nintendo/Wii U',
        'planetemu': 'nintendo-wii-u',
        'retrogamesets': 'Wii U (EU) (1Fichier)',
        'coolrom': 'wii-u',
        'vimm': 'WiiU',
        'archive_org_collection': expand_collection_group('wiiu_archive'),
    },
    'Nintendo - Virtual Boy': {
        'lolroms': 'Nintendo/Virtual Boy',
        'planetemu': 'nintendo-virtual-boy',
        'retrogamesets': 'Virtual Boy (Archive)',
        'coolrom': 'vb',
        'romsxisos': 'virtualboy',
        'vimm': 'VB',
    },
    'Nintendo - Pokémon Mini': {
        'lolroms': 'Nintendo/Pokémon Mini',
        'planetemu': 'nintendo-pokemon-mini',
        'retrogamesets': 'Pokemon Mini (Archive)',
        'romsxisos': 'pokemonmini',
        'coolrom': 'pokemonmini',
    },

    # ── Sega ──
    'Sega - Mega Drive - Genesis': {
        'edgeemu': 'sega-genesis',
        'lolroms': 'SEGA/Mega Drive - Genesis',
        'planetemu': 'sega-mega-drive',
        'retrogamesets': 'Mega Drive (Archive)',
        'romhustler': 'genesis',
        'coolrom': 'genesis',
        'romsxisos': 'segagenesis',
        'startgame': 'sega-mega-drive-genesis',
        'vimm': 'Genesis',
    },
    'Sega - Master System - Mark III': {
        'edgeemu': 'sega-mastersystem',
        'lolroms': 'SEGA/Master System - Mark III',
        'planetemu': 'sega-master-system',
        'retrogamesets': 'Master System (Archive)',
        'romhustler': 'sms',
        'coolrom': 'sms',
        'startgame': 'sega-master-system-mark-iii',
        'vimm': 'SMS',
    },
    'Sega - Game Gear': {
        'edgeemu': 'sega-gamegear',
        'lolroms': 'SEGA/Game Gear',
        'planetemu': 'sega-game-gear',
        'retrogamesets': 'Game Gear (Archive)',
        'coolrom': 'gamegear',
        'romsxisos': 'gamegear',
        'startgame': 'sega-game-gear',
        'vimm': 'GG',
    },
    'Sega - Saturn': {
        'edgeemu': 'sega-saturn',
        'lolroms': 'SEGA/Saturn',
        'planetemu': 'sega-saturn',
        'retrogamesets': 'Saturn (Archive)',
        'romhustler': 'saturn',
        'coolrom': 'saturn',
        'romsxisos': 'saturn',
        'startgame': 'sega-saturn',
        'vimm': 'Saturn',
    },
    'Sega - Dreamcast': {
        'edgeemu': 'sega-dreamcast',
        'lolroms': 'SEGA/Dreamcast',
        'planetemu': 'sega-dreamcast',
        'retrogamesets': 'Dreamcast (Archive)',
        'romhustler': 'dreamcast',
        'coolrom': 'dc',
        'romsxisos': 'dreamcast',
        'startgame': 'sega-dreamcast',
        'vimm': 'Dreamcast',
    },
    'Sega - Mega CD - Sega CD': {
        'edgeemu': 'sega-segacd',
        'lolroms': 'SEGA/Mega Drive - Genesis/Mega-CD',
        'planetemu': 'sega-mega-cd',
        'retrogamesets': 'Sega CD (Archive)',
        'romhustler': 'segacd',
        'coolrom': 'segacd',
        'romsxisos': 'segacd',
        'startgame': 'sega-mega-cd-sega-cd',
        'vimm': 'SegaCD',
    },
    'Sega - 32X': {
        'edgeemu': 'sega-32x',
        'lolroms': 'SEGA/Mega Drive - Genesis/32X',
        'planetemu': 'sega-32x',
        'retrogamesets': '32X (Archive)',
        'coolrom': '32x',
        'romsxisos': '32x',
        'startgame': 'sega-32x',
        'vimm': '32X',
    },

    # ── Sony ──
    'Sony - PlayStation': {
        'edgeemu': 'sony-playstation',
        'lolroms': 'SONY/PlayStation',
        'planetemu': 'sony-playstation',
        'retrogamesets': 'PlayStation (Archive)',
        'romhustler': 'psx',
        'coolrom': 'psx',
        'romsxisos': 'ps1',
        'startgame': 'sony-playstation',
        'vimm': 'PS1',
        'nopaystation': 'PSX_GAMES',
        'archive_org_collection': expand_collection_group('ps1_archive'),
    },
    'Sony - PlayStation Portable': {
        'edgeemu': 'sony-psp',
        'lolroms': 'SONY/PlayStation Portable',
        'planetemu': 'sony-psp',
        'retrogamesets': 'PlayStation Portable (Archive)',
        'romhustler': 'playstation-portable',
        'coolrom': 'psp',
        'romsxisos': 'psp',
        'startgame': 'sony-playstation-portable',
        'vimm': 'PSP',
        'nopaystation': 'PSP_GAMES',
        'archive_org_collection': expand_collection_group('psp_archive'),
    },
    'Sony - PlayStation 2': {
        'edgeemu': 'sony-playstation-2',
        'lolroms': 'SONY/PlayStation 2',
        'planetemu': 'sony-playstation-2',
        'retrogamesets': 'PS2 (Archive)',
        'romhustler': 'playstation2',
        'coolrom': 'ps2',
        'romsxisos': 'ps2',
        'startgame': 'sony-playstation-2',
        'vimm': 'PS2',
        'archive_org_collection': expand_collection_group('ps2_archive'),
    },
    'Sony - PlayStation 3': {
        'edgeemu': 'sony-playstation-3',
        'lolroms': 'SONY/PlayStation 3 (T-En)',
        'planetemu': 'sony-playstation-3',
        'retrogamesets': 'PS3 (Archive)',
        'romhustler': 'ps3',
        'coolrom': 'ps3',
        'romsxisos': 'ps3',
        'vimm': 'PS3',
        'nopaystation': 'PS3_GAMES',
        'archive_org_collection': expand_collection_group('ps3_archive'),
    },
    'Sony - PlayStation Vita': {
        'edgeemu': 'sony-psvita',
        'lolroms': 'SONY/PlayStation Portable',
        'planetemu': 'sony-psvita',
        'retrogamesets': 'PS Vita (Archive)',
        'romhustler': 'ps-vita',
        'coolrom': 'psvita',
        'nopaystation': 'PSV_GAMES',
    },

    # ── Atari ──
    'Atari - 2600': {
        'edgeemu': 'atari-2600',
        'lolroms': 'Atari/2600',
        'planetemu': 'atari-2600',
        'romhustler': 'atari2600',
        'coolrom': 'atari2600',
        'romsxisos': 'atari2600',
        'startgame': 'atari-2600',
        'vimm': 'Atari2600',
    },
    'Atari - Jaguar CD Interactive Multimedia System': {
        'vimm': 'JaguarCD',
        'archive_org_collection': ['redump.jaguar.revival'],
    },
    'Atari - Jaguar CD': {
        'archive_org_collection': ['redump.jaguar.revival'],
    },
    'Atari - Atari 2600': {
        'edgeemu': 'atari-2600',
        'lolroms': 'Atari/2600',
        'planetemu': 'atari-2600',
        'romhustler': 'atari2600',
        'coolrom': 'atari2600',
        'romsxisos': 'atari2600',
        'startgame': 'atari-2600',
        'vimm': 'Atari2600',
    },
    'Atari - 5200': {
        'edgeemu': 'atari-5200',
        'lolroms': 'Atari/5200',
        'planetemu': 'atari-5200',
        'romhustler': 'atari5200',
        'coolrom': 'atari5200',
        'romsxisos': 'atari5200',
        'vimm': 'Atari5200',
    },
    'Atari - Atari 5200': {
        'edgeemu': 'atari-5200',
        'lolroms': 'Atari/5200',
        'planetemu': 'atari-5200',
        'romhustler': 'atari5200',
        'coolrom': 'atari5200',
        'romsxisos': 'atari5200',
        'vimm': 'Atari5200',
    },
    'Atari - 7800': {
        'edgeemu': 'atari-7800',
        'lolroms': 'Atari/7800',
        'planetemu': 'atari-7800',
        'romhustler': 'atari7800',
        'coolrom': 'atari7800',
        'startgame': 'atari-7800',
        'vimm': 'Atari7800',
    },
    'Atari - Atari 7800': {
        'edgeemu': 'atari-7800',
        'lolroms': 'Atari/7800',
        'planetemu': 'atari-7800',
        'romhustler': 'atari7800',
        'coolrom': 'atari7800',
        'startgame': 'atari-7800',
        'vimm': 'Atari7800',
    },
    'Atari - Jaguar': {
        'edgeemu': 'atari-jaguar',
        'lolroms': 'Atari/Jaguar',
        'planetemu': 'atari-jaguar',
        'romhustler': 'jaguar',
        'coolrom': 'atarijaguar',
        'romsxisos': 'atarijaguar',
        'startgame': 'atari-jaguar',
        'vimm': 'Jaguar',
    },
    'Atari - Atari Jaguar': {
        'edgeemu': 'atari-jaguar',
        'lolroms': 'Atari/Jaguar',
        'planetemu': 'atari-jaguar',
        'romhustler': 'jaguar',
        'coolrom': 'atarijaguar',
        'romsxisos': 'atarijaguar',
        'startgame': 'atari-jaguar',
        'vimm': 'Jaguar',
    },

    # ── NEC / TurboGrafx ──
    'NEC - PC Engine - TurboGrafx 16': {
        'edgeemu': 'nec-pcengine',
        'lolroms': 'NEC/PC-Engine',
        'planetemu': 'nec-pc-engine-turbografx-16-entertainment-super-system',
        'retrogamesets': 'PC Engine (Archive)',
        'romhustler': 'pcengine',
        'coolrom': 'tg16',
        'startgame': 'nec-pc-engine-turbografx-16',
        'vimm': 'TG16',
    },
    'NEC - PC-FX': {
        'vimm': 'PCFX',
        'edgeemu': 'nec-pcfx',
        'lolroms': 'NEC/PC-FX',
        'planetemu': 'nec-pc-fx',
        'coolrom': 'pcfx',
        'startgame': 'nec-pc-fx',
    },

    # ── SNK ──
    'SNK - Neo Geo Pocket': {
        'vimm': 'NGP',
        'lolroms': 'SNK/NeoGeo Pocket',
    },
    'SNK - Neo Geo Pocket Color': {
        'vimm': 'NGPC',
        'edgeemu': 'snk-neogeopocketcolor',
        'lolroms': 'SNK/NeoGeo Pocket Color',
        'planetemu': 'snk-neo-geo-pocket-color',
        'retrogamesets': 'Neo-Geo Pocket Color (Archive)',
        'coolrom': 'ngpc',
        'romsxisos': 'pocket_color',
        'startgame': 'snk-neo-geo-pocket-color',
    },

    # ── Bandai ──
    'Bandai - WonderSwan': {
        'vimm': 'WS',
        'edgeemu': 'bandai-wonderswan',
        'lolroms': 'Bandai/WonderSwan',
        'planetemu': 'bandai-wonderswan',
        'retrogamesets': 'WonderSwan (Archive)',
        'romhustler': 'wonderswan',
        'coolrom': 'ws',
        'romsxisos': 'wonderswan',
        'startgame': 'bandai-wonderswan',
    },
    # ── Additional Nintendo (variantes avec sous-dossiers) ──
    'Nintendo - Game Boy Advance (e-Reader)': {
        'lolroms': 'Nintendo/Game Boy Advance/e-Reader',
    },
    'Nintendo - Game Boy Advance (Play-Yan)': {
        'lolroms': 'Nintendo/Game Boy Advance/Play-Yan',
    },
    'Nintendo - Game Boy Advance (Video)': {
        'lolroms': 'Nintendo/Game Boy Advance/Video',
    },
    'Nintendo - New Nintendo 3DS': {
        'lolroms': 'Nintendo/3DS/New 3DS',
    },
    'Nintendo - Nintendo DSi': {
        'lolroms': 'Nintendo/DS/DSi',
    },
    'Nintendo - Nintendo 64DD': {
        'lolroms': 'Nintendo/Nintendo 64/64DD',
    },
    'Nintendo - Satellaview': {
        'lolroms': 'Nintendo/Super Nintendo Entertainment System/Satellaview',
    },
    'Nintendo - Sufami Turbo': {
        'lolroms': 'Nintendo/Super Nintendo Entertainment System/SuFami Turbo',
    },
    'Nintendo - Family Computer Disk System': {
        'lolroms': 'Nintendo/Nintendo Entertainment System/Disk System',
    },

    # ── Sega supplémentaires ──
    'Sega - PICO': {
        'lolroms': 'SEGA/PICO',
    },
    'Sega - SG-1000': {
        'lolroms': 'SEGA/SG-1000 - SC-3000',
    },

    # ── SNK variantes ──
    'SNK - Neo Geo CD': {
        'lolroms': 'SNK/NeoGeo CD',
    },
    'SNK - NeoGeo Pocket': {
        'lolroms': 'SNK/NeoGeo Pocket',
    },
    'SNK - NeoGeo Pocket Color': {
        'lolroms': 'SNK/NeoGeo Pocket Color',
    },

    # ── Panasonic ──
    'Panasonic - 3DO Interactive Multiplayer': {
        'lolroms': 'Panasonic - 3DO',
    },

    # ── NEC variantes ──
    'NEC - PC Engine CD & TurboGrafx CD': {
        'vimm': 'TGCD',
        'lolroms': 'NEC/PC-Engine',
    },
    'NEC - PC-88': {
        'lolroms': 'NEC/PC-88',
    },
    'NEC - PC-88 series': {
        'lolroms': 'NEC/PC8 Series',
    },
    'NEC - PC-98': {
        'lolroms': 'NEC/PC-98',
    },
    'NEC - PC-98 series': {
        'lolroms': 'NEC/PC98',
    },
    'NEC - PC-FX & PC-FXGA': {
        'lolroms': 'NEC/PC-FX',
    },

    # ── Microsoft ──
    'Microsoft - Xbox': {
        'lolroms': 'Microsoft/Xbox',
        'archive_org_collection': expand_collection_group('xbox_archive'),
    },
    'Microsoft - Xbox 360': {
        'lolroms': 'Microsoft/Xbox 360',
        'archive_org_collection': expand_collection_group('xbox360_archive'),
    },
    'Microsoft - MSX': {
        'lolroms': 'Microsoft/MSX',
    },
    'Microsoft - MSX2': {
        'lolroms': 'Microsoft/MSX2',
    },

    # ── Commodore ──
    'Commodore - Amiga': {
        'lolroms': 'Commodore/Amiga',
    },
    'Commodore - Amiga CD': {
        'lolroms': 'Commodore/Amiga CD',
    },
    'Commodore - Amiga CD32': {
        'lolroms': 'Commodore/Amiga CD32',
    },
    'Commodore - Amiga CDTV': {
        'lolroms': 'Commodore/Amiga CDTV',
    },
    'Commodore - Commodore 64': {
        'lolroms': 'Commodore/64',
    },

    # ── Bandai supplémentaires ──
    'Bandai - WonderSwan Color': {
        'lolroms': 'Bandai/WonderSwan Color',
    },

    # ── Phillips ──
    'Philips - CD-i': {
        'lolroms': 'Philips/CD-i',
    },
    'Philips - Videopac+': {
        'lolroms': 'Philips - Videopac+',
    },

    # ── Atari supplémentaires ──
    'Atari - Atari Lynx': {
        'vimm': 'Lynx',
        'lolroms': 'Atari/Lynx',
    },
    'Atari - Atari ST': {
        'vimm': 'ST',
        'lolroms': 'Atari/ST',
    },
    'Atari - Jaguar CD Interactive Multimedia System': {
        'lolroms': 'Atari/Jaguar/CD',
    },
    'Atari - 8-bit Family': {
        'lolroms': 'Atari/800',
    },

    # ── Apple ──
    'Apple - Macintosh': {
        'lolroms': 'Apple/Macintosh',
    },

    # ── Fujitsu ──
    'Fujitsu - FM-Towns': {
        'lolroms': 'Fujitsu/FM Towns',
    },

    # ── Sharp ──
    'Sharp - X68000': {
        'lolroms': 'Sharp/X68000',
    },

    # ── Sega Arcade CD ──
    'Sega - Mega CD & Sega CD': {
        'edgeemu': 'sega-segacd',
        'lolroms': 'SEGA/Mega Drive - Genesis/Mega-CD',
        'planetemu': 'sega-mega-cd',
    },

    # ── Watara ──
    'Watara - Supervision': {
        'lolroms': 'Watara - Supervision',
    },

    # ── VTech ──
    'VTech - CreatiVision': {
        'lolroms': 'VTech/CreatiVision',
    },
    'VTech - V.Smile': {
        'lolroms': 'VTech/V.Smile',
    },
    'VTech - Mobigo': {
        'lolroms': 'VTech/Mobigo',
    },
    'VTech - V.Flash & V.Smile Pro': {
        'lolroms': 'VTech/V.Flash & V.Smile Pro',
    },

    # ── Mattel ──
    'Mattel - HyperScan': {
        'lolroms': 'Mattel/HyperScan',
    },
    'Mattel - Intellivision': {
        'vimm': 'Intellivision',
        'lolroms': 'Mattel/Intellivision',
    },
    'Mattel - Fisher-Price iXL': {
        'lolroms': 'Mattel/Fisher-Price iXL',
    },

    # ── GCE ──
    'GCE - Vectrex': {
        'vimm': 'Vectrex',
        'lolroms': 'GCE - Vectrex',
    },

    # ── Fairchild ──
    'Fairchild - Channel F': {
        'lolroms': 'Fairchild - Channel F',
    },

    # ── Magnavox ──
    'Magnavox - Odyssey 2': {
        'vimm': 'Odyssey2',
        'lolroms': 'Magnavox - Odyssey 2',
    },

    # ── Emerson ──
    'Emerson - Arcadia 2001': {
        'lolroms': 'Emerson - Arcadia 2001',
    },

    # ── Entex ──
    'Entex - Adventure Vision': {
        'lolroms': 'Entex - Adventure Vision',
    },

    # ── RCA ──
    'RCA - Studio II': {
        'lolroms': 'RCA - Studio II',
    },

    # ── Interton ──
    'Interton - VC 4000': {
        'lolroms': 'Interton - VC 4000',
    },

    'Acorn - Archimedes': {
        'lolroms': 'Acorn/Archimedes',
    },
    'Acorn - Atom (Tapes) (Bitstream)': {
        'lolroms': 'Acorn/Atom',
    },
    'Acorn - Risc PC': {
        'lolroms': 'Acorn/Risc PC',
    },
    'Acorn RISC OS - Flash Media (Misc)': {
        'lolroms': 'Acorn/Risc PC',
    },
    'ACT - Apricot PC Xi': {
        'lolroms': 'ACT - Apricot PC Xi',
    },
    'Amstrad - CPC': {
        'lolroms': 'Amstrad - CPC',
    },
    'APF - Imagination Machine': {
        'lolroms': 'APF/Imagination Machine',
    },
    'APF - MP-1000': {
        'lolroms': 'APF/MP-1000',
    },
    'Apple - I (Tapes)': {
        'lolroms': 'Apple/I',
    },
    'Apple - II': {
        'lolroms': 'Apple/II',
    },
    'Apple - II Plus': {
        'lolroms': 'Apple/II Plus',
    },
    'Apple - IIe': {
        'lolroms': 'Apple/IIe',
    },
    'Apple - IIGS': {
        'lolroms': 'Apple/IIGS',
    },
    'Apple - Macintosh (BETA)': {
        'lolroms': 'Apple/Macintosh',
    },
    'Apple-Bandai - Pippin (Floppies)': {
        'lolroms': 'Apple/Pippin',
    },
    'Arcade - Konami - e-Amusement': {
        'lolroms': 'Arcade/Konami e-Amusement',
    },
    'Arcade - Konami - FireBeat': {
        'lolroms': 'Arcade/Konami FireBeat',
    },
    'Arcade - Konami - System 573': {
        'lolroms': 'Arcade/Konami System 573',
    },
    'Arcade - Konami - System GV': {
        'lolroms': 'Arcade/Konami System GV',
    },
    'Arcade - Namco - Sega - Nintendo - Triforce': {
        'lolroms': 'Arcade/Triforce',
    },
    'Arcade - Namco - System 246': {
        'lolroms': 'Arcade/Namco System 246',
    },
    'Arcade - PC-based': {
        'lolroms': 'Arcade/PC-based',
    },
    'Arcade - Sega - Chihiro': {
        'lolroms': 'Arcade/Sega Chihiro',
    },
    'Arcade - Sega - Lindbergh': {
        'lolroms': 'Arcade/Sega Lindbergh',
    },
    'Arcade - Sega - Naomi': {
        'lolroms': 'Arcade/Sega Naomi',
    },
    'Arcade - Sega - Naomi 2': {
        'lolroms': 'Arcade/Sega Naomi 2',
    },
    'Arcade - Sega - RingEdge': {
        'lolroms': 'Arcade/Sega RingEdge',
    },
    'Arcade - Sega - RingEdge 2': {
        'lolroms': 'Arcade/Sega RingEdge 2',
    },
    'Arduboy Inc - Arduboy': {
        'lolroms': 'Arduboy',
    },
    'Bally - Astrocade': {
        'lolroms': 'Bally - Astrocade',
    },
    'Bally - Astrocade (Tapes)': {
        'lolroms': 'Bally - Astrocade',
    },
    'Bandai - Design Master Denshi Mangajuku': {
        'lolroms': 'Bandai/Design Master Denshi Mangajuku',
    },
    'Bandai - Gundam RX-78': {
        'lolroms': 'Bandai/Gundam RX-78',
    },
    'Bandai - Pippin': {
        'lolroms': 'Bandai/Pippin',
    },
    'Bandai - Playdia Quick Interactive System': {
        'lolroms': 'Bandai/Playdia',
    },
    'Bandai Little Jammer': {
        'lolroms': 'Bandai/Little Jammer',
    },
    'Bandai Little Jammer Pro': {
        'lolroms': 'Bandai/Little Jammer Pro',
    },
    'Benesse - Pocket Challenge V2': {
        'lolroms': 'Benesse/Pocket Challenge V2',
    },
    'Benesse - Pocket Challenge W': {
        'lolroms': 'Benesse/Pocket Challenge W',
    },
    'Bit Corporation - Gamate': {
        'lolroms': 'Bit Corporation - Gamate',
    },
    'Blaze Entertainment - Evercade': {
        'lolroms': 'Evercade',
    },
    'Casio - Loopy': {
        'lolroms': 'CASIO/Loopy',
    },
    'Casio - PV-1000': {
        'lolroms': 'CASIO/PV-1000',
    },
    'CD-ROM': {
        'lolroms': 'CD-ROM',
    },
    'Coleco - ColecoVision': {
        'vimm': 'ColecoVision',
        'lolroms': 'ColecoVision',
    },
    'Commodore - Commodore 64 (PP)': {
        'lolroms': 'Commodore/64',
    },
    'Commodore - Commodore 64 (Tapes)': {
        'lolroms': 'Commodore/64',
    },
    'Commodore - Plus-4': {
        'lolroms': 'Commodore/Plus-4',
    },
    'Commodore - VIC-20': {
        'lolroms': 'Commodore/VIC-20',
    },
    'Digital Media Cartridge - Firecore': {
        'lolroms': 'Firecore',
    },
    'DVD-ROM': {
        'lolroms': 'DVD-ROM',
    },
    'Epoch - Game Pocket Computer': {
        'lolroms': 'Epoch/Game Pocket Computer',
    },
    'Epoch - Super Cassette Vision': {
        'lolroms': 'Epoch/Super Cassette Vision',
    },
    'Fujitsu - FM Towns': {
        'lolroms': 'Fujitsu/FM Towns',
    },
    'Fujitsu - FM-7': {
        'lolroms': 'Fujitsu/FM-7',
    },
    'Fujitsu - FM-7 (Tapes)': {
        'lolroms': 'Fujitsu/FM-7',
    },
    'Fujitsu - FMR50': {
        'lolroms': 'Fujitsu/FMR50',
    },
    'Fukutake Publishing - StudyBox': {
        'lolroms': 'Fukutake Publishing/StudyBox',
    },
    'Funtech - Super Acan': {
        'lolroms': 'Funtech - Super Acan',
    },
    'funworld - Photo Play': {
        'lolroms': 'funworld/Photo Play',
    },
    'GamePark - GP2X': {
        'lolroms': 'GamePark/GP2X',
    },
    'GamePark - GP32': {
        'lolroms': 'GamePark/GP32',
    },
    'Hartung - Game Master': {
        'lolroms': 'Hartung - Game Master',
    },
    'Hitachi - S1': {
        'lolroms': 'Hitachi - S1',
    },
    'IBM - PC and Compatibles': {
        'lolroms': 'IBM - PC & Compatibles',
    },
    'IBM - PC and Compatibles (Digital) (JAST USA)': {
        'lolroms': 'IBM - PC & Compatibles',
    },
    'IBM - PC and Compatibles (Digital) (Misc)': {
        'lolroms': 'IBM - PC & Compatibles',
    },
    'IBM - PC and Compatibles (Digital) (Unknown)': {
        'lolroms': 'IBM - PC & Compatibles',
    },
    'IBM - PC and Compatibles (Flash Media)': {
        'lolroms': 'IBM - PC & Compatibles',
    },
    'IBM - PC compatible': {
        'lolroms': 'IBM - PC & Compatibles',
    },
    'Incredible Technologies - Eagle': {
        'lolroms': 'Incredible Technologies/Eagle',
    },
    'iQue - iQue': {
        'lolroms': 'iQue',
    },
    'Konami - Picno': {
        'lolroms': 'Konami - Picno',
    },
    'LeapFrog - Explorer': {
        'lolroms': 'LeapFrog/Explorer',
    },
    'LeapFrog - LeapPad': {
        'lolroms': 'LeapFrog/LeapPad',
    },
    'LeapFrog - Leapster Learning Game System': {
        'lolroms': 'LeapFrog/Leapster',
    },
    'Luxor - ABC 800': {
        'lolroms': 'Luxor - ABC 800',
    },
    'Memorex - Visual Information System': {
        'lolroms': 'Memorex/Visual Information System',
    },
    'Microsoft - Xbox One': {
        'lolroms': 'Microsoft/Xbox One',
    },
    'Milton-Bradley - Omni': {
        'lolroms': 'Milton-Bradley/Omni',
    },
    'Mobile - J2ME': {
        'lolroms': 'Mobile/J2ME',
    },
    'Mobile - Palm OS': {
        'lolroms': 'Mobile/Palm OS',
    },
    'Mobile - Pocket PC': {
        'lolroms': 'Mobile/Pocket PC',
    },
    'Mobile - Symbian': {
        'lolroms': 'Mobile/Symbian',
    },
    'MP3 CD': {
        'lolroms': 'MP3 CD',
    },
    'NEC - PC Engine SuperGrafx': {
        'lolroms': 'NEC/PC-Engine/SuperGrafx',
    },
    'Nichibutsu - My Vision': {
        'lolroms': 'Nichibutsu - My Vision',
    },
    'Nintendo - amiibo': {
        'lolroms': 'Nintendo/amiibo',
    },
    'Nintendo - Family BASIC (Tapes)': {
        'lolroms': 'Nintendo/Family BASIC',
    },
    'Nintendo - Family Computer Network System': {
        'lolroms': 'Nintendo/Family Computer Network System',
    },
    'Nintendo - Game & Watch': {
        'lolroms': 'Nintendo/Game & Watch',
    },
    'Nintendo - Kiosk Video Compact Flash': {
        'lolroms': 'Nintendo/Kiosk Video Compact Flash',
    },
    'Nintendo - Misc': {
        'lolroms': 'Nintendo/Misc',
    },
    'Nintendo - Nintendo 3DS': {
        'lolroms': 'Nintendo/3DS',
    },
    'Nintendo - Nintendo 64 (Mario no Photopi SmartMedia)': {
        'lolroms': 'Nintendo/Nintendo 64',
    },
    'Nintendo - Nintendo DS': {
        'lolroms': 'Nintendo/DS',
    },
    'Nintendo - Nintendo DS (Download Play)': {
        'lolroms': 'Nintendo/DS',
    },
    'Nintendo - Nintendo DS (DSvision SD cards)': {
        'lolroms': 'Nintendo/DS',
    },
    'Nintendo - Nintendo GameCube (Memory Card)': {
        'lolroms': 'Nintendo/GameCube',
    },
    'Nintendo - Nintendo GameCube (NPDP Carts)': {
        'lolroms': 'Nintendo/GameCube',
    },
    'Nintendo - Pokemon Mini': {
        'lolroms': 'Nintendo/Pokémon Mini',
    },
    'Nintendo - Wallpapers': {
        'lolroms': 'Nintendo/Wallpapers',
    },
    'Nokia - N-Gage': {
        'lolroms': 'Nokia/N-Gage',
    },
    'Non-Redump - Apple-Bandai - Pippin': {
        'lolroms': 'Non-Redump/Apple-Bandai Pippin',
    },
    'Non-Redump - Atari - Atari Jaguar CD': {
        'lolroms': 'Non-Redump/Atari Jaguar CD',
    },
    'Non-Redump - Audio CD': {
        'lolroms': 'Non-Redump/Audio CD',
    },
    'Non-Redump - BD-Video': {
        'lolroms': 'Non-Redump/BD-Video',
    },
    'Non-Redump - Capcom - Play System III': {
        'lolroms': 'Non-Redump/Capcom Play System III',
    },
    'Non-Redump - Commodore - Amiga CD': {
        'lolroms': 'Non-Redump/Commodore Amiga CD',
    },
    'Non-Redump - DVD-Video': {
        'lolroms': 'Non-Redump/DVD-Video',
    },
    'Non-Redump - FuRyu & Omron - Purikura': {
        'lolroms': 'Non-Redump/FuRyu & Omron Purikura',
    },
    'Non-Redump - Hasbro - iON Educational Gaming System': {
        'lolroms': 'Non-Redump/Hasbro iON',
    },
    'Non-Redump - IBM - PC Compatible (Discs)': {
        'lolroms': 'Non-Redump/IBM PC Compatible',
    },
    'Non-Redump - Konami - M2': {
        'lolroms': 'Non-Redump/Konami M2',
    },
    'Non-Redump - Konami - Python 2': {
        'lolroms': 'Non-Redump/Konami Python 2',
    },
    'Non-Redump - Merit Megatouch': {
        'lolroms': 'Non-Redump/Merit Megatouch',
    },
    'Non-Redump - Microsoft - Pocket PC': {
        'lolroms': 'Non-Redump/Microsoft Pocket PC',
    },
    'Non-Redump - Microsoft - Xbox': {
        'lolroms': 'Non-Redump/Microsoft Xbox',
    },
    'Non-Redump - Microsoft - Xbox 360': {
        'lolroms': 'Non-Redump/Microsoft Xbox 360',
    },
    'Non-Redump - Namco - Purikura': {
        'lolroms': 'Non-Redump/Namco Purikura',
    },
    'Non-Redump - NEC - PC Engine CD + TurboGrafx CD': {
        'lolroms': 'Non-Redump/NEC PC Engine CD',
    },
    'Non-Redump - NEC - PC-88': {
        'lolroms': 'Non-Redump/NEC PC-88',
    },
    'Non-Redump - Nintendo - Nintendo GameCube': {
        'lolroms': 'Non-Redump/Nintendo GameCube',
    },
    'Non-Redump - Nintendo - Wii': {
        'lolroms': 'Non-Redump/Nintendo Wii',
    },
    'Non-Redump - Nintendo - Wii U': {
        'lolroms': 'Non-Redump/Nintendo Wii U',
    },
    'Non-Redump - Panasonic - 3DO Interactive Multiplayer': {
        'lolroms': 'Non-Redump/Panasonic 3DO',
    },
    'Non-Redump - Philips - CD-i': {
        'lolroms': 'Non-Redump/Philips CD-i',
    },
    'Non-Redump - Playmaji - Polymega': {
        'lolroms': 'Non-Redump/Playmaji Polymega',
    },
    'Non-Redump - Psion - Psion Series': {
        'lolroms': 'Non-Redump/Psion',
    },
    'Non-Redump - Sega - ALLS': {
        'lolroms': 'Non-Redump/Sega ALLS',
    },
    'Non-Redump - Sega - Dreamcast': {
        'lolroms': 'Non-Redump/Sega Dreamcast',
    },
    'Non-Redump - Sega - Nu': {
        'lolroms': 'Non-Redump/Sega Nu',
    },
    'Non-Redump - Sega - Nu 1.1': {
        'lolroms': 'Non-Redump/Sega Nu 1.1',
    },
    'Non-Redump - Sega - Nu 2': {
        'lolroms': 'Non-Redump/Sega Nu 2',
    },
    'Non-Redump - Sega - Nu SX': {
        'lolroms': 'Non-Redump/Sega Nu SX',
    },
    'Non-Redump - Sega - Sega Mega CD + Sega CD': {
        'lolroms': 'Non-Redump/Sega Mega CD',
    },
    'Non-Redump - Sega - Sega Saturn': {
        'lolroms': 'Non-Redump/Sega Saturn',
    },
    'Non-Redump - Sega NAOMI Satellite Terminal PC': {
        'lolroms': 'Non-Redump/Sega NAOMI Satellite Terminal PC',
    },
    'Non-Redump - Sharp - Zaurus': {
        'lolroms': 'Non-Redump/Sharp Zaurus',
    },
    'Non-Redump - Sony - PlayStation': {
        'lolroms': 'Non-Redump/Sony PlayStation',
    },
    'Non-Redump - Sony - PlayStation 2': {
        'lolroms': 'Non-Redump/Sony PlayStation 2',
    },
    'Non-Redump - Sony - PlayStation 3': {
        'lolroms': 'Non-Redump/Sony PlayStation 3',
    },
    'Non-Redump - Sony - PlayStation Portable': {
        'lolroms': 'Non-Redump/Sony PSP',
    },
    'Non-Redump - Sony Electronic Book': {
        'lolroms': 'Non-Redump/Sony Electronic Book',
    },
    'Non-Redump - VM Labs - NUON': {
        'lolroms': 'Non-Redump/VM Labs NUON',
    },
    'Non-Redump - ZAPiT Games - Game Wave Family Entertainment System': {
        'lolroms': 'Non-Redump/ZAPiT Game Wave',
    },
    'Ouya - Ouya': {
        'lolroms': 'Ouya',
    },
    'Palm': {
        'lolroms': 'Palm',
    },
    'Photo CD': {
        'lolroms': 'Photo CD',
    },
    'PlayStation GameShark Updates': {
        'lolroms': 'PlayStation GameShark Updates',
    },
    'Pocket PC': {
        'lolroms': 'Pocket PC',
    },
    'Project EGG': {
        'lolroms': 'Project EGG',
    },
    'Sanyo - MBC-550': {
        'lolroms': 'Sanyo - MBC-550',
    },
    'Sega - Beena': {
        'lolroms': 'SEGA/Beena',
    },
    'Sega - Dreamcast (Visual Memory Unit)': {
        'lolroms': 'SEGA/Dreamcast',
    },
    'Sega - Prologue 21': {
        'lolroms': 'SEGA/Prologue 21',
    },
    'Sega - SG-1000 - SC-3000': {
        'lolroms': 'SEGA/SG-1000 - SC-3000',
    },
    'Seta - Aleck64': {
        'lolroms': 'Seta/Aleck64',
    },
    'Sharp - MZ-2200': {
        'lolroms': 'Sharp/MZ-2200',
    },
    'Sharp - MZ-700': {
        'lolroms': 'Sharp/MZ-700',
    },
    'Sharp - X1': {
        'lolroms': 'Sharp/X1',
    },
    'Sinclair - ZX Spectrum +3': {
        'lolroms': 'Sinclair - ZX Spectrum +3',
    },
    'Sony - PlayStation (PS one Classics)': {
        'lolroms': 'SONY/PlayStation',
    },
    'Sony - PlayStation Mobile': {
        'lolroms': 'SONY/PlayStation Mobile',
    },
    'Sony - PlayStation Portable (PSN) (Minis)': {
        'lolroms': 'SONY/PlayStation Portable',
    },
    'Source Code - Apple - II': {
        'lolroms': 'Source Code/Apple II',
    },
    'Source Code - Apple - IIGS': {
        'lolroms': 'Source Code/Apple IIGS',
    },
    'Source Code - Arcade': {
        'lolroms': 'Source Code/Arcade',
    },
    'Source Code - Atari - 8-bit Family': {
        'lolroms': 'Source Code/Atari 8-bit',
    },
    'Source Code - Atari - Atari 2600': {
        'lolroms': 'Source Code/Atari 2600',
    },
    'Source Code - IBM - PC and Compatibles': {
        'lolroms': 'Source Code/IBM PC',
    },
    'Source Code - Mobile - Palm OS': {
        'lolroms': 'Source Code/Mobile Palm OS',
    },
    'Source Code - Nintendo - Game Boy Advance': {
        'lolroms': 'Source Code/Nintendo GBA',
    },
    'Source Code - Nintendo - Game Boy Color': {
        'lolroms': 'Source Code/Nintendo GBC',
    },
    'Source Code - Nintendo - Nintendo DS': {
        'lolroms': 'Source Code/Nintendo DS',
    },
    'Source Code - Nintendo - Nintendo Entertainment System': {
        'lolroms': 'Source Code/Nintendo NES',
    },
    'Source Code - Nintendo - Nintendo GameCube': {
        'lolroms': 'Source Code/Nintendo GameCube',
    },
    'Source Code - Nintendo - Super Nintendo Entertainment System': {
        'lolroms': 'Source Code/Nintendo SNES',
    },
    'Source Code - Panasonic - 3DO Interactive Multiplayer': {
        'lolroms': 'Source Code/Panasonic 3DO',
    },
    'Source Code - Panasonic - M2': {
        'lolroms': 'Source Code/Panasonic M2',
    },
    'Source Code - Sega - DreamCast': {
        'lolroms': 'Source Code/Sega Dreamcast',
    },
    'Source Code - Various': {
        'lolroms': 'Source Code/Various',
    },
    'Source Code - VM Labs - NUON': {
        'lolroms': 'Source Code/VM Labs NUON',
    },
    'TAB-Austria - Quizard': {
        'lolroms': 'TAB-Austria/Quizard',
    },
    'TeleNova - Compis': {
        'lolroms': 'TeleNova - Compis',
    },
    'Texas Instruments - TI-99-4A': {
        'lolroms': 'Texas Instruments - 99-4A',
    },
    'Tiger - Game.com': {
        'lolroms': 'Tiger/Game.com',
    },
    'Tiger - Gizmondo': {
        'lolroms': 'Tiger/Gizmondo',
    },
    'Tomy - Kiss-Site': {
        'lolroms': 'Tomy/Kiss-Site',
    },
    'Toshiba - Pasopia': {
        'lolroms': 'Toshiba/Pasopia',
    },
    'Toshiba - Visicom': {
        'lolroms': 'Toshiba/Visicom',
    },
    'Unofficial - Microsoft - Xbox 360 (Title Updates)': {
        'lolroms': 'Unofficial/Microsoft Xbox 360 Title Updates',
    },
    'Unofficial - Nintendo - Nintendo 3DS': {
        'lolroms': 'Unofficial/Nintendo 3DS',
    },
    'Unofficial - Nintendo - Wii': {
        'lolroms': 'Unofficial/Nintendo Wii',
    },
    'Unofficial - Nintendo - Wii (Digital) (Split DLC)': {
        'lolroms': 'Unofficial/Nintendo Wii',
    },
    'Unofficial - Nintendo - Wii U': {
        'lolroms': 'Unofficial/Nintendo Wii U',
    },
    'Unofficial - Obscure Gamers': {
        'lolroms': 'Unofficial/Obscure Gamers',
    },
    'Unofficial - Sony - PlayStation 3': {
        'lolroms': 'Unofficial/Sony PlayStation 3',
    },
    'Unofficial - Sony - PlayStation 3 (BD-Video Extras)': {
        'lolroms': 'Unofficial/Sony PlayStation 3 BD-Video Extras',
    },
    'Unofficial - Sony - PlayStation 4': {
        'lolroms': 'Unofficial/Sony PlayStation 4',
    },
    'Unofficial - Sony - PlayStation Portable': {
        'lolroms': 'Unofficial/Sony PSP',
    },
    'Unofficial - Sony - PlayStation Vita': {
        'lolroms': 'Unofficial/Sony PlayStation Vita',
    },
    'Unofficial - Super Mario Maker Courses (WARC)': {
        'lolroms': 'Unofficial/Super Mario Maker Courses',
    },
    'Unofficial - Video Game Documents (PDF)': {
        'lolroms': 'Unofficial/Video Game Documents PDF',
    },
    'Unofficial - Video Game Magazine Scans (RAW)': {
        'lolroms': 'Unofficial/Video Game Magazine Scans',
    },
    'Unofficial - Video Game Manual Scans (JPEG)': {
        'lolroms': 'Unofficial/Video Game Manual Scans',
    },
    'Unofficial - Video Game OSTs (Digital) (RAW)': {
        'lolroms': 'Unofficial/Video Game OSTs Digital',
    },
    'Unofficial - Video Game OSTs (Hardware Recordings)': {
        'lolroms': 'Unofficial/Video Game OSTs Hardware',
    },
    'Unofficial - Video Game OSTs (Playbutton)': {
        'lolroms': 'Unofficial/Video Game OSTs Playbutton',
    },
    'Unofficial - Video Game Scans (RAW)': {
        'lolroms': 'Unofficial/Video Game Scans',
    },
    'VM Labs - NUON': {
        'lolroms': 'VM Labs/NUON',
    },
    'Welback - Mega Duck': {
        'lolroms': 'Welback - Mega Duck',
    },
    'Yamaha - Copera': {
        'lolroms': 'Yamaha - Copera',
    },
    'ZAPiT Games - Game Wave Family Entertainment System': {
        'lolroms': 'ZAPiT Games/Game Wave',
    },
    'Zeebo - Zeebo': {
        'lolroms': 'Zeebo',
    },
    # ── Arcade ──
    'Arcade - MAME': {
        'edgeemu': 'arcade-mame',
        'lolroms': 'Arcade/MAME',
        'planetemu': 'arcade',
        'romhustler': 'mame',
        'coolrom': 'arcade',
    },
}




def resolve_system_mapping(system_name: str, provider: str = 'lolroms') -> str | None:
    """Resout le mapping d'un systeme pour un provider donne.
    Essaie le mapping explicite SYSTEM_MAPPINGS, puis nettoie iterativement
    les suffixes parenthetiques (date, format, Retool, etc.) et reteste.
    Retourne le chemin/slug mappe ou None si introuvable.
    """
    if not system_name:
        return None

    # Mapping direct
    direct = SYSTEM_MAPPINGS.get(system_name, {}).get(provider)
    if direct:
        return direct

    # Aliases directs
    aliases = {
        'Nintendo - Nintendo 3DS': 'Nintendo - 3DS',
        'Nintendo - Nintendo DS': 'Nintendo - DS',
        'Nintendo - Nintendo 64': 'Nintendo - Nintendo 64',
        'Nintendo - Pokemon Mini': 'Nintendo - Pokémon Mini',
        'Nintendo - Nintendo Entertainment System (Headered)': 'Nintendo - Nintendo Entertainment System',
        'Nintendo - Nintendo Entertainment System': 'Nintendo - Nintendo Entertainment System',
        'Nintendo - Nintendo GameCube': 'Nintendo - GameCube',
        'Sony - PlayStation (PS one Classics)': 'Sony - PlayStation',
        'Sony - PlayStation Portable (PSN) (Minis)': 'Sony - PlayStation Portable',
        'Sega - SG-1000 - SC-3000': 'Sega - SG-1000',
        'Sega - Mega CD & Sega CD': 'Sega - Mega CD - Sega CD',
        'Atari - Atari 2600': 'Atari - 2600',
        'Atari - Atari 5200': 'Atari - 5200',
        'Atari - Atari 7800': 'Atari - 7800',
        'Atari - Atari Jaguar': 'Atari - Jaguar',
        'Atari - Atari Lynx': 'Atari - Lynx',
        'Atari - Atari ST': 'Atari - ST',
        'NEC - PC Engine CD & TurboGrafx CD': 'NEC - PC Engine CD & TurboGrafx CD',
        'Commodore - Commodore 64': 'Commodore - 64',
    }
    aliased = aliases.get(system_name)
    if aliased:
        direct = SYSTEM_MAPPINGS.get(aliased, {}).get(provider)
        if direct:
            return direct

    # Nettoyage iteratif des suffixes parenthetiques
    cleaned = system_name
    previous = None
    while cleaned != previous:
        previous = cleaned
        # Retirer le dernier segment entre parentheses a la fin
        m = re.search(r'^(.*?)\s*\([^)]+\)\s*$', cleaned)
        if m:
            cleaned = m.group(1).strip()
            mapped = SYSTEM_MAPPINGS.get(cleaned, {}).get(provider)
            if mapped:
                return mapped
            # Tester aussi l'alias sur le nettoye
            aliased_clean = aliases.get(cleaned)
            if aliased_clean:
                mapped = SYSTEM_MAPPINGS.get(aliased_clean, {}).get(provider)
                if mapped:
                    return mapped
    return None

def build_custom_source(source_url: str) -> dict:
    """Detecte et construit une source personnalisee Minerva ou legacy."""
    normalized_url = (source_url or '').strip()
    lower_url = normalized_url.lower()

    archive_specs = parse_archive_org_collection_specs([
        line.strip()
        for line in normalized_url.splitlines()
        if line.strip()
    ])
    if archive_specs and all(spec.get('identifier') for spec in archive_specs):
        return {
            'name': 'archive.org Custom',
            'base_url': ARCHIVE_ORG_DOWNLOAD_BASE,
            'type': 'archive_org_collection',
            'enabled': True,
            'description': 'Collections archive.org personnalisees',
            'identifiers': archive_specs,
            'order': 0,
            'priority': 0
        }

    if 'minerva-archive.org/browse/' in lower_url:
        if '/browse/no-intro' in lower_url:
            fixed_directory = '/browse/no-intro/' in lower_url and not lower_url.endswith('/browse/no-intro/')
            return {
                'name': 'Minerva Custom',
                'base_url': normalized_url if normalized_url.endswith('/') else normalized_url + '/',
                'type': 'minerva',
                'enabled': True,
                'description': 'Source personnalisee Minerva',
                'collection': 'No-Intro',
                'minerva_path_mode': 'single',
                'scan_depth': 0,
                'fixed_directory': fixed_directory,
                'torrent_scope': 'system',
                'priority': 0
            }
        if '/browse/redump' in lower_url:
            fixed_directory = '/browse/redump/' in lower_url and not lower_url.endswith('/browse/redump/')
            return {
                'name': 'Minerva Custom',
                'base_url': normalized_url if normalized_url.endswith('/') else normalized_url + '/',
                'type': 'minerva',
                'enabled': True,
                'description': 'Source personnalisee Minerva',
                'collection': 'Redump',
                'minerva_path_mode': 'single',
                'scan_depth': 0,
                'fixed_directory': fixed_directory,
                'torrent_scope': 'system',
                'priority': 0
            }
        if '/browse/tosec' in lower_url:
            fixed_directory = '/browse/tosec/' in lower_url and not lower_url.endswith('/browse/tosec/')
            return {
                'name': 'Minerva Custom',
                'base_url': normalized_url if normalized_url.endswith('/') else normalized_url + '/',
                'type': 'minerva',
                'enabled': True,
                'description': 'Source personnalisee Minerva',
                'collection': 'TOSEC',
                'minerva_path_mode': 'split',
                'scan_depth': 2,
                'fixed_directory': fixed_directory,
                'torrent_scope': 'vendor',
                'priority': 0
            }

    return {
        'name': 'Source Custom',
        'base_url': normalized_url,
        'type': 'minerva',
        'enabled': True,
        'priority': 0
    }

__all__ = [
    'get_default_sources_legacy',
    'SOURCE_TYPE_ORDER',
    'DDL_SOURCE_TYPES',
    'ONEFICHIER_SOURCE_TYPES',
    'ROMGOGETTER_ARCHIVE_ORG_COLLECTION_GROUPS',
    'source_order_key',
    'expand_collection_group',
    'parse_archive_org_collection_spec',
    'parse_archive_org_collection_specs',
    'archive_org_collection_identifiers',
    'normalize_source_label',
    'active_source_labels',
    'resolution_cache_key',
    'resolve_game_sources_with_cache',
    'source_is_excluded',
    'source_matches_label',
    'find_source_config',
    'optional_positive_int',
    'parse_candidate_limit',
    'source_timeout_seconds',
    'source_delay_seconds',
    'source_quota_limit',
    'source_policy_summary',
    'reserve_source_quota',
    'apply_source_policies',
    'get_default_sources',
    'SYSTEM_MAPPINGS',
    'resolve_system_mapping',
    'build_custom_source',
]
