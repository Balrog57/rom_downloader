"""Verifie que chaque DAT a un nombre minimal de providers et que les seuils sont respectes."""
from pathlib import Path
import sys, glob, os, json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.dat_profile import detect_dat_profile, finalize_dat_profile
from src.core.sources import SYSTEM_MAPPINGS, resolve_system_mapping

_CONFIG_PATH = Path(__file__).resolve().parent / "dat_coverage_config.json"


def _load_config() -> dict:
    if _CONFIG_PATH.exists():
        try:
            return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def main() -> None:
    files = glob.glob(r'dat\**\*.dat', recursive=True)
    if not files:
        raise SystemExit('no DAT files found')

    config = _load_config()
    providers = sorted({
        source_type for source_type in
        config.get("providers", []) + ["lolroms", "vimm", "planetemu", "coolrom",
                                        "romhustler", "retrogamesets", "romsxisos",
                                        "startgame", "hshop", "nopaystation",
                                        "archive_org_collection"]
    })

    system_names = []
    all_missing: dict[str, list[tuple[str, str]]] = {provider: [] for provider in providers}

    for f in files:
        prof = detect_dat_profile(f)
        sys_name = finalize_dat_profile(prof).get('system_name', '')
        if not sys_name:
            raise SystemExit(f'empty system_name for {f}')
        system_names.append(sys_name)

        for provider in providers:
            mapping = SYSTEM_MAPPINGS.get(sys_name, {}).get(provider)
            if not mapping:
                mapping = resolve_system_mapping(sys_name, provider=provider)
            if not mapping:
                all_missing[provider].append((os.path.basename(f), sys_name))

    unique_systems = sorted(set(system_names))
    total_systems = len(unique_systems)

    global_min = int(config.get("global_min_providers") or 1)
    per_provider_thresholds = config.get("per_provider", {})

    failures = []

    for provider in providers:
        missing = all_missing.get(provider, [])
        unique_missing = len(set(sys_name for _, sys_name in missing))
        covered_pct = 100.0 * (total_systems - unique_missing) / total_systems if total_systems else 0
        threshold = per_provider_thresholds.get(provider)

        expected = None
        if threshold is not None:
            expected = int(threshold)
        elif provider == "lolroms":
            expected = 100
        else:
            continue

        if expected == 0 or expected < 0:
            continue

        if expected > 100:
            failures.append(f"{provider}: {covered_pct:.1f}% covered, threshold {expected}% invalid (>100)")
        elif covered_pct < expected:
            failures.append(
                f"{provider}: {covered_pct:.1f}% covered below threshold {expected}% "
                f"({unique_missing} missing)"
            )

    systems_below_global = 0
    for sys_name in unique_systems:
        mapped_count = sum(
            1 for provider in providers
            if resolve_system_mapping(sys_name, provider)
        )
        if mapped_count < global_min:
            systems_below_global += 1
            failures.append(f"system '{sys_name}' has only {mapped_count} provider(s), min={global_min}")

    if failures:
        for msg in sorted(failures)[:40]:
            print(f"  COVERAGE FAIL: {msg}")
        if len(failures) > 40:
            print(f"  ... {len(failures) - 40} more failures")
        raise SystemExit(f'{len(failures)} coverage threshold violation(s)')

    print(f'dat coverage ok: {len(files)} DATs, {total_systems} unique systems')
    for provider in providers:
        unique_missing = len(set(sys_name for _, sys_name in all_missing.get(provider, [])))
        pct = 100.0 * (total_systems - unique_missing) / total_systems if total_systems else 0
        print(f'  {provider}: {pct:.1f}% ({total_systems - unique_missing}/{total_systems})')
    print(f'  systems with >= {global_min} providers: {total_systems - systems_below_global}/{total_systems}')


if __name__ == '__main__':
    main()
