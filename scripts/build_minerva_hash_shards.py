#!/usr/bin/env python3
"""
Build rom_db_shards/shard_*.zip from the official Minerva hash database.

The script parses all DAT files in the configured No-Intro and Redump folders,
collects DAT MD5 values, scans the official Minerva SQLite database once, and
writes 16 zipped SQLite shards keyed by the first MD5 hex character.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urljoin
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "minerva hashes officiel.db"
DEFAULT_DAT_ROOTS = (
    ROOT / "dat.exemple" / "no-intro",
    ROOT / "dat.exemple" / "redump",
)
DEFAULT_OUTPUT = ROOT / "rom_db_shards"
SHARD_CHARS = "0123456789abcdef"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def normalize_md5(value: str) -> str:
    value = (value or "").strip().lower()
    if len(value) == 32 and all(ch in "0123456789abcdef" for ch in value):
        return value
    return ""


def iter_dat_files(dat_roots: list[Path]) -> list[Path]:
    files = []
    for root in dat_roots:
        if root.exists():
            files.extend(path for path in root.rglob("*.dat") if path.is_file())
            files.extend(path for path in root.rglob("*.xml") if path.is_file())
    return sorted(set(files), key=lambda path: str(path).lower())


def parse_dat_md5s(dat_path: Path) -> set[str]:
    md5s: set[str] = set()
    try:
        for _event, elem in ET.iterparse(dat_path, events=("end",)):
            if local_name(elem.tag) == "rom":
                md5 = normalize_md5(elem.attrib.get("md5", ""))
                if md5:
                    md5s.add(md5)
            elem.clear()
    except ET.ParseError as exc:
        print(f"  [DAT] parse error {dat_path}: {exc}")
    return md5s


def collect_dat_md5s(dat_roots: list[Path]) -> tuple[set[str], list[dict]]:
    wanted: set[str] = set()
    dat_stats = []
    dat_files = iter_dat_files(dat_roots)
    print(f"DAT files: {len(dat_files)}")

    for index, dat_path in enumerate(dat_files, 1):
        md5s = parse_dat_md5s(dat_path)
        wanted.update(md5s)
        family = "redump" if "redump" in str(dat_path).lower() else "no-intro"
        dat_stats.append({
            "path": str(dat_path),
            "family": family,
            "unique_md5s": len(md5s),
            "matched_md5s": 0,
        })
        if index % 25 == 0 or index == len(dat_files):
            print(f"  parsed {index}/{len(dat_files)} DATs, unique MD5s: {len(wanted):,}")

    return wanted, dat_stats


def minerva_torrent_url(torrent_path: str) -> str:
    torrent_path = (torrent_path or "").replace("\\", "/").lstrip("./")
    if not torrent_path:
        return ""
    if torrent_path.startswith(("http://", "https://")):
        return torrent_path
    return urljoin("https://minerva-archive.org/assets/", quote(torrent_path, safe="/"))


def scan_minerva_db(db_path: Path, wanted_md5s: set[str]) -> dict[str, list[dict]]:
    matched: dict[str, list[dict]] = defaultdict(list)
    seen_entries: set[tuple[str, str, str]] = set()
    if not wanted_md5s:
        return matched

    print(f"Scanning official Minerva DB: {db_path}")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = con.cursor()
    query = """
        SELECT md5, file_name, full_path, size, crc32, sha1, torrents
        FROM files
        WHERE md5 IS NOT NULL AND md5 != ''
    """
    scanned = 0
    started = time.time()
    try:
        for md5, file_name, full_path, size, crc32, sha1, torrents in cur.execute(query):
            scanned += 1
            md5 = normalize_md5(md5)
            if md5 and md5 in wanted_md5s:
                torrent_path = (torrents or "").replace("\\", "/")
                dedupe_key = (md5, full_path or "", torrent_path)
                if dedupe_key not in seen_entries:
                    seen_entries.add(dedupe_key)
                    matched[md5].append({
                        "host": "minerva-torrent",
                        "file_name": file_name or Path(full_path or md5).name,
                        "full_path": (full_path or file_name or md5).replace("\\", "/"),
                        "size": size,
                        "crc32": (crc32 or "").lower(),
                        "sha1": (sha1 or "").lower(),
                        "torrent_path": torrent_path,
                        "torrent_url": minerva_torrent_url(torrent_path),
                    })
            if scanned % 250000 == 0:
                elapsed = time.time() - started
                print(f"  scanned {scanned:,} rows, matched {len(matched):,} MD5s ({elapsed:.1f}s)")
    finally:
        con.close()

    print(f"  scanned {scanned:,} rows total")
    print(f"  matched {len(matched):,}/{len(wanted_md5s):,} DAT MD5s")
    return matched


def write_shard_db(db_path: Path, shard_entries: dict[str, list[dict]]) -> None:
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute("PRAGMA journal_mode=OFF")
        cur.execute("PRAGMA synchronous=OFF")
        cur.execute("CREATE TABLE roms (md5 TEXT PRIMARY KEY, entries TEXT NOT NULL, urls TEXT NOT NULL)")
        for md5 in sorted(shard_entries):
            entries = shard_entries[md5]
            urls = []
            for entry in entries:
                url = entry.get("torrent_url") or minerva_torrent_url(entry.get("torrent_path", ""))
                if url and url not in urls:
                    urls.append(url)
            cur.execute(
                "INSERT INTO roms (md5, entries, urls) VALUES (?, ?, ?)",
                (
                    md5,
                    json.dumps(entries, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(urls, ensure_ascii=False, separators=(",", ":")),
                ),
            )
        con.commit()
    finally:
        con.close()


def backup_existing_shards(output_dir: Path) -> Path | None:
    existing = sorted(output_dir.glob("shard_*.zip")) if output_dir.exists() else []
    if not existing:
        return None
    backup_dir = output_dir.parent / f"{output_dir.name}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    for path in existing:
        shutil.move(str(path), backup_dir / path.name)
    report = output_dir / "build_report.json"
    if report.exists():
        shutil.copy2(report, backup_dir / report.name)
    print(f"Existing shards moved to: {backup_dir}")
    return backup_dir


def write_shards(output_dir: Path, matched_entries: dict[str, list[dict]], report: dict, backup: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if backup:
        backup_existing_shards(output_dir)

    by_shard: dict[str, dict[str, list[dict]]] = {char: {} for char in SHARD_CHARS}
    for md5, entries in matched_entries.items():
        by_shard[md5[0]][md5] = entries

    with tempfile.TemporaryDirectory(prefix="minerva-shards-") as temp_name:
        temp_dir = Path(temp_name)
        for shard_char in SHARD_CHARS:
            db_path = temp_dir / f"shard_{shard_char}.db"
            zip_path = temp_dir / f"shard_{shard_char}.zip"
            write_shard_db(db_path, by_shard[shard_char])
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
                zf.write(db_path, arcname=db_path.name)
            os.replace(zip_path, output_dir / zip_path.name)
            print(f"  wrote shard_{shard_char}.zip: {len(by_shard[shard_char]):,} MD5s")

    report_path = output_dir / "build_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Report: {report_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build zipped Minerva MD5 shards from DAT files.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Official Minerva hashes SQLite DB")
    parser.add_argument("--dat-root", type=Path, action="append", default=None, help="DAT root folder, repeatable")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output rom_db_shards folder")
    parser.add_argument("--no-backup", action="store_true", help="Do not move existing shard_*.zip files to a backup folder")
    args = parser.parse_args()

    dat_roots = args.dat_root if args.dat_root else list(DEFAULT_DAT_ROOTS)
    if not args.db.exists():
        raise SystemExit(f"Minerva DB not found: {args.db}")

    started = time.time()
    wanted_md5s, dat_stats = collect_dat_md5s(dat_roots)
    matched_entries = scan_minerva_db(args.db, wanted_md5s)
    matched_md5s = set(matched_entries)

    for stat in dat_stats:
        md5s = parse_dat_md5s(Path(stat["path"]))
        stat["matched_md5s"] = len(md5s & matched_md5s)
        stat["match_percent"] = round((stat["matched_md5s"] / stat["unique_md5s"] * 100), 2) if stat["unique_md5s"] else 0

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_db": str(args.db),
        "dat_roots": [str(path) for path in dat_roots],
        "dat_files": len(dat_stats),
        "dat_unique_md5s": len(wanted_md5s),
        "matched_unique_md5s": len(matched_entries),
        "matched_entries": sum(len(entries) for entries in matched_entries.values()),
        "elapsed_seconds": round(time.time() - started, 2),
        "dat_stats": dat_stats,
    }

    write_shards(args.output, matched_entries, report, backup=not args.no_backup)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
