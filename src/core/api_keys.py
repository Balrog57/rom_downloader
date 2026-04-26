import json
import os

from . import rom_database as _rom_db
from .rom_database import load_rom_database


API_CONFIG_FILE = 'api_keys.json'


def load_api_keys() -> dict:
    keys = {
        '1fichier': os.environ.get('ONE_FICHIER_API_KEY', ''),
        'alldebrid': os.environ.get('ALLDEBRID_API_KEY', ''),
        'realdebrid': os.environ.get('REALDEBRID_API_KEY', ''),
        'archive_access_key': os.environ.get('IA_S3_ACCESS_KEY', ''),
        'archive_secret_key': os.environ.get('IA_S3_SECRET_KEY', ''),
    }

    if os.path.exists(API_CONFIG_FILE):
        try:
            with open(API_CONFIG_FILE, 'r', encoding='utf-8') as f:
                json_keys = json.load(f)
                for k in keys:
                    if not keys[k] and k in json_keys:
                        keys[k] = json_keys[k]
        except Exception as e:
            print(f"Erreur lors du chargement des cles API (JSON): {e}")

    return keys


def save_api_keys(keys: dict) -> bool:
    try:
        env_path = '.env'
        lines = []
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

        mapping = {
            '1fichier': 'ONE_FICHIER_API_KEY',
            'alldebrid': 'ALLDEBRID_API_KEY',
            'realdebrid': 'REALDEBRID_API_KEY',
            'archive_access_key': 'IA_S3_ACCESS_KEY',
            'archive_secret_key': 'IA_S3_SECRET_KEY',
        }

        new_lines = []
        found_keys = set()

        for line in lines:
            stripped = line.strip()
            handled = False
            for k, env_name in mapping.items():
                if stripped.startswith(f"{env_name}="):
                    new_lines.append(f"{env_name}={keys.get(k, '')}\n")
                    found_keys.add(k)
                    handled = True
                    break
            if not handled:
                new_lines.append(line)

        for k, env_name in mapping.items():
            if k not in found_keys:
                new_lines.append(f"{env_name}={keys.get(k, '')}\n")

        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

        for k, env_name in mapping.items():
            os.environ[env_name] = keys.get(k, '')
        os.environ['IAS3_ACCESS_KEY'] = keys.get('archive_access_key', '')
        os.environ['IAS3_SECRET_KEY'] = keys.get('archive_secret_key', '')

        return True
    except Exception as e:
        print(f"Erreur lors de la sauvegarde des cles API dans .env: {e}")
        return False


def configure_api_keys():
    print("\n" + "=" * 60)
    print("CONFIGURATION DES CLES API")
    print("=" * 60)

    keys = load_api_keys()

    print("\nCles API actuelles:")
    for service, key in keys.items():
        masked = key[:10] + "..." if len(key) > 10 else key
        print(f"  - {service}: {masked if key else '(non configuree)'}")

    print("\nPour obtenir vos cles API (voir la configuration de la DB):")
    if _rom_db.ROM_DATABASE is None:
        load_rom_database()
    config = _rom_db.ROM_DATABASE.get('config_urls', {})
    print(f"  1fichier:   {config.get('1fichier_apikeys', 'Consultez le site 1fichier')}")
    print(f"  AllDebrid:  {config.get('alldebrid_apikeys', 'Consultez le site AllDebrid')}")
    print(f"  RealDebrid: {config.get('realdebrid_apikeys', 'Consultez le site RealDebrid')}")

    print("\nEntrez vos cles API (laissez vide pour conserver):")

    for service in keys:
        new_key = input(f"  Cle {service}: ").strip()
        if new_key:
            keys[service] = new_key

    if save_api_keys(keys):
        print("\nCles API sauvegardees avec succes dans le fichier .env!")
    else:
        print("\nErreur lors de la sauvegarde des cles API dans .env.")

    return keys


def is_1fichier_url(url: str) -> bool:
    return "1fichier.com" in url if url else False


__all__ = [
    'API_CONFIG_FILE',
    'load_api_keys',
    'save_api_keys',
    'configure_api_keys',
    'is_1fichier_url',
]