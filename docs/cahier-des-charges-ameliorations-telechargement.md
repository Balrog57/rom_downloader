# Cahier des charges - Ameliorations interface, telechargements et providers

## 1. Objectif

Faire evoluer ROM Downloader vers une interface de catalogue et de telechargement plus rapide, plus fiable et plus observable, sans dependance aux images. Le logiciel doit exploiter progressivement la base SQLite locale, apprendre quels providers fonctionnent pour chaque jeu, couvrir les DAT actuels et futurs, et gerer proprement les protections reseau, notamment Cloudflare.

## 2. Inspirations retenues

- Pixel Nostalgia structure les contenus par plateformes, materiels et familles de systemes, avec des rubriques comme Arcade, Console, Portable, Computer, Port, Pinball et Lite Packages. Cette logique doit inspirer les filtres de systemes et les regroupements DAT.
- Pixel Nostalgia affiche aussi une logique de publication par systeme avec nom court, plateforme cible et date. ROM Downloader doit reprendre l'idee sous forme textuelle: systeme, section DAT, date DAT, nombre de jeux, taille estimee, couverture providers.
- RGSX met en avant la detection automatique des systemes depuis `es_systems.cfg`, la gestion des archives, les API premium, le filtrage avance, la file d'attente, l'historique et les notifications de progression.
- RGSX propose une interface web locale avec parcours tous systemes, ajout de telechargements a distance, statut temps reel et historique partage avec l'application principale.
- RGSX expose des controles utiles dans les menus: mise a jour du cache jeux, scan des ROMs possedees, historique, filtre plateformes, selection dossier ROMs, extraction automatique, statut API, statut de connexion et DNS personnalise.
- PixN-Tools apporte surtout une idee de bootstrap/mise a jour simple, mais le modele batch/VBS/wget ne doit pas etre repris tel quel. L'inspiration utile est: un mode diagnostic/update autonome, relancable, loggue et capable de recuperer ses composants.

Sources consultees:

- https://pixelnostalgia.github.io/
- https://github.com/RetroGameSets/RGSX
- https://raw.githubusercontent.com/RetroGameSets/RGSX/main/README_FR.md
- https://github.com/RGS-MBU/PixN-Tools
- https://raw.githubusercontent.com/RGS-MBU/PixN-Tools/main/PixN-RB-Update-Service.cmd

## 3. Etat local constate

- La GUI actuelle est deja une interface catalogue sombre sans images, avec pages Accueil, Systemes, Jeux, Telechargements, Historique et Sources.
- La base SQLite locale existe deja et contient les tables `systems`, `games`, `roms`, `provider_successes`, `download_jobs`, `download_attempts` et `provider_metrics`.
- Etat mesure de la base locale actuelle:
  - 595 systemes indexes.
  - 403 877 jeux indexes.
  - 2 275 064 ROMs indexees.
  - 0 provider valide persiste.
  - 0 tentative de telechargement SQLite.
- Couverture de mapping mesuree sur 298 noms de systemes uniques DAT:
  - LoLROMs: 298 couverts.
  - Vimm: 50 couverts.
  - PlanetEmu: 44 couverts.
  - CoolROM: 44 couverts.
  - RetroGameSets: 40 couverts.
  - RomHustler: 37 couverts.
  - RomsXISOs: 35 couverts.
  - StartGame: 23 couverts.
  - archive.org cible: 16 couverts.
  - NoPayStation: 6 couverts.
  - hShop: 1 couvert.
  - Minerva et archive.org generique ne sont pas couverts par mapping simple, car ils demandent une logique par collection/identifier.

## 4. Principes produit

1. Le telechargement doit etre prioritaire sur l'esthetique: lisibilite, rapidite, reprise, fiabilite et diagnostic.
2. L'interface reste sans images: listes, tableaux, badges textuels, compteurs, filtres et panneaux de statut.
3. Chaque action longue doit etre persistante: indexation, resolution provider, telechargement, verification, repack TorrentZip et erreur.
4. La DB devient la source de verite locale: plus de dependance a des caches JSON pour les decisions critiques.
5. Les providers doivent etre evalues par preuve: lien resolu, fichier telecharge, hash valide, vitesse, erreurs, quota et derniere reussite.
6. Les sources Cloudflare doivent etre lentes mais fiables: bascule controlee vers navigateur, delai adaptatif, circuit breaker et reprise.

## 5. Interface cible sans images

### 5.1 Page Accueil

Ajouter un tableau de bord compact:

- Systemes indexes.
- Jeux indexes.
- Jeux deja verifies localement.
- Providers valides en DB.
- Tentatives des dernieres 24 h.
- Vitesse moyenne globale.
- Sources actuellement bloquees par circuit breaker.
- Jobs en cours, en pause, echoues, termines.

