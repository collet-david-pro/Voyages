import sqlite3
import os
import sys
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, g, abort, make_response
from flask import send_from_directory
import webbrowser
import math
from werkzeug.utils import secure_filename
from threading import Timer


app = Flask(__name__)

# Détermine le chemin de base pour l'application (fonctionne en mode normal et après compilation avec PyInstaller)
if getattr(sys, 'frozen', False):
    # Si l'application est "gelée" (compilée en .exe)
    basedir = os.path.dirname(sys.executable)
else:
    # En mode développement normal
    basedir = os.path.dirname(os.path.abspath(__file__))
app.config['DATABASE'] = os.path.join(basedir, 'voyages_scolaires.db')
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'uploads')

# -------------------------------------------
#  Gestion de la base de données
# -------------------------------------------

def get_db():
    """Ouvre une nouvelle connexion à la base de données si aucune n'existe pour le contexte actuel."""
    if 'db' not in g:
        g.db = sqlite3.connect(
            app.config['DATABASE'],
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    """Ferme la connexion à la base de données à la fin de la requête."""
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    """Initialise la base de données avec le schéma."""
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()

# -------------------------------------------
#  Fonctions utilitaires pour la base de données
# -------------------------------------------

def get_voyage(voyage_id):
    """Récupère un voyage par son ID, lève une erreur 404 si non trouvé."""
    db = get_db()
    voyage = db.execute(
        'SELECT * FROM voyages WHERE id = ?', (voyage_id,)
    ).fetchone()
    if voyage is None:
        abort(404, f"Le voyage avec l'ID {voyage_id} n'existe pas.")
    return voyage

def get_eleve(eleve_id):
    """Récupère un élève par son ID, lève une erreur 404 si non trouvé."""
    db = get_db()
    eleve = db.execute(
        'SELECT * FROM eleves WHERE id = ?', (eleve_id,)
    ).fetchone()
    if eleve is None:
        abort(404, f"L'élève avec l'ID {eleve_id} n'existe pas.")
    return eleve

def get_paiement(paiement_id):
    """Récupère un paiement par son ID, lève une erreur 404 si non trouvé."""
    db = get_db()
    paiement = db.execute(
        'SELECT * FROM paiements WHERE id = ?', (paiement_id,)
    ).fetchone()
    if paiement is None:
        abort(404, f"Le paiement avec l'ID {paiement_id} n'existe pas.")
    return paiement

# -------------------------------------------
#  Routes principales
# -------------------------------------------

@app.route('/')
def index():
    """Affiche la liste de tous les voyages et des documents généraux."""
    db = get_db()
    voyages_raw = db.execute(
        'SELECT * FROM voyages ORDER BY date_depart DESC'
    ).fetchall()

    # Conversion manuelle des dates pour éviter les erreurs dans le template
    voyages = []
    for v in voyages_raw:
        v_dict = dict(v)
        v_dict['date_depart'] = datetime.strptime(v['date_depart'], '%Y-%m-%d').date() if isinstance(v['date_depart'], str) else v['date_depart']
        voyages.append(v_dict)
    return render_template('index.html', voyages=voyages)

@app.route('/voyage/<int:voyage_id>/documents/ajouter', methods=['POST'])
def ajouter_document(voyage_id):
    """Ajoute un document à un voyage spécifique."""
    if 'document' not in request.files:
        return redirect(url_for('voyage_details', voyage_id=voyage_id))

    file = request.files['document']
    if file.filename == '':
        return redirect(url_for('voyage_details', voyage_id=voyage_id))

    if file:
        filename = secure_filename(file.filename)
        # Pour éviter les conflits, on peut préfixer avec un timestamp
        unique_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))

        db = get_db()
        db.execute(
            "INSERT INTO documents (voyage_id, nom_fichier, chemin_stockage, date_upload) VALUES (?, ?, ?, ?)",
            (voyage_id, filename, unique_filename, date.today())
        )
        db.commit()

    return redirect(url_for('voyage_details', voyage_id=voyage_id, tab='documents'))

@app.route('/documents/telecharger/<path:filename>')
def telecharger_document(filename):
    """Permet de télécharger un document."""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

@app.route('/documents/supprimer/<int:doc_id>', methods=['POST'])
def supprimer_document(doc_id):
    """Supprime un document de la base de données et du disque."""
    db = get_db()
    doc = db.execute(
        'SELECT voyage_id, chemin_stockage FROM documents WHERE id = ?', (doc_id,)
    ).fetchone()

    if doc:
        voyage_id = doc['voyage_id']
        # Supprimer le fichier physique
        try:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], doc['chemin_stockage'])
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError as e:
            print(f"Erreur lors de la suppression du fichier {doc['chemin_stockage']}: {e}")

        # Supprimer l'entrée dans la base de données
        db.execute('DELETE FROM documents WHERE id = ?', (doc_id,))
        db.commit()
        return redirect(url_for('voyage_details', voyage_id=voyage_id, tab='documents'))

    # Si le document n'existe pas, rediriger vers l'accueil
    return redirect(url_for('index'))

