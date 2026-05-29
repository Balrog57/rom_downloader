"""Tests unitaires des fonctions pures des providers (scraping, normalisation, parsing).
Aucun acces reseau n'est requis.
"""
import sys
from pathlib import Path
root = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, root)

from bs4 import BeautifulSoup
from src.core.scrapers import (
    _normalize_lolroms_file_url,
    _normalize_system_name_for_lolroms,
    _lolroms_alt_paths,
    _lolroms_subdir_for_system,
    _parse_lolroms_items,
    _redump_name_variants,
    normalize_external_game_name,
    build_listing_index,
    find_listing_match,
    iter_game_candidate_names,
    _archive_collection_spec_cache_key,
    _archive_org_shard_key,
    _candidate_initials_for_archive_group,
    select_archive_org_collection_specs_for_game,
    _gdrive_viewer_to_direct,
    _parse_romsxisos_js,
    match_source_files,
    build_lolroms_url,
)
from src.core.sources import (
    parse_archive_org_collection_spec,
    parse_archive_org_collection_specs,
    archive_org_collection_identifiers,
    provider_exclusion_labels,
    resolution_cache_key,
    resolve_system_mapping,
    source_matches_label,
    find_source_config,
    optional_positive_int,
    parse_candidate_limit,
    source_timeout_seconds,
    source_delay_seconds,
    source_quota_limit,
    apply_source_policies,
    source_policy_summary,
    reserve_source_quota,
    build_custom_source,
)
from src.network.exceptions import DownloadNetworkError
from src.core.error_codes import classify_error, error_is_poison
from src.core.sources import SYSTEM_MAPPINGS

print("Modules providers sources charges OK")

errors = []


def check(condition, label):
    if not condition:
        errors.append(f"ECHEC: {label}")
        print(f"  FAIL: {label}")
    else:
        print(f"  OK: {label}")


# --- DownloadNetworkError + raw_html --------------------------------

print("\n--- DownloadNetworkError raw_html ---")

exc = DownloadNetworkError("test message")
check(exc.raw_html == "", "raw_html vide par defaut")

exc_html = DownloadNetworkError("Blocage Cloudflare", raw_html="<html><body>cf</body></html>")
check(exc_html.raw_html == "<html><body>cf</body></html>", "raw_html preserve")
check(hasattr(exc_html, 'raw_html'), "attribut raw_html existe")

exc_empty = DownloadNetworkError("", raw_html="")
check(exc_empty.raw_html == "", "raw_html chaine vide")

# --- _normalize_lolroms_file_url ------------------------------------

print("\n--- _normalize_lolroms_file_url ---")

check(
    "https://lolroms.fr/ROMs/Nintendo%20-%20Game%20Boy%20Advance/file.7z"
    in _normalize_lolroms_file_url("https://lolroms.fr/ROMs/Nintendo - Game Boy Advance/file.7z"),
    "encodage espaces simples"
)
check(
    _normalize_lolroms_file_url("https://lolroms.fr/path/already%20encoded.7z")
    == "https://lolroms.fr/path/already%20encoded.7z",
    "ne double-encode pas"
)
check(
    _normalize_lolroms_file_url("https://lolroms.fr/path/file.7z")
    == "https://lolroms.fr/path/file.7z",
    "url sans espaces inchangee"
)

# --- _normalize_system_name_for_lolroms -----------------------------

print("\n--- _normalize_system_name_for_lolroms ---")

check(
    _normalize_system_name_for_lolroms("Nintendo - Game Boy Advance") == "Nintendo - Game Boy Advance",
    "GBA inchange"
)
check(
    _normalize_system_name_for_lolroms("SNK - Neo Geo AES") == "SNK - Neo Geo AES",
    "Neo Geo normalise"
)
check(
    _normalize_system_name_for_lolroms("NEC - PC Engine - TurboGrafx 16")
    == "NEC - PC Engine - TurboGrafx 16",
    "TurboGrafx-16 normalise"
)
check(
    "pokemon" in _normalize_system_name_for_lolroms("Pok\u00e9mon Mini").lower(),
    "Pokemon sans accent"
)
check(
    _normalize_system_name_for_lolroms("") == "",
    "chaine vide"
)

