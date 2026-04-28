import importlib
import os
import platform
import sys
import time
import traceback
from pathlib import Path

from .env import APP_ROOT, LISTING_CACHE_FILE, LISTING_CACHE_TTL_SECONDS, PREFERENCES_FILE, RESOLUTION_CACHE_FILE, RESOLUTION_CACHE_TTL_SECONDS
from .constants import BALROG_ASSETS_DIR
from .rom_database import ROM_DATABASE_SHARDS_DIR


def safe_platform_label() -> str:
    """Retourne un libelle plateforme sans appeler WMI sur Windows."""
    arch = os.environ.get('PROCESSOR_ARCHITECTURE') or os.environ.get('PROCESSOR_ARCHITEW6432') or ''
    return f"{sys.platform} {arch}".strip()


def print_sources_info():
    """Print information about available download sources."""
    from ._facade import get_default_sources
    from .sources import DDL_SOURCE_TYPES
    print("\n" + "=" * 70)
    print("SOURCES DE TELECHARGEMENT DISPONIBLES")
    print("Extrait de games.zip RGSX (74,189 URLs analysees)")
    print("=" * 70)

    print("\n--- Sources DDL prioritaires ---")
    for i, source in enumerate(get_default_sources(), 1):
        if source['type'] not in DDL_SOURCE_TYPES:
            continue
        print(f"\n{i}. {source['name']}")
        print(f"   Type: {source['type']}")
        if source['base_url']:
            print(f"   URL: Masquee")
        print(f"   Description: {source.get('description', 'N/A')}")
        print(f"   Priorite: {source.get('priority', 'N/A')}")

    print("\n--- Dernier recours torrent ---")
    for i, source in enumerate(get_default_sources(), 1):
        if source['type'] != 'minerva':
            continue
        print(f"\n{i}. {source['name']}")
        print(f"   Type: {source['type']}")
        print(f"   Collection: {source.get('collection', 'N/A')}")
        print(f"   Description: {source.get('description', 'N/A')}")
        print(f"   Priorite: {source.get('priority', 'N/A')}")

    print("\n--- Dernier recours HTTP ---")
    for i, source in enumerate(get_default_sources(), 1):
        if source['type'] != 'archive_org':
            continue
        print(f"\n{i}. {source['name']}")
        print(f"   Type: {source['type']}")
        if source['base_url']:
            print(f"   URL: Masquee")
        print(f"   Description: {source.get('description', 'N/A')}")
        print(f"   Priorite: {source.get('priority', 'N/A')}")

    print("\n--- Sources Supplementaires ---")
    additional_sources = globals().get('ADDITIONAL_SOURCES', [])
    for i, source in enumerate(additional_sources, 1):
        status = "ACTIVABLE" if not source.get('enabled', False) else "ACTIVE"
        print(f"\n{i}. {source['name']} [{status}]")
        print(f"   Type: {source['type']}")
        if source['base_url']:
            print(f"   URL: {source['base_url']}")
        print(f"   Description: {source.get('description', 'N/A')}")

    print("\n" + "=" * 70)


def provider_healthcheck(sources: list | None = None, timeout: int = 8) -> list[dict]:
    """Verifie rapidement la disponibilite HTTP des sources configurees."""
    from ._facade import create_download_session, get_default_sources, source_timeout_seconds
    session = create_download_session()
    results = []
    for source in sources or get_default_sources():
        if not source.get('enabled', True):
            continue
        url = source.get('base_url', '')
        if not url:
            results.append({
                'name': source.get('name', 'Source inconnue'),
                'type': source.get('type', ''),
                'status': 'missing_url',
                'detail': 'URL absente',
            })
            continue
        source_timeout = source_timeout_seconds(source, timeout)
        started = time.time()
        status = 'ok'
        detail = ''
        try:
            response = session.head(url, timeout=source_timeout, allow_redirects=True)
            if response.status_code in {403, 405}:
                response.close()
                response = session.get(url, timeout=source_timeout, stream=True, allow_redirects=True)
            detail = f"HTTP {response.status_code}"
            if response.status_code >= 500:
                status = 'error'
            elif response.status_code >= 400:
                status = 'warning'
            response.close()
        except Exception as e:
            status = 'error'
            detail = str(e)
        results.append({
            'name': source.get('name', 'Source inconnue'),
            'type': source.get('type', ''),
            'status': status,
            'detail': detail,
            'elapsed_ms': int((time.time() - started) * 1000),
            'timeout_seconds': source_timeout,
        })
    return results


def print_provider_healthcheck(results: list[dict]) -> None:
    """Affiche le resultat du healthcheck provider."""
    print("\n" + "=" * 70)
    print("HEALTHCHECK SOURCES")
    print("=" * 70)
    for result in results:
        print(f"{result['status'].upper():<11} {result['name']:<24} {result.get('detail', '')} ({result.get('elapsed_ms', 0)} ms, timeout {result.get('timeout_seconds', '?')}s)")
    print("=" * 70)


