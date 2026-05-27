"""Targeted runtime helper checks without network access."""

import json
from pathlib import Path
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core import (  # noqa: E402
    cache_entry_matches_source,
    archive_org_collection_identifiers,
    build_custom_source,
    expected_game_sizes,
    find_listing_match,
    listing_cache_prefixes_for_source,
    normalize_system_name,
    normalize_external_game_name,
    iter_game_candidate_names,
    optional_positive_int,
    parse_candidate_limit,
    prepare_sources_for_profile,
    resolve_dat_output_folder,
    safe_dat_folder_name,
    reserve_source_quota,
    APP_ROOT,
    RESOURCE_ROOT,
    PREFERENCES_FILE,
    RESOLUTION_CACHE_FILE,
    source_quota_limit,
    source_policy_summary,
    source_timeout_seconds,
    select_archive_org_collection_specs_for_game,
    strip_rom_extension,
    verify_downloaded_md5,
    build_catalog_index,
    list_catalog_systems,
    list_catalog_sections,
    list_catalog_games,
    record_provider_success,
    list_validated_providers,
    create_download_job,
    run_download_job,
    list_download_jobs,
    update_download_queue_item,
    list_download_queue_items,
    get_download_job_detail,
    record_provider_candidates,
    list_provider_candidates,
    list_provider_metrics,
    build_source_health_summary,
    record_download_history,
    list_download_history,
    classify_error,
    error_is_retryable,
    build_mapping_status,
    export_mapping_status,
    resolve_game_sources_with_cache,
    probe_catalog_providers,
    build_report_payload,
    write_download_report,
    write_download_reports,
    get_job_status,
    get_job_config,
    get_pending_queue_items_for_job,
    save_job_progress,
    cleanup_stale_locks,
    pause_download_job,
    resume_download_job,
    cancel_download_job,
    retry_failed_queue_items,
    update_download_job,
    QUEUE_TERMINAL_STATUSES,
    reset_local_database,
    apply_config_profile,
    config_profile_settings,
    normalize_config_profile,
)
from src.network.metrics import compute_provider_score, record_provider_attempt, prioritize_sources, load_provider_metrics  # noqa: E402
from src.network.exceptions import ChecksumMismatchError  # noqa: E402
from src.network.cloudflare_detection import looks_like_cloudflare_block  # noqa: E402
from src.pipeline import build_pipeline_summary, merge_provider_metrics  # noqa: E402
from src.progress import DownloadProgressMeter, format_duration  # noqa: E402
from src.core.downloads import recover_orphaned_parts  # noqa: E402