# --- _lolroms_alt_paths ---------------------------------------------

print("\n--- _lolroms_alt_paths ---")

check(
    _lolroms_alt_paths("Nintendo - Game Boy Advance") == [
        "Game Boy Advance",
        "Nintendo/Game Boy Advance",
    ],
    "chemin Nintendo"
)
check(
    _lolroms_alt_paths("SEGA/Mega Drive") == [],
    "chemin SEGA deja avec slash"
)
check(
    len(_lolroms_alt_paths("Sony - PlayStation")) == 1
    and "SONY" in _lolroms_alt_paths("Sony - PlayStation")[0],
    "chemin Sony"
)
check(
    len(_lolroms_alt_paths("Atari - 2600")) == 1
    and "Atari" in _lolroms_alt_paths("Atari - 2600")[0],
    "chemin Atari"
)
check(
    len(_lolroms_alt_paths("NEC - PC Engine")) == 1
    and "NEC" in _lolroms_alt_paths("NEC - PC Engine")[0],
    "chemin NEC"
)
check(
    _lolroms_alt_paths("") == [],
    "chaine vide"
)

# --- _lolroms_subdir_for_system -------------------------------------

print("\n--- _lolroms_subdir_for_system ---")

check(
    _lolroms_subdir_for_system("Nintendo - Game Boy Advance (MultiBoot)")
    == "Multi-Boot",
    "GBA MultiBoot"
)
check(
    _lolroms_subdir_for_system("Nintendo - Game Boy Advance (eReader)")
    == "eReader",
    "GBA eReader"
)
check(
    _lolroms_subdir_for_system("Nintendo - Game Boy Advance (Video)")
    == "Video",
    "GBA Video"
)
check(
    _lolroms_subdir_for_system("Nintendo - Game Boy Advance") is None,
    "GBA standard sans sous-repertoire"
)
check(
    _lolroms_subdir_for_system("Nintendo - Super Nintendo") is None,
    "systeme sans sous-repertoire"
)

# --- _parse_lolroms_items -------------------------------------------

print("\n--- _parse_lolroms_items ---")

modern_html = """<html><body>
<ul>
<li class="folder-item"><a href="SubDir/">SubDir</a></li>
<li class="file-item"><a href="Game%20Name.zip">Game Name</a></li>
<li class="file-item"><a href="Another.7z">Another</a></li>
<li class="file-item"><a href="RSS/feed">RSS</a></li>
</ul>
</body></html>"""
soup = BeautifulSoup(modern_html, 'html.parser')
files, subdirs = _parse_lolroms_items(soup, "https://lolroms.fr/Nintendo - Game Boy Advance/")
check(len(subdirs) == 1 and subdirs[0] == "SubDir", "format moderne: 1 sous-repertoire")
check(len(files) == 2, "format moderne: 2 fichiers")
check("game name" in {k.lower(): v['filename'] for k, v in files.items()},
      "format moderne: Game Name.zip trouve")
check("another" in {k.lower(): v['filename'] for k, v in files.items()},
      "format moderne: Another.7z trouve")

legacy_html = """<html><body>
<a href="folder/">Folder</a>
<a href="Game%20Name.7z">Game Name</a>
<a href="Another.gba">Another</a>
<a href="RSS/feed">RSS</a>
</body></html>"""
soup2 = BeautifulSoup(legacy_html, 'html.parser')
files2, subdirs2 = _parse_lolroms_items(soup2, "https://lolroms.fr/Nintendo - GBA/")
check(len(subdirs2) == 1 and subdirs2[0] == "Folder", "format legacy: 1 sous-repertoire")
check(len(files2) == 2, "format legacy: 2 fichiers")

empty_soup = BeautifulSoup("<html><body></body></html>", 'html.parser')
files3, subdirs3 = _parse_lolroms_items(empty_soup, "https://lolroms.fr")
check(len(files3) == 0 and len(subdirs3) == 0, "page vide: aucun fichier/rep")

# --- _redump_name_variants ------------------------------------------

print("\n--- _redump_name_variants ---")

