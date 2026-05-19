"""Detection centralisee des blocages Cloudflare et challenges HTML."""

from __future__ import annotations


CLOUDFLARE_TEXT_MARKERS = (
    "just a moment",
    "un instant",
    "attention required",
    "cloudflare",
    "cf-ray",
    "cf-mitigated",
    "challenge-platform",
    "__cf_chl",
    "under attack mode",
    "checking your browser",
    "enable javascript",
)

CLOUDFLARE_HEADER_NAMES = {"cf-ray", "cf-cache-status", "cf-request-id", "cf-mitigated"}


def looks_like_cloudflare_block(status_code: int = 0, headers: dict | None = None,
                                body_snippet: str = "", url: str = "") -> bool:
    """Detecte une reponse de challenge/blocage Cloudflare."""
    headers = headers or {}
    header_names = {str(key).lower() for key in headers.keys()}
    server = str(headers.get("server") or headers.get("Server") or "").lower()
    content_type = str(headers.get("content-type") or headers.get("Content-Type") or "").lower()
    text = f"{body_snippet or ''} {url or ''}".lower()

    if "__cf_chl" in text:
        return True
    if any(marker in text for marker in CLOUDFLARE_TEXT_MARKERS):
        return True
    if CLOUDFLARE_HEADER_NAMES.intersection(header_names):
        return status_code >= 400 or "text/html" in content_type
    if status_code in {403, 429, 503} and "cloudflare" in server:
        return True
    return False


__all__ = [
    "CLOUDFLARE_TEXT_MARKERS",
    "CLOUDFLARE_HEADER_NAMES",
    "looks_like_cloudflare_block",
]
