"""Exceptions custom pour pipeline de telechargement."""


class RomDownloaderError(Exception):
    """Base pour toutes les exceptions de l'application."""


class SourceTimeoutError(RomDownloaderError):
    """Timeout reseau sur une source."""


class ChecksumMismatchError(RomDownloaderError):
    """MD5/CRC/SHA1 du fichier telecharge ne correspond pas au DAT."""


class QuotaExceededError(RomDownloaderError):
    """Quota de la source atteint."""


class DownloadNetworkError(RomDownloaderError):
    """Erreur reseau generique."""


class SourceUnavailableError(RomDownloaderError):
    """Source temporairement indisponible."""


class ResumeNotSupportedError(RomDownloaderError):
    """Le serveur ne supporte pas la reprise."""


class TorrentDownloadError(RomDownloaderError):
    """Erreur torrent/aria2c."""


__all__ = [
    "RomDownloaderError",
    "SourceTimeoutError",
    "ChecksumMismatchError",
    "QuotaExceededError",
    "DownloadNetworkError",
    "SourceUnavailableError",
    "ResumeNotSupportedError",
    "TorrentDownloadError",
]
