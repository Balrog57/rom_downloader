import csv
import html
import json
import os
import re
from datetime import datetime
from pathlib import Path

from ..pipeline import build_pipeline_summary


REPORT_FORMATS = {"txt", "json", "csv", "html"}


def build_report_slug(value: str) -> str:
    """Nettoie une valeur pour un nom de fichier de rapport."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())
    return cleaned.strip("._-") or "run"


def normalize_report_formats(formats=("txt",)) -> tuple[str, ...]:
    """Normalise une liste de formats de rapport."""
    if isinstance(formats, str):
        raw_formats = formats.split(",")
    else:
        raw_formats = list(formats or ["txt"])
    normalized = []
    for value in raw_formats:
        fmt = str(value or "").strip().lower().lstrip(".")
        if not fmt:
            continue
        if fmt not in REPORT_FORMATS:
            raise ValueError(f"Format de rapport inconnu: {fmt}")
        if fmt not in normalized:
            normalized.append(fmt)
    return tuple(normalized or ["txt"])


def _parse_size(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _item_size(item: dict) -> int:
    size = _parse_size(item.get("size"))
    if size:
        return size
    total = 0
    for rom_info in item.get("roms", []) or []:
        total += _parse_size(rom_info.get("size"))
    return total


def _provider_for_item(item: dict) -> str:
    attempts = item.get("provider_attempts") or []
    if attempts:
        return attempts[-1].get("source") or item.get("source") or ""
    return item.get("source") or item.get("provider") or ""


def _detail_for_item(item: dict) -> str:
    attempts = item.get("provider_attempts") or []
    detail = ""
    if attempts:
        detail = attempts[-1].get("detail") or attempts[-1].get("error") or ""
    return str(item.get("error") or item.get("detail") or detail or "")


def _report_items(summary: dict) -> list[dict]:
    """Retourne une liste plate et stable d'elements pour CSV/JSON/HTML."""
    rows = []
    seen = set()

    def add_items(status: str, items: list[dict]) -> None:
        for item in items or []:
            key = (
                status,
                item.get("game_id") or "",
                item.get("game_name") or "",
                item.get("download_url") or "",
                item.get("download_filename") or "",
            )
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "status": status,
                "system_name": summary.get("system_name", ""),
                "game_name": item.get("game_name") or item.get("name") or "",
                "provider": _provider_for_item(item),
                "download_filename": item.get("download_filename") or item.get("primary_rom") or "",
                "size": _item_size(item),
                "error_code": item.get("error_code") or "",
                "detail": _detail_for_item(item),
                "file_path": item.get("downloaded_path") or item.get("file_path") or "",
            })

    add_items("downloaded", summary.get("downloaded_items", []))
    add_items("skipped", summary.get("skipped_items", []))
    add_items("failed", summary.get("failed_items", []))
    add_items("not_found", summary.get("not_available", []))
    dry_run_status = "dry_run" if summary.get("dry_run") else "resolved"
    add_items(dry_run_status, summary.get("resolved_items", []))
    return rows


def _count(summary: dict, runtime_key: str, analysis_key: str = "") -> int:
    if runtime_key in summary:
        return _parse_size(summary.get(runtime_key))
    return _parse_size(summary.get(analysis_key)) if analysis_key else 0


def _count_validation_methods(downloaded_items: list[dict]) -> dict[str, int]:
    """Compte combien d'items valides par MD5 vs taille seulement."""
    md5_count = 0
    size_only_count = 0
    for item in downloaded_items or []:
        if item.get("md5") or any(rom.get("md5") for rom in (item.get("roms") or []) if isinstance(rom, dict)):
            md5_count += 1
        else:
            size_only_count += 1
    return {"validated_md5": md5_count, "validated_size_only": size_only_count}


