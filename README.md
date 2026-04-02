# ROM Downloader

Compare un DAT No-Intro ou Redump deja retraite avec Retool a un dossier cible, detecte les ROMs manquantes, puis telecharge ce qui manque en priorite depuis Minerva.

## Fonctionnement

Le workflow attendu est simple :

1. Tu donnes un fichier `.dat`.
2. Tu donnes un dossier de sortie, qui peut deja contenir des ROMs.
3. Tu peux laisser l'URL source vide pour la detection automatique Minerva, ou renseigner manuellement la bonne URL console si besoin.
4. Le script verifie ce qui est deja present dans le dossier.
5. Il ne telecharge que les jeux manquants.
6. A la fin, il ecrit un rapport texte dans le dossier de destination avec le resume complet et surtout les jeux manquants.

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

## Ordre de recherche

L'ordre reel de recherche est le suivant :

1. `Minerva` en source principale, en se basant sur le DAT detecte ou sur l'URL manuelle si tu en fournis une.
2. `rom_database.zip` comme catalogue local de fallbacks.
3. `EdgeEmu`, `PlanetEmu` et `LoLROMs` si le jeu n'a pas encore ete resolu.
4. `archive.org` en recherche live par `md5 -> crc -> sha1 -> nom` quand aucun autre fallback n'a abouti.

Important :
La base locale peut elle-meme renvoyer des liens `archive.org`, `1fichier` ou d'autres URLs directes. En pratique, `archive.org` peut donc etre atteint soit via la base locale, soit via la recherche live finale.

## Sources de telechargement

- `Minerva No-Intro`, `Minerva Redump`, `Minerva TOSEC` : source principale
- `rom_database.zip` : catalogue local de fallbacks
- `archive.org` : fallback direct via base locale ou recherche live checksum
- `LoLROMs` : fallback direct via listing Cloudflare-compatible
- `EdgeEmu` : fallback direct
- `PlanetEmu` : fallback direct
- `1fichier (Gratuit)` : fallback

Minerva est telecharge en direct via torrent sans sortir de l'application.

## Rapport de fin

Chaque execution ecrit un fichier `rom_downloader_report_*.txt` dans le dossier de destination.

Le rapport contient notamment :

- le DAT utilise
- le systeme detecte
- les sources actives
- le nombre de jeux resolus / telecharges / ignores / en echec
- la liste complete des jeux introuvables
- le recap `ToSort` si l'option est active

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
pip install cloudscraper
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

## Notes

- L'URL source est optionnelle.
- Si elle est vide, le script essaie de deduire automatiquement la bonne collection Minerva depuis le DAT.
- Les fichiers ZIP locaux sont aussi inspectes pour verifier les checksums internes quand la taille correspond au DAT.

## Validation

Le fonctionnement principal a ete verifie sur les DAT d'exemple du repo, avec des telechargements reels :

- `Minerva` : `Malibu Beach Volleyball (USA)`
- `archive.org` via base locale : `4 in 1 (Europe) (4B-001, Sachen-Commin) (Unl)`
- `LoLROMs` : `10-Pin Bowling (USA) (Proto)`
- `EdgeEmu` : `Malibu Beach Volleyball (USA)`
- `PlanetEmu` : `4 in 1 (Europe) (4B-001, Sachen-Commin) (Unl)`

## Verification rapide

```bash
python rom_downloader.py --sources
python -m py_compile rom_downloader.py
```
