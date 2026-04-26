"""Targeted runtime helper checks without network access."""

from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core import (  # noqa: E402
    cache_entry_matches_source,
    expected_game_sizes,
    listing_cache_prefixes_for_source,
    optional_positive_int,
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

    source = {"name": "EdgeEmu", "type": "edgeemu", "timeout_seconds": "45", "quota_per_run": "2"}
    assert_true(source_timeout_seconds(source) == 45, "source timeout failed")
    assert_true(source_quota_limit(source) == 2, "source quota failed")

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

    print("core helper checks ok")


if __name__ == "__main__":
    main()
