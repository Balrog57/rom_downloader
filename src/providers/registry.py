"""Registre des providers disponibles."""

from __future__ import annotations

from .base import ProviderAdapter, ProviderContext
from ..core import get_default_sources, prepare_sources_for_profile, provider_healthcheck


def build_provider_registry(dat_profile: dict | None = None, source_configs: list[dict] | None = None) -> list[ProviderAdapter]:
    """Construit les adaptateurs providers depuis la configuration runtime."""
    configs = [source.copy() for source in (source_configs if source_configs is not None else get_default_sources())]
    configs = prepare_sources_for_profile(configs, dat_profile or {})
    adapters = [ProviderAdapter(config=config) for config in configs if config.get("enabled", True)]
    return sorted(adapters, key=lambda adapter: adapter.priority_key())


def healthcheck_registry(adapters: list[ProviderAdapter], context: ProviderContext | None = None) -> list[dict]:
    """Execute le healthcheck sur un registre de providers."""
    _context = context or ProviderContext(session=None)
    configs = [adapter.config for adapter in adapters]
    return provider_healthcheck(configs)