@app.route('/voyage/<int:voyage_id>')
def voyage_details(voyage_id):
    """Affiche les détails d'un voyage, y compris les élèves et les paiements."""
    voyage = get_voyage(voyage_id)
    db = get_db()
    
    eleves_raw = db.execute(
        'SELECT * FROM eleves WHERE voyage_id = ? ORDER BY nom, prenom', (voyage_id,)
    ).fetchall()
    nb_inscrits = len([e for e in eleves_raw if e['statut'] == 'INSCRIT'])
    nb_attente = len([e for e in eleves_raw if e['statut'] == 'LISTE_ATTENTE'])

    documents = db.execute(
        'SELECT * FROM documents WHERE voyage_id = ? ORDER BY date_upload DESC', (voyage_id,)
    ).fetchall()

    modes_paiement = db.execute('SELECT * FROM modes_paiement ORDER BY libelle').fetchall()

    eleves_details = []
    total_percu_voyage = 0.0
    for eleve in eleves_raw:
        eleve_dict = dict(eleve)

        # Calculer les finances pour chaque élève, quel que soit son statut
        paiements = db.execute(
            'SELECT SUM(montant) as total FROM paiements WHERE eleve_id = ?', (eleve['id'],)
        ).fetchone()
        total_paye_eleve = paiements['total'] or 0.0
        eleve_dict['total_paye'] = total_paye_eleve
        eleve_dict['reste_a_payer'] = voyage['prix_eleve'] - total_paye_eleve

        # Ajouter au total perçu uniquement si l'élève est inscrit
        if eleve['statut'] == 'INSCRIT':
            total_percu_voyage += total_paye_eleve

        eleves_details.append(eleve_dict)

    montant_total_attendu = voyage['nb_participants_attendu'] * voyage['prix_eleve']

    return render_template('voyage_details.html', voyage=voyage, eleves=eleves_details, modes_paiement=modes_paiement,
                           documents=documents, nb_inscrits=nb_inscrits, total_percu_voyage=total_percu_voyage,
                           montant_total_attendu=montant_total_attendu, nb_attente=nb_attente)

# -------------------------------------------
#  Gestion des voyages
# -------------------------------------------

@app.route('/voyage/ajouter', methods=['POST'])
def ajouter_voyage():
    """Ajoute un nouveau voyage."""
    destination = request.form['destination']
    date_depart_str = request.form['date_depart']
    prix_eleve = request.form['prix_eleve']
    nb_participants = request.form['nb_participants_attendu']
    nb_accompagnateurs = request.form.get('nb_accompagnateurs', 0)
    duree_sejour_nuits = request.form.get('duree_sejour_nuits', 1)

    if not all([destination, date_depart_str, prix_eleve, nb_participants, nb_accompagnateurs, duree_sejour_nuits]):
        # On pourrait ajouter un message flash pour l'utilisateur ici
        return redirect(url_for('index'))

    date_depart = datetime.strptime(date_depart_str, '%Y-%m-%d').date()

    db = get_db()
    db.execute(
        """INSERT INTO voyages 
           (destination, date_depart, prix_eleve, nb_participants_attendu, nb_accompagnateurs, duree_sejour_nuits) 
           VALUES (?, ?, ?, ?, ?, ?)""",
        (destination, date_depart, float(prix_eleve), int(nb_participants), int(nb_accompagnateurs), int(duree_sejour_nuits))
    )
    db.commit()
    return redirect(url_for('index'))

@app.route('/voyage/<int:voyage_id>/modifier', methods=['GET', 'POST'])
def modifier_voyage(voyage_id):
    """Affiche un formulaire pour modifier un voyage et traite la soumission."""
    voyage = get_voyage(voyage_id)
    db = get_db()

    if request.method == 'POST':
        destination = request.form['destination']
        date_depart_str = request.form['date_depart']
        prix_eleve = request.form['prix_eleve']
        nb_participants = request.form['nb_participants_attendu']
        nb_accompagnateurs = request.form.get('nb_accompagnateurs', 0)
        duree_sejour_nuits = request.form.get('duree_sejour_nuits', 1)

        if not all([destination, date_depart_str, prix_eleve, nb_participants, nb_accompagnateurs, duree_sejour_nuits]):
            # Idéalement, utiliser des messages flash pour les erreurs
            return redirect(url_for('modifier_voyage', voyage_id=voyage_id))

        date_depart = datetime.strptime(date_depart_str, '%Y-%m-%d').date()

        db.execute(
            """
            UPDATE voyages
            SET destination = ?, date_depart = ?, prix_eleve = ?, nb_participants_attendu = ?,
                nb_accompagnateurs = ?, duree_sejour_nuits = ?
            WHERE id = ?
            """,
            (destination, date_depart, float(prix_eleve), int(nb_participants), int(nb_accompagnateurs), int(duree_sejour_nuits), voyage_id)
        )
        db.commit()
        return redirect(url_for('voyage_details', voyage_id=voyage_id))

    return render_template('modifier_voyage.html', voyage=voyage)

