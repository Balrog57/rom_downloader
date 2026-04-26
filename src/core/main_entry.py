import argparse
import os
from pathlib import Path

from ..version import APP_VERSION

from .env import *
from .constants import *
from .dependencies import *
from .diagnostics import (
    print_sources_info,
    print_provider_healthcheck,
    print_provider_registry_info,
    build_diagnostic_report,
    print_diagnostic_report,
    provider_healthcheck,
)
from .scanner import analyze_dat_folder, print_analysis_summary
from .dat_profile import detect_dat_profile, finalize_dat_profile
from .pipeline import run_download
from .cli import cli_mode
from .gui import gui_mode
from .interactive import interactive_mode


def main():
    parser = argparse.ArgumentParser(
        description='ROM Downloader - Compare un DAT 1G1R a un dossier cible et telecharge les jeux manquants',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=r'''
Exemples:
  python main.py --gui
  python main.py "dat\Nintendo - Game Boy (Retool).dat" "Roms\Game Boy"
  python main.py "dat\Sony - PlayStation 2 (Retool).dat" "Roms\PS2" --limit 10
  python main.py "dat\Nintendo - Game Boy (Retool).dat" "Roms\Game Boy" --analyze
  python main.py  (mode interactif)
  python main.py --sources  (afficher les sources disponibles)
  python main.py --diagnose
        '''
    )
    parser.add_argument('dat_file', nargs='?', help='Chemin vers le fichier DAT')
    parser.add_argument('rom_folder', nargs='?', help='Chemin vers le dossier de sortie ou de ROMs existantes')
    parser.add_argument('-o', '--output', help='Dossier de sortie (defaut: rom_folder)')
    parser.add_argument('--dry-run', action='store_true', help='Simulation sans telechargement')
    parser.add_argument('--limit', type=int, help='Limite de telechargements')
    parser.add_argument('--gui', action='store_true', help='Mode interface graphique')
    parser.add_argument('--tosort', action='store_true', help='Deplacer les ROMs non presentes dans le DAT vers un sous-dossier ToSort')
    parser.add_argument('--clean-torrentzip', action='store_true', help='Recompresser les archives validees MD5 en ZIP TorrentZip/RomVault')
    parser.add_argument('--parallel', type=int, default=DEFAULT_PARALLEL_DOWNLOADS, help=f'Nombre de telechargements simultanes (defaut: {DEFAULT_PARALLEL_DOWNLOADS})')
    parser.add_argument('--sources', action='store_true', help='Afficher les sources de telechargement')
    parser.add_argument('--version', action='version', version=f'ROM Downloader {APP_VERSION}', help='Afficher la version puis quitter')
    parser.add_argument('--analyze', action='store_true', help='Afficher une pre-analyse DAT/dossier puis quitter')
    parser.add_argument('--analyze-candidates', default='0', help="Pendant --analyze, resoudre les sources candidates des N premiers manquants, ou 'all'")
    parser.add_argument('--diagnose', action='store_true', help='Afficher un diagnostic local de l application')
    parser.add_argument('--diagnose-output', help='Exporter le diagnostic JSON vers ce fichier')
    parser.add_argument('--healthcheck-sources', action='store_true', help='Tester rapidement les sources configurees')
    parser.add_argument('--provider-registry', action='store_true', help='Afficher les providers via l interface commune')
    parser.add_argument('--refresh-cache', action='store_true', help='Ignorer et reconstruire le cache de resolution provider')
    parser.add_argument('--clear-listing-cache', action='store_true', help='Vider le cache des listings distants puis quitter')
    parser.add_argument('--clear-cache-source', help='Vider les caches lies a une source precise puis quitter')

    args = parser.parse_args()

    from . import _facade

    if args.sources:
        print_sources_info()
        return

    if args.clear_listing_cache:
        _facade.clear_listing_cache()
        print("Cache des listings distants vide.")
        return

    if args.clear_cache_source:
        removed = _facade.clear_caches_for_source(args.clear_cache_source)
        print(
            f"Cache {args.clear_cache_source}: "
            f"{removed.get('resolution', 0)} resolution, "
            f"{removed.get('listing', 0)} listing supprime(s)."
        )
        return

    if args.diagnose:
        report = build_diagnostic_report()
        print_diagnostic_report(report)
        if args.diagnose_output:
            save_json_file(Path(args.diagnose_output), report)
            print(f"Diagnostic exporte: {args.diagnose_output}")
        return

    if args.healthcheck_sources:
        print_provider_healthcheck(provider_healthcheck())
        return

    if args.provider_registry:
        print_provider_registry_info()
        return

    if args.gui:
        gui_mode()
        return

    if not args.dat_file and not args.rom_folder:
        gui_mode()
        return

    if args.dat_file and args.rom_folder:
        if args.refresh_cache:
            _facade.clear_resolution_cache()
            _facade.clear_listing_cache()
        if args.analyze:
            print_analysis_summary(analyze_dat_folder(
                args.dat_file,
                args.rom_folder,
                include_tosort=args.tosort,
                candidate_limit=args.analyze_candidates
            ))
            return
        cli_mode(args)
        return

    parser.print_help()


if __name__ == '__main__':
    main()


__all__ = [
    'main',
]