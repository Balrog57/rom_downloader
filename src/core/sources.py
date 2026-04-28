import hashlib
import json
import re
import time

from .constants import (
    CDROMANCE_BASE,
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
            'description': 'Source principale',
            'priority': 1
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
    'retrogamesets': 20,
    'startgame': 22,
    'planetemu': 30,
    'lolroms': 40,
    'vimm': 50,
    'cdromance': 55,
    'romhustler': 60,
    'coolrom': 65,
    'romsxisos': 70,
    'nopaystation': 80,
    'hshop': 85,
    'edgeemu': 200,
    'minerva': 90,
    'archive_org': 110,
}


def source_order_key(source: dict) -> tuple:
    """Trie les sources avec archive.org en tout dernier recours."""
    return (
        SOURCE_TYPE_ORDER.get(source.get('type'), 60),
        source.get('priority', 50),
        source.get('name', '').lower()
    )


def normalize_source_label(value: str) -> str:
    """Normalise un nom de provider pour les retries."""
    return re.sub(r'\s+', ' ', (value or '').strip().lower())


def active_source_labels(sources: list) -> list[str]:
    """Retourne les labels stables des sources actives."""
    labels = []
    for source in sources or []:
        if source.get('enabled', True):
            labels.append(normalize_source_label(source.get('name') or source.get('type', '')))
    return sorted(label for label in labels if label)


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

    found, unavailable = search_all_sources(
        [clean_download_resolution(game_info)],
        sources,
        session,
        system_name,
        dat_profile,
        excluded_sources=excluded_sources
    )
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


def source_quota_limit(source: dict | None) -> int | None:
    """Quota de tentatives par run pour une source, None = illimite."""
    return optional_positive_int((source or {}).get('quota_per_run'), minimum=1, maximum=100000)


def source_policy_summary(source: dict) -> str:
    """Resume compact d'une politique source pour les logs et diagnostics."""
    parts = []
    if source.get('timeout_seconds'):
        parts.append(f"timeout {source_timeout_seconds(source)}s")
    quota = source_quota_limit(source)
    if quota is not None:
        parts.append(f"quota {quota}/run")
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
            'description': 'Source principale',
            'priority': 1
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
            'priority': 90
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
            'priority': 90
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
            'priority': 90
        },
        {
            'name': 'EdgeEmu',
            'base_url': config.get('edgeemu_browse', ''),
            'type': 'edgeemu',
            'enabled': False,
            'description': 'DESACTIVE - Retourne des fichiers vides (0 bytes)',
            'priority': 3
        },
        {
            'name': 'PlanetEmu',
            'base_url': config.get('planetemu_roms', ''),
            'type': 'planetemu',
            'enabled': True,
            'description': 'Lien direct (POST) - Source FR majeure',
            'priority': 3
        },
        {
            'name': 'LoLROMs',
            'base_url': LOLROMS_BASE,
            'type': 'lolroms',
            'enabled': True,
            'description': 'Fallback direct via Cloudflare-compatible listing',
            'priority': 3
        },
        {
            'name': 'CDRomance',
            'base_url': CDROMANCE_BASE,
            'type': 'cdromance',
            'enabled': False,
            'description': 'Site archive depuis janv 2026 (plus de telechargements)',
            'priority': 3
        },
        {
            'name': 'Vimm\'s Lair',
            'base_url': VIMM_BASE,
            'type': 'vimm',
            'enabled': True,
            'description': 'The Vault - Source de reference historique',
            'priority': 3
        },
        {
            'name': 'RetroGameSets',
            'base_url': RETRO_GAME_SETS_BASE,
            'type': 'retrogamesets',
            'enabled': True,
            'description': 'JSON DB - 1fichier (AllDebrid recommande)',
            'priority': 2
        },
        {
            'name': 'RomHustler',
            'base_url': ROMHUSTLER_BASE,
            'type': 'romhustler',
            'enabled': True,
            'description': 'DDL guest - 500KB/s, jeux populaires bloques',
            'priority': 3
        },
        {
            'name': 'CoolROM',
            'base_url': COOLROM_BASE,
            'type': 'coolrom',
            'enabled': True,
            'description': 'DDL token - Nintendo supprime, autres OK',
            'priority': 3
        },
        {
            'name': 'NoPayStation',
            'base_url': NOPAYSTATION_BASE,
            'type': 'nopaystation',
            'enabled': True,
            'description': 'Index TSV - PS1/PS2/PS3/PSP/Vita (.pkg expirants)',
            'priority': 2
        },
        {
            'name': 'StartGame',
            'base_url': STARTGAME_BASE,
            'type': 'startgame',
            'enabled': True,
            'description': 'Sets No-Intro/Redump via 1fichier (AllDebrid recommande)',
            'priority': 2
        },
        {
            'name': 'hShop',
            'base_url': HSHOP_BASE,
            'type': 'hshop',
            'enabled': True,
            'description': '3DS uniquement - .cia cryptes, partiel',
            'priority': 3
        },
        {
            'name': 'RomsXISOs',
            'base_url': ROMSXISOS_BASE,
            'type': 'romsxisos',
            'enabled': True,
            'description': 'GitHub Pages - Google Drive (ES, multi-consoles)',
            'priority': 3
        },
    ]
    return sorted(sources, key=source_order_key)


