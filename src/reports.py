"""Generation des rapports."""

from .core import build_report_payload, build_report_slug, normalize_report_formats, write_download_report, write_download_reports

__all__ = [
    "build_report_payload",
    "build_report_slug",
    "normalize_report_formats",
    "write_download_report",
    "write_download_reports",
]
