# Gestion des Voyages Scolaires

Une application web simple développée avec Flask pour gérer les voyages scolaires, les inscriptions des élèves et le suivi des paiements.

## Fonctionnalités

- Création et modification de voyages (destination, date, prix).
- Inscription des élèves à un voyage.
- Suivi des paiements pour chaque élève.
- Gestion des statuts des élèves (Inscrit, Annulé, À rembourser).
- Cases à cocher pour le suivi administratif (fiche d'engagement, liste définitive).
- Tableau de bord financier par voyage.
- Génération d'attestations de paiement personnalisées en PDF.
- Page de configuration pour les paramètres de l'établissement et les modes de paiement.

## Installation et Lancement

1.  Clonez le dépôt.
2.  Assurez-vous d'avoir Python 3 installé.
3.  Exécutez le script de démarrage qui créera un environnement virtuel et installera les dépendances :
    ```bash
    ./start.sh
    ```
4.  L'application se lancera et ouvrira automatiquement un onglet dans votre navigateur à l'adresse `http://127.0.0.1:5001`.

## Version Exécutable

Une version exécutable pour Windows est automatiquement construite via GitHub Actions à chaque mise à jour de la branche `main`.