def _top_sources(provider_metrics: dict[str, dict], top_n: int = 3) -> list[dict]:
    """Retourne les N sources les plus performantes triees par succes descendant."""
    scored = []
    for name, metric in provider_metrics.items():
        downloaded = metric.get("downloaded", 0)
        if downloaded > 0:
            scored.append({
                "source": name,
                "downloaded": downloaded,
                "failed": metric.get("failed", 0),
                "skipped": metric.get("skipped", 0),
                "seconds": metric.get("seconds", 0.0),
                "success_rate": downloaded / max(metric.get("attempts", 1), 1),
            })
    scored.sort(key=lambda x: (-x["downloaded"], -x["success_rate"]))
    return scored[:top_n]


def build_report_payload(summary: dict) -> dict:
    """Construit le payload stable exporte en JSON/CSV/HTML/TXT."""
    pipeline_summary = build_pipeline_summary(summary)
    total_games = _count(summary, "total_dat_games", "total_games")
    missing_before = _count(summary, "missing_before", "missing_games")
    present_before = _parse_size(summary.get("present_before"))
    if not present_before and total_games:
        present_before = max(0, total_games - missing_before)
    resolved_items = summary.get("resolved_items", []) or []
    downloaded_items = summary.get("downloaded_items", []) or []
    failed_items = summary.get("failed_items", []) or []
    skipped_items = summary.get("skipped_items", []) or []
    not_available = summary.get("not_available", []) or []
    items = _report_items(summary)
    mode = "dry-run" if summary.get("dry_run") else summary.get("mode") or "download"
    generated_at = summary.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    validation_counts = _count_validation_methods(downloaded_items)
    provider_metrics = pipeline_summary["provider_metrics"]
    return {
        "metadata": {
            "generated_at": generated_at,
            "mode": mode,
            "dat_file": summary.get("dat_file", ""),
            "system_name": summary.get("system_name", ""),
            "dat_profile": summary.get("dat_profile", ""),
            "output_folder": summary.get("output_folder") or summary.get("rom_folder", ""),
            "source_url": summary.get("source_url", ""),
        },
        "counts": {
            "total_dat_games": total_games,
            "present_before": present_before,
            "missing_before": missing_before,
            "resolved": len(resolved_items),
            "downloaded": len(downloaded_items),
            "failed": len(failed_items),
            "skipped": len(skipped_items),
            "not_available": len(not_available),
            **validation_counts,
        },
        "sizes": {
            "total_dat_size": _parse_size(summary.get("total_size") or summary.get("total_dat_size")),
            "missing_size": _parse_size(summary.get("missing_size")),
            "resolved_size": sum(_item_size(item) for item in resolved_items),
        },
        "sources": {
            "active": list(summary.get("active_sources", []) or []),
            "resolution_counts": pipeline_summary["source_counts"],
            "provider_metrics": provider_metrics,
            "failure_causes": pipeline_summary["failure_causes"],
            "top_sources": _top_sources(provider_metrics),
        },
        "items": items,
        "extras": {
            "tosort_moved": _parse_size(summary.get("tosort_moved")),
            "tosort_failed": _parse_size(summary.get("tosort_failed")),
            "torrentzip_repacked": _parse_size(summary.get("torrentzip_repacked")),
            "torrentzip_skipped": _parse_size(summary.get("torrentzip_skipped")),
            "torrentzip_deleted": _parse_size(summary.get("torrentzip_deleted")),
            "torrentzip_failed": _parse_size(summary.get("torrentzip_failed")),
        },
        "validated_md5": validation_counts["validated_md5"],
        "validated_size_only": validation_counts["validated_size_only"],
    }


