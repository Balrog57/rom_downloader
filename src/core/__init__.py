"""ROM Downloader - Module principal (facade).

Ce package remplace l'ancien fichier monolithique core.py.
Toutes les fonctions publiques sont importees depuis les sous-modules
et re-exportees ici pour compatibilite ascendante.
"""

from ._facade import *  # noqa: F401,F403