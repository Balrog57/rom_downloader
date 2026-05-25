"""Profils de configuration reutilisables par la CLI et la GUI."""

CONFIG_PROFILES = {
    "debutant-sur": {
        "label": "Debutant sur",
        "settings": {
            "dry_run": True,
            "parallel": 2,
            "clean_torrentzip": False,
            "tosort": False,
            "prefer_1fichier": False,
            "report_formats": "txt,json,csv,html",
        },
    },
    "rapide": {
        "label": "Rapide",
        "settings": {
            "dry_run": False,
            "parallel": 6,
            "clean_torrentzip": False,
            "tosort": False,
            "prefer_1fichier": False,
        },
    },
    "archive-propre": {
        "label": "Archive propre",
        "settings": {
            "dry_run": False,
            "parallel": 2,
            "clean_torrentzip": True,
            "tosort": True,
            "prefer_1fichier": False,
            "report_formats": "txt,json,csv,html",
        },
    },
}

CONFIG_PROFILE_LABELS = tuple(item["label"] for item in CONFIG_PROFILES.values())
CONFIG_PROFILE_CHOICES = tuple(CONFIG_PROFILES.keys())
CONFIG_PROFILE_HELP = ", ".join(
    f"{key} ({value['label']})" for key, value in CONFIG_PROFILES.items()
)

_ALIASES = {
    "debutant": "debutant-sur",
    "debutant sur": "debutant-sur",
    "debutant-sur": "debutant-sur",
    "debutant_sur": "debutant-sur",
    "safe": "debutant-sur",
    "rapide": "rapide",
    "fast": "rapide",
    "archive": "archive-propre",
    "archive propre": "archive-propre",
    "archive-propre": "archive-propre",
    "archive_propre": "archive-propre",
}


def normalize_config_profile(profile_name: str | None) -> str:
    """Retourne l'identifiant canonique du profil, ou une chaine vide."""
    if not profile_name:
        return ""
    key = str(profile_name).strip().lower().replace("_", "-")
    return _ALIASES.get(key, key if key in CONFIG_PROFILES else "")


def config_profile_settings(profile_name: str | None) -> dict:
    """Retourne une copie des reglages associes au profil."""
    profile_key = normalize_config_profile(profile_name)
    if not profile_key:
        return {}
    return dict(CONFIG_PROFILES[profile_key]["settings"])


def apply_config_profile(namespace, profile_name: str | None, explicit_fields: set[str] | None = None) -> str:
    """Applique un profil a un argparse.Namespace sans ecraser les options explicites."""
    profile_key = normalize_config_profile(profile_name)
    if not profile_key:
        return ""
    explicit_fields = explicit_fields or set()
    for field, value in config_profile_settings(profile_key).items():
        if field not in explicit_fields:
            setattr(namespace, field, value)
    return profile_key


__all__ = [
    "CONFIG_PROFILES",
    "CONFIG_PROFILE_LABELS",
    "CONFIG_PROFILE_CHOICES",
    "CONFIG_PROFILE_HELP",
    "normalize_config_profile",
    "config_profile_settings",
    "apply_config_profile",
]