def _format_txt_report(payload: dict, summary: dict) -> str:
    from ..network.utils import format_bytes

    metadata = payload["metadata"]
    counts = payload["counts"]
    sizes = payload["sizes"]
    sources = payload["sources"]
    mode = metadata["mode"]
    title = "ROM Downloader - Rapport d'audit" if mode == "dry-run" else "ROM Downloader - Rapport final"
    lines = [
        title,
        "=" * 72,
        f"Date: {metadata['generated_at']}",
        f"DAT: {metadata['dat_file']}",
        f"Systeme: {metadata['system_name']}",
        f"Profil: {metadata['dat_profile']}",
        f"Dossier de destination: {metadata['output_folder']}",
    ]
    if mode == "dry-run":
        lines.append("Mode: dry-run, aucun telechargement effectue")
    else:
        lines.append(f"Mode: {mode}")

    lines.extend([
        "",
        "Resume",
        "-" * 72,
        f"Jeux dans le DAT: {counts['total_dat_games']}",
        f"Deja presents: {counts['present_before']}",
        f"Manquants avant run: {counts['missing_before']}",
        f"Resolus via providers: {counts['resolved']}",
        f"Introuvables: {counts['not_available']}",
        f"Telecharges: {counts['downloaded']}",
        f"  - Valides MD5: {counts.get('validated_md5', 0)}",
        f"  - Valides taille: {counts.get('validated_size_only', 0)}",
        f"Echecs: {counts['failed']}",
        f"Ignores: {counts['skipped']}",
        f"Taille DAT estimee: {format_bytes(sizes['total_dat_size'])}",
        f"Taille manquante estimee: {format_bytes(sizes['missing_size'])}",
        f"Taille trouvable estimee: {format_bytes(sizes['resolved_size'])}",
    ])

    if summary.get("mode") == "analyze" and "candidate_sample_size" not in summary:
        lines.append("Trouvables via providers: non calcule")
    elif "candidate_sample_size" in summary:
        value = summary.get("candidate_sample_size") or 0
        if value:
            lines.append(f"Trouvables via providers: {sum((summary.get('candidate_source_counts') or {}).values())} sur {value} echantillon(s)")
        else:
            lines.append("Trouvables via providers: non calcule")
    elif mode == "dry-run":
        lines.append(f"Trouvables via providers: {counts['resolved']}")

    extras = payload["extras"]
    if extras["tosort_moved"] or extras["tosort_failed"]:
        lines.extend([
            f"ToSort deplaces: {extras['tosort_moved']}",
            f"ToSort echecs: {extras['tosort_failed']}",
        ])
    if any(extras[key] for key in ("torrentzip_repacked", "torrentzip_skipped", "torrentzip_deleted", "torrentzip_failed")):
        lines.extend([
            f"TorrentZip recompresse(s): {extras['torrentzip_repacked']}",
            f"TorrentZip ignore(s): {extras['torrentzip_skipped']}",
            f"TorrentZip sources supprimees: {extras['torrentzip_deleted']}",
            f"TorrentZip echecs: {extras['torrentzip_failed']}",
        ])

    lines.extend(["", "Sources", "-" * 72])
    lines.append(f"Sources actives: {', '.join(sources['active']) or 'Aucune'}")
    if sources["resolution_counts"]:
        for source_name, count in sorted(sources["resolution_counts"].items(), key=lambda item: (-item[1], item[0].lower())):
            lines.append(f"- {source_name}: {count} resolution(s)")
    else:
        lines.append("- Aucun jeu resolu")

    lines.extend(["", "Metriques providers", "-" * 72])
    if sources["provider_metrics"]:
        for source_name, metric in sorted(sources["provider_metrics"].items(), key=lambda item: item[0].lower()):
            lines.append(
                f"- {source_name}: essais={metric['attempts']}, ok={metric.get('downloaded', 0)}, "
                f"echecs={metric.get('failed', 0)}, ignores={metric.get('skipped', 0)}, "
                f"quotas={metric.get('quota_skipped', 0)}, dry-run={metric.get('dry_run', 0)}, "
                f"temps={metric['seconds']:.1f}s"
            )
    else:
        lines.append("- Aucune metrique provider")

    top_sources = sources.get("top_sources", [])
    if top_sources:
        lines.extend(["", "Sources les plus efficaces", "-" * 72])
        for i, src in enumerate(top_sources, 1):
            taux = src["success_rate"] * 100
            lines.append(f"{i}. {src['source']}: {src['downloaded']} succes(s), taux={taux:.0f}%")

    lines.extend(["", "Causes d'echec", "-" * 72])
    if sources["failure_causes"]:
        for cause, count in sorted(sources["failure_causes"].items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- {cause}: {count}")
    else:
        lines.append("- Aucune")

    sections = [
        ("Introuvables", "not_found"),
        ("Echecs", "failed"),
        ("Telecharges/Simules", None),
        ("Ignores", "skipped"),
    ]
    for title, status in sections:
        lines.extend(["", title, "-" * 72])
        if status is None:
            selected = [item for item in payload["items"] if item["status"] in {"downloaded", "dry_run", "resolved"}]
        else:
            selected = [item for item in payload["items"] if item["status"] == status]
        if selected:
            for item in selected:
                provider = f" [{item['provider']}]" if item.get("provider") else ""
                detail = f" - {item['detail']}" if item.get("detail") else ""
                lines.append(f"- {item['game_name']}{provider}{detail}")
        else:
            lines.append("- Aucun")
    return "\n".join(lines) + "\n"


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_csv(path: Path, payload: dict) -> None:
    fieldnames = ["status", "system_name", "game_name", "provider", "download_filename", "size", "error_code", "detail", "file_path"]
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in payload["items"]:
            writer.writerow({key: item.get(key, "") for key in fieldnames})


def _write_html(path: Path, payload: dict, txt_body: str) -> None:
    metadata = payload["metadata"]
    rows = []
    for item in payload["items"]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(item.get('status', ''))}</td>"
            f"<td>{html.escape(item.get('game_name', ''))}</td>"
            f"<td>{html.escape(item.get('provider', ''))}</td>"
            f"<td>{html.escape(str(item.get('size', '')))}</td>"
            f"<td>{html.escape(item.get('detail', ''))}</td>"
            "</tr>"
        )
    body = "\n".join(rows) or '<tr><td colspan="5">Aucun element</td></tr>'
    document = f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>{html.escape(metadata.get('system_name') or 'ROM Downloader')}</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; color: #1f2933; }}
    pre {{ background: #f4f6f8; padding: 16px; overflow: auto; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 18px; }}
    th, td {{ border: 1px solid #d8dee4; padding: 7px 9px; text-align: left; }}
    th {{ background: #edf2f7; }}
  </style>
</head>
<body>
  <h1>ROM Downloader</h1>
  <pre>{html.escape(txt_body)}</pre>
  <h2>Elements</h2>
  <table>
    <thead><tr><th>Statut</th><th>Jeu</th><th>Provider</th><th>Taille</th><th>Detail</th></tr></thead>
    <tbody>
      {body}
    </tbody>
  </table>
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")


def write_download_reports(output_folder: str, summary: dict, formats=("txt",)) -> dict[str, str]:
    """Ecrit un ou plusieurs rapports et retourne les chemins par format."""
    target_dir = Path(output_folder)
    target_dir.mkdir(parents=True, exist_ok=True)
    requested_formats = normalize_report_formats(formats)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    system_slug = build_report_slug(summary.get("system_name") or summary.get("systeme") or "systeme")
    base_path = target_dir / f"rom_downloader_report_{system_slug}_{timestamp}"
    payload = build_report_payload(summary)
    txt_body = _format_txt_report(payload, summary)
    paths: dict[str, str] = {}
    for fmt in requested_formats:
        report_path = base_path.with_suffix(f".{fmt}")
        if fmt == "txt":
            report_path.write_text(txt_body, encoding="utf-8")
        elif fmt == "json":
            _write_json(report_path, payload)
        elif fmt == "csv":
            _write_csv(report_path, payload)
        elif fmt == "html":
            _write_html(report_path, payload, txt_body)
        paths[fmt] = str(report_path)
        print(f"Rapport {fmt} ecrit: {report_path}")
    return paths


def write_download_report(output_folder: str, summary: dict) -> str:
    """Ecrit le rapport TXT historique et retourne son chemin."""
    return write_download_reports(output_folder, summary, formats=("txt",))["txt"]


__all__ = [
    "REPORT_FORMATS",
    "build_report_payload",
    "build_report_slug",
    "normalize_report_formats",
    "write_download_report",
    "write_download_reports",
]