@app.route('/voyage/<int:voyage_id>/supprimer', methods=['POST'])
def supprimer_voyage(voyage_id):
    """Supprime un voyage et toutes les données associées (élèves, paiements)."""
    # get_voyage va lever une 404 si le voyage n'existe pas, ce qui est une bonne sécurité.
    get_voyage(voyage_id)
    
    db = get_db()

    # 1. Récupérer les chemins des fichiers à supprimer
    docs_a_supprimer = db.execute(
        'SELECT chemin_stockage FROM documents WHERE voyage_id = ?', (voyage_id,)
    ).fetchall()

    # 2. Supprimer le voyage de la DB (ce qui supprime en cascade élèves, paiements, documents, etc.)
    db.execute('DELETE FROM voyages WHERE id = ?', (voyage_id,))
    db.commit()

    # 3. Supprimer les fichiers physiques
    for doc in docs_a_supprimer:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], doc['chemin_stockage'])
        if os.path.exists(file_path):
            os.remove(file_path)
    db.commit()
    
    # Après la suppression, on redirige vers la page d'accueil.
    return redirect(url_for('index'))

# -------------------------------------------
#  Gestion des élèves
# -------------------------------------------

@app.route('/eleve/ajouter', methods=['POST'])
def ajouter_eleve():
    """Ajoute un élève à un voyage."""
    voyage_id = int(request.form['voyage_id'])
    nom = request.form['nom']
    prenom = request.form['prenom']
    classe = request.form['classe']

    if not all([voyage_id, nom, prenom, classe]):
        # Redirection avec un message d'erreur serait mieux
        return redirect(url_for('voyage_details', voyage_id=voyage_id))

    db = get_db()
    voyage = get_voyage(voyage_id)
    nb_inscrits = db.execute(
        'SELECT COUNT(id) FROM eleves WHERE voyage_id = ? AND statut = ?', (voyage_id, 'INSCRIT')
    ).fetchone()[0]

    # Si le nombre d'inscrits est déjà atteint, le nouvel élève passe en liste d'attente
    statut_initial = 'INSCRIT' if nb_inscrits < voyage['nb_participants_attendu'] else 'LISTE_ATTENTE'

    db.execute(
        "INSERT INTO eleves (voyage_id, nom, prenom, classe, statut) VALUES (?, ?, ?, ?, ?)",
        (voyage_id, nom, prenom, classe, statut_initial)
    )
    db.commit()
    return redirect(url_for('voyage_details', voyage_id=voyage_id))

@app.route('/eleve/statut', methods=['POST'])
def modifier_statut_eleve():
    """Modifie le statut d'un élève (INSCRIT, ANNULÉ, A_REMBOURSER, LISTE_ATTENTE)."""
    voyage_id = request.form['voyage_id']
    eleve_id = request.form['eleve_id']
    nouveau_statut = request.form['statut']

    db = get_db()
    final_statut = nouveau_statut

    # Règle spéciale pour l'annulation : vérifier s'il faut rembourser.
    if nouveau_statut == 'ANNULÉ':
        result = db.execute(
            'SELECT SUM(montant) as total FROM paiements WHERE eleve_id = ?', (eleve_id,)
        ).fetchone()
        total_paye = result['total'] if result and result['total'] is not None else 0.0

        if total_paye > 0:
            final_statut = 'A_REMBOURSER'

    db.execute('UPDATE eleves SET statut = ? WHERE id = ?', (final_statut, eleve_id))
    db.commit()
    return redirect(url_for('voyage_details', voyage_id=voyage_id))

@app.route('/eleve/toggle_validation', methods=['POST'])
def toggle_validation():
    """Met à jour une case à cocher de validation pour un élève (via JS)."""
    data = request.get_json()
    eleve_id = data.get('eleve_id')
    field = data.get('field')

    # Sécurité : ne permettre que la modification des champs prévus
    if field not in ['fiche_engagement', 'liste_definitive']:
        return {"status": "error", "message": "Champ non valide"}, 400

    if not eleve_id:
        return {"status": "error", "message": "ID de l'élève manquant"}, 400

    db = get_db()
    # On récupère la valeur actuelle pour l'inverser (0 -> 1, 1 -> 0)
    current_value = db.execute(
        f'SELECT {field} FROM eleves WHERE id = ?', (eleve_id,)
    ).fetchone()[0]

    new_value = 1 - current_value

    db.execute(f'UPDATE eleves SET {field} = ? WHERE id = ?', (new_value, eleve_id))
    db.commit()

    return {"status": "success", "new_value": new_value}