check(len(_redump_name_variants("")) == 0, "chaine vide")
check(len(_redump_name_variants("Game (Track 01) (CUE).bin")) > 0, "Track 01 avec parenthese")
check(len(_redump_name_variants("Game - Track 01 (CUE).bin")) > 0, "Track 01 avec tiret")
check(
    _redump_name_variants("Game (nkit).iso"),
    "nkit format retire"
)

# --- normalize_external_game_name -----------------------------------

print("\n--- normalize_external_game_name ---")

check(
    normalize_external_game_name("Super Game (USA) (Track 01).bin") == "super game usa",
    "normalisation standard"
)
check(
    normalize_external_game_name("The Legend of Zelda") == "the legend of zelda",
    "article preserve"
)
check(
    normalize_external_game_name("Game (Demo) (Proto).gba") == "game",
    "demo proto retire"
)
check(
    normalize_external_game_name("Game v1.1 (Rev 2).gba") == "game rev 1 1 rev 2",
    "revision preserve"
)
check(
    normalize_external_game_name("Game (Disc 2).bin") == "game disc 2",
    "disc preserve"
)
check(
    normalize_external_game_name("") == "",
    "chaine vide"
)
check(
    normalize_external_game_name("Sonic & Knuckles.gba") == "sonic and knuckles",
    "esperluette -> and"
)

# --- build_listing_index --------------------------------------------

print("\n--- build_listing_index ---")

listing = {
    "Game Name (USA).zip": {
        "full_name": "Game Name (USA)",
        "filename": "Game Name (USA).zip",
        "url": "https://example.com/Game%20Name.zip",
    },
    "Another.cue": {
        "full_name": "Another",
        "filename": "Another.cue",
        "url": "https://example.com/Another.cue",
    },
}
idx = build_listing_index(listing)
check(len(idx["raw_index"]) == 2, "raw_index: 2 entrees")
check(len(idx["normalized_index"]) > 0, "normalized_index: non vide")
check("game name usa" in idx["normalized_index"], "normalized_index: Game Name USA")
check("another" in idx["normalized_index"], "normalized_index: Another")

# --- find_listing_match ---------------------------------------------

print("\n--- find_listing_match ---")

game1 = {"game_name": "Game Name (USA)", "primary_rom": "Game Name (USA).zip", "roms": []}
name1, entry1 = find_listing_match(game1, listing)
check(name1 is not None and entry1 is not None, "match exact Game Name (USA)")

game2 = {"game_name": "Another", "primary_rom": "Another.cue", "roms": []}
name2, entry2 = find_listing_match(game2, listing)
check(name2 is not None and entry2 is not None, "match exact Another")

game3 = {"game_name": "Does Not Exist", "primary_rom": "Does Not Exist.bin", "roms": [{"name": "Does Not Exist.bin"}]}
name3, entry3 = find_listing_match(game3, listing)
check(name3 is None and entry3 is None, "aucun match pour jeu inconnu")

check(find_listing_match(game1, {}) == (None, None), "listing vide => None")

# --- iter_game_candidate_names --------------------------------------

print("\n--- iter_game_candidate_names ---")

game_cand = {
    "primary_rom": "Primary Game (USA).gba",
    "game_name": "Primary Game (USA) Extended",
    "roms": [
        {"name": "Primary Game (USA) (Track 1).bin"},
        {"name": "Secondary.bin"},
    ],
}
cands = iter_game_candidate_names(game_cand)
check(len(cands) >= 3, "au moins 3 candidats")
check("Primary Game (USA)" in cands, "primary_rom present")
check("Primary Game (USA) Extended" in cands, "game_name present")
check("Secondary" in cands, "rom name present")

# --- archive.org helpers --------------------------------------------

print("\n--- archive.org helpers ---")

check(
    _archive_collection_spec_cache_key({"identifier": "test", "path_prefix": "ROMs/GBA"})
    == "archive_org_collection:test:ROMs/GBA",
    "spec cache key avec path"
)
check(
    _archive_collection_spec_cache_key({"identifier": "test_only"})
    == "archive_org_collection:test_only",
    "spec cache key sans path"
)

check(_archive_org_shard_key("roms_gba") == "", "pas de shard sans pattern")
check(_archive_org_shard_key("romgo_getter_a") == "a", "shard a")
check(_archive_org_shard_key("romgo_getter_numberssymbols") == "numberssymbols",
      "shard numberssymbols")
