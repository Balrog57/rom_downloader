"""Targeted runtime helper checks without network access."""

from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core import (  # noqa: E402
    cache_entry_matches_source,
    expected_game_sizes,
    find_listing_match,
    listing_cache_prefixes_for_source,
    normalize_system_name,
    normalize_external_game_name,
    iter_game_candidate_names,
    optional_positive_int,
    parse_candidate_limit,
    prepare_sources_for_profile,
    reserve_source_quota,
    source_quota_limit,
    source_timeout_seconds,
    verify_downloaded_md5,
)
from src.pipeline import build_pipeline_summary, merge_provider_metrics  # noqa: E402
from src.progress import DownloadProgressMeter, format_duration  # noqa: E402


def assert_true(condition, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    assert_true(format_duration(65) == "1m05s", "duration formatting failed")
    meter = DownloadProgressMeter(total_size=100, resume_from=20, report_interval=0.1)
    assert_true(meter.snapshot(50) is None, "progress meter reported too early")
    assert_true(optional_positive_int("12", maximum=10) == 10, "integer clamp failed")
    assert_true(optional_positive_int("0") is None, "zero should be ignored")
    assert_true(parse_candidate_limit("all", 42) == 42, "candidate limit all failed")
    assert_true(parse_candidate_limit("7", 42) == 7, "candidate limit number failed")
    assert_true(
        normalize_system_name("Nintendo - GameCube - Datfile (2019) (2026-03-31 11-37-45)") == "Nintendo - GameCube",
        "DAT filename cleanup failed",
    )

    source = {"name": "EdgeEmu", "type": "edgeemu", "timeout_seconds": "45", "quota_per_run": "2"}
    assert_true(source_timeout_seconds(source) == 45, "source timeout failed")
    assert_true(source_quota_limit(source) == 2, "source quota failed")

    redump_profile = {"family": "redump", "family_label": "Redump", "system_name": "Sony - PlayStation"}
    redump_sources = prepare_sources_for_profile([
        {"name": "LoLROMs", "type": "lolroms", "enabled": True},
        {"name": "PlanetEmu", "type": "planetemu", "enabled": True},
        {"name": "EdgeEmu", "type": "edgeemu", "enabled": True},
        {"name": "Minerva No-Intro", "type": "minerva", "collection": "No-Intro", "enabled": True},
        {"name": "Minerva Redump", "type": "minerva", "collection": "Redump", "enabled": True},
    ], redump_profile)
    compatibility = {item["name"]: item.get("compatible") for item in redump_sources}
    assert_true(compatibility["LoLROMs"], "LoLROMs should be usable as a Redump fallback")
    assert_true(compatibility["PlanetEmu"], "PlanetEmu should be usable as a Redump fallback")
    assert_true(compatibility["EdgeEmu"], "EdgeEmu should be usable when explicitly enabled")
    assert_true(not compatibility["Minerva No-Intro"], "No-Intro Minerva should not match a Redump DAT")
    assert_true(compatibility["Minerva Redump"], "Redump Minerva should match a Redump DAT")

    listing = {
        "kidou senshi gundam - senshitachi no kiseki (japan)": {
            "full_name": "Kidou Senshi Gundam - Senshitachi no Kiseki (Japan)",
            "filename": "Kidou Senshi Gundam - Senshitachi no Kiseki (Japan).7z",
        },
        "kidou senshi gundam - senshitachi no kiseki (japan) (special disc)": {
            "full_name": "Kidou Senshi Gundam - Senshitachi no Kiseki (Japan) (Special Disc)",
            "filename": "Kidou Senshi Gundam - Senshitachi no Kiseki (Japan) (Special Disc).7z",
        },
    }
    _match_name, match_entry = find_listing_match(
        {
            "game_name": "Kidou Senshi Gundam - Senshi-tachi no Kiseki (Japan) (Special Disc)",
            "primary_rom": "Kidou Senshi Gundam - Senshi-tachi no Kiseki (Japan) (Special Disc).iso",
        },
        listing,
    )
    assert_true(
        match_entry and "Special Disc" in match_entry["filename"],
        "LoLROMs fuzzy match should preserve special disc qualifiers",
    )

    # ── Normalisation edge cases ──
    norm = normalize_external_game_name
    assert_true(norm("") == "", "empty string normalisation failed")
    assert_true(norm("Game (USA).7z") == "game usa", "basic normalisation failed")
    assert_true(norm("Game (USA) (Disc 1).iso") == "game usa disc 1", "disc normalisation failed")
    assert_true(norm("Game (USA) (Rev 2).bin") == "game usa rev 2", "rev normalisation failed")
    assert_true(norm("Super Mario 64 (USA).z64") == "super mario 64 usa", "n64 normalisation failed")
    assert_true(norm("Resident Evil 4 (USA) (Disc 1).7z") == "resident evil 4 usa disc 1", "gc multi-disc failed")
    assert_true(norm("Crash Bandicoot (Europe) (En,Fr,De,Es,It,Nl).cue") == "crash bandicoot europe en fr de es it nl", "psx multilang failed")
    assert_true(norm("Game & Watch Gallery 4 (USA, Australia).gba") == "game and watch gallery 4 usa australia", "ampersand failed")
    assert_true(norm("Pok\u00e9mon Version Rouge (France).gbc") == "pokemon version rouge france", "accent normalisation failed")
    assert_true(norm("Final Fantasy VII (USA) (Disc 2) (v1.1).cue") == "final fantasy vii usa disc 2 rev 1 1", "combined qualifiers failed")

    # ── Candidate names ──
    candidates = iter_game_candidate_names({
        "game_name": "Super Mario Sunshine",
        "primary_rom": "Super Mario Sunshine (USA).iso",
        "roms": [{"name": "Super Mario Sunshine (USA) (Rev 1).iso"}],
    })
    assert_true(len(candidates) >= 2, "candidate generation produced too few entries")
    assert_true("Super Mario Sunshine (USA)" in candidates[0], "first candidate should be primary rom")

    # ── Matching edge cases GameCube ──
    gc_listing = {
        "resident evil 4 (usa) (disc 1)": {
            "full_name": "Resident Evil 4 (USA) (Disc 1)",
            "filename": "Resident Evil 4 (USA) (Disc 1).7z",
        },
        "resident evil 4 (usa) (disc 2)": {
            "full_name": "Resident Evil 4 (USA) (Disc 2)",
            "filename": "Resident Evil 4 (USA) (Disc 2).7z",
        },
        "metroid prime (usa)": {
            "full_name": "Metroid Prime (USA)",
            "filename": "Metroid Prime (USA).7z",
        },
    }
    _mn, re4_match = find_listing_match({
        "game_name": "Resident Evil 4 (USA)",
        "primary_rom": "Resident Evil 4 (USA) (Disc 1).iso",
        "roms": [{"name": "Resident Evil 4 (USA) (Disc 1).iso"}],
    }, gc_listing)
    assert_true(re4_match and "Disc 1" in re4_match["filename"], "GC multi-disc matching failed - disc 1 should match")

    _mn2, mp_match = find_listing_match({
        "game_name": "Metroid Prime (USA)",
        "primary_rom": "Metroid Prime (USA).iso",
    }, gc_listing)
    assert_true(mp_match and "Metroid Prime (USA).7z" == mp_match["filename"], "GC exact matching failed")

    # ── Matching edge cases PlayStation ──
    psx_listing = {
        "crash bandicoot (europe)": {
            "full_name": "Crash Bandicoot (Europe)",
            "filename": "Crash Bandicoot (Europe).7z",
        },
        "crash bandicoot (usa)": {
            "full_name": "Crash Bandicoot (USA)",
            "filename": "Crash Bandicoot (USA).7z",
        },
        "final fantasy vii (usa) (disc 1)": {
            "full_name": "Final Fantasy VII (USA) (Disc 1)",
            "filename": "Final Fantasy VII (USA) (Disc 1).7z",
        },
        "final fantasy vii (usa) (disc 2)": {
            "full_name": "Final Fantasy VII (USA) (Disc 2)",
            "filename": "Final Fantasy VII (USA) (Disc 2).7z",
        },
        "final fantasy vii (usa) (disc 3)": {
            "full_name": "Final Fantasy VII (USA) (Disc 3)",
            "filename": "Final Fantasy VII (USA) (Disc 3).7z",
        },
    }
    _mn3, ff7_d1 = find_listing_match({
        "game_name": "Final Fantasy VII (USA)",
        "primary_rom": "Final Fantasy VII (USA) (Disc 1).cue",
        "roms": [{"name": "Final Fantasy VII (USA) (Disc 1).cue"}],
    }, psx_listing)
    assert_true(ff7_d1 and "Disc 1" in ff7_d1["filename"], "PSX multi-disc matching failed - disc 1 should match")

    _mn4, ff7_d3 = find_listing_match({
        "game_name": "Final Fantasy VII (USA)",
        "primary_rom": "Final Fantasy VII (USA) (Disc 3).cue",
        "roms": [{"name": "Final Fantasy VII (USA) (Disc 3).cue"}],
    }, psx_listing)
    assert_true(ff7_d3 and "Disc 3" in ff7_d3["filename"], "PSX multi-disc matching failed - disc 3 should match")

    _mn5, cb_eu = find_listing_match({
        "game_name": "Crash Bandicoot (Europe) (En,Fr,De,Es,It,Nl)",
        "primary_rom": "Crash Bandicoot (Europe) (En,Fr,De,Es,It,Nl).cue",
    }, psx_listing)
    assert_true(cb_eu and "Crash Bandicoot (Europe)" in cb_eu["filename"], "PSX multilang fuzzy matching failed")

    # ── Normalisation preserves disc after cleanup ──
    assert_true(norm("Game (USA) (Disc 1) (Rev 2).iso") == "game usa disc 1 rev 2", "disc rev combo failed")
    assert_true(norm("Game (USA) (Demo).zip") == "game usa", "demo qualifier stripped")

    usage = {}
    assert_true(reserve_source_quota("EdgeEmu", [source], usage)[0], "first quota reservation failed")
    assert_true(reserve_source_quota("EdgeEmu", [source], usage)[0], "second quota reservation failed")
    quota_ok, quota_detail = reserve_source_quota("EdgeEmu", [source], usage)
    assert_true(not quota_ok and "quota atteint" in quota_detail, "quota limit not enforced")
    assert_true(listing_cache_prefixes_for_source("Minerva No-Intro") == {"minerva"}, "listing cache prefix failed")
    assert_true(
        cache_entry_matches_source({"sources": ["minerva no-intro"], "found_sources": []}, "Minerva"),
        "resolution cache source match failed",
    )
    pipeline_summary = build_pipeline_summary({
        "resolved_items": [{
            "source": "Minerva",
            "provider_attempts": [{"source": "Minerva", "status": "dry_run", "duration_seconds": 1.25}],
        }],
        "failed_items": [{
            "provider_attempts": [{"source": "EdgeEmu", "status": "quota_skipped", "detail": "quota atteint"}],
        }],
        "not_available": [{"game_name": "Missing"}],
    })
    assert_true(pipeline_summary["source_counts"]["Minerva"] == 1, "pipeline source count failed")
    assert_true(pipeline_summary["provider_metrics"]["EdgeEmu"]["quota_skipped"] == 1, "pipeline quota metric failed")
    assert_true(pipeline_summary["failure_causes"]["not_found"] == 1, "pipeline not_found cause failed")
    merged = merge_provider_metrics({"EdgeEmu": {"attempts": 1, "failed": 1}}, {"EdgeEmu": {"attempts": 2, "downloaded": 1}})
    assert_true(merged["EdgeEmu"]["attempts"] == 3 and merged["EdgeEmu"]["downloaded"] == 1, "provider metric merge failed")

    # ── System name cleanup: format suffixes ──
    nsys = normalize_system_name
    assert_true(nsys("Atari - Atari 7800 (BIN)") == "Atari - Atari 7800", "format suffix (BIN) not stripped")
    assert_true(nsys("Atari - Atari Jaguar (J64)") == "Atari - Atari Jaguar", "format suffix (J64) not stripped")
    assert_true(nsys("Atari - Atari Lynx (LYX)") == "Atari - Atari Lynx", "format suffix (LYX) not stripped")
    assert_true(nsys("Nintendo - Nintendo Entertainment System (Headered)") == "Nintendo - Nintendo Entertainment System", "headered suffix survives")
    assert_true(nsys("Nintendo - Game Boy (WIP)") == "Nintendo - Game Boy", "WIP suffix not stripped")
    assert_true(nsys("Sony - PlayStation 3 (PSN) (DLC)") == "Sony - PlayStation 3", "PSN DLC not stripped")
    assert_true(nsys("NEC - PC-88 series (KryoFlux)") == "NEC - PC-88 series", "KryoFlux suffix not stripped")
    assert_true(nsys("Nintendo - Nintendo 64 (BigEndian)") == "Nintendo - Nintendo 64", "BigEndian suffix not stripped")
    assert_true(nsys("Sony - PlayStation Portable (PSN) (Encrypted)") == "Sony - PlayStation Portable", "PSN Encrypted not stripped")
    assert_true(nsys("Nintendo - Nintendo 3DS (Digital) (CDN)") == "Nintendo - Nintendo 3DS", "Digital CDN not stripped")
    assert_true(nsys("Sony - PlayStation Vita (PSN) (NoNpDrm)") == "Sony - PlayStation Vita", "NoNpDrm not stripped")
    assert_true(nsys("Nintendo - Nintendo DS (Decrypted)") == "Nintendo - Nintendo DS", "Decrypted not stripped")
    assert_true(nsys("Nintendo - Family Computer Disk System (FDS)") == "Nintendo - Family Computer Disk System", "FDS suffix not stripped")
    assert_true(nsys("IBM - PC and Compatibles (Digital) (Steam)") == "IBM - PC and Compatibles", "Digital Steam not stripped")

    game = {"roms": [{"size": "4"}]}
    assert_true(expected_game_sizes(game) == {4}, "expected size extraction failed")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        rom_path = tmp_path / "game.bin"
        rom_path.write_bytes(b"abcd")
        ok, message = verify_downloaded_md5(game, str(rom_path))
        assert_true(ok and "Taille DAT OK" in message, "direct size validation failed")

        bad_ok, bad_message = verify_downloaded_md5({"roms": [{"size": "5"}]}, str(rom_path))
        assert_true(not bad_ok and "Taille DAT KO" in bad_message, "direct size mismatch failed")

        zip_path = tmp_path / "game.zip"
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("game.bin", b"abcd")
        zip_ok, zip_message = verify_downloaded_md5(game, str(zip_path))
        assert_true(zip_ok and "Taille DAT OK" in zip_message, "archive size validation failed")

    # ROM_DATABASE stale-binding guard: verify module-level attribute access works
    from src.core import rom_database as _rd_mod
    _rd_mod.ROM_DATABASE
    assert_true(
        not isinstance(_rd_mod.ROM_DATABASE, dict) or 'config_urls' in _rd_mod.ROM_DATABASE,
        "ROM_DATABASE should be None or a dict with config_urls after module load",
    )

    print("core helper checks ok")


if __name__ == "__main__":
    main()
