import os
import re
from datetime import datetime
from pathlib import Path

from ..pipeline import build_pipeline_summary


def build_report_slug(value: str) -> str:
    """Nettoie une valeur pour un nom de fichier de rapport."""
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', '_', (value or '').strip())
    return cleaned.strip('._-') or 'run'


def write_download_report(output_folder: str, summary: dict) -> str:
    """Ecrit un recapitulatif lisible de la session dans le dossier de destination."""
    from ..network.utils import format_bytes
    os.makedirs(output_folder, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    system_slug = build_report_slug(summary.get('system_name', 'systeme'))
    report_path = os.path.join(output_folder, f"rom_downloader_report_{system_slug}_{timestamp}.txt")

    missing_titles = [item['game_name'] for item in summary.get('not_available', [])]
    failed_titles = [item['game_name'] for item in summary.get('failed_items', [])]
    downloaded_titles = [item['game_name'] for item in summary.get('downloaded_items', [])]
    skipped_titles = [item['game_name'] for item in summary.get('skipped_items', [])]

    pipeline_summary = build_pipeline_summary(summary)
    source_counts = pipeline_summary['source_counts']
    provider_metrics = pipeline_summary['provider_metrics']
    failure_causes = pipeline_summary['failure_causes']

    lines = [
        "ROM Downloader - Recapitulatif",
        "=" * 72,
        f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"DAT: {summary.get('dat_file', '')}",
        f"Systeme: {summary.get('system_name', '')}",
        f"Profil: {summary.get('dat_profile', '')}",
        f"Dossier de destination: {summary.get('output_folder', '')}",
        "Sources: automatiques",
        f"Sources actives: {', '.join(summary.get('active_sources', [])) or 'Aucune'}",
        "",
        "Resume",
        "-" * 72,
        f"Jeux dans le DAT: {summary.get('total_dat_games', 0)}",
        f"Jeux manquants avant telechargement: {summary.get('missing_before', 0)}",
        f"Jeux resolves sur les providers: {len(summary.get('resolved_items', []))}",
        f"Telecharges: {len(downloaded_titles)}",
        f"Echecs de telechargement: {len(failed_titles)}",
        f"Ignores / deja presents / limite: {len(skipped_titles)}",
        f"Introuvables sur toutes les sources: {len(missing_titles)}",
    ]

    if 'tosort_moved' in summary or 'tosort_failed' in summary:
        lines.extend([
            f"ToSort deplaces: {summary.get('tosort_moved', 0)}",
            f"ToSort echecs: {summary.get('tosort_failed', 0)}",
        ])

    if 'torrentzip_repacked' in summary or 'torrentzip_failed' in summary:
        lines.extend([
            f"TorrentZip recompresse(s): {summary.get('torrentzip_repacked', 0)}",
            f"TorrentZip ignore(s): {summary.get('torrentzip_skipped', 0)}",
            f"TorrentZip sources supprimees: {summary.get('torrentzip_deleted', 0)}",
            f"TorrentZip echecs: {summary.get('torrentzip_failed', 0)}",
        ])

    lines.extend(["", "Resolution par source", "-" * 72])
    if source_counts:
        for source_name, count in sorted(source_counts.items(), key=lambda item: (-item[1], item[0].lower())):
            lines.append(f"- {source_name}: {count}")
    else:
        lines.append("- Aucun jeu resolu")

    lines.extend(["", "Metriques providers", "-" * 72])
    if provider_metrics:
        for source_name, metric in sorted(provider_metrics.items(), key=lambda item: item[0].lower()):
            lines.append(
                f"- {source_name}: essais={metric['attempts']}, ok={metric.get('downloaded', 0)}, "
                f"echecs={metric.get('failed', 0)}, ignores={metric.get('skipped', 0)}, "
                f"quotas={metric.get('quota_skipped', 0)}, dry-run={metric.get('dry_run', 0)}, "
                f"temps={metric['seconds']:.1f}s"
            )
    else:
        lines.append("- Aucune metrique provider")

    lines.extend(["", "Causes d'echec", "-" * 72])
    if failure_causes:
        for cause, count in sorted(failure_causes.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- {cause}: {count}")
    else:
        lines.append("- Aucune")

    lines.extend(["", "Manquants non trouves", "-" * 72])
    if missing_titles:
        lines.extend(f"- {title}" for title in missing_titles)
    else:
        lines.append("- Aucun")

    lines.extend(["", "Echecs de telechargement", "-" * 72])
    if failed_titles:
        lines.extend(f"- {title}" for title in failed_titles)
    else:
        lines.append("- Aucun")

    lines.extend(["", "Telecharges", "-" * 72])
    if downloaded_titles:
        lines.extend(f"- {title}" for title in downloaded_titles)
    else:
        lines.append("- Aucun")

    lines.extend(["", "Ignores", "-" * 72])
    if skipped_titles:
        lines.extend(f"- {title}" for title in skipped_titles)
    else:
        lines.append("- Aucun")

    Path(report_path).write_text("\n".join(lines) + "\n", encoding='utf-8')
    print(f"Rapport ecrit: {report_path}")
    return report_path


__all__ = [
    'build_report_slug',
    'write_download_report',
]