check(_archive_org_shard_key("romgo_getter_z_part1") == "z", "shard z avec part")

game_for_initials = {
    "primary_rom": "Super Mario Bros.gba",
    "game_name": "Super Mario Bros",
    "roms": [],
}
initials = _candidate_initials_for_archive_group(game_for_initials)
check("s" in initials, "initiale s pour Super Mario Bros")

game_for_initials_num = {
    "primary_rom": "1080 Snowboarding.zip",
    "game_name": "1080 Snowboarding",
    "roms": [],
}
initials_num = _candidate_initials_for_archive_group(game_for_initials_num)
check("numberssymbols" in initials_num, "initiale numberssymbols pour 1080")

# select_archive_org_collection_specs_for_game
big_identifiers = []
for letter in "abcdefghijklmnopqrstuvwxyz":
    big_identifiers.append(f"romgo_getter_{letter}")
selected = select_archive_org_collection_specs_for_game(
    big_identifiers, game_for_initials
)
check(len(selected) < len(big_identifiers), "filtrage reduit la liste")

# --- _gdrive_viewer_to_direct ---------------------------------------

print("\n--- _gdrive_viewer_to_direct ---")

check(
    _gdrive_viewer_to_direct(
        "https://drive.google.com/file/d/abc123def/view"
    ) == "https://drive.google.com/uc?export=download&id=abc123def",
    "conversion /file/d/"
)
check(
    _gdrive_viewer_to_direct(
        "https://drive.google.com/open?id=xyz789"
    ) == "https://drive.google.com/uc?export=download&id=xyz789",
    "conversion open?id="
)
check(
    _gdrive_viewer_to_direct("https://example.com/not-gdrive") == "https://example.com/not-gdrive",
    "url non gdrive inchangee"
)

# --- _parse_romsxisos_js --------------------------------------------

print("\n--- _parse_romsxisos_js ---")

js_data = '''
const roms = [
  {name: "Test Game (USA)", link1: "https://example.com/dl1", size: "4MB"},
  {name: "Another Game", link1: "https://example.com/dl2", size: "8MB"},
];
'''
parsed = _parse_romsxisos_js(js_data)
check(len(parsed) == 2, "parse 2 entrees")
check(parsed[0]["name"] == "Test Game (USA)", "premiere entree: name")
check(parsed[0]["link1"] == "https://example.com/dl1", "premiere entree: link1")

js_no_array = "const other = 42;"
check(len(_parse_romsxisos_js(js_no_array)) == 0, "pas de const roms => vide")

check(len(_parse_romsxisos_js("")) == 0, "js vide => []")

# --- match_source_files ---------------------------------------------

print("\n--- match_source_files ---")

missing = [
    {"game_name": "Game A", "primary_rom": "Game A.zip", "roms": []},
    {"game_name": "Game B", "primary_rom": "Game B.7z", "roms": []},
]
files_set = {"game a.zip", "game b.7z", "extra game.iso"}
found, not_found = match_source_files(missing, files_set, "TestSource")
check(len(found) == 2, "2 jeux trouves")
check(len(not_found) == 0, "0 non trouves")
check(found[0].get("source", "") != "" and "TestSource" in found[0].get("source", ""),
      "source nommee")

missing2 = [{"game_name": "Game C", "primary_rom": "Game C.iso", "roms": []}]
found2, not_found2 = match_source_files(missing2, set())
check(len(found2) == 0, "aucun fichier source => 0 trouve")
check(len(not_found2) == 1, "1 non trouve")

# --- parse_archive_org_collection_spec ------------------------------

print("\n--- parse_archive_org_collection_spec ---")

check(
    parse_archive_org_collection_spec("test_identifier") == {
        "identifier": "test_identifier",
    },
    "identifier simple"
)

spec_dir = parse_archive_org_collection_spec("test_identifier/subdir/")
check(
    spec_dir is not None and spec_dir["identifier"] == "test_identifier/subdir/",
    "identifier avec chemin (plat)"
)

spec_url = parse_archive_org_collection_spec(
    "https://archive.org/download/test_identifier/ROMs"
)
check(
    spec_url is not None and spec_url["identifier"] == "test_identifier"
    and spec_url.get("path_prefix") == "ROMs",
    "url archive.org download avec path"
)

