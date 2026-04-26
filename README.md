# ROM Downloader

Application Python pour comparer un DAT 1G1R a un dossier de ROMs, detecter les jeux manquants et tenter leur recuperation via les sources integrees.

## Utilisation

Interface graphique:

```powershell
python main.py --gui
```

Sans argument, l'application lance aussi la GUI:

```powershell
python main.py
```

Ligne de commande:

```powershell
python main.py <fichier.dat> <dossier_roms> [--dry-run] [--limit N] [--parallel N] [--tosort] [--clean-torrentzip]
```

Exemples:

```powershell
python main.py "dat\retool\Nintendo - Game Boy (20260405-031740).dat" "Roms\Game Boy"
python main.py "dat\retool\Sony - PlayStation 2 (2026-04-05 01-38-25) (Retool 2026-04-06 18-57-20) (2,560) (-nz) [-AaBbcDdefkMmopPruv].dat" "Roms\PS2" --limit 10
python main.py "dat\retool\Nintendo - Game Boy (20260405-031740).dat" "Roms\Game Boy" --tosort
python main.py "dat\retool\Nintendo - Game Boy (20260405-031740).dat" "Roms\Game Boy" --analyze
python main.py "dat\retool\Nintendo - Game Boy (20260405-031740).dat" "Roms\Game Boy" --analyze --analyze-candidates 10
python main.py --sources
python main.py --diagnose
python main.py --diagnose --diagnose-output diagnostic.json
python main.py --healthcheck-sources
python main.py --clear-listing-cache
```

## Structure du depot

- `main.py`: point d'entree de l'application.
- `src/`: code Python de l'application.
- `assets/`: images et icones utilisees par l'interface.
- `dat/`: fichiers DAT disponibles dans le menu de selection.
- `db/shard_*.zip`: shards SQLite compresses pour la recherche locale par MD5.
- `.env.example`: exemple de configuration locale.
- `requirements.txt`: dependances Python.
- `PACKAGING_WINDOWS.md`: notes pour une archive Windows portable.

Le depot ne contient plus de runtime externe ni de dossier de generation. Les fichiers temporaires, caches, rapports locaux et donnees extraites restent ignores par Git.

## Interface

Le champ DAT de la GUI est un menu deroulant alimente par `dat/**/*.dat`, avec recherche texte et filtres par section.
Les dossiers directs de `dat/` sont affiches comme titres de section en italique et ne sont pas selectionnables. Les fichiers DAT sous chaque section sont selectionnables.
Le bouton `Parcourir` reste disponible comme secours pour choisir un DAT externe.
Le bouton `Analyser` lance une pre-analyse sans telechargement: total DAT, presents, manquants, taille estimee et sources actives.
En GUI, l'analyse resout aussi un petit echantillon de sources candidates pour les premiers jeux manquants.
La GUI retient localement le dernier DAT, le dernier dossier, les options ToSort/TorrentZip, le parallelisme et l'etat des logs.
Le panneau `Logs` est repliable et affiche le detail des operations sans quitter la fenetre.
L'ecran `Configurer les sources` permet aussi de changer l'ordre des sources, les activer/desactiver, fixer un timeout et un quota par run, saisir les cles API locales dans `.env` et vider les caches.

Les sources de telechargement sont automatiques: les sources directes sont essayees avant Minerva, puis archive.org en dernier recours.
La resolution des providers est mise en cache temporairement dans `.rom_downloader_resolution_cache.json` pour eviter de refaire les memes recherches pendant plusieurs essais; `--refresh-cache` force une reconstruction.
Les listings distants scrapes sont mis en cache 24 h dans `.rom_downloader_listing_cache.json`; `--clear-listing-cache` ou le bouton `Vider cache` de la GUI les supprime.
Les telechargements HTTP utilisent des fichiers `.part`, reprennent quand le serveur accepte les requetes `Range`, et journalisent debit/ETA pendant les gros transferts.
Les quotas par source sont appliques pendant les retries: quand une source atteint sa limite de tentatives sur un run, le moteur passe au provider suivant.
Avant d'ignorer un fichier deja present, l'application valide le MD5 DAT quand il existe, puis la taille DAT si aucun MD5 n'est disponible.

## Dependances

Dependances Python principales:

- `requests`
- `beautifulsoup4`
- `internetarchive`
- `cloudscraper`
- `libtorrent` pour les torrents Minerva
- `tkinterdnd2` optionnel pour le glisser-deposer GUI

Le programme tente d'installer certaines dependances optionnelles si elles manquent.
Voir `PACKAGING_WINDOWS.md` pour preparer une archive portable.

## Base locale

La recherche locale utilise les shards compresses `db/shard_*.zip`.
Ces fichiers doivent etre presents dans le depot pour activer la recherche MD5 hors ligne.

Le cache local `db/retrogamesets/`, les rapports de sortie et les caches Python sont ignores par Git.

## Verification

```powershell
$files = @("main.py") + (Get-ChildItem src,tests -Recurse -Filter *.py | ForEach-Object { $_.FullName })
python -m py_compile @files
python tests\smoke_checks.py
python tests\core_helper_checks.py
python main.py --sources
python main.py --diagnose
python main.py --clear-listing-cache
```

## Roadmap implementee

- UI: bouton `Analyser`, recherche/filtre DAT, logs repliables, resume de pre-analyse et preferences GUI locales.
- Optimisation: cache de resolution provider, reprise HTTP via fichiers `.part`, validation MD5/taille avant skip et logs debit/ETA.
- Analyse: sources candidates par echantillon et metriques provider dans les rapports.
- Sources: commande `--healthcheck-sources`, configuration GUI activation/ordre/timeouts/quotas, cles API locales, cache de listings distants et registre provider commun.
- Diagnostic: commande `--diagnose` et export JSON pour l'etat local utile au support.
- Qualite: CI GitHub Actions avec compilation, smoke checks, checks helpers et garde anti-regression.

## Roadmap

### 1. UI

- Remplacer la GUI Tk monolithique par une UI plus structuree avec composants separes.
- Etendre la pre-analyse candidate a tous les jeux avec pagination et cache visible.
- Ajouter une recherche systeme plus avancee et un statut detaille par jeu.

### 2. Optimisation du telechargement

- Separer davantage resolution et telechargement en pipeline testable.
- Ajouter debit et ETA directement dans la barre de statut GUI.
- Ajouter des graphiques simples de temps par provider et d'echecs par cause.

### 3. Gestion des sources

- Brancher progressivement chaque source sur l'interface provider commune: `resolve()`, `download()`, `healthcheck()` et `priority()`.
- Ajouter des statistiques visuelles par source dans l'ecran de configuration.
- Exposer l'etat du cache de listings dans l'interface avec expiration et invalidation par source.

### 4. Qualite et architecture

- Finir l'extraction de `src/core.py` vers des modules plus petits avec tests unitaires cibles.
- Ajouter plus de tests unitaires autour du pipeline de resolution et des providers reseau.
- Ajouter un mode diagnostic exportable: versions, chemins, sources actives, DB presente et dependances disponibles.
- Convertir la strategie portable en build `.exe` automatise si necessaire.
