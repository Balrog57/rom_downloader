# Packaging et installation Windows

Ce depot reste centre sur le runtime Python, mais il fournit aussi un circuit de versioning et de distribution Windows via GitHub Releases.

## Installation utilisateur

Depuis PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/Balrog57/rom_downloader/main/install.ps1 | iex"
```

Options utiles:

```powershell
.\install.ps1 -Version 0.1.0
.\install.ps1 -InstallDir "$env:LOCALAPPDATA\ROMDownloader" -Force
.\install.ps1 -NoDesktopShortcut
```

L'installateur telecharge `ROMDownloader-windows-<version>.zip` depuis la derniere release GitHub, extrait l'application dans `%LOCALAPPDATA%\ROMDownloader`, cree les raccourcis, et genere `uninstall.ps1`.

Pour desinstaller:

```powershell
& "$env:LOCALAPPDATA\ROMDownloader\uninstall.ps1"
```

Avec `-KeepConfig`, le desinstalleur conserve `.env` et `.rom_downloader_preferences.json`.

## Versioning

La version applicative est stockee dans `VERSION` et exposee par:

```powershell
python main.py --version
ROMDownloader.exe --version
```

Format attendu: SemVer (`MAJOR.MINOR.PATCH`, par exemple `0.1.0`).

Pour publier une release:

```powershell
.\release.ps1 -Version 0.1.0 -Push
```

Le workflow `Release Windows` construit l'executable, cree une archive portable versionnee, publie un checksum `.sha256`, puis cree la release GitHub.

## Archive portable

L'archive de release contient:

- `ROMDownloader.exe`
- `VERSION`
- `.env.example`
- `README.md`
- `PACKAGING_WINDOWS.md`
- `install.ps1`

Sur une machine Windows propre:

```powershell
.\ROMDownloader.exe --version
.\ROMDownloader.exe --gui
```

Le binaire PyInstaller embarque `assets/`, `dat/` et `db/`.

## Points a verifier

- `libtorrent` peut ne pas etre disponible ou echouer a l'import avec `DLL load failed` selon le wheel et l'environnement Windows. Si cela arrive, Minerva torrent sera indisponible, mais les autres sources et la GUI restent utilisables.
- `py7zr` et `rarfile` sont inclus pour valider les archives `.7z` et `.rar`; la verification ZIP utilise la bibliotheque standard Python.
- `tkinterdnd2` est optionnel. Si le backend DnD ne repond pas, la GUI demarre quand meme avec les boutons `Parcourir`.
- `7-Zip` est utile pour verifier/repack les archives `.7z`. Le programme cherche `7z.exe` dans le PATH et dans les emplacements Windows courants.
- `.env` doit rester local et ne doit pas etre inclus dans une archive publique.

## Verification avant livraison

```powershell
$files = @("main.py") + (Get-ChildItem src,tests -Recurse -Filter *.py | ForEach-Object { $_.FullName })
python -m py_compile @files
python tests\smoke_checks.py
python tests\core_helper_checks.py
python main.py --version
python main.py --sources
```

## Workflows GitHub

- `CI`: compilation, smoke checks et garde anti-regression.
- `Windows Package`: build manuel simple de `ROMDownloader.exe`.
- `Release Windows`: publication versionnee sur tag `v*`.

Il faut tester explicitement apres generation l'acces en ecriture aux caches locaux `.rom_downloader_*.json`, le backend torrent `aria2c`, et le comportement de `tkinterdnd2` dans le bundle.
