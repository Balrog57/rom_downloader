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
python main.py --sources
python main.py --diagnose
python main.py --healthcheck-sources
```

## Structure du depot

- `main.py`: point d'entree de l'application.
- `src/`: code Python de l'application.
- `assets/`: images et icones utilisees par l'interface.
- `dat/`: fichiers DAT disponibles dans le menu de selection.
- `db/shard_*.zip`: shards SQLite compresses pour la recherche locale par MD5.
- `.env.example`: exemple de configuration locale.
- `requirements.txt`: dependances Python.

Le depot ne contient plus de runtime externe ni de dossier de generation. Les fichiers temporaires, caches, rapports locaux et donnees extraites restent ignores par Git.

## Interface

Le champ DAT de la GUI est un menu deroulant alimente par `dat/**/*.dat`.
Les dossiers directs de `dat/` sont affiches comme titres de section en italique et ne sont pas selectionnables. Les fichiers DAT sous chaque section sont selectionnables.
Le bouton `Parcourir` reste disponible comme secours pour choisir un DAT externe.
Le bouton `Analyser` lance une pre-analyse sans telechargement: total DAT, presents, manquants, taille estimee et sources actives.
La GUI retient localement le dernier DAT, le dernier dossier et les options ToSort/TorrentZip.

Les sources de telechargement sont automatiques: les sources directes sont essayees avant Minerva, puis archive.org en dernier recours.
La resolution des providers est mise en cache temporairement dans `.rom_downloader_resolution_cache.json` pour eviter de refaire les memes recherches pendant plusieurs essais; `--refresh-cache` force une reconstruction.
Les telechargements HTTP utilisent des fichiers `.part` et reprennent quand le serveur accepte les requetes `Range`.

## Dependances

Dependances Python principales:

- `requests`
- `beautifulsoup4`
- `internetarchive`
- `cloudscraper`
- `libtorrent` pour les torrents Minerva
- `tkinterdnd2` optionnel pour le glisser-deposer GUI

Le programme tente d'installer certaines dependances optionnelles si elles manquent.

## Base locale

La recherche locale utilise les shards compresses `db/shard_*.zip`.
Ces fichiers doivent etre presents dans le depot pour activer la recherche MD5 hors ligne.

Le cache local `db/retrogamesets/`, les rapports de sortie et les caches Python sont ignores par Git.

## Verification

```powershell
$files = @("main.py") + (Get-ChildItem src -Recurse -Filter *.py | ForEach-Object { $_.FullName })
python -m py_compile @files
python main.py --sources
python main.py --diagnose
```

## Roadmap implementee

- UI: bouton `Analyser`, resume de pre-analyse et preferences GUI locales.
- Optimisation: cache de resolution provider et reprise HTTP via fichiers `.part`.
- Sources: commande `--healthcheck-sources` pour verifier les sources actives.
- Diagnostic: commande `--diagnose` pour exporter l'etat local utile au support.

## Roadmap

### 1. UI

- Remplacer la GUI Tk monolithique par une UI plus structuree: panneau DAT avec recherche, filtres par famille, recherche systeme, statut detaille par jeu et logs repliables.
- Etendre la pre-analyse avec les sources candidates par jeu.
- Ajouter une preference persistante pour le parallelisme.

### 2. Optimisation du telechargement

- Separer davantage resolution et telechargement en pipeline testable.
- Ajouter validation taille/hash avant skip pour toutes les sources.
- Afficher debit, ETA, temps par provider et nombre d'echecs par cause.

### 3. Gestion des sources

- Formaliser une interface provider commune: `resolve()`, `download()`, `healthcheck()` et `priority()`.
- Ajouter un ecran de configuration des sources: activation, ordre, timeouts, quotas et cles API.
- Mettre en cache les listings distants avec expiration et invalidation manuelle.

### 4. Qualite et architecture

- Finir l'extraction de `src/core.py` vers des modules plus petits avec tests unitaires cibles.
- Ajouter une CI GitHub Actions: compilation Python, smoke tests sans reseau et grep anti-regression.
- Ajouter un mode diagnostic exportable: versions, chemins, sources actives, DB presente et dependances disponibles.
- Etudier un packaging Windows portable avec assets, DAT, DB et dependances documentes.
