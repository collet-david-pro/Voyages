# Gestion Voyages Scolaires — documentation complète

Cette application Flask aide à gérer les voyages scolaires (participants, paiements, budgets, génération de documents). Ce README couvre : l'installation, l'utilisation, les fonctions disponibles, la configuration, la génération de PDF, le packaging Windows (CI) et les scripts d'aide au déploiement.

---

## Table des matières
- Présentation
- Fonctionnalités principales
- Page Configuration (logo / signatures / texte d'attestation)
- PDF & documents générés
- Suppressions et décisions récentes
- Exécution locale / développeur
- Build / Release (Windows .exe) — CI GitHub Actions
- Script pratique : publier une release (push tag + create release)
- Tests & CI locale
- Contribuer
- Licence

---

## Présentation

Gestion Voyages Scolaires est une application monofichier (backend principal : `app.py`), SQLite (`voyages_scolaires.db`) et des templates Jinja/Bootstrap dans `templates/`.

Elle est conçue pour :
- organiser des voyages scolaires (création / modification / suppression),
- enregistrer les participants (élèves et accompagnateurs),
- gérer les paiements et créances associés,
- produire des documents PDF (attestations, listes, échéanciers, budgets),
- fournir une interface d'administration pour configurer l'établissement et personnaliser le texte des attestations.

---

## Fonctionnalités principales

- Création/édition/suppression de voyages (destination, date, prix par élève, nb participants attendus, accompagnateurs, nuits)
- Gestion des participants (inscription, liste d'attente automatique, statuts : INSCRIT / ANNULÉ / À_REMBOURSER, etc.)
- Gestion financière par participant : saisie, modification, suppression des paiements
- Calculs automatisés : total perçu, reste à payer, élèves à rembourser
- Gestion budgétaire par catégories (recettes / dépenses / solde prévisionnel)
- Exports PDF : attestations individuelles, listes, échéanciers, documents financiers (avec logo + signatures)
- Page Configuration : nom/ville/ordonnateur/secrétaire + upload du logo et 2 signatures (ordonnateur / secrétaire)
- UI / ergonomie : onglets unifiés pour les pages liées à un voyage toujours dans le même ordre

---

## Page Configuration (logo / signatures / texte d'attestation)

- Vous pouvez personnaliser les informations de l'établissement et le texte par défaut de l'attestation.
- Uploads supportés : logo (PNG/JPG) et 2 images de signature. Les images de signatures sont normalisées côté serveur (64×64 px) pour assurer une représentation cohérente dans les PDF.
- Les images sont sauvegardées dans `uploads/config/` et leurs chemins sont stockés en base via `config_etablissement`.

Remarque importante : le champ `logo_path`, `ordonnateur_image` et `secretaire_image` existent dans la table `config_etablissement` (migration automatique tentée au démarrage).

---

## PDF & documents

La génération de PDF utilise `fpdf2` et une classe PDF utilitaire commune pour :
- marges, orientation et largeur de contenu cohérentes,
- insertion du logo centré si fourni,
- insertion (non dupliquée) des signatures (ordonnateur / secrétaire) lorsque présentes,
- génération d'attestations de paiement, liste des participants, courriers et bilans budgétaires.

NB : les signatures identiques ou identiques au logo sont détectées et évitées pour ne pas dessiner de doublons visuels.

---

## Suppressions et décisions récentes

- La fonctionnalité de sauvegarde (backup UI : créer / lister / télécharger / supprimer depuis l'interface) a été retirée du produit — volontairement. Les traces documentaires ont été mises à jour et l'UI ne montre plus la zone "Sauvegarde".
- Si vous gérez des sauvegardes, conservez des copies manuelles du fichier SQLite `voyages_scolaires.db` en dehors de l'application.

---

## Exécution locale (développement et tests)

1. Clonez le dépôt
2. Assurez-vous d'avoir Python 3.11+ installé
3. Lancez le script de démarrage (il crée un `venv` et installe les dépendances) :

```bash
./start.sh
# ou manuellement (si vous préférez garder le contrôle) :
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

4. L'application est disponible par défaut sur : http://127.0.0.1:5001

---

## Build / Release (Windows .exe) — CI GitHub Actions ✅

Le dépôt contient un workflow GitHub Actions (`.github/workflows/winexe.yml`) qui construit automatiquement un exécutable Windows autonome quand une Release est publiée (événement `release` de type `published`).

Points clés :
- Le workflow s'exécute sur un runner `windows-latest` et utilise PyInstaller pour générer un seul fichier exécutable (`--onefile`, sans console/`--windowed`).
- Le build inclut par défaut les dossiers `templates` et `uploads`. Si vous avez un dossier `fonts/` (polices embarquées), le workflow l'ajoutera aussi automatiquement pour que les PDF utilisent correctement des polices Unicode (accents, symbole €).
- Le binaire produit (`dist/GestionVoyages.exe`) est attaché comme asset à la Release et nommé `GestionVoyages-<tag>.exe`.

Remarques et bonnes pratiques :
- Ce build produit un binaire pour Windows : testez-le sur la plateforme cible (certaines dépendances système natives peuvent se comporter différemment selon la version de Windows).
- Si vos exports PDF nécessitent une police TTF spécifique (DejaVu / Noto), placez-les dans `fonts/` dans le dépôt ou fournissez-les via le processus de packaging – le workflow essaiera d'inclure le dossier `fonts` s'il existe.
- Le workflow se déclenche lors de la publication d'une Release. Pour reproduire localement, installez PyInstaller et exécutez une commande équivalente (voir plus bas).

Exemple local (équivalent à ce que fait la CI) :

```bash
# depuis la racine du projet, dans un venv activé
pip install -r requirements.txt pyinstaller
python -c "import os, PyInstaller.__main__ as P; data = []
for d in ('templates','uploads','fonts'):
  if os.path.exists(d): data += ['--add-data', f'{d}{os.pathsep}{d}']
P.run(['--noconfirm', '--clean', '--name', 'GestionVoyages', '--onefile', '--windowed'] + data + ['app.py'])"

# résultat : dist/GestionVoyages.exe
```

---

## Script pratique : publier une release (push tag + create release)

Un script d'aide est fourni : `scripts/publish_release.sh`.

Fonctionnalités :
- crée un tag (annoté) si nécessaire,
- pousse le tag vers `origin`,
- crée la Release (préférence pour `gh` CLI si disponible),
- fallback via l'API GitHub nécessite la variable d'environnement `GITHUB_TOKEN`.

Usage rapide :

```bash
chmod +x ./scripts/publish_release.sh
./scripts/publish_release.sh v1.0.0 "Titre de la release" "Notes / changelog"  
```

Après publication : GitHub Actions construira et attachera l'exécutable à la Release.

---

## Tests & qualité

- Le dépôt contient des tests simples (à compléter). Pour exécuter les tests :

```bash
source venv/bin/activate
python -m pytest
```

---

## Contribuer

Contributions bienvenues :
- ouvrez une issue avant les gros changements,
- créez des PRs petites et ciblées,
- respectez le style Python et ajoutez des tests où possible.

---

## Licence

Licence : à préciser par le projet (aucune licence explicite par défaut dans le repo). Si vous souhaitez que j'ajoute un fichier `LICENSE` (MIT / Apache / GPL), dites‑le.

---

Si vous voulez que je complète ce README avec un guide d'administration, une checklist de déploiement ou la procédure de packaging multiplateforme (macOS / Linux), je peux le faire maintenant.
---

## Administration — Sauvegardes & restauration (guide détaillé)

Cette section décrit les pratiques recommandées pour sauvegarder la base de données SQLite, mettre en place des sauvegardes régulières, vérifier l'intégrité des sauvegardes et restaurer un point de restauration.

Important : le fichier de base de données principal est `voyages_scolaires.db` situé à la racine de l'application. Avant toute opération de restauration (écrasement), ARRÊTEZ l'application pour éviter la corruption.

### 1) Sauvegarde manuelle (rapide)
- Créer un dossier local `backups/` (si absent) :

```bash
mkdir -p backups
```

- Copier le fichier avec un timestamp :

```bash
# depuis la racine du repo
cp voyages_scolaires.db backups/voyages_$(date +%F_%H-%M-%S).db
```

Remarque : la copie binaire fonctionne si le fichier n'est pas en écriture intensive.

### 2) Sauvegarde sûre (utiliser SQLite backup API)
Pour garantir une sauvegarde sans risque de corruption même si le serveur tourne, utilisez l'utilitaire sqlite3 :

```bash
sqlite3 voyages_scolaires.db ".backup 'backups/voyages_$(date +%F_%H-%M-%S).db'"
```

Cette méthode utilise l'API d'export (backup) de SQLite et permet d'obtenir une copie cohérente.

### 3) Sauvegardes planifiées (Linux / macOS)
Exemple cron pour sauvegarder tous les jours à 02:00 et garder 14 jours :

```cron
0 2 * * * cd /path/to/your/project && sqlite3 voyages_scolaires.db \
  ".backup 'backups/voyages_$(date +\%F_\%H-\%M-\%S).db'" && \
  find backups -type f -mtime +14 -delete
```

Notes :
- Remplacez `/path/to/your/project` par le chemin absolu vers le dépôt sur votre serveur.
- `find ... -mtime +14 -delete` supprime les backups plus vieux que 14 jours (rotation).

### 4) Sauvegardes planifiées (Windows)
Utilisez le Planificateur de tâches (Task Scheduler) ou un script PowerShell :

PowerShell rapide (exécuter via le planificateur) :

```powershell
$ts = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
Copy-Item -Path 'C:\path\to\voyages_scolaires.db' -Destination "C:\path\to\backups\voyages_$ts.db"
# Optionnel: purge des anciens backups -- exemple pour conserver 14 derniers
$files = Get-ChildItem -Path 'C:\path\to\backups' | Sort-Object LastWriteTime -Descending
$files | Select-Object -Skip 14 | Remove-Item
```

### 5) Vérification d'intégrité
Avant de compter sur un backup, testez-le :

```bash
sqlite3 backups/voyages_2025-12-09_22-00-00.db "PRAGMA integrity_check;"
# attend 'ok' si la DB est saine
```

### 6) Restauration (procédure sûre)
1. ARRÊTEZ l'application (ou tout processus qui accède à la DB).
2. Validez la sauvegarde choisie (intégrity_check).
3. Faites une copie de la base courante pour précaution :

```bash
cp voyages_scolaires.db voyages_scolaires.db.before_restore_$(date +%F_%H-%M-%S)
```

4. Remplacez la base par le backup :

```bash
cp backups/voyages_2025-12-09_22-00-00.db voyages_scolaires.db
# (optionnel) changer permissions / propriétaire si nécessaire
```

5. Redémarrez l'application, vérifiez le comportement et faites des tests de cohérence.

### 7) Bonnes pratiques
- Testez régulièrement vos procédures de restauration dans un environnement non-productif.
- Conservez au moins 2 jeux de sauvegarde (local + externe/cloud).
- Protégez les backups (chiffrement si nécessaire) et limitez les permissions d'accès.
- Documentez qui a accès et la procédure — rendre la restauration simple et testée.

---

Si tu veux, j'ajoute un script `scripts/backup_db.sh` prêt à l'emploi qui effectue la sauvegarde, la rotation et la vérification d'intégrité (ou une version PowerShell pour Windows). Je peux aussi ajouter un exemple de job systemd timer si tu préfères cela à cron.
# Gestion des Voyages Scolaires

Une application web complète développée avec Flask pour la gestion de A à Z des voyages scolaires : suivi des participants, gestion financière et budgétaire, et génération de documents.

## Table des matières
- [Gestion des Voyages Scolaires](#gestion-des-voyages-scolaires)
  - [Table des matières](#table-des-matières)
  - [Fonctionnalités](#fonctionnalités)
    - [Gestion des Voyages](#gestion-des-voyages)
    - [Gestion des Participants](#gestion-des-participants)
    - [Gestion Financière](#gestion-financière)
    - [Gestion Budgétaire](#gestion-budgétaire)
    - [Exports PDF](#exports-pdf)
    - [Configuration](#configuration)
  - [Installation et Lancement](#installation-et-lancement)

## Fonctionnalités

### Gestion des Voyages
- **Création de voyage** : Depuis le tableau de bord, créez un voyage en spécifiant :
  - La destination.
  - La date de départ.
  - Le prix par élève.
  - Le nombre de participants (élèves) attendus.
  - Le nombre d'accompagnateurs.
  - La durée du séjour en nuits.
- **Modification et Suppression** : Accédez aux détails d'un voyage pour modifier ses informations ou le supprimer définitivement (cette action supprime toutes les données associées).

### Gestion des Participants
L'onglet **Participants** est le centre de contrôle des élèves pour un voyage donné.
- **Inscription** : Ajoutez des élèves un par un avec leur nom, prénom et classe.
- **Liste d'attente automatique** : Si le nombre de participants attendus est atteint, tout nouvel élève inscrit est automatiquement placé en **Liste d'attente**.
- **Gestion des statuts** : Modifiez le statut de chaque élève :
  - **Inscrit** : Participe au voyage.
  - **Liste d'attente** : En attente d'une place.
  - **Annulé** : Inscription annulée (sans paiement effectué).
  - **À rembourser** : Inscription annulée après un ou plusieurs paiements. Le changement de statut est automatique.
- **Suivi administratif** : Cochez les cases "Fiche d'engagement" et "Liste définitive" pour un suivi visuel rapide.

### Gestion Financière
- **Saisie des paiements** : Pour chaque élève, ajoutez des paiements via une fenêtre dédiée en spécifiant le montant, la date, le mode de paiement et une référence.
- **Tableau de bord financier** : La page de détails du voyage affiche un récapitulatif financier avec :
  - Le total perçu pour le voyage.
  - Le montant total attendu.
  - Une barre de progression visuelle.
- **Historique par élève** : Une page dédiée ("Gérer") permet de voir, modifier ou supprimer tous les paiements d'un élève.

### Gestion Budgétaire
L'onglet **Budget** offre une vue complète des finances prévisionnelles du voyage.
- **Dépenses et Recettes** : Saisissez toutes les lignes budgétaires (transport, hébergement, subventions, dons...) en les classant par catégorie.
- **Solde prévisionnel** : Le solde est calculé en temps réel et affiché en vert (bénéfice) ou en rouge (déficit).
- **Catégories personnalisables** : Les catégories de budget sont prédéfinies mais peuvent être étendues.

### Exports PDF
Plusieurs documents peuvent être générés pour faciliter l'administration.
- **Attestation de paiement individuelle** : Depuis la page de gestion des paiements d'un élève, générez un PDF certifiant les sommes versées.
 - **Liste éditable des inscrits (nouveau)** : depuis la page du voyage, cliquez sur "Éditer la liste (PDF)" pour modifier les montants payés et générer un PDF final contenant les montants payés et le reste à payer.
 - **Export direct : liste des inscrits (nouveau)** : depuis la page du voyage, cliquez sur "Exporter la liste (PDF)" pour télécharger immédiatement un PDF contenant uniquement : Nom, Prénom, Classe et Reste à payer. Le PDF affiche les montants comme "123.45 EUR" (format sûr pour l'affichage sur tous les font par défaut).
- **Liste des élèves filtrée** : Depuis l'onglet "Participants", exportez une liste d'élèves en PDF avec des filtres :
  - Tous les élèves (tous statuts confondus).
  - Uniquement les élèves ayant tout payé.
  - Uniquement les élèves ayant un solde restant.
- **Lettre d'échéancier pour les familles** : Générez une lettre type personnalisée pour le voyage, incluant un échéancier de paiement calculé selon vos critères (nombre de versements ou montant par versement).
- **Budget prévisionnel détaillé** : Depuis l'onglet "Budget", exportez un rapport complet incluant :
  - Le détail des recettes et dépenses.
  - Le solde final.
  - Des indicateurs clés : coût moyen par élève, par accompagnateur, par participant et par nuitée.

### Configuration
La page **Configuration** vous permet de personnaliser l'application.
- **Informations de l'établissement** : Nom de l'établissement, ville, nom du principal et du gestionnaire. Ces informations sont réutilisées dans les documents PDF.
- **Texte de l'attestation** : Personnalisez le corps du texte qui apparaît sur les attestations de paiement.
- **Modes de paiement** : Ajoutez ou supprimez des modes de paiement (Chèque, Espèces, etc.).

## Installation et Lancement

1.  Clonez le dépôt.
2.  Assurez-vous d'avoir Python 3 installé.
3.  Ouvrez un terminal dans le dossier du projet.
4.  Exécutez le script de démarrage qui créera un environnement virtuel et installera les dépendances :
    ```bash
    ./start.sh
    ```
    *(Sur Windows, vous pouvez lancer les commandes du script manuellement dans un terminal `cmd` ou `PowerShell`)*.
5.  L'application se lancera et ouvrira automatiquement un onglet dans votre navigateur à l'adresse `http://127.0.0.1:5001`.
6.  La première fois, une base de données `voyages_scolaires.db` sera créée dans le dossier de l'application.

## Builds automatiques (Windows .exe)

Un workflow GitHub Actions construit automatiquement un exécutable Windows autonome (un seul fichier .exe créé par PyInstaller, sans console) lorsque vous publiez une release (tag) sur GitHub. Le binaire est ajouté en tant qu'asset à la release (nommé : `GestionVoyages-<tag>.exe`).

Pour déclencher la compilation :

1. Créez une release (avec un tag tel que `v1.0.0`) depuis l'interface GitHub ou en poussant un tag.
2. Le pipeline GitHub Actions se déclenchera automatiquement, construira l'exécutable et l'attachera à la release.

Remarque : le build vise un exécutable Windows autonome (sans terminal). Assurez-vous de tester le binaire sur la plateforme cible.

## Script pratique : créer/publier une release depuis la machine

Un petit script est fourni pour automatiser la création d'un tag, le push et la création de la Release GitHub :

Fichier : `scripts/publish_release.sh`

Usage recommandé (dans la racine du repo) :

```bash
# rendre exécutable (au besoin)
chmod +x ./scripts/publish_release.sh

# créer et publier la release
./scripts/publish_release.sh v1.0.0 "Titre de la release" "Notes / changelog succinct"
```

Le script :
- pousse le tag sur origin
- crée la Release via `gh` (si `gh` est installé) ou via l'API GitHub (nécessite la variable d'environnement `GITHUB_TOKEN`).

