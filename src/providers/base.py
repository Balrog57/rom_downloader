"""Interfaces communes pour les providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(slots=True)
class ProviderContext:
    """Contexte partage par les providers pendant resolution/telechargement."""

    session: Any
    system_name: str = ""
    dat_profile: dict | None = None
    output_folder: str = ""


@dataclass(slots=True)
class ProviderResult:
    """Resultat normalise d'une resolution provider."""

    game_name: str
    source: str
    download_filename: str = ""
    download_url: str = ""
    page_url: str = ""
    torrent_url: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class ProviderAdapter:
    """Adaptateur minimal autour d'une source configuree."""

    config: dict
    resolve_func: Callable[[dict, ProviderContext], ProviderResult | None] | None = None
    download_func: Callable[[ProviderResult, ProviderContext], bool] | None = None
    healthcheck_func: Callable[["ProviderAdapter", ProviderContext], dict] | None = None

    @property
    def name(self) -> str:
        return self.config.get("name", "")

    @property
    def type(self) -> str:
        return self.config.get("type", "")

    @property
    def priority(self) -> int:
        return int(self.config.get("priority", 50))

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("enabled", True))

    def priority_key(self) -> tuple[int, int, str]:
        return (
            int(self.config.get("order", self.priority)),
            self.priority,
            self.name.lower(),
        )

    def resolve(self, game_info: dict, context: ProviderContext) -> ProviderResult | None:
        if not self.resolve_func:
            return None
        return self.resolve_func(game_info, context)

    def download(self, result: ProviderResult, context: ProviderContext) -> bool:
        if not self.download_func:
            return False
        return self.download_func(result, context)

    def healthcheck(self, context: ProviderContext) -> dict:
        if self.healthcheck_func:
            return self.healthcheck_func(self, context)
        return {
            "name": self.name,
            "type": self.type,
            "status": "unknown",
            "detail": "healthcheck non implemente",
        }