@app.route('/eleve/<int:eleve_id>/paiements')
def eleve_paiements(eleve_id):
    """Affiche la liste des paiements pour un élève donné."""
    eleve = get_eleve(eleve_id)
    voyage = get_voyage(eleve['voyage_id'])
    db = get_db()
    
    paiements = db.execute(
        """
        SELECT p.id, p.montant, p.date, p.reference, mp.libelle as mode_paiement
        FROM paiements p
        JOIN modes_paiement mp ON p.mode_paiement_id = mp.id
        WHERE p.eleve_id = ?
        ORDER BY p.date DESC
        """,
        (eleve_id,)
    ).fetchall()

    total_paye = sum(p['montant'] for p in paiements)
    reste_a_payer = voyage['prix_eleve'] - total_paye

    return render_template(
        'eleve_paiements.html',
        eleve=eleve,
        voyage=voyage,
        paiements=paiements,
        total_paye=total_paye,
        reste_a_payer=reste_a_payer
    )

@app.route('/attestation/<int:eleve_id>/pdf')
def generer_attestation_pdf(eleve_id):
    """Génère une attestation de paiement en PDF pour un élève."""
    from fpdf import FPDF

    eleve = get_eleve(eleve_id)
    voyage = get_voyage(eleve['voyage_id'])
    db = get_db()

    paiements = db.execute(
        """
        SELECT p.montant, p.date, mp.libelle as mode_paiement
        FROM paiements p JOIN modes_paiement mp ON p.mode_paiement_id = mp.id
        WHERE p.eleve_id = ? ORDER BY p.date
        """, (eleve_id,)
    ).fetchall()

    total_paye = sum(p['montant'] for p in paiements)

    params_raw = db.execute("SELECT cle, valeur FROM parametres").fetchall()
    params = {p['cle']: p['valeur'] for p in params_raw}

    pdf = FPDF()
    pdf.add_page()

    # En-tête
    pdf.set_font('Helvetica', 'B', 14)
    pdf.cell(0, 10, params.get('nom_college', 'Nom du Collège'), 0, 1, 'L')
    pdf.set_font('Helvetica', '', 12)
    pdf.cell(0, 10, 'Service de Gestion', 0, 1, 'L')
    pdf.ln(15)

    # Titre du document
    pdf.set_font('Helvetica', 'B', 16)
    pdf.cell(0, 10, 'Attestation de Paiement', 0, 1, 'C')
    pdf.ln(10)

    # Informations sur le voyage et l'élève
    pdf.set_font('Helvetica', '', 12)
    pdf.cell(0, 10, f"Voyage : {voyage['destination']}", 0, 1)
    pdf.cell(0, 10, f"Date du voyage : {voyage['date_depart'].strftime('%d/%m/%Y')}", 0, 1)
    pdf.ln(5)
    pdf.cell(0, 10, f"Élève : {eleve['prenom']} {eleve['nom']}", 0, 1)
    pdf.cell(0, 10, f"Classe : {eleve['classe']}", 0, 1)
    pdf.ln(10)

    # Corps du texte
    pdf.set_font('Helvetica', 'I', 11)
    pdf.multi_cell(0, 5, params.get('texte_attestation', ''))
    pdf.ln(10)

    # Tableau des paiements
    pdf.set_font('Helvetica', 'B', 12)
    pdf.cell(40, 10, 'Date', 1, 0, 'C')
    pdf.cell(80, 10, 'Mode de paiement', 1, 0, 'C')
    pdf.cell(40, 10, 'Montant', 1, 1, 'C')

    # Lignes du tableau
    pdf.set_font('Helvetica', '', 11)
    for p in paiements:
        pdf.cell(40, 10, p['date'].strftime('%d/%m/%Y'), 1, 0, 'C')
        pdf.cell(80, 10, p['mode_paiement'], 1, 0, 'L')
        pdf.cell(40, 10, f"{p['montant']:.2f} EUR", 1, 1, 'R')

    # Ligne du total
    pdf.set_font('Helvetica', 'B', 12)
    pdf.cell(120, 10, 'Total versé', 1, 0, 'R')
    pdf.cell(40, 10, f"{total_paye:.2f} EUR", 1, 1, 'R')
    pdf.ln(20)

    # Pied de page avec signatures
    pdf.set_font('Helvetica', '', 11)
    pdf.cell(0, 7, f"Fait à {params.get('ville_college', 'Ville')}, le {datetime.now().strftime('%d/%m/%Y')}", 0, 1, 'R')
    pdf.ln(15)
    pdf.cell(95, 7, 'Le Principal,', 0, 0, 'C')
    pdf.cell(95, 7, 'Le Secrétaire Général,', 0, 1, 'C')
    pdf.ln(15)
    pdf.cell(95, 7, params.get('nom_principal', ''), 0, 0, 'C')
    pdf.cell(95, 7, params.get('nom_secretaire_general', ''), 0, 1, 'C')

    response = make_response(pdf.output())
    response.headers.set('Content-Disposition', 'attachment', filename=f"attestation_{eleve['nom']}_{eleve['prenom']}.pdf")
    response.headers.set('Content-Type', 'application/pdf')
    return response

