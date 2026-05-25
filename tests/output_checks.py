import sys
from pathlib import Path
root = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, root)
print("root: " + root)

# Test direct import
from src.core.constants import ROM_EXTENSIONS
print("constants OK: " + str(len(ROM_EXTENSIONS)) + " extensions")

from src.core.dat_parser import parse_dat_file
print("dat_parser OK")

from src.core.fixdat import build_fixdat
print("fixdat module OK")

from src.core.frontend_mapping import frontend_folder_for_system, generate_es_gamelist_xml
print("gba -> " + frontend_folder_for_system("Nintendo - Game Boy Advance"))
print("psx -> " + frontend_folder_for_system("Sony - PlayStation"))
print("nes -> " + frontend_folder_for_system("Nintendo - Nintendo Entertainment System"))
print("wii -> " + frontend_folder_for_system("Nintendo - Wii"))
print("frontend module OK")

test_xml = build_fixdat("test.dat", {"Test Game (USA)": {"game_name": "Test Game (USA)", "roms": [{"name": "test.rom", "size": "1024", "crc": "abc123", "md5": "d41d8cd98f00b204e9800998ecf8427e"}]}})
if "<game name=\"Test Game (USA)\"" in test_xml:
    print("fixdat XML generation OK")
else:
    print("fixdat FAILED")
    sys.exit(1)

games = [{"game_name": "Test Game", "download_filename": "test.rom", "primary_rom": "test.rom"}]
gamelist = generate_es_gamelist_xml(games, "gba")
if "test.rom" in gamelist:
    print("gamelist generation OK")
else:
    print("gamelist FAILED")
    sys.exit(1)

print("\nALL CHECKS PASSED")