def print_provider_registry_info() -> None:
    """Affiche les providers via l'interface commune."""
    from .providers import build_provider_registry

    adapters = build_provider_registry()
    print("\n" + "=" * 70)
    print("REGISTRE PROVIDERS")
    print("=" * 70)
    for index, adapter in enumerate(adapters, 1):
        print(
            f"{index:>2}. {adapter.name:<24} "
            f"type={adapter.type:<14} priority={adapter.priority:<4} "
            f"enabled={'oui' if adapter.enabled else 'non'}"
        )
    print("=" * 70)


def build_diagnostic_report() -> dict:
    """Construit un diagnostic exportable de l'environnement runtime."""
    from ._facade import discover_dat_menu_items, describe_cache_file
    from ..version import APP_VERSION
    dat_items = discover_dat_menu_items()
    dependencies = {}
    dependency_errors = {}
    for module_name in ('requests', 'bs4', 'internetarchive', 'cloudscraper', 'libtorrent', 'py7zr', 'rarfile', 'tkinterdnd2'):
        try:
            importlib.import_module(module_name)
            dependencies[module_name] = True
        except Exception:
            dependencies[module_name] = False
            dependency_errors[module_name] = traceback.format_exc(limit=1).strip().splitlines()[-1]
    return {
        'app_version': APP_VERSION,
        'python': sys.version.split()[0],
        'executable': sys.executable,
        'platform': safe_platform_label(),
        'app_root': str(APP_ROOT),
        'cwd': os.getcwd(),
        'dat_sections': [item['label'] for item in dat_items if item.get('type') == 'section'],
        'dat_files': sum(1 for item in dat_items if item.get('type') == 'file'),
        'db_shards': len(list(ROM_DATABASE_SHARDS_DIR.glob('shard_*.zip'))) if ROM_DATABASE_SHARDS_DIR.exists() else 0,
        'assets_present': BALROG_ASSETS_DIR.exists(),
        'preferences_file': str(PREFERENCES_FILE),
        'resolution_cache_file': str(RESOLUTION_CACHE_FILE),
        'listing_cache_file': str(LISTING_CACHE_FILE),
        'caches': {
            'resolution': describe_cache_file(RESOLUTION_CACHE_FILE, RESOLUTION_CACHE_TTL_SECONDS),
            'listing': describe_cache_file(LISTING_CACHE_FILE, LISTING_CACHE_TTL_SECONDS),
        },
        'dependencies': dependencies,
        'dependency_errors': dependency_errors,
        'env': {
            'IA_credentials': bool(os.environ.get('IAS3_ACCESS_KEY') and os.environ.get('IAS3_SECRET_KEY')),
            'fichier_key': bool(os.environ.get('ONEFICHIER_API_KEY')),
            'alldebrid_key': bool(os.environ.get('ALLDEBRID_API_KEY')),
            'realdebrid_key': bool(os.environ.get('REALDEBRID_API_KEY')),
        },
    }


def print_diagnostic_report(report: dict) -> None:
    """Affiche le diagnostic runtime."""
    from ._facade import format_bytes, format_cache_status
    from ..version import APP_VERSION
    print("\n" + "=" * 70)
    print("DIAGNOSTIC ROM DOWNLOADER")
    print("=" * 70)
    print(f"Version app: {report.get('app_version', APP_VERSION)}")
    print(f"Python: {report['python']} ({report['executable']})")
    print(f"Plateforme: {report['platform']}")
    print(f"Racine app: {report['app_root']}")
    print(f"DAT: {report['dat_files']} fichiers, sections: {', '.join(report['dat_sections']) or 'aucune'}")
    print(f"DB shards: {report['db_shards']}")
    print(f"Assets presents: {'oui' if report['assets_present'] else 'non'}")
    print(f"Cache resolution: {report['resolution_cache_file']}")
    print(f"Cache listings: {report['listing_cache_file']}")
    if report.get('caches'):
        print("Caches:")
        print(f"  - {format_cache_status('resolution', report['caches'].get('resolution', {}))}")
        print(f"  - {format_cache_status('listings', report['caches'].get('listing', {}))}")
    print("Dependances:")
    for name, ok in report['dependencies'].items():
        detail = ''
        if not ok and report.get('dependency_errors', {}).get(name):
            detail = f" ({report['dependency_errors'][name]})"
        print(f"  - {name}: {'ok' if ok else 'absent'}{detail}")
    print("Configuration:")
    for name, ok in report['env'].items():
        print(f"  - {name}: {'present' if ok else 'absent'}")
    print("=" * 70)


def export_diagnostic_report(path: str | Path) -> str:
    """Exporte le diagnostic runtime en JSON."""
    from ._facade import save_json_file
    output_path = Path(path)
    report = build_diagnostic_report()
    save_json_file(output_path, report)
    return str(output_path)

__all__ = [
    'print_sources_info',
    'provider_healthcheck',
    'print_provider_healthcheck',
    'print_provider_registry_info',
    'build_diagnostic_report',
    'print_diagnostic_report',
    'export_diagnostic_report',
]
