import os
from pathlib import Path

from ..version import APP_VERSION

from .env import *
from .constants import *
from .dependencies import *
from .pipeline import run_download


def cli_mode(args):
    """Run in command-line mode."""
    output_folder = args.output if args.output else args.rom_folder
    os.makedirs(output_folder, exist_ok=True)

    run_download(
        args.dat_file,
        args.rom_folder,
        '',
        output_folder,
        args.dry_run,
        args.limit,
        args.tosort,
        args.clean_torrentzip,
        parallel_downloads=args.parallel,
        refresh_resolution_cache=args.refresh_cache,
        prefer_1fichier=args.prefer_1fichier
    )


def discover_dat_menu_items(dat_root: Path | None = None) -> list[dict]:
    """Retourne les sections et DAT disponibles pour le menu GUI."""
    dat_root = dat_root or (APP_ROOT / 'dat')
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
