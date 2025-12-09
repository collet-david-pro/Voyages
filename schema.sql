-- Schéma de la base de données pour l'application de gestion des voyages scolaires

-- Table des voyages
CREATE TABLE IF NOT EXISTS voyages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    destination TEXT NOT NULL,
    date_depart DATE NOT NULL, -- Changé en DATE pour une meilleure gestion
    prix_eleve INTEGER NOT NULL, -- Stocké en centimes
    nb_participants_attendu INTEGER NOT NULL DEFAULT 0,
    nb_accompagnateurs INTEGER NOT NULL DEFAULT 0,
    duree_sejour_nuits INTEGER NOT NULL DEFAULT 1
);

-- Table des modes de paiement
CREATE TABLE IF NOT EXISTS modes_paiement (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    libelle TEXT UNIQUE NOT NULL
);

-- Table des élèves (obsolète, remplacée par participants)
-- CREATE TABLE IF NOT EXISTS eleves (
--     id INTEGER PRIMARY KEY AUTOINCREMENT,
--     voyage_id INTEGER NOT NULL,
--     nom TEXT NOT NULL,
--     prenom TEXT NOT NULL,
--     classe TEXT NOT NULL,
--     statut TEXT NOT NULL CHECK(statut IN ('INSCRIT', 'ANNULÉ', 'A_REMBOURSER', 'LISTE_ATTENTE')),
--     fiche_engagement INTEGER NOT NULL DEFAULT 0,
--     liste_definitive INTEGER NOT NULL DEFAULT 0,
--     FOREIGN KEY (voyage_id) REFERENCES voyages (id) ON DELETE CASCADE
-- );

-- Table des participants (élèves et accompagnateurs)
CREATE TABLE IF NOT EXISTS participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    voyage_id INTEGER NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('ELEVE', 'ACCOMPAGNATEUR')),
    nom TEXT NOT NULL,
    prenom TEXT NOT NULL,
    classe TEXT, -- Nullable, car non applicable aux accompagnateurs
    fonction TEXT, -- Nullable, car non applicable aux élèves
    statut TEXT NOT NULL CHECK(statut IN ('INSCRIT', 'ANNULÉ', 'A_REMBOURSER', 'LISTE_ATTENTE')),
    remboursement_validé INTEGER NOT NULL DEFAULT 0,
    fiche_engagement INTEGER NOT NULL DEFAULT 0,
    liste_definitive INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (voyage_id) REFERENCES voyages (id) ON DELETE CASCADE
);

-- Table des créances (dettes des participants)
CREATE TABLE IF NOT EXISTS creances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    participant_id INTEGER NOT NULL,
    montant_initial INTEGER NOT NULL, -- Stocké en centimes
    montant_remise INTEGER NOT NULL DEFAULT 0, -- Stocké en centimes
    FOREIGN KEY (participant_id) REFERENCES participants (id) ON DELETE CASCADE
);

-- Table des paiements
CREATE TABLE IF NOT EXISTS paiements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creance_id INTEGER NOT NULL,
    mode_paiement_id INTEGER NOT NULL,
    montant INTEGER NOT NULL, -- Stocké en centimes
    date DATE NOT NULL,
    reference TEXT,
    FOREIGN KEY (creance_id) REFERENCES creances (id) ON DELETE CASCADE,
    FOREIGN KEY (mode_paiement_id) REFERENCES modes_paiement (id)
);

-- Table pour la configuration de l'établissement (singleton)
CREATE TABLE IF NOT EXISTS config_etablissement (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    nom_etablissement TEXT,
    adresse TEXT,
    ordonnateur_nom TEXT,
    secretaire_general_nom TEXT,
    ville_signature TEXT,
    texte_attestation TEXT
);

-- Images et chemins (logo, signatures) stockés en chemin relatif uploads/...
ALTER TABLE config_etablissement ADD COLUMN IF NOT EXISTS logo_path TEXT;
ALTER TABLE config_etablissement ADD COLUMN IF NOT EXISTS ordonnateur_image TEXT;
ALTER TABLE config_etablissement ADD COLUMN IF NOT EXISTS secretaire_image TEXT;

-- Insertion d'une ligne de configuration par défaut
INSERT OR IGNORE INTO config_etablissement (id, nom_etablissement) VALUES (1, 'Nom du Collège');


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
    montant INTEGER NOT NULL, -- Stocké en centimes
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

-- Table pour les demandes de fonds sociaux
CREATE TABLE IF NOT EXISTS demandes_fonds_sociaux (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    participant_id INTEGER NOT NULL,
    montant_demande INTEGER NOT NULL, -- Stocké en centimes
    montant_accorde INTEGER, -- Stocké en centimes
    date_commission DATE,
    statut TEXT NOT NULL CHECK(statut IN ('EN_COURS', 'VALIDE', 'REFUSE')),
    motif_affectation TEXT,
    is_processed INTEGER NOT NULL DEFAULT 0, -- 0 for false, 1 for true
    FOREIGN KEY (participant_id) REFERENCES participants (id) ON DELETE CASCADE
);


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
