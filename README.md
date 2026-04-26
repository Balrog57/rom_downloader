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
python main.py "dat\retool\Nintendo - Game Boy (20260405-031740).dat" "Roms\Game Boy" --analyze --analyze-candidates all
python main.py --sources
python main.py --diagnose
python main.py --diagnose --diagnose-output diagnostic.json
python main.py --healthcheck-sources
python main.py --provider-registry
python main.py --clear-listing-cache
python main.py --clear-cache-source Minerva
```

## Structure du depot

- `main.py`: point d'entree de l'application.
- `src/`: code Python de l'application.
- `src/progress.py`: helpers de progression, debit et ETA des transferts.
- `src/pipeline.py`: agregations testables du pipeline resolution/telechargement.
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
En GUI, l'analyse resout aussi les sources candidates selon la limite configuree (`0` pour aucune, `all` pour tout resoudre) et affiche les resultats detailles dans une fenetre paginee.
La GUI retient localement le dernier DAT, le dernier dossier, les options ToSort/TorrentZip, le parallelisme et l'etat des logs.
Le panneau `Logs` est repliable et affiche le detail des operations sans quitter la fenetre.
L'ecran `Configurer les sources` permet aussi de changer l'ordre des sources, les activer/desactiver, fixer un timeout et un quota par run, saisir les cles API locales dans `.env`, voir l'etat des caches, vider tous les caches, invalider la source selectionnee et consulter les statistiques cumulees par provider.

Les sources de telechargement sont automatiques: les sources directes sont essayees avant Minerva, puis archive.org en dernier recours.
La resolution des providers est mise en cache temporairement dans `.rom_downloader_resolution_cache.json` pour eviter de refaire les memes recherches pendant plusieurs essais; `--refresh-cache` force une reconstruction.
Les listings distants scrapes sont mis en cache 24 h dans `.rom_downloader_listing_cache.json`; `--clear-listing-cache` supprime tous les listings et `--clear-cache-source <source>` invalide les caches associes a une source.
Les telechargements HTTP utilisent des fichiers `.part`, reprennent quand le serveur accepte les requetes `Range`, journalisent debit/ETA pendant les gros transferts et remontent ces infos dans la barre de statut GUI.
Les quotas par source sont appliques pendant les retries: quand une source atteint sa limite de tentatives sur un run, le moteur passe au provider suivant.
Avant d'ignorer un fichier deja present, l'application valide le MD5 DAT quand il existe, puis la taille DAT si aucun MD5 n'est disponible.

## Dependances

Dependances Python principales:

- `requests`
- `beautifulsoup4`
- `internetarchive`
- `cloudscraper`
- `py7zr` pour lire/verifier les archives `.7z`
- `rarfile` pour lire/verifier les archives `.rar`
- `tkinterdnd2` optionnel pour le glisser-deposer GUI

`charset_normalizer` n'est pas liste directement car il est installe comme dependance transitive de `requests`.
Le programme tente encore d'installer certaines dependances optionnelles si elles manquent au moment d'une verification d'archive.
Les torrents Minerva demandent un binding Python `libtorrent` fonctionnel, mais il n'est pas liste dans `requirements.txt` car les wheels disponibles dependent fortement de la version Python et de Windows. Si `--diagnose` indique `libtorrent` absent ou une erreur `DLL load failed`, seuls les telechargements Minerva torrent sont affectes; les sources HTTP, la DB locale, l'analyse DAT et la GUI restent fonctionnelles. Sous Windows, si `libtorrent` reclame OpenSSL 1.1, renseigner `LIBTORRENT_DLL_DIR` dans `.env` vers le dossier contenant `libcrypto-1_1-x64.dll` et `libssl-1_1-x64.dll`.
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

- UI: bouton `Analyser`, recherche/filtre DAT, logs repliables, resume de pre-analyse, limite de resolution candidate configurable, resultats de pre-analyse pagines et preferences GUI locales.
- Optimisation: cache de resolution provider, reprise HTTP via fichiers `.part`, validation MD5/taille avant skip, logs debit/ETA et agregations pipeline testables.
- Analyse: sources candidates par echantillon et metriques provider dans les rapports.
- Sources: commandes `--healthcheck-sources` et `--provider-registry`, configuration GUI activation/ordre/timeouts/quotas, cles API locales, etat des caches, invalidation par source, statistiques provider, cache de listings distants et registre provider commun.
- Diagnostic: commande `--diagnose` et export JSON pour l'etat local utile au support.
- Qualite: CI GitHub Actions avec compilation, smoke checks, checks helpers, garde anti-regression, workflow packaging Windows et debut d'extraction des helpers runtime.

## Etat de la roadmap

- 1. UI: socle operationnel fait; restent surtout la decomposition de la GUI Tk en composants et une recherche systeme plus avancee.
- 2. Optimisation telechargement: reprise, cache, validation, metriques, agregations pipeline testables et ETA dans la barre de statut GUI sont en place; restent les vues statistiques.
- 3. Sources: ordre, activation, cles API, timeouts, quotas, healthcheck, cache, invalidation par source, statistiques provider et registre commun inspectable sont en place; reste le branchement complet resolution/download de chaque provider sur l'interface commune.
- 4. Qualite/architecture: CI, checks, packaging portable et workflow `.exe` manuel sont en place; restent extraction progressive de `src/core.py` et tests providers reseau.

## Roadmap

### 1. UI

- Remplacer la GUI Tk monolithique par une UI plus structuree avec composants separes.
- Ajouter une recherche systeme plus avancee.

### 2. Optimisation du telechargement

- Extraire la resolution effective et l'orchestration de telechargement hors `src/core.py`.
- Ajouter des graphiques simples de temps par provider et d'echecs par cause.

### 3. Gestion des sources

- Brancher progressivement chaque source sur l'interface provider commune: `resolve()`, `download()`, `healthcheck()` et `priority()`.
- Brancher les statistiques provider sur une vue graphique dediee.

### 4. Qualite et architecture

- Continuer l'extraction de `src/core.py` vers des modules plus petits avec tests unitaires cibles.
- Ajouter plus de tests unitaires autour du pipeline de resolution et des providers reseau.
- Tester et durcir le `.exe` genere dans GitHub Actions sur une machine Windows propre.
