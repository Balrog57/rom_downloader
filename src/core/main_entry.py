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
from .dat_profile import detect_dat_profile, finalize_dat_profile, resolve_dat_output_folder
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
    parser.add_argument('--output-root-by-dat', action='store_true', help='Utiliser rom_folder/output comme racine et creer un sous-dossier nomme comme le DAT')
    parser.add_argument('--prefer-1fichier', action='store_true', help='Prioriser RetroGameSets/StartGame avant les DDL directs')
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
    parser.add_argument('--index-catalog', action='store_true', help='Construire ou rafraichir le catalogue local DAT/jeux')
    parser.add_argument('--catalog-status', action='store_true', help='Afficher un resume du catalogue local')
    parser.add_argument('--db-status', action='store_true', help='Afficher un resume de la base SQLite locale')
    parser.add_argument('--queue-status', action='store_true', help='Afficher les derniers jobs de telechargement persistants')
    parser.add_argument('--queue-limit', type=int, default=20, help='Nombre de jobs affiches avec --queue-status')
    parser.add_argument('--pause-job', metavar='JOB_ID', help='Mettre en pause un job en cours')
    parser.add_argument('--resume-job', metavar='JOB_ID', help='Reprendre un job en pause')
    parser.add_argument('--cancel-job', metavar='JOB_ID', help='Annuler un job')
    parser.add_argument('--retry-job', metavar='JOB_ID', help='Remettre en file les items echoues d''un job')
    parser.add_argument('--mapping-status', action='store_true', help='Afficher la couverture des mappings DAT/providers')
    parser.add_argument('--mapping-missing-limit', type=int, default=20, help='Nombre de mappings manquants affiches par provider')
    parser.add_argument('--mapping-output', help='Exporter --mapping-status en JSON ou CSV')
    parser.add_argument('--probe-providers', action='store_true', help='Resoudre des providers candidats sans telecharger')
    parser.add_argument('--probe-system', '--system', dest='probe_system', help='Systeme catalogue a sonder avec --probe-providers')
    parser.add_argument('--probe-limit', type=int, default=50, help='Nombre de jeux sondes avec --probe-providers')
    parser.add_argument('--reset-local-db', action='store_true', help='Supprimer la base SQLite locale puis quitter')

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

    if args.index_catalog:
        from .catalog import build_catalog_index
        result = build_catalog_index(force=True)
        print(f"Catalogue indexe: {result['systems']} systeme(s), {result['games']} jeu(x)")
        return

    if args.reset_local_db:
        from .local_database import reset_local_database
        reset_local_database()
        print("Base SQLite locale supprimee.")
        return

    if args.db_status:
        from .local_database import database_status
        status = database_status()
        print(f"Base SQLite: {status['path']}")
        print(f"Systemes: {status['systems']}")
        print(f"Jeux: {status['games']}")
        print(f"ROMs: {status['roms']}")
        print(f"Providers valides: {status['provider_successes']}")
        print(f"Providers candidats: {status['provider_candidates']}")
        print(f"Metriques providers: {status['provider_metrics']}")
        print(f"Jobs: {status['download_jobs']}")
        print(f"File: {status['download_queue_items']}")
        print(f"Historique: {status['download_attempts']}")
        return

    if args.queue_status:
        from .local_database import list_download_jobs
        jobs = list_download_jobs(limit=max(1, int(args.queue_limit or 20)))
        print(f"Jobs de telechargement: {len(jobs)}")
        for job in jobs:
            queue = job.get('queue') or {}
            queue_text = ", ".join(f"{key}={value}" for key, value in sorted(queue.items())) or "vide"
            print(
                f"  - {job['job_id']} [{job['status']}] "
                f"{job['completed']}/{job['total']} - {job['output_folder']} - {queue_text}"
            )
        return

    if args.pause_job:
        from .local_database import pause_download_job
        ok = pause_download_job(args.pause_job)
        print(f"Pause {'OK' if ok else 'ECHEC'} (job non trouve ou status incompatible)")
        return

    if args.resume_job:
        from .local_database import resume_download_job
        ok = resume_download_job(args.resume_job)
        print(f"Reprise {'OK' if ok else 'ECHEC'} (job non trouve ou status incompatible)")
        return

    if args.cancel_job:
        from .local_database import cancel_download_job
        ok = cancel_download_job(args.cancel_job)
        print(f"Annulation {'OK' if ok else 'ECHEC'} (job non trouve ou status incompatible)")
        return

    if args.retry_job:
        from .local_database import retry_failed_queue_items
        count = retry_failed_queue_items(args.retry_job)
        print(f"{count} item(s) remis en file pour retry")
        return

    if args.mapping_status:
        from .mapping_status import build_mapping_status, export_mapping_status, format_mapping_status_report
        status = build_mapping_status()
        print(format_mapping_status_report(status, missing_limit=max(0, int(args.mapping_missing_limit or 0))))
        if args.mapping_output:
            print(f"Export mapping: {export_mapping_status(status, args.mapping_output)}")
        return

    if args.probe_providers:
        if not args.probe_system:
            parser.error("--probe-providers requiert --probe-system")
        from .provider_probe import probe_catalog_providers, format_probe_report
        print(format_probe_report(probe_catalog_providers(
            args.probe_system,
            limit=max(0, int(args.probe_limit or 0)),
        )))
        return

    if args.catalog_status:
        from .catalog import list_catalog_systems
        systems = list_catalog_systems()
        game_count = sum(int(item.get('game_count', 0) or 0) for item in systems)
        print(f"Catalogue: {len(systems)} systeme(s), {game_count} jeu(x)")
        for item in systems[:20]:
            print(f"  - {item['system_name']} ({item.get('dat_section', 'dat')}): {item['game_count']} jeu(x)")
        if len(systems) > 20:
            print(f"  ... {len(systems) - 20} autre(s) systeme(s)")
        return

    if args.gui:
        gui_mode()
        return

    if not args.dat_file and not args.rom_folder:
        gui_mode()
        return

    if args.dat_file and args.rom_folder:
        effective_rom_folder = resolve_dat_output_folder(
            args.dat_file,
            args.output or args.rom_folder,
            args.output_root_by_dat,
        )
        if args.refresh_cache:
            _facade.clear_resolution_cache()
            _facade.clear_listing_cache()
        if args.analyze:
            os.makedirs(effective_rom_folder, exist_ok=True)
            print_analysis_summary(analyze_dat_folder(
                args.dat_file,
                effective_rom_folder,
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
