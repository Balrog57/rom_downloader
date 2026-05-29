"""Registre des providers disponibles."""

from __future__ import annotations

from .base import ProviderAdapter, ProviderContext, ProviderResult
from ..core import get_default_sources, prepare_sources_for_profile, provider_healthcheck

_PROVIDER_RESOLVERS: dict[str, callable] = {}
_PROVIDER_DOWNLOADERS: dict[str, callable] = {}


def register_provider_resolver(source_type: str, resolve_func: callable):
    """Enregistre une fonction de resolution pour un type de source."""
    _PROVIDER_RESOLVERS[source_type] = resolve_func


def register_provider_downloader(source_type: str, download_func: callable):
    """Enregistre une fonction de telechargement pour un type de source."""
    _PROVIDER_DOWNLOADERS[source_type] = download_func


def build_provider_registry(dat_profile: dict | None = None, source_configs: list[dict] | None = None) -> list[ProviderAdapter]:
    """Construit les adaptateurs providers depuis la configuration runtime."""
    from . import _wiring
    if not _PROVIDER_RESOLVERS:
        _wiring.wire_provider_callbacks()
    configs = [source.copy() for source in (source_configs if source_configs is not None else get_default_sources())]
    configs = prepare_sources_for_profile(configs, dat_profile or {})
    adapters = []
    for config in configs:
        if not config.get("enabled", True):
            continue
        source_type = config.get("type", "")
        adapter = ProviderAdapter(
            config=config,
            resolve_func=_PROVIDER_RESOLVERS.get(source_type),
            download_func=_PROVIDER_DOWNLOADERS.get(source_type),
        )
        adapters.append(adapter)
    return sorted(adapters, key=lambda adapter: adapter.priority_key())


def healthcheck_registry(adapters: list[ProviderAdapter], context: ProviderContext | None = None) -> list[dict]:
    """Execute le healthcheck sur un registre de providers."""
    _context = context or ProviderContext(session=None)
    configs = [adapter.config for adapter in adapters]
    return provider_healthcheck(configs)
