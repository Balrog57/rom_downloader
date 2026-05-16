"""Verifie que chaque fichier .dat est mappable vers LoLROMs et Vimm."""
from pathlib import Path
import sys, glob, os

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.dat_profile import detect_dat_profile, finalize_dat_profile
from src.core.sources import SYSTEM_MAPPINGS, resolve_system_mapping


def main() -> None:
    files = glob.glob(r'dat\**\*.dat', recursive=True)
    if not files:
        raise SystemExit('no DAT files found')

    lol_missing = []
    vimm_missing = []
    system_names = []

    for f in files:
        prof = detect_dat_profile(f)
        sys_name = finalize_dat_profile(prof).get('system_name', '')
        if not sys_name:
            raise SystemExit(f'empty system_name for {f}')
        system_names.append(sys_name)

        # LoLROMs coverage (direct or via resolve_system_mapping)
        lol = SYSTEM_MAPPINGS.get(sys_name, {}).get('lolroms')
        if not lol:
            lol = resolve_system_mapping(sys_name, provider='lolroms')
        if not lol:
            lol_missing.append((os.path.basename(f), sys_name))

        # Vimm coverage (optional, only ~35 systems supported)
        vimm = SYSTEM_MAPPINGS.get(sys_name, {}).get('vimm')
        if not vimm:
            vimm = resolve_system_mapping(sys_name, provider='vimm')

    if lol_missing:
        for basename, sys_name in sorted(set(lol_missing))[:20]:
            print(f'  missing lolroms: {sys_name} ({basename})')
        raise SystemExit(f'{len(set(lol_missing))} DATs missing LoLROMs mapping')

    print(f'dat coverage ok: {len(files)} DATs, {len(set(system_names))} unique systems')
    print(f'  LoLROMs: {len(files)} covered')
    vimm_count = sum(1 for s in system_names if SYSTEM_MAPPINGS.get(s, {}).get('vimm') or resolve_system_mapping(s, 'vimm'))
    print(f'  Vimm:    {vimm_count} covered')


if __name__ == '__main__':
    main()
