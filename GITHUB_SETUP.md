# Guide de publication sur GitHub

## ✅ Ce qui a été fait

- [x] README.md mis à jour avec documentation complète
- [x] Fichier .gitignore créé (exclut API keys, ROMs, fichiers temporaires)
- [x] Dépôt Git initialisé localement
- [x] Commit initial effectué (6 fichiers)
- [x] Branche renommée en `main`

## 📤 Pousser vers GitHub

### Option 1 : Dépôt public

1. Créez un nouveau dépôt sur GitHub :
   - Allez sur https://github.com/new
   - Nom du dépôt : `rom_downloader`
   - Description : "ROMVault Missing ROM Downloader - Compare DAT files and download missing ROMs from multiple sources"
   - **Ne cochez PAS** "Add a README file"
   - Cliquez sur "Create repository"

2. Exécutez ces commandes dans le dossier du projet :

```bash
cd rom_downloader

# Ajouter le remote GitHub (remplacez VOTRE_USER par votre username GitHub)
git remote add origin https://github.com/VOTRE_USER/rom_downloader.git

# Vérifier la connexion
git remote -v

# Pousser vers GitHub
git push -u origin main
```

### Option 2 : Dépôt privé

Mêmes étapes, mais :
- Cochez "Private" lors de la création du dépôt
- Ou utilisez l'URL SSH : `git remote add origin git@github.com:VOTRE_USER/rom_downloader.git`

## 🔒 Fichiers sensibles (déjà exclus par .gitignore)

Les fichiers suivants **NE SERONT PAS** poussés vers GitHub :

- `api_keys.json` - Vos clés API (à ne jamais committer !)
- `__pycache__/` - Fichiers compilés Python
- `Roms/*.gb`, `Roms/*.zip`, etc. - Les ROMs téléchargées
- `*.log` - Fichiers de log
- `test_*.py` - Scripts de test temporaires

## 📊 Structure du dépôt

```
rom_downloader/
├── rom_downloader.py       # Script principal (2500+ lignes)
├── rom_database.zip        # Base de données (74 189 URLs)
├── README.md               # Documentation complète
├── .gitignore              # Fichiers à ignorer
├── GEMINI.md               # Notes Gemini (optionnel)
└── .agents/                # Configuration agents (optionnel)
```

## 🎯 Prochaines étapes après publication

1. **Ajouter un fichier LICENSE** (MIT, GPL, etc.)
2. **Créer des releases** pour versionner
3. **Ajouter des badges** dans le README :
   - Version
   - License
   - Downloads
   - Stars

4. **Améliorations possibles** :
   - Screenshots de l'interface GUI
   - Diagramme du flux de travail
   - Wiki avec tutoriels détaillés

## 🐛 En cas de problème

### "remote origin already exists"
```bash
git remote remove origin
git remote add origin https://github.com/VOTRE_USER/rom_downloader.git
```

### "permission denied"
Vérifiez que vous utilisez le bon username GitHub dans l'URL.

### "failed to push some refs"
```bash
git pull origin main --rebase
git push -u origin main
```

## 📝 Message de commit pour futures modifications

```bash
git add .
git commit -m "Description courte et précise des changements"
git push
```

---

**Développé pour la préservation du rétro-gaming** 🎮