def assert_true(condition, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    assert_true(format_duration(65) == "1m05s", "duration formatting failed")
    assert_true(
        looks_like_cloudflare_block(
            403,
            {"server": "cloudflare", "content-type": "text/html", "cf-ray": "abc"},
            "Just a moment...",
            "https://example.invalid/__cf_chl",
        ),
        "cloudflare detection failed",
    )
    assert_true(APP_ROOT.exists(), "app root should exist")
    assert_true(RESOURCE_ROOT.exists(), "resource root should exist")
    assert_true(PREFERENCES_FILE.parent == APP_ROOT, "preferences should live under app root")
    assert_true(RESOLUTION_CACHE_FILE.parent == APP_ROOT, "resolution cache should live under app root")
    meter = DownloadProgressMeter(total_size=100, resume_from=20, report_interval=0.1)
    assert_true(meter.snapshot(50) is None, "progress meter reported too early")
    assert_true(optional_positive_int("12", maximum=10) == 10, "integer clamp failed")
    assert_true(optional_positive_int("0") is None, "zero should be ignored")
    assert_true(parse_candidate_limit("all", 42) == 42, "candidate limit all failed")
    assert_true(parse_candidate_limit("7", 42) == 7, "candidate limit number failed")
    assert_true(normalize_config_profile("Archive propre") == "archive-propre", "profile alias failed")
    assert_true(config_profile_settings("debutant-sur")["dry_run"] is True, "safe profile must force dry-run")
    profile_args = type("Args", (), {
        "dry_run": False,
        "parallel": 3,
        "clean_torrentzip": False,
        "tosort": False,
        "prefer_1fichier": True,
        "report_formats": "txt",
    })()
    applied = apply_config_profile(profile_args, "archive-propre", {"parallel"})
    assert_true(applied == "archive-propre", "profile should apply")
    assert_true(profile_args.parallel == 3, "explicit parallel must be preserved")
    assert_true(profile_args.clean_torrentzip is True, "archive profile must enable torrentzip")
    assert_true(profile_args.tosort is True, "archive profile must enable tosort")
    assert_true(
        normalize_system_name("Nintendo - GameCube - Datfile (2019) (2026-03-31 11-37-45)") == "Nintendo - GameCube",
        "DAT filename cleanup failed",
    )
    assert_true(
        safe_dat_folder_name(r"C:\DAT\Nintendo - GameCube: Datfile? (2026).dat") == "Nintendo - GameCube Datfile (2026)",
        "dat folder sanitizing failed",
    )
    assert_true(
        resolve_dat_output_folder(r"C:\DAT\Nintendo - GameCube: Datfile? (2026).dat", r"S:\downloads", True)
        == str(Path(r"S:\downloads") / "Nintendo - GameCube Datfile (2026)"),
        "dat output folder resolution failed",
    )
    gc_output = resolve_dat_output_folder(r"C:\DAT\Nintendo - GameCube.dat", r"S:\downloads", True)
    jag_output = resolve_dat_output_folder(r"C:\DAT\Atari - Jaguar CD.dat", r"S:\downloads", True)
    assert_true(gc_output != jag_output, "multi-DAT output folders should differ by DAT stem")
    assert_true(strip_rom_extension("Game.nkit.gcz") == "Game", "nkit.gcz stripping failed")
    assert_true(strip_rom_extension("Game.nkit.iso") == "Game", "nkit.iso stripping failed")
    assert_true(strip_rom_extension("Game.rvz") == "Game", "rvz stripping failed")
    assert_true(strip_rom_extension("Game.cue") == "Game", "cue stripping failed")
    assert_true(strip_rom_extension("Game.bin") == "Game", "bin stripping failed")

    redump_candidates = iter_game_candidate_names({
        "game_name": "Baldies (World)",
        "primary_rom": "Baldies (World) (Track 01).bin",
        "roms": [{"name": "Baldies (World) (Track 02).bin"}],
    })
    assert_true("Baldies (World)" in redump_candidates, "redump track variant missing")

    match_cases = [
        (
            {"game_name": "Super Mario Sunshine (USA)", "primary_rom": "Super Mario Sunshine (USA).iso", "roms": []},
            {"Super Mario Sunshine (USA).nkit.gcz": {"full_name": "Super Mario Sunshine (USA).nkit.gcz"}},
            "gamecube redump match failed",
        ),
        (
            {"game_name": "Baldies (World)", "primary_rom": "Baldies (World) (Track 01).bin", "roms": []},
            {"Baldies (World).chd": {"full_name": "Baldies (World).chd"}},
            "jaguar cd redump match failed",
        ),
        (
            {"game_name": "Sonic Adventure (USA) (Disc 1)", "primary_rom": "Sonic Adventure (USA) (Disc 1).gdi", "roms": []},
            {"Sonic Adventure (USA) (Disc 1).chd": {"full_name": "Sonic Adventure (USA) (Disc 1).chd"}},
            "dreamcast redump match failed",
        ),
        (
            {"game_name": "Final Fantasy VII (USA) (Disc 1)", "primary_rom": "Final Fantasy VII (USA) (Disc 1).cue", "roms": []},
            {"Final Fantasy VII (USA) (Disc 1).chd": {"full_name": "Final Fantasy VII (USA) (Disc 1).chd"}},
            "playstation redump match failed",
        ),
    ]
    for game_info, listing, message in match_cases:
        _candidate, entry = find_listing_match(game_info, listing)
        assert_true(entry is not None, message)

    source = {"name": "EdgeEmu", "type": "edgeemu", "timeout_seconds": "45", "quota_per_run": "2"}
    assert_true(source_timeout_seconds(source) == 45, "source timeout failed")
    assert_true(source_quota_limit(source) == 2, "source quota failed")
    delayed = {"name": "LoLROMs", "type": "lolroms", "delay_seconds": "2.5"}
    assert_true("delai 2.5s" in source_policy_summary(delayed), "source delay summary failed")

    archive_source = build_custom_source("https://archive.org/download/tp-roms_0/TeknoParrot/")
    assert_true(archive_source["type"] == "archive_org_collection", "archive.org custom source detection failed")
    assert_true(
        archive_source["identifiers"] == [{"identifier": "tp-roms_0", "path_prefix": "TeknoParrot"}],
        "archive.org download URL parsing failed",
    )
    assert_true(
        archive_org_collection_identifiers("ps2_archive")[:2] == ["sony_playstation2_numberssymbols", "sony_playstation2_a"],
        "RomGoGetter archive group expansion failed",
    )
    selected_specs = select_archive_org_collection_specs_for_game(
        [
            "sony_playstation2_a",
            "sony_playstation2_b",
            "sony_playstation2_c",
            "sony_playstation2_d_part1",
            "sony_playstation2_e",
            "sony_playstation2_f",
            "sony_playstation2_g",
            "sony_playstation2_h",
            "sony_playstation2_numberssymbols",
        ],
        {"game_name": "Final Fantasy X", "primary_rom": "Final Fantasy X (USA).iso"},
    )
    assert_true(
        [spec["identifier"] for spec in selected_specs] == ["sony_playstation2_f"],
        "archive.org shard selection failed",
    )

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
        listing_cache_prefixes_for_source("archive.org cible") == {"archive_org_collection"},
        "archive.org cache prefix failed",
    )
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

    with tempfile.TemporaryDirectory() as report_dir:
        report_summary = {
            "dat_file": "Nintendo - Test.dat",
            "system_name": "Nintendo - Test",
            "dat_profile": "No-Intro - Nintendo - Test",
            "output_folder": report_dir,
            "dry_run": True,
            "active_sources": ["ProviderA", "ProviderB"],
            "total_dat_games": 4,
            "present_before": 1,
            "missing_before": 3,
            "total_size": 12,
            "missing_size": 9,
            "resolved_items": [
                {
                    "game_name": "Alpha <Bad & \"Game\">",
                    "source": "ProviderA",
                    "download_filename": "alpha.zip",
                    "size": 4,
                    "provider_attempts": [{"source": "ProviderA", "status": "dry_run", "duration_seconds": 0.5}],
                }
            ],
            "failed_items": [
                {
                    "game_name": "Beta Game",
                    "source": "ProviderB",
                    "error_code": "checksum_mismatch",
                    "error": "MD5 DAT KO",
                    "provider_attempts": [{"source": "ProviderB", "status": "failed", "detail": "MD5 DAT KO"}],
                }
            ],
            "not_available": [{"game_name": "Gamma Game"}],
            "skipped_items": [{"game_name": "Delta Game"}],
            "source_health": [{
                "provider": "ProviderB",
                "status": "degraded",
                "coverage": 2,
                "active_candidates": 1,
                "success_count": 0,
                "failure_count": 1,
                "last_error_code": "checksum_mismatch",
                "recommended_action": "Verifier mapping DAT/provider",
            }],
        }
        payload = build_report_payload(report_summary)
        assert_true(payload["metadata"]["mode"] == "dry-run", "report payload mode failed")
        assert_true(payload["counts"]["present_before"] == 1, "report payload present count failed")
        report_paths = write_download_reports(report_dir, report_summary, formats=("txt", "json", "csv", "html"))
        assert_true(set(report_paths) == {"txt", "json", "csv", "html"}, "multi report formats failed")
        for path in report_paths.values():
            assert_true(Path(path).exists(), f"report file missing: {path}")
        txt_report = Path(report_paths["txt"]).read_text(encoding="utf-8")
        assert_true("Mode: dry-run, aucun telechargement effectue" in txt_report, "dry-run report marker missing")
        assert_true("Telecharges/Simules" in txt_report, "txt simulated section missing")
        json_report = json.loads(Path(report_paths["json"]).read_text(encoding="utf-8"))
        assert_true("metadata" in json_report and "counts" in json_report and "items" in json_report, "json report shape failed")
        assert_true(json_report["source_health"][0]["provider"] == "ProviderB", "json source health failed")
        csv_report = Path(report_paths["csv"]).read_text(encoding="utf-8")
        assert_true("status,system_name,game_name,provider,download_filename,size,error_code,detail,file_path" in csv_report, "csv header failed")
        assert_true("checksum_mismatch" in csv_report and "not_found" in csv_report, "csv rows failed")
        html_report = Path(report_paths["html"]).read_text(encoding="utf-8")
        assert_true("Alpha &lt;Bad &amp; &quot;Game&quot;&gt;" in html_report, "html escaping failed")
        assert_true("Sante sources" in html_report and "ProviderB" in html_report, "html source health failed")
        assert_true("Alpha <Bad" not in html_report, "html must not contain raw game name")
        compat_path = write_download_report(report_dir, report_summary)
        assert_true(Path(compat_path).exists() and compat_path.endswith(".txt"), "compat txt report failed")

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

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        dat_root = tmp_path / "dat"
        catalog_root = tmp_path / "db"
        dat_section = dat_root / "No-Intro"
        dat_section.mkdir(parents=True)
        dat_file = dat_section / "Nintendo - Test System.dat"
        dat_file.write_text(
            """<?xml version="1.0"?>
<datafile>
  <header><name>Nintendo - Test System</name><url>https://no-intro.org</url></header>
  <game name="Alpha Game (USA)">
    <rom name="Alpha Game (USA).bin" size="4" crc="1a2b3c4d" md5="0123456789abcdef0123456789abcdef" sha1="0123456789abcdef0123456789abcdef01234567" />
  </game>
  <game name="Beta Game (Europe)">
    <rom name="Beta Game (Europe).bin" size="8" crc="2a2b3c4d" md5="1123456789abcdef0123456789abcdef" sha1="1123456789abcdef0123456789abcdef01234567" />
  </game>
</datafile>
""",
            encoding="utf-8",
        )
        catalog_result = build_catalog_index(dat_root, force=True, catalog_dir=catalog_root)
        assert_true(catalog_result["systems"] == 1 and catalog_result["games"] == 2, "catalog index counts failed")
        incremental_result = build_catalog_index(dat_root, force=False, catalog_dir=catalog_root)
        assert_true(
            incremental_result["systems"] == 0 and incremental_result["games"] == 0 and incremental_result["skipped"] == 1,
            "catalog incremental skip failed",
        )
        systems = list_catalog_systems(catalog_dir=catalog_root)
        assert_true(len(systems) == 1 and systems[0]["game_count"] == 2, "catalog system listing failed")
        assert_true(systems[0]["dat_section"] == "No-Intro", "catalog section should come from DAT folder")
        assert_true(list_catalog_sections(catalog_dir=catalog_root) == ["No-Intro"], "catalog sections listing failed")
        assert_true(
            len(list_catalog_systems({"section": "No-Intro"}, catalog_dir=catalog_root)) == 1,
            "catalog section filter failed",
        )
        games = list_catalog_games(systems[0]["system_id"], query="alpha", catalog_dir=catalog_root)
        assert_true(len(games) == 1 and games[0]["game_name"].startswith("Alpha"), "catalog game query failed")
        assert_true(not list_validated_providers(games[0]["game_id"], path=catalog_root), "provider should not persist before success")
        record_provider_success(
            games[0]["game_id"],
            {"source": "ProviderA", "download_url": "https://example.invalid/a.zip", "download_filename": "a.zip"},
            {"file_path": str(tmp_path / "a.zip"), "size": 4, "duration_seconds": 1.0, "average_speed": 4.0},
            path=catalog_root,
        )
        record_provider_success(
            games[0]["game_id"],
            {"source": "ProviderA", "download_url": "https://example.invalid/a.zip", "download_filename": "a.zip"},
            {"file_path": str(tmp_path / "a.zip"), "size": 4, "duration_seconds": 1.0, "average_speed": 4.0},
            path=catalog_root,
        )
        record_provider_success(
            games[0]["game_id"],
            {"source": "ProviderB", "torrent_url": "https://example.invalid/b.torrent", "download_filename": "b.zip"},
            {"file_path": str(tmp_path / "b.zip"), "size": 4, "duration_seconds": 1.0, "average_speed": 4.0},
            path=catalog_root,
        )
        enriched = list_catalog_games(systems[0]["system_id"], query="alpha", catalog_dir=catalog_root)[0]
        assert_true(len(enriched["providers"]) == 2, "catalog provider dedup failed")

        beta = list_catalog_games(systems[0]["system_id"], query="beta", catalog_dir=catalog_root)[0]
        job_id = create_download_job(
            systems[0]["system_id"],
            [enriched, beta],
            str(tmp_path / "downloads"),
            path=catalog_root,
            settings={"parallel_downloads": 2},
        )
        queued = list_download_queue_items({"job_id": job_id}, path=catalog_root)
        assert_true(len(queued) == 2 and {item["status"] for item in queued} == {"pending"}, "download queue creation failed")
        assert_true(
            update_download_queue_item(job_id, game_id=enriched["game_id"], status="running", locked_by="test", increment_attempts=True, path=catalog_root),
            "download queue running update failed",
        )
        update_download_queue_item(job_id, game_id=enriched["game_id"], status="completed", path=catalog_root)
        queued = list_download_queue_items({"job_id": job_id}, path=catalog_root)
        alpha_queue = next(item for item in queued if item["game_id"] == enriched["game_id"])
        assert_true(
            alpha_queue["status"] == "completed" and alpha_queue["attempt_count"] == 1 and not alpha_queue["locked_by"],
            "download queue terminal update failed",
        )
        job_state = run_download_job(job_id, path=catalog_root)
        assert_true(job_state["queue"].get("completed") == 1 and job_state["queue"].get("pending") == 1, "download queue state summary failed")
        record_download_history(
            {
                "job_id": job_id,
                "game_id": beta["game_id"],
                "system_id": systems[0]["system_id"],
                "game_name": beta["game_name"],
                "provider": "ProviderA",
                "status": "failed",
                "error_code": "http_429",
                "error": "HTTP 429",
                "retryable": True,
            },
            path=catalog_root,
        )
        job_detail = get_download_job_detail(job_id, path=catalog_root)
        assert_true(
            job_detail["job"]["job_id"] == job_id
            and job_detail["queue"].get("completed") == 1
            and job_detail["errors"].get("http_429") == 1
            and job_detail["summary"]["last_error_code"] == "http_429"
            and job_detail["attempts"][0]["retryable"] == 1,
            "download job detail failed",
        )
        jobs = list_download_jobs(path=catalog_root)
        assert_true(len(jobs) == 1 and jobs[0]["queue"].get("completed") == 1, "download jobs listing failed")

        from src.core.local_database import pause_download_job as _pause  # noqa: E402
        from src.core.local_database import resume_download_job as _resume  # noqa: E402
        from src.core.local_database import cancel_download_job as _cancel  # noqa: E402
        from src.core.local_database import retry_failed_queue_items as _retry  # noqa: E402
        assert_true(not _pause(job_id + "9999", path=catalog_root), "pause non existent job should fail")
        assert_true(not _resume(job_id + "9999", path=catalog_root), "resume non existent job should fail")
        running_job_id = create_download_job(
            systems[0]["system_id"],
            [enriched],
            str(tmp_path / "downloads2"),
            path=catalog_root,
        )
        assert_true(_pause(running_job_id, path=catalog_root), "pause running job should succeed")
        assert_true(_resume(running_job_id, path=catalog_root), "resume paused job should succeed")
        assert_true(_cancel(running_job_id, path=catalog_root), "cancel running job should succeed")
        queued = list_download_queue_items({"job_id": running_job_id}, path=catalog_root)
        assert_true(all(item["status"] == "cancelled" for item in queued), "cancel must cascade to queue items")
        retried_count = _retry(running_job_id, path=catalog_root)
        assert_true(retried_count == 1, f"retry must reset 1 item, got {retried_count}")
        jobs_after = list_download_jobs(path=catalog_root)
        retry_job = next(j for j in jobs_after if j["job_id"] == running_job_id)
        assert_true(retry_job["status"] == "running" and retry_job["completed"] == 0, "retry must reset job to running")

        stored_candidates = record_provider_candidates(
            enriched["game_id"],
            [
                {"source": "ProviderA", "download_url": "https://example.invalid/a.zip", "download_filename": "a.zip", "confidence": 0.8},
                {"source": "ProviderC", "page_url": "https://example.invalid/c", "download_filename": "c.zip"},
            ],
            path=catalog_root,
        )
        assert_true(stored_candidates == 2, "provider candidate insert failed")
        record_provider_candidates(
            enriched["game_id"],
            [{"source": "ProviderA", "download_url": "https://example.invalid/a.zip", "download_filename": "a2.zip"}],
            status="resolved",
            path=catalog_root,
        )
        candidates = list_provider_candidates(enriched["game_id"], path=catalog_root)
        assert_true(len(candidates) == 2, "provider candidate dedup failed")
        provider_a = next(item for item in candidates if item["source"] == "ProviderA")
        assert_true(provider_a["download_filename"] == "a2.zip", "provider candidate update failed")
        assert_true(provider_a["expires_at"] > time.time(), "provider candidate TTL missing")
        stored_error = record_provider_candidates(
            enriched["game_id"],
            [{
                "source": "ProviderB",
                "page_url": "https://example.invalid/html",
                "status": "not_found",
                "error_code": "html_response",
                "http_status": 403,
                "content_type": "text/html; charset=utf-8",
                "html_snippet": "<html>Just a moment</html>",
                "provider_rank": 2,
            }],
            path=catalog_root,
        )
        assert_true(stored_error == 1, "provider candidate error insert failed")
        provider_b = next(item for item in list_provider_candidates(enriched["game_id"], path=catalog_root) if item["source"] == "ProviderB")
        assert_true(
            provider_b["error_code"] == "html_response"
            and provider_b["http_status"] == 403
            and "Just a moment" in provider_b["html_snippet"],
            "provider candidate diagnostic fields failed",
        )

        from src.core import local_database as _local_db
        from src.core import _facade as _core_facade
        original_list_provider_candidates = _local_db.list_provider_candidates
        original_search_all_sources = _core_facade.search_all_sources
        try:
            _local_db.list_provider_candidates = lambda _game_id, status="all": [
                {
                    "game_id": enriched["game_id"],
                    "system_id": systems[0]["system_id"],
                    "game_name": enriched["game_name"],
                    "source": "ProviderA",
                    "type": "providera",
                    "download_url": "https://example.invalid/a2.zip",
                    "download_filename": "a2.zip",
                    "status": "resolved",
                    "expires_at": 0,
                }
            ]
            found, unavailable, cache_hit = resolve_game_sources_with_cache(
                enriched,
                [{"name": "ProviderA", "type": "providera", "enabled": True}],
                session=None,
                system_name=systems[0]["system_name"],
                dat_profile=None,
                cache={"entries": {}},
            )
            assert_true(cache_hit and not unavailable and found[0]["download_filename"] == "a2.zip", "provider candidate reuse failed")
            _local_db.list_provider_candidates = lambda _game_id, status="all": [
                {
                    "game_id": enriched["game_id"],
                    "system_id": systems[0]["system_id"],
                    "game_name": enriched["game_name"],
                    "source": "ProviderExpired",
                    "type": "expired",
                    "download_url": "https://example.invalid/expired.zip",
                    "download_filename": "expired.zip",
                    "status": "resolved",
                    "expires_at": time.time() - 1,
                }
            ]
            _core_facade.search_all_sources = lambda *_args, **_kwargs: ([], [])
            found, unavailable, cache_hit = resolve_game_sources_with_cache(
                enriched,
                [{"name": "ProviderExpired", "type": "expired", "enabled": True}],
                session=None,
                system_name=systems[0]["system_name"],
                dat_profile=None,
                cache={"entries": {}},
            )
            assert_true(not cache_hit and not found, "expired provider candidate must not be reused")
        finally:
            _local_db.list_provider_candidates = original_list_provider_candidates
            _core_facade.search_all_sources = original_search_all_sources

        mapping_root = tmp_path / "mapping-dat"
        mapping_root.mkdir()
        (mapping_root / "Nintendo - Game Boy.dat").write_text(
            """<?xml version="1.0"?>
<datafile>
  <header><name>Nintendo - Game Boy</name></header>
  <game name="Mapping Check"><rom name="Mapping Check.gb" size="4" /></game>
</datafile>
""",
            encoding="utf-8",
        )
        mapping_status = build_mapping_status(mapping_root, provider_types=["lolroms", "vimm"])
        assert_true(mapping_status["dat_files"] == 1 and mapping_status["unique_systems"] == 1, "mapping status counts failed")
        assert_true(mapping_status["providers"]["lolroms"]["covered"] == 1, "mapping status lolroms coverage failed")
        mapping_json = tmp_path / "mapping.json"
        mapping_csv = tmp_path / "mapping.csv"
        export_mapping_status(mapping_status, mapping_json)
        export_mapping_status(mapping_status, mapping_csv)
        assert_true(mapping_json.exists() and '"dat_files": 1' in mapping_json.read_text(encoding="utf-8"), "mapping JSON export failed")
        assert_true(mapping_csv.exists() and "provider,system_name,status,mapping" in mapping_csv.read_text(encoding="utf-8"), "mapping CSV export failed")

        def fake_probe_resolver(game, _sources, _session, _system_name, _dat_profile, cache=None):
            return [
                {
                    **game,
                    "source": "ProviderProbe",
                    "type": "probe",
                    "download_url": "https://example.invalid/probe.zip",
                    "download_filename": "probe.zip",
                }
            ], [], False

        probe_result = probe_catalog_providers(
            "Nintendo - Test System",
            limit=1,
            sources=[{"name": "ProviderProbe", "type": "probe", "enabled": True}],
            session=None,
            catalog_dir=catalog_root,
            resolver=fake_probe_resolver,
        )
        assert_true(
            probe_result["resolved"] == 1 and probe_result["stored"] == 1,
            "provider probe failed",
        )

        history_file = tmp_path / "history.sqlite"
        record_download_history(
            {
                "game_name": "Alpha Game (USA)",
                "system_name": systems[0]["system_name"],
                "system_id": systems[0]["system_id"],
                "provider": "ProviderA",
                "status": "completed",
                "size": 4,
            },
            path=history_file,
        )
        history = list_download_history({"query": "alpha"}, path=history_file)
        assert_true(len(history) == 1 and history[0]["status"] == "completed", "download history failed")
        metrics = list_provider_metrics(path=history_file)
        assert_true(
            metrics["ProviderA"]["attempts"] == 1
            and metrics["ProviderA"]["downloaded"] == 1
            and metrics["ProviderA"]["bytes"] == 4,
            "provider metrics success failed",
        )
        assert_true(classify_error("failed", "Blocage Cloudflare 403") == "cloudflare_challenge", "cloudflare error classification failed")
        assert_true(error_is_retryable("http_5xx"), "retryable error classification failed")
        record_download_history(
            {
                "game_name": "Beta Game (Europe)",
                "system_name": systems[0]["system_name"],
                "system_id": systems[0]["system_id"],
                "provider": "LoLROMs",
                "status": "failed",
                "error": "Blocage Cloudflare 403",
            },
            path=history_file,
        )
        failed_history = list_download_history({"query": "beta", "status": "failed"}, path=history_file)
        assert_true(
            len(failed_history) == 1 and failed_history[0]["error_code"] == "cloudflare_challenge" and failed_history[0]["retryable"],
            "download history error code failed",
        )
        metrics = list_provider_metrics(path=history_file)
        assert_true(
            metrics["LoLROMs"]["attempts"] == 1 and metrics["LoLROMs"]["failed"] == 1,
            "provider metrics failure failed",
        )
        record_download_history(
            {
                "game_name": "Gamma Game",
                "system_id": systems[0]["system_id"],
                "provider": "ProviderB",
                "status": "failed",
                "error_code": "html_response",
                "error": "Reponse HTML inattendue",
                "http_status": 403,
                "content_type": "text/html",
                "html_snippet": "<html>challenge</html>",
                "provider_rank": 2,
            },
            path=catalog_root,
        )
        record_download_history(
            {
                "game_name": "Delta Game",
                "system_id": systems[0]["system_id"],
                "provider": "ProviderC",
                "status": "failed",
                "error_code": "checksum_mismatch",
                "error": "MD5 KO",
            },
            path=catalog_root,
        )
        health = build_source_health_summary(
            [
                {"name": "ProviderA", "type": "providera", "enabled": True},
                {"name": "ProviderB", "type": "providerb", "enabled": True},
                {"name": "ProviderC", "type": "providerc", "enabled": True},
            ],
            path=catalog_root,
        )
        health_by_name = {row["provider"]: row for row in health}
        assert_true(health_by_name["ProviderA"]["active_candidates"] >= 1, "source health candidates failed")
        assert_true(
            health_by_name["ProviderB"]["html_count"] == 1
            and health_by_name["ProviderB"]["last_error_code"] == "html_response",
            "source health HTML diagnostics failed",
        )
        assert_true(health_by_name["ProviderC"]["hash_mismatch_count"] == 1, "source health hash diagnostics failed")

        from src.core import download_orchestrator as orchestrator

        invalid_dir = tmp_path / "invalid-download"
        invalid_dir.mkdir()
        original_download_file = orchestrator.download_file
        try:
            def fake_download_file(_url, dest_path, *_args, **_kwargs):
                Path(dest_path).write_bytes(b"bad")
                return True

            orchestrator.download_file = fake_download_file
            try:
                orchestrator.attempt_download_from_resolved_provider(
                    {
                        "source": "database",
                        "download_url": "https://example.invalid/alpha.bin",
                        "download_filename": "alpha.bin",
                        "game_name": "Alpha Game (USA)",
                        "roms": [{"md5": "0123456789abcdef0123456789abcdef", "size": "4"}],
                    },
                    str(invalid_dir),
                    [],
                    session=None,
                )
                raise SystemExit("invalid checksum should fail")
            except ChecksumMismatchError:
                pass
            assert_true(not (invalid_dir / "alpha.bin").exists(), "invalid MD5 file should be deleted")
        finally:
            orchestrator.download_file = original_download_file

        fallback_dir = tmp_path / "fallback-download"
        fallback_dir.mkdir()
        valid_path = fallback_dir / "alpha-good.bin"
        original_attempt_download = orchestrator.attempt_download_from_resolved_provider
        try:
            calls = []

            def fake_attempt_download(game_info, *_args, **_kwargs):
                calls.append(game_info["source"])
                if game_info["source"] == "ProviderA":
                    raise ChecksumMismatchError("MD5 DAT KO")
                valid_path.write_bytes(b"good")
                return True, str(valid_path)

            orchestrator.attempt_download_from_resolved_provider = fake_attempt_download
            status, result = orchestrator.download_with_provider_retries(
                {
                    "source": "ProviderA",
                    "download_filename": "alpha-bad.bin",
                    "game_name": "Alpha Game (USA)",
                    "provider_candidates": [
                        {
                            "source": "ProviderB",
                            "download_filename": "alpha-good.bin",
                            "game_name": "Alpha Game (USA)",
                        }
                    ],
                },
                [],
                session=None,
                system_name="Nintendo - Test System",
                dat_profile=None,
                output_folder=str(fallback_dir),
            )
            assert_true(status == "downloaded" and result["source"] == "ProviderB", "provider fallback failed")
            assert_true(calls == ["ProviderA", "ProviderB"], "provider fallback order failed")
        finally:
            orchestrator.attempt_download_from_resolved_provider = original_attempt_download

    fast_score = compute_provider_score({"attempts": 4, "downloaded": 4, "failed": 0, "seconds": 4.0, "average_speed": 4 * 1024 * 1024})
    slow_score = compute_provider_score({"attempts": 4, "downloaded": 2, "failed": 2, "seconds": 80.0, "average_speed": 128 * 1024})
    assert_true(fast_score > slow_score, "provider dynamic score failed")

    # ROM_DATABASE stale-binding guard: verify module-level attribute access works
    from src.core import rom_database as _rd_mod
    _rd_mod.ROM_DATABASE
    assert_true(
        not isinstance(_rd_mod.ROM_DATABASE, dict) or 'config_urls' in _rd_mod.ROM_DATABASE,
        "ROM_DATABASE should be None or a dict with config_urls after module load",
    )

    from src.network.circuits import SourceCircuitBreaker
    cb = SourceCircuitBreaker(
        failure_threshold=3,
        recovery_timeout=0.1,
        typed_thresholds={"cloudflare_challenge": 2, "http_429": 3, "quota_exceeded": 2},
        typed_recoveries={"cloudflare_challenge": 0.1, "http_429": 0.1, "quota_exceeded": 0.1},
    )
    cb.is_open("TestSource")
    assert_true(not cb.is_open("TestSource"), "fresh circuit must be closed (global)")
    assert_true(not cb.is_open("TestSource", error_type="cloudflare_challenge"), "fresh circuit must be closed (typed)")
    cb.record_failure("TestSource", error_type="cloudflare_challenge")
    cb.record_failure("TestSource", error_type="cloudflare_challenge")
    assert_true(cb.is_open("TestSource", error_type="cloudflare_challenge"), "2 cloudflare failures must open typed circuit")
    assert_true(not cb.is_open("TestSource"), "global should not trip at 2 typed")
    time.sleep(0.15)
    assert_true(not cb.is_open("TestSource", error_type="cloudflare_challenge"), "typed circuit must recover after 0.1s")
    assert_true(not cb.is_open("TestSource"), "global must also recover")
    cb.record_failure("TestSource", error_type="http_429")
    cb.record_failure("TestSource", error_type="http_429")
    cb.record_failure("TestSource", error_type="http_429")
    assert_true(cb.is_open("TestSource", error_type="http_429"), "3 HTTP 429 failures must open typed circuit")
    assert_true(not cb.is_open("TestSource", error_type="cloudflare_challenge"), "cloudflare circuit must remain unaffected")
    cb.record_success("TestSource")
    assert_true(not cb.is_open("TestSource", error_type="http_429"), "success must reset typed circuit")
    assert_true(not cb.is_open("TestSource", error_type="cloudflare_challenge"), "success must reset all typed circuits")
    assert_true(not cb.is_open("TestSource"), "success must reset global circuit")
    status = cb.status()
    assert_true("TestSource" not in status or status["TestSource"]["failures"] == 0, "status must reflect reset")
    cb.record_failure("TestSource", error_type="quota_exceeded")
    cb.record_failure("TestSource", error_type="quota_exceeded")
    assert_true(cb.is_open("TestSource", error_type="quota_exceeded"), "2 quota failures must open quota circuit")
    time.sleep(0.15)
    assert_true(not cb.is_open("TestSource", error_type="quota_exceeded"), "quota circuit must recover after 0.1s")

    from src.core.download_orchestrator import adapt_sources_for_circuit_state
    cb2 = SourceCircuitBreaker(
        failure_threshold=10,
        recovery_timeout=300,
        typed_thresholds={"cloudflare_challenge": 2, "quota_exceeded": 2},
        typed_recoveries={"cloudflare_challenge": 0.1, "quota_exceeded": 0.1},
    )
    sources = [
        {'name': 'LoLROMs', 'type': 'lolroms', 'delay_seconds': 3, 'enabled': True},
        {'name': 'Vimm\'s Lair', 'type': 'vimm', 'enabled': True},
        {'name': 'PremiumDB', 'type': 'premium', 'enabled': True},
    ]
    adapted_none, par_none = adapt_sources_for_circuit_state(sources, None, 4)
    assert_true(par_none == 4, "no circuit breaker keeps original parallel")
    cb2.record_failure("LoLROMs", error_type="cloudflare_challenge")
    cb2.record_failure("LoLROMs", error_type="cloudflare_challenge")
    assert_true(cb2.is_open("LoLROMs", error_type="cloudflare_challenge"), "cloudflare circuit must open")
    adapted, par = adapt_sources_for_circuit_state(sources, cb2, 4)
    assert_true(par == 1, f"parallel must be forced to 1 when cloudflare circuit open (got {par})")
    lolroms = next(s for s in adapted if s['name'] == 'LoLROMs')
    assert_true(lolroms['delay_seconds'] >= 6, f"delay must double: got {lolroms['delay_seconds']}")
    assert_true(all(s['enabled'] for s in adapted), "only quota_exceeded should disable sources")
    del cb2
    cb3 = SourceCircuitBreaker(
        failure_threshold=10,
        recovery_timeout=300,
        typed_thresholds={"http_429": 2},
        typed_recoveries={"http_429": 0.1},
    )
    sources_http = [{'name': 'LoLROMs', 'type': 'lolroms', 'delay_seconds': 3, 'enabled': True}]
    cb3.record_failure("LoLROMs", error_type="http_429")
    cb3.record_failure("LoLROMs", error_type="http_429")
    assert_true(cb3.is_open("LoLROMs", error_type="http_429"), "http_429 circuit must open")
    adapted_429, par_429 = adapt_sources_for_circuit_state(sources_http, cb3, 4)
    lolroms_429 = next(s for s in adapted_429 if s['name'] == 'LoLROMs')
    assert_true(lolroms_429['delay_seconds'] >= 6, f"http_429 must double delay: got {lolroms_429['delay_seconds']}")
    assert_true(par_429 == 4, "http_429 does not force parallel=1")
    del cb3
    cb4 = SourceCircuitBreaker(
        failure_threshold=10,
        recovery_timeout=300,
        typed_thresholds={"quota_exceeded": 2},
        typed_recoveries={"quota_exceeded": 0.1},
    )
    cb4.record_failure("LoLROMs", error_type="quota_exceeded")
    cb4.record_failure("LoLROMs", error_type="quota_exceeded")
    assert_true(cb4.is_open("LoLROMs", error_type="quota_exceeded"), "quota circuit must open")
    adapted_quota, _ = adapt_sources_for_circuit_state(sources, cb4, 2)
    lolroms_q = next((s for s in adapted_quota if s['name'] == 'LoLROMs'), None)
    assert_true(lolroms_q is not None and not lolroms_q['enabled'], "quota_exceeded circuit must disable source")
    vimm_q = next((s for s in adapted_quota if s['name'] == 'Vimm\'s Lair'), None)
    assert_true(vimm_q is None or vimm_q.get('enabled', True), "quota should not affect premium")
    del cb4
    del adapt_sources_for_circuit_state

    with tempfile.TemporaryDirectory() as _tmp_dir:
        _tmp_path = Path(_tmp_dir)
        _dat_root = _tmp_path / "dat"
        _catalog_root = _tmp_path / "db"
        _section = _dat_root / "No-Intro"
        _section.mkdir(parents=True)
        (_section / "Nintendo - Test System.dat").write_text(
            """<?xml version="1.0"?>
<datafile>
  <header><name>Nintendo - Test System</name><url>https://no-intro.org</url></header>
  <game name="Alpha Game (USA)">
    <rom name="Alpha Game (USA).bin" size="4" crc="1a2b3c4d" md5="0123456789abcdef0123456789abcdef" sha1="0123456789abcdef0123456789abcdef01234567" />
  </game>
</datafile>
""",
            encoding="utf-8",
        )
        build_catalog_index(_dat_root, force=True, catalog_dir=_catalog_root)

        from src.core.provider_mapper import map_all_providers, format_map_all_report
        import src.core.provider_mapper as _pm
        def _fake_resolver(game, sources, session, system_name, dat_profile, cache=None):
            result = [
                {**game, "source": "LoLROMs", "type": "lolroms", "download_url": "https://fake.invalid/a.zip", "download_filename": game.get("primary_rom", "a.zip")}
            ]
            return result, [], False

        _orig_mapping = _pm.resolve_system_mapping
        _pm.resolve_system_mapping = lambda sn, p="lolroms": "mapped-slug"
        try:
            report = map_all_providers(
                samples_per_system=1,
                providers_filter=["lolroms"],
                log_func=lambda _: None,
                resolver=_fake_resolver,
                max_systems=3,
                catalog_dir=_catalog_root,
            )
            assert_true(report["systems_processed"] >= 1, "mapper must process at least 1 system")
            assert_true(report["systems_with_candidates"] >= 1, f"mapper must find providers: {report}")
            assert_true(report["total_candidates"] >= 1, "mapper must generate candidates")
            formatted = format_map_all_report(report)
            assert_true("Avec au moins 1 provider" in formatted, "mapper report must show provider count")
        finally:
            _pm.resolve_system_mapping = _orig_mapping

    from src.core.local_database import (
        init_local_database,
        open_local_database,
    )
    # ── Queue persistante ──
    with tempfile.TemporaryDirectory() as job_tmp_dir:
        job_db = Path(job_tmp_dir) / ".rom_downloader.sqlite"
        init_local_database(path=job_db)
        with open_local_database(job_db) as conn:
            conn.execute(
                "INSERT INTO systems (system_id, dat_path, dat_label, dat_section, system_name, family, family_label, updated_at) "
                "VALUES ('system-test', '/fake/test.dat', 'Test', 'No-Intro', 'Test System', 'Test', 'Test', 0)"
            )
            conn.execute(
                "INSERT INTO games (game_id, system_id, game_name, primary_rom, updated_at) "
                "VALUES ('game-a', 'system-test', 'Alpha Game', 'alpha.bin', 0)"
            )
            conn.execute(
                "INSERT INTO games (game_id, system_id, game_name, primary_rom, updated_at) "
                "VALUES ('game-c', 'system-test', 'Gamma Game', 'gamma.bin', 0)"
            )
            conn.execute(
                "INSERT INTO games (game_id, system_id, game_name, primary_rom, updated_at) "
                "VALUES ('game-b', 'system-test', 'Beta Game', 'beta.bin', 0)"
            )
            conn.execute(
                "INSERT INTO games (game_id, system_id, game_name, primary_rom, updated_at) "
                "VALUES ('game-d', 'system-test', 'Delta Game', 'delta.bin', 0)"
            )
        job_id = create_download_job(
            "system-test",
            [{"game_id": "game-a", "system_id": "system-test", "game_name": "Alpha Game"}],
            str(job_tmp_dir),
            path=job_db,
        )
        assert_true(len(job_id) == 32, "create_download_job must return uuid hex")
        jobs = list_download_jobs(limit=5, path=job_db)
        assert_true(any(j["job_id"] == job_id for j in jobs), "job must appear in list")

        assert_true(get_job_status(job_id, path=job_db) == "running", "new job must be running")
        assert_true(pause_download_job(job_id, path=job_db), "pause must succeed")
        assert_true(get_job_status(job_id, path=job_db) == "paused", "paused job status mismatch")
        assert_true(resume_download_job(job_id, path=job_db), "resume must succeed")
        assert_true(get_job_status(job_id, path=job_db) == "running", "resumed job must be running")

        config = get_job_config(job_id, path=job_db)
        assert_true(config["output_folder"] == str(job_tmp_dir), "job config output_folder mismatch")

        update_download_queue_item(job_id, game_id="game-a", status="running", locked_by="orchestrator", path=job_db)
        assert_true(cancel_download_job(job_id, path=job_db), "cancel must succeed")
        assert_true(get_job_status(job_id, path=job_db) == "cancelled", "cancelled job status mismatch")

        cancel_job_id = create_download_job(
            "system-test",
            [
                {"game_id": "game-b", "system_id": "system-test", "game_name": "Beta Game"},
                {"game_id": "game-c", "system_id": "system-test", "game_name": "Gamma Game"},
            ],
            str(job_tmp_dir),
            path=job_db,
        )
        update_download_queue_item(cancel_job_id, game_id="game-b", status="completed", path=job_db)
        update_download_queue_item(cancel_job_id, game_id="game-c", status="failed", path=job_db)
        retried = retry_failed_queue_items(cancel_job_id, path=job_db)
        assert_true(retried == 1, "retry must reset exactly 1 failed item")

        pending = get_pending_queue_items_for_job(cancel_job_id, include_failed=True, path=job_db)
        assert_true(len(pending) == 1, "pending items count after retry")
        assert_true(pending[0]["game_id"] == "game-c", "retried item must be game-c")

        save_job_progress(cancel_job_id, 42, path=job_db)
        config2 = get_job_config(cancel_job_id, path=job_db)
        assert_true(config2.get("settings", {}).get("last_processed_index") == 42, "job progress not saved")

        lock_job_id = create_download_job(
            "system-test",
            [{"game_id": "game-d", "system_id": "system-test", "game_name": "Delta Game"}],
            str(job_tmp_dir),
            path=job_db,
        )
        update_download_queue_item(lock_job_id, game_id="game-d", status="running", locked_by="orchestrator", path=job_db)
        stale = cleanup_stale_locks(timeout_seconds=-1, path=job_db)
        assert_true(stale["unlocked_items"] >= 1, "cleanup must unlock stale locks")
        assert_true(stale["unlocked_items"] >= 1, "cleanup must unlock stale locks")

        reset_local_database(path=job_db)
        assert_true(get_job_status(job_id, path=job_db) == "", "db reset must clear jobs")

    # ── recover_orphaned_parts ──
    with tempfile.TemporaryDirectory() as part_tmp_dir:
        part_dir = Path(part_tmp_dir)
        orphan = part_dir / "game_abc.part"
        orphan.write_text("dummy data", encoding="utf-8")
        assert_true(orphan.exists(), "part file must exist")
        removed = recover_orphaned_parts(str(part_tmp_dir))
        assert_true(str(orphan) in removed, "orphan part must be removed")
        assert_true(not orphan.exists(), "part file must be deleted")

    # ── Scoring per-systeme ──
    per_system_metrics: dict = {}
    record_provider_attempt(per_system_metrics, "LoLROMs", "downloaded", 5.0, system_name="Nintendo - Game Boy Advance")
    record_provider_attempt(per_system_metrics, "LoLROMs", "failed", 2.0, system_name="Nintendo - Game Boy Advance")
    record_provider_attempt(per_system_metrics, "LoLROMs", "downloaded", 3.0, system_name="Sony - PlayStation")
    assert_true("LoLROMs::Nintendo - Game Boy Advance" in per_system_metrics, "composite key for GBA must exist")
    assert_true("LoLROMs::Sony - PlayStation" in per_system_metrics, "composite key for PS1 must exist")
    assert_true("LoLROMs" in per_system_metrics, "global key must be accumulated")
    gba_metric = per_system_metrics["LoLROMs::Nintendo - Game Boy Advance"]
    assert_true(gba_metric["downloaded"] == 1 and gba_metric["failed"] == 1, "GBA per-system counts wrong")
    global_metric = per_system_metrics["LoLROMs"]
    assert_true(global_metric["attempts"] == 3, f"global attempts must be 3, got {global_metric['attempts']}")

    empty_sources = [{"name": "LoLROMs", "order": 3, "priority": 50}]
    ordered = prioritize_sources(empty_sources, per_system_metrics, system_name="Nintendo - Game Boy Advance")
    assert_true(len(ordered) == 1, "prioritize must preserve source count")
    neutral_ordered = prioritize_sources(empty_sources, {}, system_name="Nintendo - Game Boy Advance")
    assert_true(len(neutral_ordered) == 1, "empty metrics must not crash")

    from src.pipeline import aggregate_provider_metrics
    sys_items = [{"provider_attempts": [
        {"source": "Vimm", "status": "downloaded", "duration_seconds": 2.0, "bytes": 100}
    ]}]
    sys_metrics = aggregate_provider_metrics(sys_items, system_name="SNES")
    assert_true("Vimm::SNES" in sys_metrics, "composite key in aggregate_provider_metrics missing")
    assert_true(sys_metrics["Vimm::SNES"]["downloaded"] == 1, "aggregate count wrong")

    no_sys_metrics = aggregate_provider_metrics(sys_items)
    assert_true("Vimm" in no_sys_metrics, "global only in aggregate_provider_metrics missing")

    print("core helper checks ok")


if __name__ == "__main__":
    main()
