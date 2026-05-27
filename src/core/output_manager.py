"""Organisation de sortie et rebuilder ToSort leger."""

from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path

from .dat_parser import normalize_checksum
from .frontend_mapping import build_frontend_output_path
from .signatures import hash_file_signatures, iter_archive_member_signatures
from .torrentzip import create_torrentzip_single_file


def _safe_name(name: str) -> str:
    return Path(name or "rom.bin").name


def _target_path(item: dict, output_folder: str, system_name: str = "",
                 output_mode: str = "flat", frontend: str | None = None) -> Path:
    filename = _safe_name(item.get("download_filename") or item.get("primary_rom") or item.get("game_name"))
    root = Path(output_folder)
    if frontend:
        return Path(build_frontend_output_path(system_name, filename, output_folder, frontend))
    if output_mode == "verified":
        return root / "Verified" / filename
    if output_mode == "tosort":
        return root / "ToSort" / filename
    if output_mode == "dat-structure":
        primary = item.get("primary_rom") or filename
        return root / Path(primary)
    return root / filename


def _zip_file(source: Path, target_zip: Path, internal_name: str, torrentzip: bool = False) -> Path:
    target_zip.parent.mkdir(parents=True, exist_ok=True)
    if torrentzip:
        create_torrentzip_single_file(source, internal_name, target_zip)
        return target_zip
    with zipfile.ZipFile(target_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(source, arcname=internal_name)
    return target_zip


def organize_downloaded_items(items: list[dict], output_folder: str, system_name: str = "",
                              output_mode: str = "flat", archive_mode: str = "none",
                              frontend: str | None = None, dry_run: bool = False) -> dict:
    """Deplace/repacke les fichiers valides selon le profil de sortie."""
    summary = {"moved": 0, "zipped": 0, "torrentzipped": 0, "skipped": 0, "failed": 0, "items": []}
    if output_mode == "flat" and not frontend and archive_mode == "none":
        return summary
    for item in items or []:
        source = Path(item.get("downloaded_path") or item.get("file_path") or "")
        if not source.exists() or not source.is_file():
            summary["skipped"] += 1
            continue
        target = _target_path(item, output_folder, system_name, output_mode, frontend)
        if archive_mode in {"zip", "torrentzip"} and source.suffix.lower() != ".zip":
            target = target.with_suffix(".zip")
        try:
            if dry_run:
                final_path = target
            elif archive_mode in {"zip", "torrentzip"} and source.suffix.lower() != ".zip":
                final_path = _zip_file(source, target, _safe_name(item.get("primary_rom") or source.name), archive_mode == "torrentzip")
                source.unlink(missing_ok=True)
                summary["torrentzipped" if archive_mode == "torrentzip" else "zipped"] += 1
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.resolve() != target.resolve():
                    shutil.move(str(source), str(target))
                    summary["moved"] += 1
                final_path = target
            item["organized_path"] = str(final_path)
            item["downloaded_path"] = str(final_path)
            summary["items"].append({"game_name": item.get("game_name", ""), "path": str(final_path)})
        except Exception as exc:
            summary["failed"] += 1
            summary["items"].append({"game_name": item.get("game_name", ""), "path": str(source), "error": str(exc)})
    return summary


def _rom_signature_refs(dat_games: dict) -> tuple[dict, dict[int, list[dict]]]:
    by_hash = {"md5": {}, "crc": {}, "sha1": {}}
    by_size: dict[int, list[dict]] = {}
    for game in dat_games.values():
        for rom in game.get("roms", []):
            ref = {"game": game, "rom": rom}
            for kind in by_hash:
                value = normalize_checksum(rom.get(kind, ""), kind)
                if value:
                    by_hash[kind].setdefault(value, []).append(ref)
            try:
                size = int(rom.get("size") or 0)
            except (TypeError, ValueError):
                size = 0
            if size > 0:
                by_size.setdefault(size, []).append(ref)
    return by_hash, by_size


def _candidate_signatures(path: Path) -> list[dict]:
    if path.suffix.lower() in {".zip", ".7z", ".rar"}:
        return list(iter_archive_member_signatures(path))
    sig = hash_file_signatures(path)
    return [{"name": path.name, "member": "", "size": path.stat().st_size, **sig}]


def rebuild_tosort(dat_games: dict, tosort_folder: str, output_folder: str,
                   output_mode: str = "verified", archive_mode: str = "none",
                   frontend: str | None = None, system_name: str = "",
                   copy: bool = False, dry_run: bool = False) -> dict:
    """Reconstruit une sortie propre depuis ToSort avec matching hash puis taille."""
    summary = {
        "rebuilt": 0,
        "copied": 0,
        "moved": 0,
        "already_in_place": 0,
        "zipped": 0,
        "torrentzipped": 0,
        "failed": 0,
        "archive_unsupported": 0,
        "hash_mismatch": 0,
        "items": [],
    }
    source_root = Path(tosort_folder)
    if not source_root.exists():
        return summary
    by_hash, by_size = _rom_signature_refs(dat_games)
    for path in sorted(p for p in source_root.rglob("*") if p.is_file() and not p.name.endswith(".part")):
        try:
            signatures = _candidate_signatures(path)
        except Exception as exc:
            summary["archive_unsupported"] += 1
            summary["items"].append({"source": str(path), "status": "archive_unsupported", "detail": str(exc)})
            continue
        match = None
        method = ""
        for sig in signatures:
            for kind in ("md5", "sha1", "crc"):
                refs = by_hash[kind].get(normalize_checksum(sig.get(kind, ""), kind), [])
                if refs:
                    match = refs[0]
                    method = kind
                    break
            if match:
                break
        if not match:
            for sig in signatures:
                refs = by_size.get(int(sig.get("size") or 0), [])
                if len(refs) == 1:
                    match = refs[0]
                    method = "size"
                    break
        if not match:
            summary["hash_mismatch"] += 1
            summary["items"].append({"source": str(path), "status": "hash_mismatch"})
            continue

        game = match["game"]
        rom = match["rom"]
        item = {**game, "download_filename": Path(rom.get("name") or path.name).name, "primary_rom": rom.get("name") or path.name}
        target = _target_path(item, output_folder, system_name, output_mode, frontend)
        if archive_mode in {"zip", "torrentzip"} and path.suffix.lower() != ".zip":
            target = target.with_suffix(".zip")
        try:
            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                if archive_mode in {"zip", "torrentzip"} and path.suffix.lower() != ".zip":
                    _zip_file(path, target, _safe_name(rom.get("name") or path.name), archive_mode == "torrentzip")
                    if not copy:
                        path.unlink(missing_ok=True)
                    summary["torrentzipped" if archive_mode == "torrentzip" else "zipped"] += 1
                elif copy:
                    shutil.copy2(path, target)
                    summary["copied"] += 1
                else:
                    if path.resolve() != target.resolve():
                        shutil.move(str(path), str(target))
                        summary["moved"] += 1
                    else:
                        summary["already_in_place"] += 1
            summary["rebuilt"] += 1
            summary["items"].append({"source": str(path), "target": str(target), "game_name": game.get("game_name", ""), "method": method, "status": "rebuilt"})
        except Exception as exc:
            summary["failed"] += 1
            summary["items"].append({"source": str(path), "target": str(target), "status": "failed", "detail": str(exc)})
    return summary


__all__ = ["organize_downloaded_items", "rebuild_tosort"]
