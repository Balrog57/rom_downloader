"""Modules reseau fondamentaux pour ROM Downloader."""

from .exceptions import (
    RomDownloaderError,
    SourceTimeoutError,
    ChecksumMismatchError,
    QuotaExceededError,
    DownloadNetworkError,
    SourceUnavailableError,
    ResumeNotSupportedError,
    TorrentDownloadError,
)
from .sessions import (
    create_optimized_session,
    timed_request,
    get_chunk_size,
    safe_stream_write,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_TIMEOUT_SECONDS,
)
from .circuits import SourceCircuitBreaker
from .cache_runtime import RuntimeCache, get_session_cache, clear_session_cache
from .metrics import (
    load_provider_metrics,
    save_provider_metrics,
    compute_provider_score,
    prioritize_sources,
    record_provider_attempt,
)
from .downloads import ParallelDownloadPool
from .search import ParallelSearchPool

__all__ = [
    # exceptions
    "RomDownloaderError",
    "SourceTimeoutError",
    "ChecksumMismatchError",
    "QuotaExceededError",
    "DownloadNetworkError",
    "SourceUnavailableError",
    "ResumeNotSupportedError",
    "TorrentDownloadError",
    # sessions
    "create_optimized_session",
    "timed_request",
    "get_chunk_size",
    "safe_stream_write",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_TIMEOUT_SECONDS",
    # circuits
    "SourceCircuitBreaker",
    # cache
    "RuntimeCache",
    "get_session_cache",
    "clear_session_cache",
    # metrics
    "load_provider_metrics",
    "save_provider_metrics",
    "compute_provider_score",
    "prioritize_sources",
    "record_provider_attempt",
    # downloads
    "ParallelDownloadPool",
    # search
    "ParallelSearchPool",
]