check(parse_archive_org_collection_spec("") is None, "chaine vide => None")

# --- parse_archive_org_collection_specs -----------------------------

print("\n--- parse_archive_org_collection_specs ---")

specs = parse_archive_org_collection_specs(["id1", "id2", "id1"])
check(len(specs) == 2, "deduplication 3 -> 2")

check(len(parse_archive_org_collection_specs([])) == 0, "liste vide => []")

# --- archive_org_collection_identifiers -----------------------------

print("\n--- archive_org_collection_identifiers ---")

ids = archive_org_collection_identifiers(["id1", "id2/subdir/"])
check("id1" in ids and len(ids) == 2, "identifiants extraits")

# --- provider_exclusion_labels --------------------------------------

print("\n--- provider_exclusion_labels ---")

labels = provider_exclusion_labels({
    "source": "ArchiveOrg",
    "download_url": "https://archive.org/download/test/file.zip",
    "page_url": "",
    "torrent_url": "",
    "archive_org_identifier": "test",
})
check(len(labels) >= 1 and "archiveorg" in {l.lower() for l in labels}, "label provider inclu")
check("archiveorg" in {l.lower() for l in labels}, "label normalise inclu")

# --- resolution_cache_key -------------------------------------------

print("\n--- resolution_cache_key ---")

k1 = resolution_cache_key(
    {"game_name": "Test", "primary_rom": "test.zip"},
    [{"type": "archive_org", "name": "Archive.org"}],
    "Nintendo - Test",
    {"profile": "no-intro"},
)
k2 = resolution_cache_key(
    {"game_name": "Test", "primary_rom": "test.zip"},
    [{"type": "archive_org", "name": "Archive.org"}],
    "Nintendo - Test",
    {"profile": "no-intro"},
)
check(k1 == k2, "meme cle pour memes arguments")
check(isinstance(k1, str) and len(k1) > 0, "cle ressemble a un hash")

# --- resolve_system_mapping -----------------------------------------

print("\n--- resolve_system_mapping ---")

gba_mapping = resolve_system_mapping("Nintendo - Game Boy Advance", "lolroms")
check(gba_mapping is not None, "GBA mappee pour lolroms")

snes_mapping = resolve_system_mapping("Nintendo - Super Nintendo Entertainment System", "lolroms")
check(snes_mapping is not None, "SNES mappee pour lolroms")

nonexistent = resolve_system_mapping("Systeme - Inexistant XYZ Totalement", "lolroms")
check(nonexistent is None, "systeme inexistant non mappe")

# --- source_matches_label / find_source_config ----------------------

print("\n--- source_matches_label ---")

source_obj = {"name": "LoLROMs", "type": "lolroms", "priority": 1}
check(source_matches_label(source_obj, "lolroms"), "match par type")
check(not source_matches_label(source_obj, "archive_org"), "pas de match")

config = find_source_config(
    [{"name": "LoLROMs", "type": "lolroms", "priority": 1},
     {"name": "PlanetEmu", "type": "planetemu", "priority": 2}],
    "lolroms",
)
check(config is not None and config["name"] == "LoLROMs", "trouve LoLROMs")

# --- optional_positive_int / parse_candidate_limit ------------------

print("\n--- optional_positive_int / parse_candidate_limit ---")

check(optional_positive_int(5) == 5, "valeur normale")
check(optional_positive_int(0) is None, "0 => None")
check(optional_positive_int(-1) is None, "-1 => None")
check(optional_positive_int(None) is None, "None => None")

check(parse_candidate_limit(10) == 10, "limite explicite")
check(parse_candidate_limit("all", missing_count=50) == 50, "'all' => missing_count")
check(parse_candidate_limit(0) == 0, "0 => 0")

# --- source timeout / delay / quota ---------------------------------

print("\n--- source_timeout_seconds / delay / quota ---")

check(source_timeout_seconds({"timeout_seconds": 60}) == 60, "timeout explicite 60s")
check(source_timeout_seconds({}, 120) == 120, "timeout par defaut 120s")
check(source_timeout_seconds(None, 90) == 90, "source None => defaut")

