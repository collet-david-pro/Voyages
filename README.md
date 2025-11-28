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
