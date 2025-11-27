import sqlite3
import os
import sys
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, g, abort, make_response
import webbrowser
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
    """Affiche la liste de tous les voyages."""
    db = get_db()
    voyages = db.execute(
        'SELECT * FROM voyages ORDER BY date_depart DESC'
    ).fetchall()
    return render_template('index.html', voyages=voyages)

@app.route('/voyage/<int:voyage_id>')
def voyage_details(voyage_id):
    """Affiche les détails d'un voyage, y compris les élèves et les paiements."""
    voyage = get_voyage(voyage_id)
    db = get_db()
    
    eleves_raw = db.execute(
        'SELECT * FROM eleves WHERE voyage_id = ? ORDER BY nom, prenom', (voyage_id,)
    ).fetchall()
    nb_inscrits = len([e for e in eleves_raw if e['statut'] == 'INSCRIT'])

    modes_paiement = db.execute('SELECT * FROM modes_paiement ORDER BY libelle').fetchall()

    eleves_details = []
    total_percu_voyage = 0.0
    for eleve in eleves_raw:
        paiements = db.execute(
            'SELECT SUM(montant) as total FROM paiements WHERE eleve_id = ?', (eleve['id'],)
        ).fetchone()
        total_paye = paiements['total'] or 0.0
        total_percu_voyage += total_paye
        
        eleve_dict = dict(eleve)
        eleve_dict['total_paye'] = total_paye
        eleve_dict['reste_a_payer'] = voyage['prix_eleve'] - total_paye
        eleves_details.append(eleve_dict)

    montant_total_attendu = voyage['nb_participants_attendu'] * voyage['prix_eleve']

    return render_template('voyage_details.html', voyage=voyage, eleves=eleves_details, modes_paiement=modes_paiement,
                           nb_inscrits=nb_inscrits, total_percu_voyage=total_percu_voyage,
                           montant_total_attendu=montant_total_attendu)

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

    if not all([destination, date_depart_str, prix_eleve, nb_participants]):
        # On pourrait ajouter un message flash pour l'utilisateur ici
        return redirect(url_for('index'))

    date_depart = datetime.strptime(date_depart_str, '%Y-%m-%d').date()

    db = get_db()
    db.execute(
        'INSERT INTO voyages (destination, date_depart, prix_eleve, nb_participants_attendu) VALUES (?, ?, ?, ?)',
        (destination, date_depart, float(prix_eleve), int(nb_participants))
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

        if not all([destination, date_depart_str, prix_eleve, nb_participants]):
            # Idéalement, utiliser des messages flash pour les erreurs
            return redirect(url_for('modifier_voyage', voyage_id=voyage_id))

        date_depart = datetime.strptime(date_depart_str, '%Y-%m-%d').date()

        db.execute(
            """
            UPDATE voyages
            SET destination = ?, date_depart = ?, prix_eleve = ?, nb_participants_attendu = ?
            WHERE id = ?
            """,
            (destination, date_depart, float(prix_eleve), int(nb_participants), voyage_id)
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
    db.execute('DELETE FROM voyages WHERE id = ?', (voyage_id,))
    db.commit()
    
    # Après la suppression, on redirige vers la page d'accueil.
    return redirect(url_for('index'))

# -------------------------------------------
#  Gestion des élèves
# -------------------------------------------

@app.route('/eleve/ajouter', methods=['POST'])
def ajouter_eleve():
    """Ajoute un élève à un voyage."""
    voyage_id = request.form['voyage_id']
    nom = request.form['nom']
    prenom = request.form['prenom']
    classe = request.form['classe']

    if not all([voyage_id, nom, prenom, classe]):
        # Redirection avec un message d'erreur serait mieux
        return redirect(url_for('voyage_details', voyage_id=voyage_id))

    db = get_db()
    db.execute(
        "INSERT INTO eleves (voyage_id, nom, prenom, classe, statut) VALUES (?, ?, ?, ?, 'INSCRIT')",
        (voyage_id, nom, prenom, classe)
    )
    db.commit()
    return redirect(url_for('voyage_details', voyage_id=voyage_id))

@app.route('/eleve/statut', methods=['POST'])
def modifier_statut_eleve():
    """Modifie le statut d'un élève (INSCRIT, ANNULÉ, A_REMBOURSER)."""
    voyage_id = request.form['voyage_id']
    eleve_id = request.form['eleve_id']
    nouveau_statut = request.form['statut']

    db = get_db()
    
    # Règle critique : si un élève annule avec des paiements, son statut passe à "A_REMBOURSER"
    if nouveau_statut == 'ANNULÉ':
        total_paye = db.execute(
            'SELECT SUM(montant) as total FROM paiements WHERE eleve_id = ?', (eleve_id,)
        ).fetchone()['total'] or 0.0
        
        final_statut = 'A_REMBOURSER' if total_paye > 0 else 'ANNULÉ'
    else:
        final_statut = nouveau_statut

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

    parametres_raw = db.execute("SELECT cle, valeur FROM parametres").fetchall()
    parametres = {p['cle']: p['valeur'] for p in parametres_raw}

    return render_template('configuration.html', modes=modes, parametres=parametres)

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
    # Attention: Pour une app plus robuste, il faudrait désactiver le mode
    # ou empêcher la suppression s'il est utilisé par des paiements.
    db = get_db()
    db.execute('DELETE FROM modes_paiement WHERE id = ?', (mode_id,))
    db.commit()
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
    # Lance le navigateur 1 seconde après le démarrage du serveur
    Timer(1, open_browser).start()
    app.run(host='127.0.0.1', port=5001, debug=False)