check(source_delay_seconds({"delay_seconds": 2.5}) == 2.5, "delay explicite")
check(source_delay_seconds({}, 1.0) == 1.0, "delay par defaut")

check(source_quota_limit({"quota_per_run": 10}) == 10, "quota 10")
check(source_quota_limit({}) is None, "quota absent => unlimited")

# --- apply_source_policies ------------------------------------------

print("\n--- apply_source_policies ---")

sources = [
    {"name": "LoLROMs", "type": "lolroms", "priority": 1},
    {"name": "PlanetEmu", "type": "planetemu", "priority": 2},
]
policies = {
    "LoLROMs": {"timeout_seconds": 30, "delay_seconds": 3},
}
modified = apply_source_policies(sources, policies)
lol_policy = next((s for s in modified if s["type"] == "lolroms"), {})
check(lol_policy.get("timeout_seconds") == 30, "timeout applique a LoLROMs")
check(lol_policy.get("delay_seconds") == 3.0, "delay applique a LoLROMs")

# --- source_policy_summary ------------------------------------------

print("\n--- source_policy_summary ---")

summary = source_policy_summary({
    "name": "LoLROMs",
    "timeout_seconds": 60,
    "delay_seconds": 3,
    "quota_per_run": 10,
})
check("timeout" in summary.lower() and "60" in summary, "summary contient timeout")
check("quota" in summary.lower() and "10" in summary, "summary contient quota")
check("delai" in summary.lower() and "3" in summary, "summary contient delay")

# --- reserve_source_quota -------------------------------------------

print("\n--- reserve_source_quota ---")

source_src = {"name": "LoLROMs", "type": "lolroms", "quota_per_run": 3}
usage = {}
allowed, msg = reserve_source_quota("lolroms", [source_src], usage)
check(allowed, "premiere reservation autorisee")
allowed2, _ = reserve_source_quota("lolroms", [source_src], usage)
allowed3, _ = reserve_source_quota("lolroms", [source_src], usage)
allowed4, _ = reserve_source_quota("lolroms", [source_src], usage)
check(not allowed4, "quota epuise apres 3 reservations")

# --- build_custom_source --------------------------------------------

print("\n--- build_custom_source ---")

custom = build_custom_source("https://minerva.torrent.example.com/test")
check(custom is not None, "source custom non None")
check(custom.get("type") != "myrient", "pas de type myrient")

custom_empty = build_custom_source("")
check(custom_empty is not None and custom_empty.get("name") == "Source Custom", "url vide => source custom par defaut")

# --- build_lolroms_url ----------------------------------------------

print("\n--- build_lolroms_url ---")

url = build_lolroms_url("Nintendo - Game Boy Advance/Multi-Boot")
check("lolroms.com" in url or "lolroms.fr" in url, "URL contient le domaine lolroms")
check("Game%20Boy" in url, "espaces encodes")
check("Multi-Boot" in url, "sous-repertoire present")

# --- classify_error + HTML snippet ----------------------------------

print("\n--- classify_error ---")

check(classify_error(detail="Blocage Cloudflare detecte") == "cloudflare_challenge",
      "cloudflare classifie")
check(classify_error(detail="reponse html inattendue") == "html_response",
      "html inattendu classifie")
check(classify_error(detail="MD5 KO, checksum mismatch") == "checksum_mismatch",
      "checksum mismatch classifie")
check(classify_error(detail="timeout reseau") == "network_timeout",
      "timeout classifie")
check(classify_error(detail="quota exceede") == "quota_exceeded",
      "quota classifie")

# --- error_is_poison ------------------------------------------------

print("\n--- error_is_poison ---")

check(error_is_poison("html_response"), "html_response est poison")
check(error_is_poison("unexpected_html"), "unexpected_html est poison")
check(not error_is_poison("network_timeout"), "network_timeout pas poison")
check(not error_is_poison(""), "vide pas poison")

# --- Verdict final --------------------------------------------------

print("\n" + "=" * 50)
if errors:
    print(f"{len(errors)} ECHEC(S):")
    for e in errors:
        print(f"  - {e}")
    raise SystemExit(1)
else:
    print("Tous les tests providers passes avec succes.")


def main():
    pass


if __name__ == "__main__":
    main()
