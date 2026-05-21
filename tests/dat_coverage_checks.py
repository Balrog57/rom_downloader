"""Verifie que chaque DAT a un nombre minimal de providers et que les seuils sont respectes."""
from pathlib import Path
import sys, glob, json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.mapping_status import build_mapping_status

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
                                        "archive_org_collection", "minerva", "archive_org"]
    })
    status = build_mapping_status(provider_types=providers)
    total_systems = int(status.get("unique_systems") or 0)
    all_missing: dict[str, list[tuple[str, str]]] = {
        provider: [("", sys_name) for sys_name in (row.get("missing_systems") or [])]
        for provider, row in (status.get("providers") or {}).items()
    }

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
    if global_min <= 1:
        for sys_name in status.get("without_any_provider") or []:
            systems_below_global += 1
            failures.append(f"system '{sys_name}' has only 0 provider(s), min={global_min}")
    else:
        provider_counts: dict[str, int] = {}
        for row in (status.get("providers") or {}).values():
            for item in row.get("covered_systems") or []:
                system_name = item.get("system_name", "")
                provider_counts[system_name] = provider_counts.get(system_name, 0) + 1
            for sys_name in row.get("fallback_systems") or []:
                provider_counts[sys_name] = provider_counts.get(sys_name, 0) + 1
        system_names = set(provider_counts) | set(status.get("without_any_provider") or [])
        for sys_name in sorted(system_names):
            mapped_count = provider_counts.get(sys_name, 0)
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