@app.route('/voyage/<int:voyage_id>/liste_eleves_pdf', methods=['POST'])
def generer_liste_eleves_pdf(voyage_id):
    """Génère une liste d'élèves en PDF avec des filtres."""
    from fpdf import FPDF

    filtre = request.form.get('filtre', 'tous')
    voyage = get_voyage(voyage_id)
    db = get_db()

    # 1. Récupérer tous les élèves avec leurs détails financiers
    eleves_raw = db.execute(
        'SELECT * FROM eleves WHERE voyage_id = ? ORDER BY nom, prenom', (voyage_id,)
    ).fetchall()

    eleves_details = []
    for eleve in eleves_raw:
        eleve_dict = dict(eleve)
        paiements = db.execute('SELECT SUM(montant) as total FROM paiements WHERE eleve_id = ?', (eleve['id'],)).fetchone()
        total_paye = paiements['total'] or 0.0
        eleve_dict['total_paye'] = total_paye
        eleve_dict['reste_a_payer'] = voyage['prix_eleve'] - total_paye
        eleves_details.append(eleve_dict)

    # 2. Appliquer le filtre
    if filtre == 'paye':
        eleves_filtres = [e for e in eleves_details if e['statut'] == 'INSCRIT' and e['reste_a_payer'] <= 0]
        titre_filtre = " (Paiements soldés)"
    elif filtre == 'non_paye':
        eleves_filtres = [e for e in eleves_details if e['statut'] == 'INSCRIT' and e['reste_a_payer'] > 0]
        titre_filtre = " (Paiements en attente)"
    else: # 'tous'
        eleves_filtres = eleves_details
        titre_filtre = " (Tous les statuts)"

    # 3. Générer le PDF
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    pdf.set_font('Helvetica', 'B', 16)
    pdf.cell(0, 10, f"Liste des élèves - Voyage {voyage['destination']}", 0, 1, 'C')
    pdf.set_font('Helvetica', 'I', 12)
    pdf.cell(0, 10, f"Filtre appliqué : {titre_filtre}", 0, 1, 'C')
    pdf.ln(10)

    # En-têtes du tableau
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(40, 10, 'Nom', 1, 0, 'C')
    pdf.cell(40, 10, 'Prénom', 1, 0, 'C')
    pdf.cell(30, 10, 'Classe', 1, 0, 'C')
    pdf.cell(40, 10, 'Statut', 1, 0, 'C')
    pdf.cell(35, 10, 'Total Payé', 1, 0, 'C')
    pdf.cell(35, 10, 'Reste à Payer', 1, 1, 'C')

    # Lignes du tableau
    pdf.set_font('Helvetica', '', 10)
    for eleve in eleves_filtres:
        pdf.cell(40, 10, eleve['nom'], 1)
        pdf.cell(40, 10, eleve['prenom'], 1)
        pdf.cell(30, 10, eleve['classe'], 1, 0, 'C')
        pdf.cell(40, 10, eleve['statut'].replace('_', ' ').title(), 1, 0, 'C')
        pdf.cell(35, 10, f"{eleve['total_paye']:.2f} EUR", 1, 0, 'R')
        pdf.cell(35, 10, f"{eleve['reste_a_payer']:.2f} EUR", 1, 1, 'R')

    response = make_response(pdf.output())
    response.headers.set('Content-Disposition', 'attachment', filename=f"liste_eleves_{voyage['destination']}_{filtre}.pdf")
    response.headers.set('Content-Type', 'application/pdf')
    return response

@app.route('/voyage/<int:voyage_id>/generer_echeancier_pdf', methods=['POST'])
def generer_echeancier_pdf(voyage_id):
    """Génère une lettre type pour les familles avec un échéancier de paiement."""
    from fpdf import FPDF

    voyage = get_voyage(voyage_id)
    db = get_db()

    # Récupérer les paramètres de configuration
    params_raw = db.execute("SELECT cle, valeur FROM parametres").fetchall()
    params = {p['cle']: p['valeur'] for p in params_raw}

    # Récupérer les données du formulaire
    methode_calcul = request.form.get('methode_calcul')
    prix_total = voyage['prix_eleve']
    echeances = []

    if methode_calcul == 'nombre':
        nombre = int(request.form.get('nombre_echeances', 1))
        if nombre > 0:
            montant_echeance = prix_total / nombre
            for i in range(nombre):
                echeances.append(f"Echéance {i+1}: {montant_echeance:.2f} EUR")
    elif methode_calcul == 'montant':
        montant = float(request.form.get('montant_echeance', prix_total))
        if montant > 0:
            nombre_echeances = math.ceil(prix_total / montant)
            for i in range(nombre_echeances):
                montant_a_afficher = montant if (i < nombre_echeances - 1) else prix_total - (montant * (nombre_echeances - 1))
                echeances.append(f"Echéance {i+1}: {montant_a_afficher:.2f} EUR")

    # Génération du PDF
    pdf = FPDF()
    pdf.add_page()

    # En-tête de l'établissement
    pdf.set_font('Helvetica', 'B', 14)
    pdf.cell(0, 10, params.get('nom_college', 'Nom du Collège'), 0, 1, 'L')
    pdf.set_font('Helvetica', '', 12)
    pdf.cell(0, 10, 'Service de Gestion', 0, 1, 'L')
    pdf.ln(15)

    # Titre
    pdf.set_font('Helvetica', 'B', 16)
    pdf.cell(0, 10, f"Information - Voyage Scolaire : {voyage['destination']}", 0, 1, 'C')
    pdf.ln(10)

    # Corps de la lettre
    pdf.set_font('Helvetica', '', 12)
    pdf.multi_cell(0, 7, f"Madame, Monsieur,\n\n"
                         f"Nous avons le plaisir de vous informer de l'organisation d'un voyage scolaire à destination de {voyage['destination']}, "
                         f"qui se déroulera à partir du {voyage['date_depart'].strftime('%d/%m/%Y')}.\n\n"
                         f"Le coût total de la participation pour chaque élève a été fixé à {prix_total:.2f} EUR.")
    pdf.ln(10)

    if echeances:
        pdf.set_font('Helvetica', 'B', 12)
        pdf.cell(0, 10, "Proposition d'échéancier de paiement :", 0, 1)
        pdf.set_font('Helvetica', '', 12)
        for echeance in echeances:
            pdf.cell(0, 7, f"- {echeance}", 0, 1)
        pdf.ln(5)
        pdf.set_font('Helvetica', 'I', 10)
        pdf.multi_cell(0, 5, "Veuillez noter que les dates limites pour chaque paiement vous seront communiquées ultérieurement. "
                              "N'hésitez pas à contacter le service de gestion pour toute question.")

    pdf.ln(20)
    pdf.set_font('Helvetica', '', 12)
    pdf.cell(0, 10, "Cordialement,", 0, 1)
    pdf.cell(0, 10, "L'équipe de gestion.", 0, 1)

    response = make_response(pdf.output())
    response.headers.set('Content-Disposition', 'attachment', filename=f"echeancier_{voyage['destination']}.pdf")
    response.headers.set('Content-Type', 'application/pdf')
    return response

