# ROMVault Missing ROM Downloader

Compare un fichier DAT avec des ROMs locales et télécharge les manquantes depuis plusieurs sources.

## 🎯 Fonctionnalités

- ✅ **Comparaison DAT** - Analyse les fichiers DAT No-Intro et identifie les ROMs manquantes
- 🔍 **Recherche multi-sources** - Myrient, archive.org, 1fichier, services Debrid
- 📦 **Support étendu** - Toutes extensions de ROMs (GB, GBC, GBA, NES, SNES, N64, MD, etc.)
- 🗂️ **ToSort** - Déplace automatiquement les ROMs non présentes dans le DAT
- 💻 **3 modes** - GUI, ligne de commande, ou interactif

## 📊 Sources de téléchargement

### Sources gratuites
| Source | Type | Priorité | Statut |
|--------|------|----------|--------|
| **Myrient No-Intro** | Direct | 1 | ✅ Actif (ferme le 31/03/2026) |
| **Myrient Redump** | Direct | 2 | ✅ Actif |
| **Myrient TOSEC** | Direct | 2 | ✅ Actif |
| **archive.org** | Recherche MD5 | 3 | ⚠️ Limité (fallback) |

### Sources Premium (clé API requise)
| Source | Type | Description |
|--------|------|-------------|
| **1fichier (API)** | API directe | Téléchargement via API |
| **1fichier (Gratuit)** | Mode free | Avec attente et captcha |
| **AllDebrid** | Service Debrid | Multi-hébergeurs |
| **RealDebrid** | Service Debrid | Multi-hébergeurs |

## 🚀 Utilisation

### Mode Interface Graphique (Recommandé)
```bash
python rom_downloader.py --gui
```

### Mode Ligne de commande
```bash
python rom_downloader.py <fichier.dat> <dossier_roms> [url_myrient] [--dry-run] [--limit N] [--tosort]
```

**Exemples :**
```bash
# Téléchargement normal
python rom_downloader.py "Dat\Nintendo - Game Boy.dat" "Roms\GB"

# Simulation (sans téléchargement)
python rom_downloader.py "Dat\Nintendo - Game Boy.dat" "Roms\GB" "" --dry-run

# Limiter à 10 téléchargements
python rom_downloader.py "Dat\Nintendo - Game Boy.dat" "Roms\GB" "" --limit 10

# Avec déplacement des ROMs hors DAT vers ToSort
python rom_downloader.py "Dat\Nintendo - Game Boy.dat" "Roms\GB" "" --tosort
```

### Mode Interactif
```bash
python rom_downloader.py
```
(Pose des questions pour les chemins et options)

## 📦 Installation

### Prérequis
- Python 3.8 ou supérieur
- pip (gestionnaire de packages Python)

### Installation des dépendances
Le script installe automatiquement les dépendances manquantes. Sinon :

```bash
pip install requests beautifulsoup4 internetarchive
```

### Structure des fichiers
```
rom_downloader/
├── rom_downloader.py          # Script principal
├── rom_database.zip           # Base de données (74 189 URLs)
├── README.md                  # Ce fichier
├── api_keys.json              # Clés API (créé automatiquement)
└── Roms/                      # Dossier des ROMs
    └── GB_Test/              # Dossier de test
```

## 🔑 Configuration des clés API

Pour les services premium (1fichier, AllDebrid, RealDebrid) :

```bash
python rom_downloader.py --configure-api
```

Ou via le menu dans l'interface graphique.

**Obtenir vos clés API :**
- 1fichier : https://1fichier.com/api/
- AllDebrid : https://alldebrid.com/apikeys/
- RealDebrid : https://real-debrid.com/apitoken

## 🔄 Flux de travail

1. **Parsing DAT** - Lit le fichier DAT et extrait la liste des jeux
2. **Scan local** - Analyse le dossier de ROMs existantes
3. **Comparaison** - Identifie les jeux manquants
4. **Recherche** :
   - Base de données locale (74 189 URLs)
   - Myrient (listing direct des dossiers)
   - archive.org (recherche par MD5 en dernier recours)
5. **Téléchargement** - Télécharge les ROMs trouvées
6. **ToSort** (optionnel) - Déplace les ROMs hors DAT

## 📁 Extensions supportées

Le script gère **toutes les extensions de ROMs** :

- **Nintendo** : `.gb`, `.gbc`, `.gba`, `.nes`, `.smc`, `.sfc`, `.n64`, `.z64`, `.nds`, `.3ds`, `.cia`
- **GameCube/Wii** : `.gcm`, `.rvz`, `.iso`, `.wbfs`, `.nkit.iso`, `.ciso`, `.gcz`
- **Sega** : `.sms`, `.gg`, `.md`, `.gen`, `.32x`, `.chd`, `.cue`, `.iso`
- **Sony** : `.psx`, `.psf`, `.pbp`, `.ecm`, `.img`, `.ccd`
- **Autres** : `.pce`, `.ngp`, `.ws`, `.vb`, `.lnx`, `.a26`, `.jag`, etc.
- **Archives** : `.zip`, `.7z`, `.rar`, `.gz`, `.tar`

## ⚠️ Notes importantes

### Myrient
- ⚠️ **Myrient fermera le 31 mars 2026**
- Profitez-en pour télécharger les ROMs importantes avant cette date
- Le script est optimisé pour Myrient actuellement

### archive.org
- Recherche par MD5 souvent infructueuse pour les ROMs No-Intro
- Utilisé en **dernier recours** après Myrient
- Collections No-Intro non accessibles publiquement

### ToSort
- Les ROMs non présentes dans le DAT sont déplacées vers `../ToSort/`
- Utile pour nettoyer les collections mélangées

## 🛠️ Options avancées

### `--dry-run`
Simulation sans téléchargement réel. Utile pour tester.

### `--limit N`
Limite le nombre de téléchargements (ex: `--limit 5`)

### `--tosort`
Active le déplacement des ROMs hors DAT vers le dossier ToSort

### `--sources`
Affiche la liste complète des sources disponibles

### `--configure-api`
Configure interactivement les clés API premium

## 📝 Exemple complet

```bash
# Télécharger 20 ROMs manquantes depuis Game Boy DAT
# avec déplacement des fichiers hors DAT
python rom_downloader.py "Dat\Nintendo - Game Boy.dat" "Roms\GB" "" --limit 20 --tosort
```

## 🐛 Dépannage

### "Aucune ROM trouvée sur Myrient"
- Vérifiez que le dossier Myrient existe pour votre système
- Le nom du système dans le DAT doit correspondre (ex: "Nintendo - Game Boy")

### "archive.org ne trouve rien"
- Normal : archive.org a des limitations pour les ROMs No-Intro
- Privilégiez Myrient tant qu'il est en ligne

### Erreurs de téléchargement
- Vérifiez votre connexion internet
- Certains hébergeurs ont des limites de débit
- Réessayez avec `--limit` plus bas

## 📄 Licence

Script à but éducatif. Téléchargez uniquement les ROMs que vous possédez physiquement.

## 🤝 Contribution

Les améliorations sont les bienvenues ! Fonctionnalités possibles :
- Support d'autres sources (EdgeEmu, PlanetEmu)
- Amélioration de la recherche archive.org
- Support des torrents
- Interface web

---

**Développé avec ❤️ pour la préservation du rétro-gaming**
