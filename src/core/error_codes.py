"""Classification centralisee des erreurs de telechargement."""

from __future__ import annotations


RETRYABLE_ERROR_CODES = {
    "network_timeout",
    "http_429",
    "http_5xx",
    "cloudflare_challenge",
}


def classify_error(status: str | None = None, detail: str | None = None) -> str:
    """Retourne un code d'erreur stable a partir d'un statut et d'un message."""
    normalized_status = (status or "").strip().lower()
    message = (detail or "").strip().lower()
    haystack = f"{normalized_status} {message}"

    if normalized_status in {"completed", "downloaded"}:
        return ""
    if normalized_status == "skipped":
        return "skipped"
    if normalized_status == "dry_run":
        return "dry_run"
    if normalized_status in {"cancelled", "stopped"} or "arret" in haystack:
        return "cancelled"
    if normalized_status == "not_found" or "aucun provider" in haystack or "not found" in haystack:
        return "game_not_found"
    if "checksum" in haystack or "md5 ko" in haystack or "crc" in haystack or "sha1" in haystack:
        return "checksum_mismatch"
    if "cloudflare" in haystack or "__cf_chl" in haystack or "just a moment" in haystack:
        return "cloudflare_challenge"
    if "quota" in haystack or "rate limit" in haystack:
        return "quota_exceeded"
    if "timeout" in haystack or "timed out" in haystack or "delai" in haystack:
        return "network_timeout"
    if "404" in haystack:
        return "http_404"
    if "403" in haystack:
        return "http_403"
    if "429" in haystack:
        return "http_429"
    if any(code in haystack for code in ("500", "502", "503", "504")):
        return "http_5xx"
    if "mapping" in haystack or "provider_not_mapped" in haystack:
        return "provider_not_mapped"
    if "archive" in haystack and ("invalid" in haystack or "invalide" in haystack):
        return "archive_invalid"
    if "no space" in haystack or "disk full" in haystack or "espace disque" in haystack:
        return "disk_full"
    if "permission" in haystack or "access denied" in haystack or "acces refuse" in haystack:
        return "permission_denied"
    if normalized_status in {"failed", "error"}:
        return "network_error"
    return ""


def error_is_retryable(error_code: str | None) -> bool:
    """Indique si une erreur peut etre retentee automatiquement."""
    return (error_code or "") in RETRYABLE_ERROR_CODES


def retry_delay_seconds(error_code: str | None) -> int:
    """Delai conseille avant retry automatique."""
    return {
        "network_timeout": 60,
        "http_429": 300,
        "http_5xx": 120,
        "cloudflare_challenge": 300,
    }.get(error_code or "", 0)


__all__ = [
    "RETRYABLE_ERROR_CODES",
    "classify_error",
    "error_is_retryable",
    "retry_delay_seconds",
]