# -------------------------------------------
#  Gestion du budget
# -------------------------------------------

@app.route('/voyage/<int:voyage_id>/budget')
def voyage_budget(voyage_id):
    """Affiche la page de gestion du budget pour un voyage."""
    voyage = get_voyage(voyage_id)
    db = get_db()

    categories = db.execute('SELECT * FROM budget_categories ORDER BY nom').fetchall()
    
    items = db.execute(
        """
        SELECT bi.*, bc.nom as categorie_nom FROM budget_items bi
        JOIN budget_categories bc ON bi.categorie_id = bc.id
        WHERE bi.voyage_id = ? ORDER BY bi.type, bc.nom
        """, (voyage_id,)
    ).fetchall()

    depenses = [item for item in items if item['type'] == 'depense']
    recettes = [item for item in items if item['type'] == 'recette']

    total_depenses = sum(item['montant'] for item in depenses)
    total_recettes = sum(item['montant'] for item in recettes)
    solde = total_recettes - total_depenses

    return render_template('voyage_budget.html', voyage=voyage, categories=categories,
                           depenses=depenses, recettes=recettes, total_depenses=total_depenses,
                           total_recettes=total_recettes, solde=solde)

@app.route('/budget/ajouter', methods=['POST'])
def ajouter_item_budget():
    """Ajoute une ligne de dépense ou de recette au budget."""
    voyage_id = request.form['voyage_id']
    type = request.form['type']
    categorie_id = request.form['categorie_id']
    description = request.form['description']
    montant = request.form['montant']

    if not all([voyage_id, type, categorie_id, description, montant]):
        return redirect(url_for('voyage_budget', voyage_id=voyage_id))

    db = get_db()
    db.execute(
        'INSERT INTO budget_items (voyage_id, type, categorie_id, description, montant) VALUES (?, ?, ?, ?, ?)',
        (voyage_id, type, categorie_id, description, float(montant))
    )
    db.commit()
    return redirect(url_for('voyage_budget', voyage_id=voyage_id))

@app.route('/budget/supprimer/<int:item_id>', methods=['POST'])
def supprimer_item_budget(item_id):
    """Supprime une ligne du budget."""
    db = get_db()
    item = db.execute('SELECT voyage_id FROM budget_items WHERE id = ?', (item_id,)).fetchone()
    if item:
        voyage_id = item['voyage_id']
        db.execute('DELETE FROM budget_items WHERE id = ?', (item_id,))
        db.commit()
        return redirect(url_for('voyage_budget', voyage_id=voyage_id))
    return redirect(url_for('index'))

