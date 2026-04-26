# Packaging Windows portable

Ce depot reste centre sur le runtime Python. Aucun script de generation n'est requis dans le repo pour utiliser l'application.

## Option recommandee

Distribuer une archive portable contenant:

- `main.py`
- `src/`
- `assets/`
- `dat/`
- `db/shard_*.zip`
- `.env.example`
- `requirements.txt`
- `README.md`

Sur une machine Windows propre:

```powershell
py -3.13 -m venv .venv
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py --diagnose
python main.py --gui
```

Activez le venv avant les commandes `python`/`pip` si vous ne lancez pas l'interpreteur directement depuis votre outil d'environnement.

## Points a verifier

- `libtorrent` peut ne pas etre disponible pour toutes les versions Python. Si l'installation echoue, Minerva torrent sera indisponible, mais les autres sources et la GUI restent utilisables.
- `tkinterdnd2` est optionnel. Si le backend DnD ne repond pas, la GUI demarre quand meme avec les boutons `Parcourir`.
- `7-Zip` est utile pour verifier/repack les archives `.7z`. Le programme cherche `7z.exe` dans le PATH et dans les emplacements Windows courants.
- `.env` doit rester local et ne doit pas etre inclus dans une archive publique.

## Verification avant livraison

```powershell
$files = @("main.py") + (Get-ChildItem src,tests -Recurse -Filter *.py | ForEach-Object { $_.FullName })
python -m py_compile @files
python tests\smoke_checks.py
python tests\core_helper_checks.py
python main.py --diagnose
```

## Executable

Un `.exe` PyInstaller est possible plus tard, mais il faudra tester explicitement:

- inclusion de `assets/`, `dat/` et `db/`;
- import dynamique des dependances optionnelles;
- acces en ecriture aux caches locaux `.rom_downloader_*.json`;
- comportement de `libtorrent` et `tkinterdnd2` dans le bundle.
