-- Schéma de la base de données pour l'application de gestion des voyages scolaires

-- Table des voyages
CREATE TABLE IF NOT EXISTS voyages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    destination TEXT NOT NULL,
    date_depart DATE NOT NULL, -- Changé en DATE pour une meilleure gestion
    prix_eleve REAL NOT NULL,
    nb_participants_attendu INTEGER NOT NULL DEFAULT 0
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
    statut TEXT NOT NULL CHECK(statut IN ('INSCRIT', 'ANNULÉ', 'A_REMBOURSER')),
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

-- Insertion des modes de paiement par défaut
INSERT OR IGNORE INTO modes_paiement (libelle) VALUES
('Chèque'),
('Espèces'),
('Virement'),
('Carte Bancaire');

-- Insertion du texte par défaut pour l'attestation
INSERT OR IGNORE INTO parametres (cle, valeur) VALUES
('texte_attestation', 'Je soussigné(e), [Nom du responsable], certifie que l''élève a bien réglé les sommes indiquées ci-dessous pour sa participation au voyage scolaire.');

-- Insertion des paramètres généraux pour l'attestation
INSERT OR IGNORE INTO parametres (cle, valeur) VALUES
('nom_college', 'Nom du Collège'),
('ville_college', 'Ville'),
('nom_principal', 'Nom du Principal'),
('nom_secretaire_general', 'Nom du Secrétaire Général');
