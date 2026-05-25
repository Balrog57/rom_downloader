# Roadmap ROM Downloader

Cette roadmap transforme les objectifs produit en lots suivables. Elle garde deux limites volontaires:

- Myrient n'est pas une source a gerer directement. Minerva torrent et archive.org restent les derniers recours.
- ROM Downloader ne choisit pas les variantes 1G1R. Pour un set 1G1R, utilisez un DAT Retool/1G1R deja filtre.

## Court terme

- Maintenir les captures d'interface et rapports HTML dans `docs/screenshots/`.
- Stabiliser les rapports TXT/JSON/CSV/HTML et conserver leur schema JSON.
- Renforcer le mode audit/dry-run comme chemin par defaut pour les nouveaux utilisateurs.
- Exposer plus clairement les erreurs reseau: Cloudflare, HTML inattendu, quota, 403, 404, hash KO.
- Garder les tests autonomes sans pytest: compile-check, smoke, core helpers, download single, coverage DAT, output helpers, Web UI.

## Moyen terme

- Ameliorer la queue persistante SQLite: reprise fine, retry des echecs, nettoyage `.part`, priorite par systeme.
- Enrichir les metriques provider par systeme: taux de succes, vitesse, faux positifs, Cloudflare, hash invalide.
- Ajouter des exports pratiques pour les workflows RomVault/clrmamepro: FixDAT, rapports filtrables, listes d'echecs.
- Completer le tableau de sante des sources dans la GUI et la Web UI locale avec plus d'actions par provider.
- Ajouter des variantes plus fines aux profils de configuration: debutant, rapide, archive propre sont disponibles en GUI et CLI.

## Long terme

- Support CHD et cas disque avances au-dela de la validation hash/taille.
- Rebuilder `ToSort` plus riche sans devenir un clone complet de RomVault.
- Modes de sortie plus stricts pour les cas multi-ROM et multi-disque.
- Compatibilite frontend plus complete: BIOS, CHD, gamelist enrichi.
- API/Web UI locale plus riche: progression temps reel type SSE/WebSocket si necessaire.

## Hors scope volontaire

- Provider Myrient HTTP.
- Selection 1G1R interne par region/langue.
- Scraping reseau obligatoire dans les tests CI.
- Transformation en gestionnaire ROM complet type RomVault/clrmamepro.
