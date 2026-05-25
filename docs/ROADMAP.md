# Roadmap ROM Downloader

Cette roadmap transforme les objectifs produit en lots suivables. Elle garde deux limites volontaires:

- Myrient n'est pas une source a gerer directement. Minerva torrent et archive.org restent les derniers recours.
- ROM Downloader ne choisit pas les variantes 1G1R. Pour un set 1G1R, utilisez un DAT Retool/1G1R deja filtre.

## Court terme

- Finaliser la documentation utilisateur avec captures GUI reelles.
- Stabiliser les rapports TXT/JSON/CSV/HTML et conserver leur schema JSON.
- Renforcer le mode audit/dry-run comme chemin par defaut pour les nouveaux utilisateurs.
- Exposer plus clairement les erreurs reseau: Cloudflare, HTML inattendu, quota, 403, 404, hash KO.
- Garder les tests autonomes sans pytest: compile-check, smoke, core helpers, download single, coverage DAT, output helpers.

## Moyen terme

- Ameliorer la queue persistante SQLite: reprise fine, retry des echecs, nettoyage `.part`, priorite par systeme.
- Enrichir les metriques provider par systeme: taux de succes, vitesse, faux positifs, Cloudflare, hash invalide.
- Ajouter des exports pratiques pour les workflows RomVault/clrmamepro: FixDAT, rapports filtrables, listes d'echecs.
- Completer le tableau de sante des sources dans la GUI et la Web UI locale.
- Ajouter des variantes plus fines aux profils de configuration: debutant, rapide, archive propre sont disponibles en GUI et CLI.

## Long terme

- Support CHD et cas disque avances quand la validation DAT peut rester fiable.
- Rebuilder leger depuis `ToSort` sans devenir un clone complet de RomVault.
- Modes de sortie plus stricts: `verified`, `tosort`, `dat-structure`, `flat`.
- Compatibilite frontend plus complete: Batocera, RetroBat, ES-DE, LaunchBox.
- API/Web UI locale plus riche: ajout a la file, progression temps reel, historique partage, actions sources.

## Hors scope volontaire

- Provider Myrient HTTP.
- Selection 1G1R interne par region/langue.
- Scraping reseau obligatoire dans les tests CI.
- Transformation en gestionnaire ROM complet type RomVault/clrmamepro.
