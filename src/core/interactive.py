import os

from ..network.sessions import create_optimized_session

from .env import *
from .dependencies import *


def clean_path_input(path: str) -> str:
    """Remove surrounding quotes from path."""
    path = path.strip()
    if path.startswith('"') and path.endswith('"'):
        path = path[1:-1]
    elif path.startswith("'") and path.endswith("'"):
        path = path[1:-1]
    return path


def get_input(prompt: str) -> str:
    """Get user input with quote cleaning."""
    result = input(prompt).strip()
    return clean_path_input(result)


def create_download_session() -> 'requests.Session':
    """Cree une session HTTP isolee pour un thread de telechargement (Phase 1)."""
    return create_optimized_session()


def interactive_mode():
    """Run in interactive console mode."""
    print("=" * 60)
    print("ROM Downloader - Mode Interactif")
    print("=" * 60)
    print()

    dat_file = get_input("Chemin vers le fichier DAT: ")
    rom_folder = get_input("Chemin vers le dossier des ROMs: ")
    myrient_url = ''
    print()
    
    tosort_input = get_input("Deplacer les ROMs non presentes dans le DAT vers ToSort ? (o/n): ")
    move_to_tosort = tosort_input.lower() in ['o', 'oui', 'y', 'yes']
    clean_input = get_input("Recompresser les archives validees en ZIP TorrentZip/RomVault ? (o/n): ")
    clean_torrentzip = clean_input.lower() in ['o', 'oui', 'y', 'yes']
    print()

    if not os.path.exists(dat_file):
        print(f"Erreur: Fichier DAT introuvable: {dat_file}")
        return
    if not os.path.exists(rom_folder):
        print(f"Erreur: Dossier ROMs introuvable: {rom_folder}")
        return

    from .pipeline import run_download
    run_download(dat_file, rom_folder, myrient_url, rom_folder, False, None, move_to_tosort, clean_torrentzip)


__all__ = [
    'clean_path_input',
    'get_input',
    'create_download_session',
    'interactive_mode',
]