# ROM Downloader

ROM Downloader compare un DAT No-Intro, Redump ou Retool a un dossier de ROMs, detecte les jeux manquants et tente de les recuperer via les sources configurees.

Version courante: `0.1.4`.

## Installation Windows

### Exe portable

Telechargez `ROMDownloader.exe` depuis la derniere release GitHub, placez-le dans le dossier de votre choix, puis lancez-le directement.

En mode exe portable:

- les ressources embarquees (`assets/`, `dat/`, `db/`, `VERSION`) sont lues depuis l'exe;
- les fichiers utilisateur sont crees a cote de `ROMDownloader.exe`: `.env`, preferences, caches, metriques provider;
- une reinstall ou un deplacement du dossier conserve donc la configuration si ces fichiers restent avec l'exe.

Installation rapide depuis PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/Balrog57/rom_downloader/main/install.ps1 | iex"
```

### Depuis Python

```powershell
python -m pip install -r requirements.txt
python main.py --gui
```

Sans argument, l'application lance aussi la GUI:

```powershell
python main.py
```

## Utilisation CLI

```powershell
python main.py <fichier.dat> <dossier_roms> [--dry-run] [--limit N] [--parallel N] [--tosort] [--clean-torrentzip]
```

Commandes utiles:

```powershell
python main.py --version
python main.py --sources
python main.py --diagnose
python main.py --healthcheck-sources
python main.py --provider-registry
python main.py --clear-listing-cache
python main.py --clear-cache-source LoLROMs
```

Pour les sets GBA LoLROMs, utilisez `--clean-torrentzip` si vous voulez des ZIP compatibles RomVault: LoLROMs fournit souvent des `.7z` contenant les ROMs attendues par les DAT.

## Sources et fiabilite

Le pipeline essaie les providers dans cet ordre logique:

1. base locale shardee par checksum;
2. sources DDL directes: PlanetEmu, RomHustler, CoolROM, RomsXISOs, NoPayStation, hShop, Vimm's Lair, LoLROMs, RetroGameSets, StartGame;
3. collections archive.org ciblees par systeme, dont des groupes issus de RomGoGetter pour PS1/PS2/PS3/Xbox/Xbox 360/NDS/3DS/Wii U/PSP;
4. Minerva par torrent;
5. archive.org general en dernier recours.

La fiabilite repose sur:

- fichiers `.part` et reprise HTTP quand le serveur accepte `Range`;
- redemarrage propre si un serveur refuse la reprise ou retourne HTTP 416;
- detection des pages HTML/Cloudflare pour eviter de sauvegarder une page de challenge comme ROM;
- validation finale MD5, puis taille DAT si aucun MD5 n'est disponible;
- fallback provider apres erreur reseau, timeout, quota, rate-limit ou validation KO;
- circuit-breaker par source pendant la session;
- metriques provider persistantes pour reordonner les sources les plus fiables.

Les politiques par source se reglent dans la GUI: activation, ordre, timeout, quota par run et delai avant telechargement. LoLROMs utilise par defaut un delai pour limiter les blocages Cloudflare.

## Configuration

Copiez `.env.example` vers `.env`.

Variables courantes:

- `ONE_FICHIER_API_KEY`
- `ALLDEBRID_API_KEY`
- `REALDEBRID_API_KEY`
- `IA_S3_ACCESS_KEY`
- `IA_S3_SECRET_KEY`
- `LIBTORRENT_DLL_DIR` si vous utilisez le backend Python libtorrent avec DLL OpenSSL 1.1.

`aria2c` est le backend torrent Minerva prioritaire quand il est present dans le `PATH` ou installe via Winget/Chocolatey. Si `aria2c` et `libtorrent` sont absents, seules les sources HTTP/DDL restent disponibles.

## Structure

- `main.py`: point d'entree.
- `VERSION`: version SemVer utilisee par CLI, GUI et releases.
- `ROMDownloader.spec`: configuration PyInstaller officielle.
- `src/core/`: pipeline applicatif, GUI, DAT, scrapers, verification, torrentzip.
- `src/network/`: sessions, caches, circuit-breaker, metriques, pools.
- `src/providers/`: interface provider commune.
- `assets/`: icones/images GUI.
- `dat/`: DAT proposes dans le menu GUI.
- `db/shard_*.zip`: base locale de recherche checksum.
- `.github/workflows/`: CI, packaging Windows, release Windows.

## Verification locale

```powershell
$files = @("main.py") + (Get-ChildItem src,tests -Recurse -Filter *.py | ForEach-Object { $_.FullName })
python -m py_compile @files
python tests\smoke_checks.py
python tests\core_helper_checks.py
python main.py --version
python main.py --sources
python main.py --diagnose
```

Build exe portable:

```powershell
pyinstaller --noconfirm --clean ROMDownloader.spec
dist\ROMDownloader.exe --version
dist\ROMDownloader.exe --sources
dist\ROMDownloader.exe --diagnose
```

Dans le diagnostic de l'exe, `Racine app` doit pointer vers le dossier contenant `ROMDownloader.exe`, pas vers un dossier temporaire `_MEI...`.

## Release mainteneur

```powershell
.\release.ps1 -Version 0.1.4 -Push
```

Le workflow `Release Windows` construit `ROMDownloader.exe`, genere `ROMDownloader.exe.sha256`, valide l'exe portable et attache les assets a la release GitHub quand le tag `v*` est pousse.
