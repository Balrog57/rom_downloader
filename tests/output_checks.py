import sys
from pathlib import Path
import tempfile
root = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, root)
print("root: " + root)

# Test direct import
from src.core.constants import ROM_EXTENSIONS
print("constants OK: " + str(len(ROM_EXTENSIONS)) + " extensions")

from src.core.dat_parser import parse_dat_file
print("dat_parser OK")

from src.core.dat_capabilities import analyze_dat_capabilities
from src.core.output_manager import organize_downloaded_items, rebuild_tosort
from src.core.signatures import hash_file_signatures

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

with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    dat_path = tmp_path / "mini.dat"
    raw_rom = tmp_path / "game.bin"
    raw_rom.write_bytes(b"abcd")
    sig = hash_file_signatures(raw_rom)
    dat_path.write_text(f"""<?xml version="1.0"?>
<datafile>
  <header><name>Mini Arcade</name><type>headered</type></header>
  <game name="Parent"><rom name="parent.bin" size="4" crc="{sig['crc']}" md5="{sig['md5']}" sha1="{sig['sha1']}"/></game>
  <game name="Clone" cloneof="Parent" romof="Parent"><disk name="clone-disk" sha1="{sig['sha1']}"/></game>
</datafile>
""", encoding="utf-8")
    parsed = parse_dat_file(str(dat_path))
    if "Clone" not in parsed or not parsed["Clone"]["roms"][0]["name"].endswith(".chd"):
        print("DAT disk/CHD parsing FAILED")
        sys.exit(1)
    caps = analyze_dat_capabilities(str(dat_path))
    if caps["chd_disks"] != 1 or caps["clone_games"] != 1 or not caps["headered"]:
        print("DAT capabilities FAILED")
        sys.exit(1)
    print("dat capabilities OK")

    out_dir = tmp_path / "out"
    item = {"game_name": "Parent", "download_filename": "game.bin", "primary_rom": "parent.bin", "downloaded_path": str(raw_rom)}
    org = organize_downloaded_items([item], str(out_dir), output_mode="verified", archive_mode="zip")
    if org["zipped"] != 1 or not (out_dir / "Verified" / "game.zip").exists():
        print("output organization FAILED")
        sys.exit(1)
    print("output organization OK")

    tosort = out_dir / "ToSort"
    tosort.mkdir(parents=True, exist_ok=True)
    candidate = tosort / "loose.bin"
    candidate.write_bytes(b"abcd")
    rebuilt = rebuild_tosort(parsed, str(tosort), str(out_dir), output_mode="verified")
    if rebuilt["rebuilt"] != 1 or not (out_dir / "Verified" / "parent.bin").exists():
        print("rebuild ToSort FAILED")
        sys.exit(1)
    print("rebuild ToSort OK")

print("\nALL CHECKS PASSED")
