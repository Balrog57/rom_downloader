# Guide utilisateur ROM Downloader

Ce guide couvre le parcours recommande pour utiliser ROM Downloader sans surprise: audit d'abord, telechargement ensuite, puis rapport final.

## Premier lancement avec l'EXE

1. Telechargez `ROMDownloader.exe` depuis la release GitHub `v0.1.4`.
2. Placez-le dans un dossier dedie, par exemple `D:\Apps\ROMDownloader`.
3. Lancez l'exe.
4. Chargez un DAT No-Intro, Redump ou Retool.
5. Choisissez le dossier qui contient deja vos ROMs ou le dossier de sortie.
6. Lancez d'abord un audit dry-run.

Les fichiers de configuration, caches et preferences sont crees a cote de l'exe. Gardez ce dossier ensemble si vous deplacez l'application.

## Audit dry-run recommande

Le dry-run est le mode le plus sur pour commencer: il analyse, estime et produit un rapport sans ecrire de ROM finale.

```powershell
python main.py "dat\Nintendo - Game Boy Advance.dat" "D:\Roms\GBA" --dry-run --report-formats txt,json,csv,html
```

Le rapport indique les jeux attendus, deja presents, manquants, resolus via providers, introuvables et les tailles estimees. Utilisez ce rapport pour verifier le DAT et le dossier avant tout telechargement reel.

## DAT Retool et 1G1R

ROM Downloader ne choisit pas les variantes 1G1R en interne. Pour obtenir un set 1G1R, fournissez directement un DAT Retool ou 1G1R deja filtre.

Exemple:

```powershell
python main.py "dat\Retool - French No Unl\Nintendo - Game Boy Advance.dat" "D:\Roms\GBA" --dry-run
```

Le logiciel suit le DAT donne: regions, langues, exclusions beta/demo/proto et choix 1G1R doivent donc etre faits avant, dans le DAT.

## Web UI locale

La Web UI locale permet de piloter l'analyse et les jobs depuis un navigateur local.

```powershell
python main.py --web
```

Adresse par defaut:

```text
http://127.0.0.1:8888
```

Pour choisir le port:

```powershell
python main.py --web 127.0.0.1:8890
```

Pages utiles:

- `Accueil`: statistiques et formulaire analyse/job.
- `Systemes`: navigation catalogue.
- `Jobs`: suivi, pause, reprise, retry et annulation.
- `Sources`: etat SQLite, couverture candidats, dernier diagnostic, test source et nettoyage cache.
- `Historique`: tentatives passees.

Les endpoints `/api/*` renvoient du JSON et utilisent le polling, pas de WebSocket.

## Sortie RomVault et TorrentZip

Pour une sortie compatible RomVault, utilisez les modes de sortie et d'archive explicites:

```powershell
python main.py "dat\Nintendo - Game Boy Advance.dat" "D:\Roms\GBA" --output-mode verified --archive-mode torrentzip
```

Pour les sets LoLROMs GBA, `--clean-torrentzip` reste compatible et convertit les archives validees en ZIP TorrentZip:

```powershell
python main.py "dat\Nintendo - Game Boy Advance.dat" "D:\Roms\GBA" --clean-torrentzip
```

Pour reconstruire depuis un dossier `ToSort`:

```powershell
python main.py "dat\Nintendo - Game Boy Advance.dat" "D:\Roms\GBA" --rebuild-tosort --output-mode verified
```

Le rebuilder v1 matche par MD5, SHA1, CRC ou taille unique. Il ne remplace pas RomVault pour les sets arcade split/merged complexes.

## FAQ rapide

**Cloudflare ou page HTML**  
ROM Downloader detecte les reponses HTML suspectes et les marque comme erreur reseau. Reduisez le parallele, augmentez le delai LoLROMs ou desactivez temporairement la source.

**Hash KO / MD5 invalide**  
Le fichier est ignore ou nettoye selon le flux, le provider est penalise, et le rapport conserve le detail. Relancez avec un autre provider ou inspectez le DAT.

**archive.org demande un compte**  
Renseignez `ARCHIVE_ORG_USERNAME` et `ARCHIVE_ORG_PASSWORD` dans `.env` si la collection exige une session.

**aria2c absent**  
Minerva utilise `aria2c` en priorite pour les torrents. Installez-le via Winget/Chocolatey ou laissez l'application utiliser les sources HTTP disponibles.

**CHD**  
Les CHD sont detectes et peuvent etre valides par hash/taille si le DAT contient les informations utiles. ROM Downloader ne convertit pas les CHD et ne reconstruit pas les sets arcade split/merged complets.

**Myrient**  
Myrient reste hors scope comme provider expose. Minerva torrent et archive.org restent les derniers recours.