SYSTEM_MAPPINGS = {
    'Nintendo - Game Boy': {
        'edgeemu': 'nintendo-gameboy',
        'planetemu': 'nintendo-game-boy',
        'lolroms': 'Nintendo - Game Boy',
        'vimm': 'GB',
        'retrogamesets': 'Game Boy (Archive)',
        'romhustler': 'gbc',
        'coolrom': 'gb',
        'romsxisos': 'gameboy',
    },
    'Nintendo - Game Boy Color': {
        'edgeemu': 'nintendo-gameboycolor',
        'planetemu': 'nintendo-game-boy-color',
        'lolroms': 'Nintendo - Game Boy Color',
        'vimm': 'GBC',
        'retrogamesets': 'Game Boy Color (Archive)',
        'romhustler': 'gbc',
        'coolrom': 'gbc',
        'romsxisos': 'gameboycolor',
    },
    'Nintendo - Game Boy Advance': {
        'edgeemu': 'nintendo-gba',
        'planetemu': 'nintendo-game-boy-advance',
        'lolroms': 'Nintendo - Game Boy Advance',
        'vimm': 'GBA',
        'retrogamesets': 'Game Boy Advance (Archive)',
        'romhustler': 'gba',
        'coolrom': 'gba',
        'romsxisos': 'gba',
    },
    'Nintendo - Game Boy Advance (Multiboot)': {
        'lolroms': 'Nintendo - Game Boy Advance/Multi-Boot',
    },
    'Nintendo - Game Boy Advance (eReader)': {
        'lolroms': 'Nintendo - Game Boy Advance/eReader',
    },
    'Nintendo - Nintendo Entertainment System': {
        'edgeemu': 'nintendo-nes',
        'planetemu': 'nintendo-entertainment-system',
        'lolroms': 'Nintendo - Famicom/Headerless',
        'vimm': 'NES',
        'retrogamesets': 'NES (Archive)',
        'romhustler': 'nes',
        'coolrom': 'nes',
        'romsxisos': 'nes',
    },
    'Nintendo - Nintendo Entertainment System (Headered)': {
        'edgeemu': 'nintendo-nes',
        'planetemu': 'nintendo-entertainment-system',
        'lolroms': 'Nintendo - Famicom/Headered',
        'vimm': 'NES',
        'romhustler': 'nes',
        'coolrom': 'nes',
    },
    'Nintendo - Super Nintendo Entertainment System': {
        'edgeemu': 'nintendo-snes',
        'planetemu': 'nintendo-super-nintendo-entertainment-system',
        'lolroms': 'Nintendo - Super Famicom',
        'vimm': 'SNES',
        'retrogamesets': 'SNES (Archive)',
        'romhustler': 'snes',
        'coolrom': 'snes',
        'romsxisos': 'snes',
    },
    'Nintendo - Nintendo 64': {
        'edgeemu': 'nintendo-n64',
        'planetemu': 'nintendo-64',
        'lolroms': 'Nintendo - 64',
        'vimm': 'N64',
        'retrogamesets': 'Nintendo 64 (Archive)',
        'romhustler': 'n64',
        'coolrom': 'n64',
        'romsxisos': 'n64',
    },
    'Nintendo - DS': {
        'lolroms': 'Nintendo - DS',
        'vimm': 'DS',
        'retrogamesets': 'Nintendo DS (LolRoms)',
        'romhustler': 'nds',
        'coolrom': 'nds',
        'romsxisos': 'nds',
    },
    'Nintendo - 3DS': {
        'lolroms': 'Nintendo - 3DS',
        'vimm': '3DS',
        'retrogamesets': '3DS (Archive)',
        'romhustler': '3ds',
        'hshop': 'games',
        'romsxisos': '3ds',
    },
    'Nintendo - GameCube': {
        'lolroms': 'Nintendo - GameCube',
        'vimm': 'GameCube',
        'retrogamesets': 'Game Cube (Archive)',
        'romhustler': 'gamecube',
        'coolrom': 'gamecube',
        'romsxisos': 'gamecube',
    },
    'Nintendo - Wii': {
        'lolroms': 'Nintendo - Wii',
        'vimm': 'Wii',
        'retrogamesets': 'Wii (Archive)',
        'romhustler': 'wii',
        'coolrom': 'wii',
        'romsxisos': 'wii',
    },
    'Nintendo - Wii U': {
        'lolroms': 'Nintendo - Wii U',
        'vimm': 'WiiU',
        'retrogamesets': 'Wii U (EU) (1Fichier)',
        'romhustler': 'wii-u',
    },
    'Nintendo - Virtual Boy': {
        'lolroms': 'Nintendo - Virtual Boy',
        'vimm': 'VirtualBoy',
        'retrogamesets': 'Virtual Boy (Archive)',
        'romhustler': 'virtual-boy',
        'romsxisos': 'virtualboy',
    },
    'Nintendo - Pokémon Mini': {
        'lolroms': 'Nintendo - Pokémon Mini',
        'retrogamesets': 'Pokemon Mini (Archive)',
        'romsxisos': 'pokemonmini',
    },
    'Nintendo - Nintendo Entertainment System (Headered)': {
        'edgeemu': 'nintendo-nes',
        'planetemu': 'nintendo-entertainment-system',
        'lolroms': 'Nintendo - Famicom/Headered',
        'vimm': 'NES',
        'romhustler': 'nintendo-nes',
        'coolrom': 'nes',
    },
    'Nintendo - Super Nintendo Entertainment System': {
        'edgeemu': 'nintendo-snes',
        'planetemu': 'nintendo-super-nintendo-entertainment-system',
        'lolroms': 'Nintendo - Super Famicom',
        'vimm': 'SNES',
        'retrogamesets': 'SNES (Archive)',
        'romhustler': 'nintendo-snes',
        'coolrom': 'snes',
        'romsxisos': 'nintendo-super-nintendo-entertainment-system',
    },
    'Nintendo - Nintendo 64': {
        'edgeemu': 'nintendo-n64',
        'planetemu': 'nintendo-64',
        'lolroms': 'Nintendo - 64',
        'vimm': 'N64',
        'retrogamesets': 'Nintendo 64 (Archive)',
        'romhustler': 'nintendo-n64',
        'coolrom': 'n64',
        'romsxisos': 'nintendo-nintendo-64',
    },
    'Nintendo - DS': {
        'lolroms': 'Nintendo - DS',
        'vimm': 'DS',
        'retrogamesets': 'Nintendo DS (LolRoms)',
        'romhustler': 'nintendo-nds',
        'coolrom': 'nds',
        'romsxisos': 'nintendo-ds',
    },
    'Nintendo - 3DS': {
        'lolroms': 'Nintendo - 3DS',
        'vimm': '3DS',
        'retrogamesets': '3DS (Archive)',
        'romhustler': 'nintendo-3ds',
        'hshop': 'games',
        'romsxisos': 'nintendo-3ds',
    },
    'Nintendo - GameCube': {
        'lolroms': 'Nintendo - GameCube',
        'vimm': 'GameCube',
        'retrogamesets': 'Game Cube (Archive)',
        'romhustler': 'nintendo-gamecube',
        'coolrom': 'gamecube',
        'romsxisos': 'nintendo-gamecube',
    },
    'Nintendo - Wii': {
        'lolroms': 'Nintendo - Wii',
        'vimm': 'Wii',
        'retrogamesets': 'Wii (Archive)',
        'romhustler': 'nintendo-wii',
        'coolrom': 'wii',
        'romsxisos': 'nintendo-wii',
    },
    'Nintendo - Wii U': {
        'lolroms': 'Nintendo - Wii U',
        'vimm': 'WiiU',
        'retrogamesets': 'Wii U (EU) (1Fichier)',
        'romhustler': 'nintendo-wii-u',
    },
    'Nintendo - Virtual Boy': {
        'lolroms': 'Nintendo - Virtual Boy',
        'vimm': 'VirtualBoy',
        'retrogamesets': 'Virtual Boy (Archive)',
        'romhustler': 'nintendo-virtual-boy',
    },
    'Nintendo - Pok\u00e9mon Mini': {
        'lolroms': 'Nintendo - Pok\u00e9mon Mini',
        'retrogamesets': 'Pokemon Mini (Archive)',
    },
    'Sega - Mega Drive - Genesis': {
        'edgeemu': 'sega-genesis',
        'planetemu': 'sega-mega-drive',
        'lolroms': 'SEGA/Mega Drive',
        'vimm': 'Genesis',
        'retrogamesets': 'Mega Drive (Archive)',
        'romhustler': 'genesis',
        'coolrom': 'genesis',
        'romsxisos': 'segagenesis',
        'startgame': 'sega-mega-drive-genesis',
    },
    'Sega - Master System - Mark III': {
        'edgeemu': 'sega-mastersystem',
        'planetemu': 'sega-master-system',
        'lolroms': 'SEGA/Master System',
        'vimm': 'SMS',
        'retrogamesets': 'Master System (Archive)',
        'romhustler': 'sms',
        'coolrom': 'sms',
        'romsxisos': 'master_system',
        'startgame': 'sega-master-system-mark-iii',
    },
    'Sega - Game Gear': {
        'edgeemu': 'sega-gamegear',
        'planetemu': 'sega-game-gear',
        'lolroms': 'SEGA/Game Gear',
        'vimm': 'GameGear',
        'retrogamesets': 'Game Gear (Archive)',
        'romhustler': 'game-gear',
        'coolrom': 'gamegear',
        'romsxisos': 'gamegear',
        'startgame': 'sega-game-gear',
    },
    'NEC - PC Engine - TurboGrafx 16': {
        'edgeemu': 'nec-pcengine',
        'planetemu': 'nec-pc-engine-turbografx-16-entertainment-super-system',
        'vimm': 'Engine',
        'retrogamesets': 'PC Engine (Archive)',
        'romhustler': 'pcengine',
        'coolrom': 'tg16',
        'startgame': 'nec-pc-engine-turbografx-16',
    },
    'SNK - Neo Geo Pocket Color': {
        'edgeemu': 'snk-neogeopocketcolor',
        'planetemu': 'snk-neo-geo-pocket-color',
        'lolroms': 'SNK/NeoGeo Pocket Color',
        'retrogamesets': 'Neo-Geo Pocket Color (Archive)',
        'romhustler': 'neogeo-pocket',
        'romsxisos': 'pocket_color',
    },
    'Sony - PlayStation': {
        'lolroms': 'SONY/PlayStation',
        'vimm': 'PS1',
        'retrogamesets': 'PlayStation (Archive)',
        'romhustler': 'psx',
        'coolrom': 'psx',
        'romsxisos': 'ps1',
        'startgame': 'sony-playstation',
        'nopaystation': 'PSX_GAMES',
    },
    'Sony - PlayStation Portable': {
        'lolroms': 'SONY/PlayStation Portable',
        'vimm': 'PSP',
        'retrogamesets': 'PlayStation Portable (Archive)',
        'romhustler': 'playstation-portable',
        'coolrom': 'psp',
        'romsxisos': 'psp',
        'startgame': 'sony-playstation-portable',
        'nopaystation': 'PSP_GAMES',
    },
    'Sony - PlayStation 2': {
        'romhustler': 'playstation2',
        'coolrom': 'ps2',
        'startgame': 'sony-playstation-2',
    },
    'Sony - PlayStation 3': {
        'romhustler': 'ps3',
        'startgame': 'sony-playstation-3',
        'nopaystation': 'PS3_GAMES',
    },
    'Sony - PlayStation Vita': {
        'romhustler': 'ps-vita',
        'romsxisos': 'psvita',
        'nopaystation': 'PSV_GAMES',
    },
    'Sega - Saturn': {
        'romhustler': 'saturn',
        'coolrom': 'saturn',
        'romsxisos': 'saturn',
    },
    'Sega - Dreamcast': {
        'romhustler': 'dreamcast',
        'coolrom': 'dc',
        'romsxisos': 'dreamcast',
    },
    'Sega - Mega CD - Sega CD': {
        'romhustler': 'segacd',
        'coolrom': 'segacd',
        'startgame': 'sega-mega-cd-sega-cd',
    },
    'Sega - 32X': {
        'romhustler': 'sega-32x',
        'coolrom': '32x',
        'startgame': 'sega-32x',
    },
    'Sega - Saturn': {
        'romhustler': 'saturn',
        'coolrom': 'saturn',
        'romsxisos': 'saturn',
        'startgame': 'sega-saturn',
    },
    'Sega - Dreamcast': {
        'romhustler': 'dreamcast',
        'coolrom': 'dc',
        'romsxisos': 'dreamcast',
        'startgame': 'sega-dreamcast',
    },
    'Atari - 2600': {
        'romhustler': 'atari-2600',
        'startgame': 'atari-2600',
    },
    'Atari - 7800': {
        'romhustler': 'atari-7800',
        'startgame': 'atari-7800',
    },
    'Atari - Jaguar': {
        'romhustler': 'atari-jaguar',
        'startgame': 'atari-jaguar',
    },
    'Sega - 32X': {
        'romhustler': 'sega-32x',
        'coolrom': '32x',
    },
    'Atari - 2600': {
        'romhustler': 'atari-2600',
    },
    'Atari - 7800': {
        'romhustler': 'atari-7800',
    },
    'Atari - Jaguar': {
        'romhustler': 'atari-jaguar',
    },
    'Arcade - MAME': {
        'romhustler': 'mame',
        'coolrom': 'arcade',
    },
    'Bandai - WonderSwan': {
        'romhustler': 'wonderswan',
        'romsxisos': 'wonderswan',
        'startgame': 'bandai-wonderswan',
    },
    'NEC - PC-FX': {
        'romhustler': 'pc-fx',
        'startgame': 'nec-pc-fx',
    },
    'SNK - Neo Geo Pocket Color': {
        'edgeemu': 'snk-neogeopocketcolor',
        'planetemu': 'snk-neo-geo-pocket-color',
        'lolroms': 'SNK/NeoGeo Pocket Color',
        'retrogamesets': 'Neo-Geo Pocket Color (Archive)',
        'romhustler': 'neogeo-pocket',
        'romsxisos': 'pocket_color',
        'startgame': 'snk-neo-geo-pocket-color',
    },
    'NEC - PC-FX': {
        'romhustler': 'pc-fx',
    },
}


def build_custom_source(source_url: str) -> dict:
    """Detecte et construit une source personnalisee Minerva ou legacy."""
    normalized_url = (source_url or '').strip()
    lower_url = normalized_url.lower()

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
    'source_order_key',
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
    'source_quota_limit',
    'source_policy_summary',
    'reserve_source_quota',
    'get_default_sources',
    'SYSTEM_MAPPINGS',
    'build_custom_source',
]