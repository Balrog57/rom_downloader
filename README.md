# ROM Downloader

Compare un DAT No-Intro ou Redump deja retraite avec Retool a un dossier cible, detecte les ROMs manquantes, puis telecharge ce qui manque en priorite depuis Minerva.

## Fonctionnement

Le workflow attendu est simple :

1. Tu donnes un fichier `.dat`.
2. Tu donnes un dossier de sortie, qui peut deja contenir des ROMs.
3. Tu peux laisser l'URL source vide pour la detection automatique Minerva, ou renseigner manuellement la bonne URL console si besoin.
4. Le script verifie ce qui est deja present dans le dossier.
5. Il ne telecharge que les jeux manquants.

Le projet est pense pour des DAT 1G1R deja prepares avec Retool. Des exemples sont fournis dans [dat.exemple](rom_downloader\dat.exemple).

## Priorite de correspondance

Pour verifier si un jeu est deja present localement, la priorite est :

1. `md5`
2. `crc`
3. `sha1`
4. nom de ROM
5. nom du jeu

Le meme ordre est utilise pour les fallbacks `archive.org` quand c'est possible.

Note importante :
La base locale `rom_database.zip` ne contient pas d'index checksum dedie. Elle sert donc surtout de fallback par nom de fichier ou nom de jeu.

## Sources de telechargement

- `Minerva No-Intro`, `Minerva Redump`, `Minerva TOSEC` : source principale
- `archive.org` : fallback
- `EdgeEmu` : fallback
- `PlanetEmu` : fallback
- `1fichier (Gratuit)` : fallback
- `1fichier (API)`, `AllDebrid (API)`, `RealDebrid (API)` : options necessitant une cle

Minerva est telecharge en direct via torrent sans sortir de l'application.

## Option ToSort

Si l'option est cochee, les fichiers presents dans le dossier mais absents du DAT sont deplaces vers un sous-dossier `ToSort`.

## Utilisation

### Interface graphique

```bash
python rom_downloader.py --gui
```

### Ligne de commande

```bash
python rom_downloader.py <fichier.dat> <dossier_roms> [url_source] [--dry-run] [--limit N] [--tosort]
```

Exemples :

```bash
python rom_downloader.py "dat.exemple\\retool\\Nintendo - Game Boy (20260314-052418) (Retool 2026-03-15 19-50-33) (625) (-nz) [-aABbcDdekMmoPrv].dat" "Roms\\Game Boy"

python rom_downloader.py "dat.exemple\\retool\\Sony - PlayStation (2026-03-15 02-49-21) (Retool 2026-03-15 19-51-21) (1,805) (-nz) [-aABbcDdekMmoPrv].dat" "Roms\\PS1" "https://minerva-archive.org/browse/Redump/Sony%20-%20PlayStation/"

python rom_downloader.py "dat.exemple\\retool\\Nintendo - Game Boy (20260314-052418) (Retool 2026-03-15 19-50-33) (625) (-nz) [-aABbcDdekMmoPrv].dat" "Roms\\Game Boy" "" --tosort
```

### Mode interactif

```bash
python rom_downloader.py
```

## Installation

### Prerequis

- Python 3.10 ou plus recent recommande
- Node.js et `npm` pour le helper torrent Minerva

### Dependances Python

Le script peut installer les dependances manquantes automatiquement. Sinon :

```bash
pip install requests beautifulsoup4 internetarchive
```

### Dependances Node

Le runtime torrent est installe automatiquement au premier telechargement Minerva. Si besoin :

```bash
npm install
```

## Structure utile

- [rom_downloader.py](rom_downloader\rom_downloader.py) : script principal
- [scripts/minerva_torrent_download.js](rom_downloader\scripts\minerva_torrent_download.js) : helper torrent Minerva
- [rom_database.zip](rom_downloader\rom_database.zip) : base locale des URLs
- [dat.exemple](rom_downloader\dat.exemple) : exemples de DAT No-Intro, Redump et Retool

## Options utiles

- `--dry-run` : simule sans telecharger
- `--limit N` : limite le nombre de telechargements
- `--tosort` : deplace le hors-DAT dans `ToSort`
- `--sources` : affiche les sources disponibles
- `--configure-api` : configure les services necessitant une cle

## Notes

- L'URL source est optionnelle.
- Si elle est vide, le script essaie de deduire automatiquement la bonne collection Minerva depuis le DAT.
- Les fichiers ZIP locaux sont aussi inspectes pour verifier les checksums internes quand la taille correspond au DAT.

## Verification rapide

```bash
python rom_downloader.py --sources
python -m py_compile rom_downloader.py
```
