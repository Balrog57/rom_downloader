# ROM Downloader

Compare un DAT No-Intro ou Redump deja retraite avec Retool a un dossier cible, detecte les ROMs manquantes, puis telecharge ce qui manque en priorite via les sources DDL. Les torrents Minerva restent le dernier recours.

## Fonctionnement

Le workflow attendu est simple :

1. Tu donnes un fichier `.dat`.
2. Tu donnes un dossier de sortie, qui peut deja contenir des ROMs.
3. Tu peux laisser l'URL source vide pour utiliser l'ordre automatique DDL puis Minerva, ou renseigner manuellement une URL de listing si besoin.
4. Le script verifie ce qui est deja present dans le dossier.
5. Il ne telecharge que les jeux manquants.
6. A la fin, il ecrit un rapport texte dans le dossier de destination avec le resume complet et surtout les jeux manquants.

Le projet est pense pour des DAT 1G1R deja prepares avec Retool. Des exemples sont fournis dans [dat.exemple](dat.exemple).

Le projet est autonome pour son interface :

- les assets GUI necessaires sont inclus dans [assets](assets)
- il ne depend plus du dossier `Balrog Toolkit`

## Priorite de correspondance

Pour verifier si un jeu est deja present localement, la priorite est :

1. `md5`
2. `crc`
3. `sha1`
4. nom de ROM
5. nom du jeu

Le meme ordre est utilise pour les fallbacks `archive.org` quand c'est possible.

Note importante :
La base locale active est fragmente en shards SQLite zippes dans `rom_db_shards/shard_*.zip`. Les shards reconstruits depuis Minerva sont indexes par MD5 et ne necessitent pas de conserver la DB source officielle dans le repo.

## Ordre de recherche

L'ordre reel de recherche est le suivant :

1. Shards locaux `rom_db_shards/shard_*.zip` comme catalogue MD5, avec recherche `md5 -> crc -> sha1 -> nom`.
2. Sources DDL specialisees: `RetroGameSets`, `EdgeEmu`, `PlanetEmu`, `LoLROMs`, `CDRomance`, `Vimm's Lair` et liens directs compatibles.
3. `archive.org` en recherche live par `md5 -> crc -> sha1 -> nom` quand aucun DDL n'a abouti.
4. `Minerva` via torrent uniquement en dernier recours, en se basant sur le DAT detecte ou sur l'URL manuelle si tu en fournis une.

Important :
La base locale peut elle-meme renvoyer des liens `archive.org`, `1fichier` ou d'autres URLs directes. En pratique, `archive.org` peut donc etre atteint soit via la base locale, soit via la recherche live finale.

## Sources de telechargement

- `rom_db_shards/shard_*.zip` : catalogue local MD5 fragmente et zippe
- `archive.org` : DDL via base locale ou recherche live checksum
- `RetroGameSets` : DDL communautaire / 1fichier
- `LoLROMs` : DDL via listing Cloudflare-compatible
- `EdgeEmu` : DDL
- `PlanetEmu` : DDL avec POST/token
- `CDRomance` : DDL avec ticket
- `Vimm's Lair` : DDL via formulaire
- `1fichier (Gratuit)` : DDL avec attente si necessaire
- `Minerva No-Intro`, `Minerva Redump`, `Minerva TOSEC` : dernier recours torrent

Etat de la base locale au 2026-04-19 :

- les shards `rom_db_shards/shard_*.zip` ont ete reconstruits depuis `minerva hashes officiel.db`
- les DAT sources sont `dat.exemple/no-intro` et `dat.exemple/redump`
- le matching Minerva officiel est strictement fait par MD5 DAT
- la DB source officielle et les rapports de build sont ignores par Git apres generation

Apres chaque telechargement, le MD5 est verifie par rapport au DAT. Pour un ZIP, la verification se fait sur les fichiers internes, pas sur le MD5 du conteneur ZIP.
Si le MD5 ne correspond pas au DAT, le fichier telecharge est supprime et le meme jeu est retente automatiquement sur le provider suivant jusqu'a epuisement des sources.

Minerva est telecharge en direct via torrent sans sortir de l'application, mais seulement apres les sources DDL.

## Reconstruction de la base Minerva

La base locale se reconstruit depuis `minerva hashes officiel.db` en matchant les DAT No-Intro et Redump par MD5. Ce fichier source est volumineux et n'est pas conserve dans le repo apres la generation des shards.

```bash
python scripts/build_minerva_hash_shards.py
```

Par defaut, le script lit :

- `dat.exemple/no-intro`
- `dat.exemple/redump`

Il ecrit 16 shards SQLite compresses dans `rom_db_shards/shard_*.zip` et produit temporairement `rom_db_shards/build_report.json`. Les anciens shards sont deplaces dans un dossier `rom_db_shards_backup_YYYYMMDD_HHMMSS`. Le rapport, la DB source et les backups sont ignores par Git.

Dernier rebuild execute :

- DAT parses : `340`
- MD5 DAT uniques : `1,632,262`
- MD5 trouves dans la DB officielle Minerva : `3,690`
- Entrees Minerva correspondantes : `7,966`

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

- [rom_downloader.py](rom_downloader.py) : script principal
- [assets](assets) : icones locales necessaires a la GUI
- [scripts/build_minerva_hash_shards.py](scripts/build_minerva_hash_shards.py) : reconstruit les shards depuis la DB officielle Minerva
- [scripts/minerva_torrent_download.js](scripts/minerva_torrent_download.js) : helper torrent Minerva
- [rom_db_shards](rom_db_shards) : base locale MD5 en shards SQLite zippes
- [dat.exemple](dat.exemple) : exemples de DAT No-Intro, Redump et Retool

## Options utiles

- `--dry-run` : simule sans telecharger
- `--limit N` : limite le nombre de telechargements
- `--tosort` : deplace le hors-DAT dans `ToSort`
- `--sources` : affiche les sources disponibles

## Notes

- L'URL source est optionnelle.
- Si elle est vide, le script essaie les DDL en premier puis deduit automatiquement la bonne collection Minerva depuis le DAT pour le dernier recours.
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