Critere d'acceptation: l'utilisateur voit en moins de 5 secondes si le catalogue est pret, si les sources sont disponibles et si des telechargements sont actifs.

### 5.2 Page Systemes

Remplacer la simple liste par une vue orientee coverage:

- Colonnes: systeme, section DAT, jeux, taille, date DAT extraite du nom, coverage provider, local complet, statut mapping.
- Filtres: Tous, No-Intro, Redump, Retool, Arcade, Console, Portable, Computer, Port, Pinball, Custom, Non-Redump, Source Code.
- Recherche globale systeme/DAT.
- Tri par couverture provider, nombre de jeux, taille, date DAT.
- Badge texte:
  - `OK`: au moins un provider valide ou mappable.
  - `PARTIEL`: mapping connu mais non valide.
  - `A MAPPER`: aucun provider exploitable.
  - `LOCAL`: systeme deja complet dans le dossier ROMs.

Critere d'acceptation: on peut identifier les systemes sans provider fiable sans ouvrir chaque DAT.

### 5.3 Page Jeux

Ajouter une vue de travail proche de RGSX mais textuelle:

- Colonnes: jeu, ROM principale, taille, providers valides, providers candidats, statut local, derniere erreur.
- Filtres alphabetiques existants conserves.
- Nouveaux filtres: manquants, deja presents, providers valides, sans provider, erreur hash, erreur reseau.
- Actions:
  - `Ajouter a la file`.
  - `Telecharger maintenant`.
  - `Resoudre providers`.
  - `Verifier local`.
  - `Copier diagnostic`.

Critere d'acceptation: l'utilisateur peut preparer une file sans lancer immediatement le telechargement.

### 5.4 Page Telechargements

Transformer la page en vrai gestionnaire de file:

- Onglet `File`: jobs en attente, actifs, en pause.
- Onglet `Actifs`: progression par fichier et par job.
- Onglet `Erreurs`: erreurs regroupables par provider, code HTTP, hash, timeout, Cloudflare, quota.
- Onglet `Historique`: historique SQLite filtre.
- Actions job: pause, reprise, annulation propre, reessayer les echecs, ouvrir dossier, exporter rapport.
- Actions provider: desactiver temporairement, reduire parallele, augmenter delai, reset circuit breaker.

Critere d'acceptation: fermer et relancer l'application ne doit pas faire perdre la file ni l'etat des tentatives.

### 5.5 Page Sources

Ajouter un tableau de pilotage provider:

- Colonnes: actif, provider, type, priorite, couverture DAT, succes, echecs, vitesse, quota, delai, timeout, dernier succes, dernier echec.
- Bouton `Tester connexion`.
- Bouton `Diagnostiquer Cloudflare`.
- Bouton `Scanner mapping`.
- Bouton `Purger cookies/session provider`.
- Edition directe des politiques: parallele max, delai, timeout, quota par run, mode premium requis.

Critere d'acceptation: les sources lentes ou cassees peuvent etre isolees sans modifier le code.

## 6. Moteur de telechargement cible

### 6.1 File persistante

Etendre `download_jobs` et `download_attempts` pour representer une vraie queue:

- `download_jobs`: ajouter `priority`, `paused_at`, `started_at`, `finished_at`, `error_count`, `bytes_total`, `bytes_done`, `settings_json`.
- Nouvelle table `download_queue_items`:
  - `item_id`, `job_id`, `game_id`, `system_id`, `status`, `priority`, `attempt_count`, `next_retry_at`, `locked_by`, `locked_at`, `created_at`, `updated_at`.
- Nouvelle table `provider_candidates`:
  - `game_id`, `provider`, `confidence`, `download_url`, `page_url`, `torrent_url`, `metadata_json`, `last_checked_at`, `expires_at`, `status`.

Regle: les candidates non verifiees vont dans `provider_candidates`; seuls les telechargements MD5/CRC/SHA1 valides vont dans `provider_successes`.

### 6.2 Ordonnancement rapide et fiable

Implementer une strategie par provider:

1. Reutiliser d'abord `provider_successes` pour le meme jeu.
2. Reutiliser ensuite `provider_candidates` non expirees.
3. Resoudre en parallele les providers mappes et actifs.
4. Prioriser par score:
   - hash deja valide: tres haut.
   - provider premium debride configure: haut.
   - torrent Minerva pour gros sets: haut si seed OK.
   - direct HTTP rapide: moyen.
   - Cloudflare: bas sauf si seul provider.
