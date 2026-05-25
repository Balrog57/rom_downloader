import os
from pathlib import Path

from ..version import APP_VERSION

from .env import *
from .constants import *
from .dependencies import *
from .dat_profile import resolve_dat_output_folder
from .pipeline import run_download
from .fixdat import build_fixdat_from_results


def cli_mode(args):
    """Run in command-line mode."""
    output_root = args.output if args.output else args.rom_folder
    output_folder = resolve_dat_output_folder(args.dat_file, output_root, bool(getattr(args, 'output_root_by_dat', False)))
    os.makedirs(output_folder, exist_ok=True)

    result = run_download(
        args.dat_file,
        output_folder,
        '',
        output_folder,
        args.dry_run,
        args.limit,
        args.tosort,
        args.clean_torrentzip,
        parallel_downloads=args.parallel,
        refresh_resolution_cache=args.refresh_cache,
        prefer_1fichier=args.prefer_1fichier,
        report_formats=getattr(args, "report_formats", "txt"),
        report_dir=getattr(args, "report_dir", None),
        frontend=getattr(args, "frontend", None),
        output_mode=getattr(args, "output_mode", "flat"),
        archive_mode=getattr(args, "archive_mode", "none"),
    )

    if result and getattr(args, "fixdat", False):
        from .dat_parser import parse_dat_file
        dat_games = parse_dat_file(args.dat_file)
        not_available = result.get("not_available", [])
        failed_items = result.get("failed_items", [])
        missing = list(not_available) + list(failed_items)
        if missing:
            fixdat_path = build_fixdat_from_results(args.dat_file, dat_games, missing, output_folder)
            print(f"\nFixDAT genere: {fixdat_path}")
        else:
            print("\nAucun jeu manquant ou echoue: FixDAT non genere")


def discover_dat_menu_items(dat_root: Path | None = None) -> list[dict]:
    """Retourne les sections et DAT disponibles pour le menu GUI."""
    dat_root = dat_root or (RESOURCE_ROOT / 'dat')
    items = []
    if not dat_root.exists():
        return items

    direct_files = sorted(dat_root.glob('*.dat'), key=lambda path: path.name.lower())
    if direct_files:
        items.append({'type': 'section', 'label': 'dat'})
        items.extend({'type': 'file', 'label': path.name, 'path': str(path)} for path in direct_files)

    for section in sorted((path for path in dat_root.iterdir() if path.is_dir()), key=lambda path: path.name.lower()):
        files = sorted(section.rglob('*.dat'), key=lambda path: str(path.relative_to(section)).lower())
        if not files:
            continue
        items.append({'type': 'section', 'label': section.name})
        for path in files:
            label = str(path.relative_to(section))
            items.append({'type': 'file', 'label': label, 'path': str(path)})
    return items


__all__ = [
    'cli_mode',
    'discover_dat_menu_items',
]
