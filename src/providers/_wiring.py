"""Enregistrement des callbacks provider (resolve/download) par type de source.
Les fonctions de telechargement sont trop imbriquees dans l'orchestrateur pour etre wires
directement comme callbacks externes, mais les fonctions de resolution simples sont wires.
"""
from __future__ import annotations

from .registry import register_provider_resolver, register_provider_downloader


def wire_provider_callbacks():
    """Enregistre les fonctions resolve/download pour chaque type de source DDL."""
    from ..core.scrapers import (
        resolve_edgeemu_game,
        resolve_retrogamesets_game,
        resolve_romhustler_game,
        resolve_coolrom_game,
        resolve_nopaystation_game,
        resolve_startgame_game,
        resolve_hshop_game,
        resolve_romsxisos_game,
        resolve_vimm_game,
        resolve_archive_org_collection_game,
        download_planetemu as _download_planetemu,
        download_vimm as _download_vimm,
        download_lolroms_file as _download_lolroms,
    )
    from ..core.downloads import download_file as _download_file

    register_provider_resolver("edgeemu", resolve_edgeemu_game)
    register_provider_resolver("retrogamesets", resolve_retrogamesets_game)
    register_provider_resolver("romhustler", resolve_romhustler_game)
    register_provider_resolver("coolrom", resolve_coolrom_game)
    register_provider_resolver("nopaystation", resolve_nopaystation_game)
    register_provider_resolver("startgame", resolve_startgame_game)
    register_provider_resolver("hshop", resolve_hshop_game)
    register_provider_resolver("romsxisos", resolve_romsxisos_game)
    register_provider_resolver("vimm", resolve_vimm_game)
    register_provider_resolver("archive_org_collection", resolve_archive_org_collection_game)

    register_provider_downloader("planetemu", _download_planetemu)
    register_provider_downloader("vimm", _download_vimm)
    register_provider_downloader("lolroms", _download_lolroms)
    register_provider_downloader("edgeemu", _download_file)
    register_provider_downloader("romsxisos", _download_file)
    register_provider_downloader("coolrom", _download_file)