5. Appliquer un circuit breaker par provider et par type d'erreur.
6. Adapter automatiquement `parallel_downloads` par provider:
   - Premium/debrid: parallele haut.
   - HTTP direct stable: parallele moyen.
   - Cloudflare/LoLROMs: parallele 1 et delai adaptatif.
   - Provider avec quota: respect strict du quota.

Critere d'acceptation: un echec provider n'arrete pas le job tant qu'un provider alternatif existe.

### 6.3 Reprise et verification

Exigences:

- Tous les telechargements HTTP utilisent `.part`, Range et reprise si le serveur le permet.
- Apres telechargement, verifier hash DAT avant de marquer le provider comme valide.
- En cas de hash KO:
  - deplacer ou supprimer selon politique.
  - enregistrer `checksum_mismatch`.
  - penaliser le provider pour ce jeu, pas forcement tout le provider.
- Pour `.7z`, verifier les entrees internes comme deja prevu, puis proposer repack TorrentZip automatique pour les sets RomVault.
- Ne jamais sauver une page HTML Cloudflare comme ROM.

Critere d'acceptation: chaque fichier final a un statut clair: valide, invalide, abandonne, ou en attente de verification.

## 7. Alimentation progressive de la DB

### 7.1 Pendant la resolution

Pour chaque jeu:

- Enregistrer les providers candidats avec URL, nom fichier, taille annoncee, date de scan, source mapping utilisee.
- Marquer `not_found` par provider avec TTL court, pour eviter de rescanner en boucle.
- Marquer les erreurs temporaires avec TTL court: timeout, Cloudflare, 429, 5xx.
- Marquer les erreurs definitives avec TTL long: systeme non supporte, jeu absent, lien mort 404.

### 7.2 Pendant le telechargement

Pour chaque tentative:

- Enregistrer debut, fin, duree, bytes, vitesse moyenne, provider, URL, code erreur.
- Enregistrer les transitions de statut dans SQLite.
- Mettre a jour `provider_metrics` apres chaque tentative, pas seulement en fin de job.
- Enregistrer les succes dans `provider_successes` uniquement apres verification.

### 7.3 Apres le job

Produire un resume:

- Jeux telecharges.
- Jeux deja presents.
- Jeux introuvables.
- Jeux avec erreur reseau.
- Jeux avec erreur hash.
- Providers les plus rapides.
- Providers les plus defectueux.
- Nouveaux liens valides ajoutes a la DB.

Critere d'acceptation: un second run du meme systeme doit etre plus rapide grace aux providers valides deja appris.

## 8. Mapping providers/DAT actuel et futur

### 8.1 Inventaire automatique

Creer une commande:

```powershell
python main.py --mapping-status
```

Sortie attendue:

- Nombre de DAT.
- Nombre de systemes uniques.
- Couverture par provider.
- Liste des systemes sans mapping exploitable.
- Liste des mappings suspects ou ambigus.
- Export CSV/JSON optionnel.

### 8.2 Regles de mapping

Pour chaque systeme DAT:

- Conserver le mapping explicite dans `SYSTEM_MAPPINGS`.
- Ajouter une table SQLite ou fichier JSON genere pour les aliases decouverts automatiquement.
- Gerer les variantes:
  - Redump vs No-Intro.
  - Retool derive d'un DAT parent.
  - noms courts Batocera/Retrobat.
  - noms Pixel Nostalgia.
  - slugs provider.
  - variantes region/media: CD, Digital, PSN, CDN, BIOS, Updates, DLC.
- Ne pas considerer `lolroms` comme unique preuve de couverture: il faut distinguer mapping theorique et lien telechargeable valide.

### 8.3 Probing provider

Ajouter un mode de scan non destructif:

```powershell
python main.py --probe-providers --system "Nintendo - Game Boy Advance" --limit 50
```

Il doit:

- Tester les providers actifs sans telecharger les fichiers complets.
- Recuperer HEAD/metadata quand possible.
- Tester les pages de listing.
- Detecter Cloudflare/challenge/HTML.
- Enregistrer les candidates dans `provider_candidates`.

Critere d'acceptation: on peut ameliorer la couverture provider sans lancer de gros telechargements.

### 8.4 Tests de couverture

Etendre `tests/dat_coverage_checks.py`:

- Garder LoLROMs comme couverture minimale actuelle si souhaite.
- Ajouter un seuil par provider configurable.
- Ajouter un seuil global: chaque systeme doit avoir au moins un provider potentiel hors `archive_org` generique, ou etre marque explicitement `unsupported`.
- Echouer si un nouveau DAT n'a aucun mapping ni exclusion documentee.

## 9. Gestion Cloudflare

### 9.1 Detection

Centraliser la detection Cloudflare:

- HTTP 403/429/503 avec headers Cloudflare.
- `content-type: text/html` pour URL archive/ROM.
- marqueurs `Just a moment`, `cf-mitigated`, `challenge-platform`, `__cf_chl`.
- taille anormale pour fichier attendu.

