"""Trace the NoneType error in search/download pipeline."""
import sys
import os
import traceback

sys.path.insert(0, '.')

from src.core import (
    parse_dat_file, scan_local_roms, find_missing_games,
    detect_dat_profile, finalize_dat_profile,
    get_default_sources, prepare_sources_for_profile,
    resolve_game_sources_with_cache, source_order_key,
)
from src.core.search_pipeline import search_all_sources
from src.network.sessions import create_optimized_session
from src.network.cache_runtime import clear_session_cache

DAT_FILE = r'dat\no-intro\Nintendo - Game Boy Advance (20260331-153403).dat'

dat_games = parse_dat_file(DAT_FILE)
print(f'Games in DAT: {len(dat_games)}')

rom_folder = r'C:\Users\Marc\Downloads\Nintendo - Game Boy Advance (20260331-153403)'
if not os.path.isdir(rom_folder):
    rom_folder = 'roms'

local_roms, local_norm, local_names, sig = scan_local_roms(rom_folder, dat_games)
missing = find_missing_games(dat_games, local_roms, local_norm, local_names, sig)
print(f'Missing: {len(missing)}')

profile = finalize_dat_profile(detect_dat_profile(DAT_FILE))
sources = get_default_sources()
sources = prepare_sources_for_profile(sources, profile)

clear_session_cache()
session = create_optimized_session()

# Test with 3 games
test_games = missing[:3]
for g in test_games:
    print(f'  {g.get("game_name", "?")}')

try:
    found, not_found = search_all_sources(test_games, sources, session, profile.get('system_name'), profile)
    print(f'\nFound: {len(found)}, Not found: {len(not_found)}')
    for f in found:
        src = f.get('source', '?')
        url = f.get('download_url', f.get('torrent_url', f.get('page_url', '')))[:80]
        print(f'  {f.get("game_name", "?")} -> {src}: {url}')
        print(f'  Keys: {sorted(f.keys())}')
except Exception as e:
    traceback.print_exc()

# Also test resolve_game_sources_with_cache
print('\n--- Testing resolve_game_sources_with_cache ---')
for game in test_games[:1]:
    try:
        result = resolve_game_sources_with_cache(game, sources, session, profile.get('system_name'), profile)
        found_list, unavail, cache_hit = result
        if found_list:
            f = found_list[0]
            print(f'  Source: {f.get("source", "?")}')
            print(f'  Keys: {sorted(f.keys())}')
            # Check each key for None
            for k, v in f.items():
                if v is None:
                    print(f'  WARNING: key "{k}" is None')
        else:
            print(f'  No source found for {game.get("game_name", "?")}')
    except Exception as e:
        traceback.print_exc()