@app.route('/voyage/<int:voyage_id>/budget_pdf')
def generer_budget_pdf(voyage_id):
    """Génère le PDF détaillé du budget."""
    from fpdf import FPDF

    voyage = get_voyage(voyage_id)
    db = get_db()

    items = db.execute(
        """
        SELECT bi.*, bc.nom as categorie_nom FROM budget_items bi
        JOIN budget_categories bc ON bi.categorie_id = bc.id
        WHERE bi.voyage_id = ? ORDER BY bi.type DESC, bc.nom
        """, (voyage_id,)
    ).fetchall()

    depenses = [item for item in items if item['type'] == 'depense']
    recettes = [item for item in items if item['type'] == 'recette']
    total_depenses = sum(item['montant'] for item in depenses)
    total_recettes = sum(item['montant'] for item in recettes)
    solde = total_recettes - total_depenses

    # Calculs statistiques
    nb_eleves = voyage['nb_participants_attendu']
    nb_accompagnateurs = voyage['nb_accompagnateurs']
    nb_total_participants = nb_eleves + nb_accompagnateurs
    duree = voyage['duree_sejour_nuits']

    prix_moyen_nuite = (total_depenses / duree) / nb_total_participants if duree > 0 and nb_total_participants > 0 else 0
    prix_par_eleve = total_depenses / nb_eleves if nb_eleves > 0 else 0
    prix_par_accompagnateur = total_depenses / nb_accompagnateurs if nb_accompagnateurs > 0 else 0
    prix_moyen_participant = total_depenses / nb_total_participants if nb_total_participants > 0 else 0

    # Génération du PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font('Helvetica', 'B', 16)
    pdf.cell(0, 10, f"Budget prévisionnel - Voyage {voyage['destination']}", 0, 1, 'C')
    pdf.ln(10)

    def draw_table(title, data, color):
        pdf.set_font('Helvetica', 'B', 12)
        pdf.set_fill_color(color[0], color[1], color[2])
        pdf.cell(0, 10, title, 1, 1, 'C', 1)
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(130, 7, 'Description', 1)
        pdf.cell(60, 7, 'Montant', 1, 1, 'C')
        pdf.set_font('Helvetica', '', 10)
        for item in data:
            pdf.cell(130, 7, f"{item['categorie_nom']} - {item['description']}", 1)
            pdf.cell(60, 7, f"{item['montant']:.2f} EUR", 1, 1, 'R')

    draw_table(f"Recettes ({total_recettes:.2f} EUR)", recettes, (223, 240, 216)) # Vert clair
    pdf.ln(5)
    draw_table(f"Dépenses ({total_depenses:.2f} EUR)", depenses, (248, 215, 218)) # Rouge clair
    pdf.ln(10)

    pdf.set_font('Helvetica', 'B', 14)
    solde_str = f"+{solde:.2f}" if solde >= 0 else f"{solde:.2f}"
    pdf.cell(0, 10, f"Solde prévisionnel : {solde_str} EUR", 1, 1, 'C')
    pdf.ln(10)

    pdf.set_font('Helvetica', 'B', 12)
    pdf.cell(0, 10, "Indicateurs Clés", 0, 1)
    pdf.set_font('Helvetica', '', 10)
    pdf.multi_cell(0, 7, f"- Coût total par élève : {prix_par_eleve:.2f} EUR\n"
                         f"- Coût total par accompagnateur : {prix_par_accompagnateur:.2f} EUR\n"
                         f"- Coût moyen par participant (tous inclus) : {prix_moyen_participant:.2f} EUR\n"
                         f"- Coût moyen par nuit et par participant : {prix_moyen_nuite:.2f} EUR")

    response = make_response(pdf.output())
    response.headers.set('Content-Disposition', 'attachment', filename=f"budget_{voyage['destination']}.pdf")
    response.headers.set('Content-Type', 'application/pdf')
    return response

# -------------------------------------------
#  Gestion des paiements
# -------------------------------------------

@app.route('/paiement/ajouter', methods=['POST'])
def ajouter_paiement():
    """Ajoute un paiement pour un élève."""
    voyage_id = request.form['voyage_id']
    eleve_id = request.form['eleve_id']
    mode_paiement_id = request.form['mode_paiement_id']
    montant = request.form['montant']
    date_paiement_str = request.form['date']
    reference = request.form.get('reference', '') # .get pour les champs optionnels

    if not all([voyage_id, eleve_id, mode_paiement_id, montant, date_paiement_str]):
        return redirect(url_for('voyage_details', voyage_id=voyage_id))

    date_paiement = datetime.strptime(date_paiement_str, '%Y-%m-%d').date()

    db = get_db()
    db.execute(
        'INSERT INTO paiements (eleve_id, mode_paiement_id, montant, date, reference) VALUES (?, ?, ?, ?, ?)',
        (eleve_id, mode_paiement_id, float(montant), date_paiement, reference)
    )
    db.commit()
    return redirect(url_for('voyage_details', voyage_id=voyage_id))

@app.route('/paiement/<int:paiement_id>/modifier', methods=['GET', 'POST'])
def modifier_paiement(paiement_id):
    """Modifie un paiement existant."""
    paiement = get_paiement(paiement_id)
    eleve = get_eleve(paiement['eleve_id'])
    db = get_db()

    if request.method == 'POST':
        montant = request.form['montant']
        mode_paiement_id = request.form['mode_paiement_id']
        date_paiement_str = request.form['date']
        reference = request.form.get('reference', '')

        if not all([montant, mode_paiement_id, date_paiement_str]):
            # Idéalement, utiliser des messages flash pour les erreurs
            return redirect(url_for('modifier_paiement', paiement_id=paiement_id))

        date_paiement = datetime.strptime(date_paiement_str, '%Y-%m-%d').date()

        db.execute(
            """
            UPDATE paiements
            SET montant = ?, mode_paiement_id = ?, date = ?, reference = ?
            WHERE id = ?
            """,
            (float(montant), mode_paiement_id, date_paiement, reference, paiement_id)
        )
        db.commit()
        return redirect(url_for('eleve_paiements', eleve_id=eleve['id']))

    modes_paiement = db.execute('SELECT * FROM modes_paiement ORDER BY libelle').fetchall()
    return render_template('modifier_paiement.html', paiement=paiement, eleve=eleve, modes_paiement=modes_paiement)