### 9.2 Strategie LoLROMs et sites proteges

Politique cible:

1. Session `cloudscraper` avec cookies persistants par provider.
2. Prechauffage: visite accueil + dossier systeme avant fichier.
3. Si challenge:
   - parallele force a 1 pour ce provider.
   - delai augmente progressivement.
   - circuit breaker specifique `cloudflare_challenge`.
4. Fallback Playwright headless pour listing.
5. Fallback Edge natif visible pour validation humaine si necessaire.
6. Reutilisation des cookies valides apres validation.
7. Si echec repete: source bloquee temporairement, job continue sur providers alternatifs.

### 9.3 Interface Cloudflare

Ajouter dans la page Sources:

- statut `OK`, `Challenge`, `Bloque`, `Cooldown`.
- bouton `Valider dans le navigateur`.
- affichage du prochain retry.
- affichage du delai adaptatif courant.

Critere d'acceptation: l'utilisateur comprend pourquoi LoLROMs ralentit ou se bloque, et le job ne sauvegarde jamais de faux fichiers HTML.

## 10. Gestion erreurs

Normaliser les erreurs avec codes internes:

- `network_timeout`
- `http_403`
- `http_404`
- `http_429`
- `http_5xx`
- `cloudflare_challenge`
- `quota_exceeded`
- `provider_not_mapped`
- `game_not_found`
- `checksum_mismatch`
- `archive_invalid`
- `disk_full`
- `permission_denied`
- `cancelled`
- `user_paused`

Chaque erreur doit avoir:

- message utilisateur en francais.
- detail technique pour rapport.
- retryable oui/non.
- delai de retry.
- impact provider: aucun, penalite jeu, penalite provider, circuit breaker.

Critere d'acceptation: l'historique permet de filtrer et reessayer uniquement les echecs utiles.

## 11. Performance

Objectifs mesurables:

- Index catalogue incremental: ne reparsing que les DAT modifies.
- Recherche jeux sous 200 ms sur systeme moyen, avec index SQLite adapte.
- Resolution provider: parallele par provider, timeout court configurable.
- Telechargement: saturer la bande passante quand providers rapides, sans declencher de rate-limit sur providers sensibles.
- DB: commits par batch pour gros jobs, WAL conserve.

Ameliorations techniques:

- Ajouter index SQLite sur `provider_successes(provider)`, `download_attempts(status)`, `download_jobs(status)`.
- Ajouter recherche FTS5 optionnelle pour `games.game_name` et `systems.system_name`.
- Mettre en cache les mappings resolus par `(system_name, provider)`.
- Eviter de reparser les DAT dans `run_download_job` si `games`/`roms` sont deja en DB et a jour.

## 12. Priorites de livraison

### P0 - Fondations fiables

- Ajouter vraie queue persistante.
- Enregistrer toutes les tentatives dans SQLite.
- Persister provider candidates et provider successes.
- Normaliser les erreurs.
- Ajouter `--mapping-status`.
- Ajouter diagnostic Cloudflare centralise.

### P1 - Rapidite et UX

- Refondre pages Systemes, Jeux, Telechargements et Sources en tableaux de pilotage.
- Ajouter pause/reprise/retry echecs.
- Ajouter tri et filtres par couverture provider/statut local/erreur.
- Ajouter score provider et priorisation dynamique.
- Ajouter index incremental DAT.

### P2 - Couverture provider

- Ajouter probe non destructif des providers.
- Mapper systematiquement les providers premium et collections archive.org/Minerva.
- Ajouter exports CSV/JSON des manques.
- Ajouter tests de seuil de couverture.

### P3 - Service distant optionnel

- Ajouter une API locale/Web UI optionnelle inspiree de RGSX:
  - liste systemes/jeux.
  - ajout file.
  - statut temps reel.
  - historique.
  - test sources.

## 13. Definition de termine

Une iteration est terminee quand:

- Les tests existants passent:

```powershell
$files = @("main.py") + (Get-ChildItem src,tests -Recurse -Filter *.py | ForEach-Object { $_.FullName }); python -m py_compile @files
python tests\smoke_checks.py
python tests\core_helper_checks.py
```

- Les nouveaux tests de DB/queue/mapping passent.
- Un run interrompu peut reprendre sans doublons.
- Un echec Cloudflare est visible, non destructif et n'arrete pas les autres providers.
- Un succes telecharge alimente `provider_successes`.
- Un second run reutilise les providers valides et fait moins de resolution reseau.
- Le rapport final explique clairement ce qui est telecharge, ignore, introuvable, invalide ou a reessayer.
