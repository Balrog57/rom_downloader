# Roadmap ROM Downloader

Cette roadmap transforme les objectifs produit en lots suivables. Elle garde deux limites volontaires:

- Minerva torrent et archive.org restent les derniers recours; l'ancien provider HTTP Myrient n'est pas expose ni developpe.
- ROM Downloader ne choisit pas les variantes 1G1R. Pour un set 1G1R, utilisez un DAT Retool/1G1R deja filtre.

## Livre en v0.1.5

- Alignement produit: Minerva torrent et archive.org comme derniers recours, sans provider HTTP obsolete.
- Documentation et `goal.md` synchronises sur la contrainte 1G1R externe via DAT Retool/1G1R deja filtre.
- Tests de garde contre la reintroduction d'un provider obsolete ou d'un profil 1G1R interne.
- Nettoyage progressif des libelles internes de source personnalisee, avec alias de compatibilite.

## Livre en v0.1.4

- Web UI locale REST + polling: analyse DAT, jobs, actions pause/reprise/retry/cancel, sources et cache.
- Rapports TXT/JSON/CSV/HTML enrichis avec details provider, erreurs HTML, hash final et sections DAT/rebuild.
- Sorties finalisees: `--output-mode`, `--archive-mode`, `--rebuild-tosort` et compatibilite TorrentZip.
- DAT capabilities: detection CHD, headers, clones, BIOS/devices et merge metadata, sans rebuild arcade complet.
- Documentation publique: README, guide utilisateur, captures, roadmap, templates issues, labels, licence et disclaimer.
- Release Windows `v0.1.4`: EXE portable, checksum SHA256, CI, CodeQL, Dependabot et workflow release.

## Court terme

- Maintenir les captures d'interface et rapports HTML dans `docs/screenshots/`.
- Stabiliser les rapports TXT/JSON/CSV/HTML et conserver leur schema JSON.
- Renforcer le mode audit/dry-run comme chemin par defaut pour les nouveaux utilisateurs.
- Exposer plus clairement les erreurs reseau: Cloudflare, HTML inattendu, quota, 403, 404, hash KO.
- Garder les tests autonomes sans pytest: compile-check, smoke, core helpers, download single, coverage DAT, output helpers, Web UI, provider checks.

## Moyen terme

- Ameliorer la queue persistante SQLite: reprise fine, retry des echecs, nettoyage `.part`, priorite par systeme et reprise apres fermeture.
- Enrichir les metriques provider par systeme: taux de succes, vitesse, faux positifs, Cloudflare, hash invalide et scoring plus fin.
- Persister les `provider_candidates` non verifies avec TTL, statut et raison d'erreur.
- Ajouter des exports pratiques pour les workflows RomVault/clrmamepro: FixDAT, rapports filtrables, listes d'echecs.
- Completer le tableau de sante des sources dans la GUI et la Web UI locale avec plus d'actions par provider.
- Ajouter des variantes plus fines aux profils de configuration: debutant, rapide, archive propre sont disponibles en GUI et CLI.
- Capture HTML brute dans `DownloadNetworkError` pour diagnostic Cloudflare.
- Mapping LaunchBox: 95+ entrees de systemes.
- Tests unitaires provider: 97 tests sur les fonctions pures (parsing, normalisation, matching).
- Thread-safety des metriques providers.
- Validation `.env` au demarrage.
- Wiring des callbacks resolve/download dans `ProviderAdapter`.
- chdman verify pour validation CHD.
- Logging structure avec fichier `rom_downloader.log`.

## Long terme

- Support CHD avance et cas disque au-dela de la validation hash/taille.
- Merge arcade complet: split, merged, non-merged et cas multi-ROM/multi-disque complexes.
- Rebuilder `ToSort` plus riche sans devenir un clone complet de RomVault.
- Compatibilite frontend plus complete: BIOS, CHD, gamelist enrichi (BIOS places dans `bios/` pour Batocera/RetroBat/ES-DE).
- Web UI locale plus riche: SSE pour progression temps reel, dashboard auto-refresh.

## Hors scope volontaire

- Provider HTTP obsolete remplace par Minerva torrent.
- Selection 1G1R interne par region/langue; le DAT fourni reste la source de verite.
- Scraping reseau obligatoire dans les tests CI.
- Transformation en gestionnaire ROM complet type RomVault/clrmamepro.
