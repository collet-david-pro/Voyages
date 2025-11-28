-- Schéma de la base de données pour l'application de gestion des voyages scolaires

-- Table des voyages
CREATE TABLE IF NOT EXISTS voyages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    destination TEXT NOT NULL,
    date_depart DATE NOT NULL, -- Changé en DATE pour une meilleure gestion
    prix_eleve REAL NOT NULL,
    nb_participants_attendu INTEGER NOT NULL DEFAULT 0,
    nb_accompagnateurs INTEGER NOT NULL DEFAULT 0,
    duree_sejour_nuits INTEGER NOT NULL DEFAULT 1
);

-- Table des modes de paiement
CREATE TABLE IF NOT EXISTS modes_paiement (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    libelle TEXT UNIQUE NOT NULL
);

-- Table des élèves
CREATE TABLE IF NOT EXISTS eleves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    voyage_id INTEGER NOT NULL,
    nom TEXT NOT NULL,
    prenom TEXT NOT NULL,
    classe TEXT NOT NULL,
    statut TEXT NOT NULL CHECK(statut IN ('INSCRIT', 'ANNULÉ', 'A_REMBOURSER', 'LISTE_ATTENTE')),
    fiche_engagement INTEGER NOT NULL DEFAULT 0,
    liste_definitive INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (voyage_id) REFERENCES voyages (id) ON DELETE CASCADE
);

-- Table des paiements
CREATE TABLE IF NOT EXISTS paiements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eleve_id INTEGER NOT NULL,
    mode_paiement_id INTEGER NOT NULL,
    montant REAL NOT NULL,
    date DATE NOT NULL, -- Changé en DATE
    reference TEXT,
    FOREIGN KEY (eleve_id) REFERENCES eleves (id) ON DELETE CASCADE,
    FOREIGN KEY (mode_paiement_id) REFERENCES modes_paiement (id)
);

-- Table pour les paramètres généraux de l'application
CREATE TABLE IF NOT EXISTS parametres (
    cle TEXT PRIMARY KEY NOT NULL,
    valeur TEXT NOT NULL
);

-- Table pour les catégories budgétaires
CREATE TABLE IF NOT EXISTS budget_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT UNIQUE NOT NULL
);

-- Table pour les lignes budgétaires (dépenses et recettes)
CREATE TABLE IF NOT EXISTS budget_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    voyage_id INTEGER NOT NULL,
    categorie_id INTEGER NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('recette', 'depense')),
    description TEXT NOT NULL,
    montant REAL NOT NULL,
    FOREIGN KEY (voyage_id) REFERENCES voyages (id) ON DELETE CASCADE,
    FOREIGN KEY (categorie_id) REFERENCES budget_categories (id)
);

-- Table pour les documents liés à un voyage
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    voyage_id INTEGER NOT NULL,
    nom_fichier TEXT NOT NULL,
    chemin_stockage TEXT UNIQUE NOT NULL,
    date_upload DATE NOT NULL,
    FOREIGN KEY (voyage_id) REFERENCES voyages (id) ON DELETE CASCADE
);

essai un-- Insertion du texte par défaut pour l'attestation
INSERT OR IGNORE INTO parametres (cle, valeur) VALUES
('texte_attestation', 'Je soussigné(e), [Nom du responsable], certifie que l''élève a bien réglé les sommes indiquées ci-dessous pour sa participation au voyage scolaire.');

-- Insertion des paramètres généraux pour l'attestation
INSERT OR IGNORE INTO parametres (cle, valeur) VALUES
('nom_college', 'Nom du Collège'),
('ville_college', 'Ville'),
('nom_principal', 'Nom du Principal'),
('nom_secretaire_general', 'Nom du Secrétaire Général');

-- Insertion des modes de paiement par défaut
INSERT OR IGNORE INTO modes_paiement (libelle) VALUES
('Chèque'),
('Espèces'),
('Virement'),
('Carte Bancaire');

-- Insertion des catégories budgétaires par défaut
INSERT OR IGNORE INTO budget_categories (nom) VALUES
('Transport'),
('Hébergement'),
('Repas'),
('Activités / Visites'),
('Assurances'),
('Subventions'),
('Dons'),
('Participation des familles');