@app.route('/paiement/<int:paiement_id>/supprimer', methods=['POST'])
def supprimer_paiement(paiement_id):
    """Supprime un paiement."""
    paiement = get_paiement(paiement_id)
    eleve = get_eleve(paiement['eleve_id'])
    db = get_db()
    
    db.execute('DELETE FROM paiements WHERE id = ?', (paiement_id,))
    db.commit()
    
    return redirect(url_for('eleve_paiements', eleve_id=eleve['id']))




# -------------------------------------------
#  Configuration
# -------------------------------------------

@app.route('/configuration')
def configuration():
    """Affiche la page de configuration des modes de paiement."""
    db = get_db()
    modes = db.execute('SELECT * FROM modes_paiement ORDER BY libelle').fetchall()
    categories = db.execute('SELECT * FROM budget_categories ORDER BY nom').fetchall()

    parametres_raw = db.execute("SELECT cle, valeur FROM parametres").fetchall()
    parametres = {p['cle']: p['valeur'] for p in parametres_raw}

    return render_template('configuration.html', modes=modes, categories=categories, parametres=parametres)

@app.route('/configuration/ajouter', methods=['POST'])
def ajouter_mode_paiement():
    """Ajoute un nouveau mode de paiement."""
    libelle = request.form['libelle']
    if libelle:
        db = get_db()
        try:
            db.execute('INSERT INTO modes_paiement (libelle) VALUES (?)', (libelle,))
            db.commit()
        except sqlite3.IntegrityError:
            # Le libellé existe déjà, ignorer l'erreur.
            pass
    return redirect(url_for('configuration'))

@app.route('/configuration/supprimer/<int:mode_id>', methods=['POST'])
def supprimer_mode_paiement(mode_id):
    """Supprime un mode de paiement."""
    db = get_db()
    try:
        db.execute('DELETE FROM modes_paiement WHERE id = ?', (mode_id,))
        db.commit()
    except sqlite3.IntegrityError:
        # Empêche le crash si le mode est utilisé.
        # Idéalement, on afficherait un message d'erreur à l'utilisateur.
        print(f"Tentative de suppression du mode de paiement {mode_id} qui est en cours d'utilisation.")
    return redirect(url_for('configuration'))

@app.route('/configuration/budget/categorie/ajouter', methods=['POST'])
def ajouter_categorie_budget():
    """Ajoute une nouvelle catégorie de budget."""
    nom = request.form['nom']
    if nom:
        db = get_db()
        try:
            db.execute('INSERT INTO budget_categories (nom) VALUES (?)', (nom,))
            db.commit()
        except sqlite3.IntegrityError:
            pass # La catégorie existe déjà, on ignore.
    return redirect(url_for('configuration'))

@app.route('/configuration/budget/categorie/supprimer/<int:categorie_id>', methods=['POST'])
def supprimer_categorie_budget(categorie_id):
    """Supprime une catégorie de budget."""
    db = get_db()
    try:
        db.execute('DELETE FROM budget_categories WHERE id = ?', (categorie_id,))
        db.commit()
    except sqlite3.IntegrityError:
        print(f"Tentative de suppression de la catégorie {categorie_id} qui est en cours d'utilisation.")
    return redirect(url_for('configuration'))

@app.route('/configuration/enregistrer_parametres', methods=['POST'])
def enregistrer_parametres():
    """Enregistre les paramètres généraux comme le texte de l'attestation."""
    db = get_db()
    parametres_cles = ['texte_attestation', 'nom_college', 'ville_college', 'nom_principal', 'nom_secretaire_general']
    
    for cle in parametres_cles:
        valeur = request.form.get(cle)
        if valeur is not None:
            db.execute("UPDATE parametres SET valeur = ? WHERE cle = ?", (valeur, cle))
    db.commit()
    return redirect(url_for('configuration'))

# -------------------------------------------
#  Initialisation et lancement de l'application
# -------------------------------------------

def open_browser():
    """Ouvre le navigateur par défaut sur la page de l'application."""
    webbrowser.open_new('http://127.0.0.1:5001/')

if __name__ == '__main__':
    # Initialise la base de données si elle n'existe pas
    if not os.path.exists(app.config['DATABASE']):
        init_db()
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    # Lance le navigateur 1 seconde après le démarrage du serveur
    Timer(1, open_browser).start()
    app.run(host='127.0.0.1', port=5001, debug=False)