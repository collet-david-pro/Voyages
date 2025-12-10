from __future__ import annotations

import sqlite3
import os
import sys
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, g, abort, make_response, flash, jsonify
from flask import send_from_directory
import webbrowser
import math
from werkzeug.utils import secure_filename
from fpdf import FPDF, HTMLMixin
try:
    from PIL import Image
except Exception:
    Image = None
try:
    import webview
    WEBVIEW_AVAILABLE = True
except Exception:
    webview = None
    WEBVIEW_AVAILABLE = False

# Allow disabling embedded webview via environment variable
USE_WEBVIEW = os.environ.get('USE_WEBVIEW', '1') not in ('0', 'false', 'False')
WEBVIEW_ENABLED = WEBVIEW_AVAILABLE and USE_WEBVIEW
from threading import Timer, Thread
import random
import logging

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET', 'dev-secret-please-change')

# logging is configured after basedir is defined further down
logger = logging.getLogger(__name__)

# --- Fonctions et classes utilitaires pour la génération de PDF ---
def encode_str(s):
    """Encode les chaînes pour fpdf avec les polices standard (latin-1).
    Remplace les accents français problématiques par des variantes."""
    s = str(s)
    # Remplacer les accents problématiques
    replacements = {
        'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
        'à': 'a', 'â': 'a', 'ä': 'a',
        'ù': 'u', 'û': 'u', 'ü': 'u',
        'ô': 'o', 'ö': 'o',
        'î': 'i', 'ï': 'i',
        'ç': 'c',
        'É': 'E', 'È': 'E', 'Ê': 'E', 'Ë': 'E',
        'À': 'A', 'Â': 'A', 'Ä': 'A',
        'Ù': 'U', 'Û': 'U', 'Ü': 'U',
        'Ô': 'O', 'Ö': 'O',
        'Î': 'I', 'Ï': 'I',
        'Ç': 'C',
    }
    for old, new in replacements.items():
        s = s.replace(old, new)
    return s.encode('latin-1', 'replace').decode('latin-1')

def sanitize_filename(s):
    """Enlève les accents et caractères spéciaux du nom de fichier."""
    import unicodedata
    s = str(s)
    # Normaliser et enlever les accents
    nfkd_form = unicodedata.normalize('NFKD', s)
    return ''.join([c for c in nfkd_form if not unicodedata.combining(c)])


def save_uploaded_file(uploaded_file, subfolder='config', prefix=None):
    """Save uploaded file into uploads/<subfolder>/ and return relative path (subfolder/filename).
    Returns None if file not provided or invalid extension.
    """
    if not uploaded_file:
        return None
    if uploaded_file.filename == '':
        return None

    filename = secure_filename(uploaded_file.filename)
    if prefix:
        filename = f"{prefix}_{filename}"
    dest_dir = os.path.join(app.config['UPLOAD_FOLDER'], subfolder)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, filename)
    uploaded_file.save(dest_path)
    # If PIL is available, normalize images:
    # - signatures (ordonnateur/secretaire) should be resized to 64x64px
    # - logos should be constrained to a reasonable max width to avoid huge files
    if Image and filename.lower().endswith(('.png', '.jpg', '.jpeg')):
        try:
            with Image.open(dest_path) as img:
                # Determine if this is a signature image by prefix or filename
                lower_prefix = (prefix or '').lower()
                lower_fname = filename.lower()
                if 'ordonnateur' in lower_prefix or 'secretaire' in lower_prefix or 'ordonnateur' in lower_fname or 'secretaire' in lower_fname:
                    # Force exact 64x64 pixels for signatures
                    img = img.convert('RGBA') if img.mode in ('RGBA', 'LA') else img.convert('RGB')
                    img = img.resize((64, 64), Image.LANCZOS)
                    img.save(dest_path)
                else:
                    # For logos, limit max width to avoid huge images (keep aspect ratio)
                    max_w = 512
                    if img.width > max_w:
                        ratio = max_w / float(img.width)
                        new_size = (max_w, int(img.height * ratio))
                        img = img.resize(new_size, Image.LANCZOS)
                        img.save(dest_path)
        except Exception:
            # best-effort: if resizing fails, keep original file
            pass
    # return path relative to UPLOAD_FOLDER
    return os.path.join(subfolder, filename)


def ensure_config_columns():
    """Ensure config_etablissement has image columns; run at startup even outside Flask request context.
    Uses a direct sqlite connection so this function can run before the app context is created.
    """
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cols = [r['name'] for r in cursor.execute("PRAGMA table_info(config_etablissement)").fetchall()]
    needed = {
        'logo_path': 'ALTER TABLE config_etablissement ADD COLUMN logo_path TEXT',
        'ordonnateur_image': 'ALTER TABLE config_etablissement ADD COLUMN ordonnateur_image TEXT',
        'secretaire_image': 'ALTER TABLE config_etablissement ADD COLUMN secretaire_image TEXT'
    }

    for col, alter in needed.items():
        if col not in cols:
            try:
                cursor.execute(alter)
                conn.commit()
            except Exception:
                # best-effort: ignore failures
                pass

    # Ensure default config row exists
    try:
        cursor.execute("INSERT OR IGNORE INTO config_etablissement (id, nom_etablissement) VALUES (1, 'Nom du Collège')")
        conn.commit()
    except Exception:
        pass
    finally:
        cursor.close()
        conn.close()


def draw_signature_pair(pdf: PDF, config: dict, left_key: str, left_name: str, right_key: str, right_name: str, img_mm: float = 22):
    """Draw two signature blocks side by side: images (if present) and names below.
    img_mm is the size of the images in mm (width and height).
    """
    cw = content_width(pdf)
    col_w = (cw - 10) / 2  # leave a small gap
    # compute x positions
    x_left = pdf.l_margin
    x_right = pdf.l_margin + col_w + 10

    # Prepare paths for left/right images and compute dedupe/logo checks BEFORE drawing
    left_img = config.get(left_key)
    right_img = config.get(right_key)
    left_path = os.path.join(app.config['UPLOAD_FOLDER'], left_img) if left_img else None
    right_path = os.path.join(app.config['UPLOAD_FOLDER'], right_img) if right_img else None
    # Determine actual file paths and check for duplicate files (same path or same content)

    def file_sha1(path):
        try:
            import hashlib
            h = hashlib.sha1()
            with open(path, 'rb') as fh:
                while True:
                    chunk = fh.read(8192)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return None

    same_sig = False
    if left_path and right_path and os.path.exists(left_path) and os.path.exists(right_path):
        try:
            if os.path.abspath(left_path) == os.path.abspath(right_path):
                same_sig = True
            else:
                # if sizes differ, not identical; if same size, check sha1
                if os.path.getsize(left_path) == os.path.getsize(right_path):
                    same_sig = (file_sha1(left_path) == file_sha1(right_path))
        except Exception:
            same_sig = False
    # DEBUG logging removed

    # Decide whether each signature is effectively a logo (same content) and whether left/right are duplicates
    logo_rel = config.get('logo_path')
    logo_path = os.path.join(app.config['UPLOAD_FOLDER'], logo_rel) if logo_rel else None

    left_is_logo = False
    if left_path and logo_path and os.path.exists(left_path) and os.path.exists(logo_path):
        try:
            left_is_logo = (os.path.abspath(left_path) == os.path.abspath(logo_path)) or (
                os.path.getsize(left_path) == os.path.getsize(logo_path) and file_sha1(left_path) == file_sha1(logo_path)
            )
        except Exception:
            left_is_logo = False

    right_is_logo = False
    if right_path and logo_path and os.path.exists(right_path) and os.path.exists(logo_path):
        try:
            right_is_logo = (os.path.abspath(right_path) == os.path.abspath(logo_path)) or (
                os.path.getsize(right_path) == os.path.getsize(logo_path) and file_sha1(right_path) == file_sha1(logo_path)
            )
        except Exception:
            right_is_logo = False

    # Draw images at the same vertical position if applicable
    y0 = pdf.get_y()
    if left_img and not left_is_logo:
        left_img_path = os.path.join(app.config['UPLOAD_FOLDER'], left_img)
        if os.path.exists(left_img_path):
            try:
                left_center = x_left + (col_w - img_mm) / 2
                pdf.image(left_img_path, x=left_center, y=y0, w=img_mm, h=img_mm)
            except Exception:
                pass

    if right_img and not same_sig and not right_is_logo:
        right_img_path = os.path.join(app.config['UPLOAD_FOLDER'], right_img)
        if os.path.exists(right_img_path):
            try:
                right_center = x_right + (col_w - img_mm) / 2
                pdf.image(right_img_path, x=right_center, y=y0, w=img_mm, h=img_mm)
            except Exception:
                pass

    # move Y below images to print names
    pdf.set_y(y0 + img_mm + 4)
    # Draw left name centered
    pdf.set_font('Helvetica', '', 11)
    pdf.cell(col_w, 6, encode_str(left_name), 0, 0, 'C')

    # move to right column
    pdf.set_x(x_right)
    # Only draw right image if it's present, not the same file as left (avoid duplicate), and not the logo
    if right_img and not same_sig and not right_is_logo:
        img_path = os.path.join(app.config['UPLOAD_FOLDER'], right_img)
        if os.path.exists(img_path):
            try:
                x_center = x_right + (col_w - img_mm) / 2
                y = pdf.get_y() - (img_mm + 4)  # previous Y used for left column
                pdf.image(img_path, x=x_center, y=y, w=img_mm, h=img_mm)
            except Exception:
                pass
    # ensure Y is properly placed to draw right name
    pdf.set_y(pdf.get_y())
    pdf.set_x(x_right)
    pdf.cell(col_w, 6, encode_str(right_name), 0, 1, 'C')


def draw_logo_if_present(pdf: PDF, config: dict, max_width_mm: float = 60):
    """Draw the logo centered at the top if available. Returns True if drawn."""
    logo = config.get('logo_path')
    if not logo:
        return False
    img_path = os.path.join(app.config['UPLOAD_FOLDER'], logo)
    if not os.path.exists(img_path):
        return False
    try:
        cw = content_width(pdf)
        # clamp width
        w = min(max_width_mm, cw)
        # compute x to center
        x = pdf.l_margin + (cw - w) / 2
        y = pdf.get_y()
        pdf.image(img_path, x=x, y=y, w=w)
        pdf.ln((w * 0.5) / 1 + 4)  # add some vertical space (approx image height)
        return True
    except Exception:
        return False


def ensure_unicode_font(pdf: PDF, prefer='DejaVuSans'):
    """Try to add a unicode TTF font to the PDF instance if present on disk.
    Returns the font name to use or None.
    Checks a few common locations (project root, fonts/, uploads/config/).
    """
    # Map of on-disk filenames -> PDF family name to register
    candidate_map = {
        'DejaVuSans.ttf': 'DejaVuSans',
        'DejaVuSans-Bold.ttf': 'DejaVuSans',
        'NotoSans-Regular.ttf': 'NotoSans',
        'NotoSans-Bold.ttf': 'NotoSans',
    }

    search_paths = [
        basedir,
        os.path.join(basedir, 'fonts'),
        os.path.join(app.config.get('UPLOAD_FOLDER', ''), 'config')
    ]

    found_base = None
    for dirpath in search_paths:
        for filename, family in candidate_map.items():
            p = os.path.join(dirpath, filename)
            if os.path.exists(p) and os.path.getsize(p) > 0:
                # register both regular and bold variants if available
                try:
                    # determine regular and bold filenames for this family
                    if family == 'DejaVuSans':
                        regular = os.path.join(dirpath, 'DejaVuSans.ttf')
                        bold = os.path.join(dirpath, 'DejaVuSans-Bold.ttf')
                    else:
                        regular = os.path.join(dirpath, 'NotoSans-Regular.ttf')
                        bold = os.path.join(dirpath, 'NotoSans-Bold.ttf')

                    # register regular
                    if os.path.exists(regular) and os.path.getsize(regular) > 0:
                        try:
                            pdf.add_font(family, '', regular, uni=True)
                        except Exception:
                            pass

                    # register bold if present
                    if os.path.exists(bold) and os.path.getsize(bold) > 0:
                        try:
                            pdf.add_font(family, 'B', bold, uni=True)
                        except Exception:
                            pass

                    found_base = family
                    return found_base
                except Exception:
                    # try next one
                    continue

    return None

# Largeur utilisable pour multi_cell sur une page A4 avec marges de 15mm
# Remove fixed MULTI_CELL_WIDTH constant — compute content width dynamically
def content_width(pdf: FPDF) -> float:
    """Retourne la largeur utilisable pour le contenu selon les marges du PDF (en mm)."""
    # w = total page width (mm), l_margin and r_margin are set on the PDF instance
    return pdf.w - pdf.l_margin - pdf.r_margin

class PDF(FPDF, HTMLMixin):
    def __init__(self, orientation: str = 'P', unit: str = 'mm', format: str = 'A4', margin_mm: int = 15, *args, **kwargs):
        # Normalize the call to parent with explicit defaults (orientation, unit, format)
        super().__init__(orientation=orientation, unit=unit, format=format, *args, **kwargs)
        # Standard margins (left, top, right) — bottom margin will be handled by auto page break
        self.set_margins(margin_mm, margin_mm, margin_mm)
        # Standard bottom margin via auto page break
        self.set_auto_page_break(auto=True, margin=margin_mm)
        # Default font to ensure consistent layout
        try:
            self.set_font('Helvetica', '', 11)
        except Exception:
            # if Helvetica isn't available, fall back to core font
            self.set_font('Arial', '', 11)
    
    def header(self):
        # Optionally customize a minimal header area with a small top margin spacing
        # Keep header blank by default; derived usage may override
        pass

    def footer(self):
        # Minimal footer to keep consistent bottom spacing - currently empty
        pass

@app.template_filter('format_currency')
def format_currency_filter(value):
    """Formats an integer in cents to a string in euros."""
    if value is None:
        return "0.00"
    return f"{value / 100.0:.2f}"

# Détermine le chemin de base pour l'application (fonctionne en mode normal et après compilation avec PyInstaller)
if getattr(sys, 'frozen', False):
    # Si l'application est "gelée" (compilée en .exe).
    # PyInstaller extrait data files into sys._MEIPASS; prefer that if available.
    basedir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
else:
    # En mode développement normal
    basedir = os.path.dirname(os.path.abspath(__file__))
app.config['DATABASE'] = os.path.join(basedir, 'voyages_scolaires.db')
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'uploads')

# Setup logging now that basedir is available
LOG_DIR = os.path.join(basedir, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, 'app.log')
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

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
        # prefer Flask's open_resource (searches in app.root_path), but fall back to basedir
        schema_read = False
        try:
            with app.open_resource('schema.sql', mode='r') as f:
                db.cursor().executescript(f.read())
            schema_read = True
        except FileNotFoundError:
            # Try to open schema.sql from the basedir (useful for frozen PyInstaller builds)
            alt_path = os.path.join(basedir, 'schema.sql')
            try:
                with open(alt_path, 'r', encoding='utf8') as f:
                    db.cursor().executescript(f.read())
                schema_read = True
            except FileNotFoundError:
                schema_read = False

        if not schema_read:
            raise FileNotFoundError(f"schema.sql not found in app.open_resource or at {alt_path}")
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

def get_participant(participant_id):
    """Récupère un participant par son ID, lève une erreur 404 si non trouvé."""
    db = get_db()
    participant = db.execute(
        'SELECT * FROM participants WHERE id = ?', (participant_id,)
    ).fetchone()
    if participant is None:
        abort(404, f"Le participant avec l'ID {participant_id} n'existe pas.")
    return participant

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
    """Affiche la liste de tous les voyages avec le nombre d'inscrits."""
    db = get_db()
    voyages_raw = db.execute(
        """
        SELECT v.*, COUNT(p.id) as nb_inscrits
        FROM voyages v
        LEFT JOIN participants p ON v.id = p.voyage_id AND p.statut = 'INSCRIT'
        GROUP BY v.id
        ORDER BY v.date_depart DESC
        """
    ).fetchall()

    voyages = []
    for v in voyages_raw:
        voyage_dict = dict(v)
        # Calculer le nombre d'élèves à rembourser pour chaque voyage
        nb_remboursables = db.execute(
            """
            SELECT COUNT(*) FROM participants
            WHERE voyage_id = ? AND statut = 'A_REMBOURSER' AND (remboursement_validé IS NULL OR remboursement_validé = 0)
            """, (v['id'],)
        ).fetchone()[0]
        voyage_dict['nb_remboursables'] = nb_remboursables
        voyages.append(voyage_dict)

    return render_template('index.html', voyages=voyages)


@app.route('/health')
def health():
    """Health check endpoint used by the embedded webview startup waiter."""
    return jsonify({'status': 'ok'})

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
        # Créer un sous-dossier pour le voyage s'il n'existe pas
        voyage_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(voyage_id))
        os.makedirs(voyage_folder, exist_ok=True)
        
        unique_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
        file_path = os.path.join(voyage_folder, unique_filename)
        file.save(file_path)

        db = get_db()
        db.execute(
            "INSERT INTO documents (voyage_id, nom_fichier, chemin_stockage, date_upload) VALUES (?, ?, ?, ?)",
            (voyage_id, filename, os.path.join(str(voyage_id), unique_filename), date.today())
        )
        db.commit()

    return redirect(url_for('voyage_details', voyage_id=voyage_id, tab='documents'))

@app.route('/documents/telecharger/<path:filename>')
def telecharger_document(filename):
    """Permet de télécharger un document."""
    # Serve files inline by default (so images can be previewed in the browser/templates)
    # If some callers require a forced download, they can call this route with ?download=1
    download = request.args.get('download')
    as_attachment = True if download and download in ('1', 'true', 'yes') else False
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=as_attachment)

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
    """Affiche les détails d'un voyage, y compris les participants et les paiements."""
    voyage = get_voyage(voyage_id)
    db = get_db()
    # récupérer la config pour utiliser logo + signatures dans le PDF
    config_row = db.execute("SELECT * FROM config_etablissement WHERE id = 1").fetchone()
    config = dict(config_row) if config_row else {}
    
    # Jointure pour récupérer les participants et leurs créances
    participants_raw = db.execute(
        """
        SELECT p.*, c.montant_initial, c.montant_remise, c.id as creance_id
        FROM participants p
        JOIN creances c ON p.id = c.participant_id
        WHERE p.voyage_id = ?
        ORDER BY p.nom, p.prenom
        """, (voyage_id,)
    ).fetchall()
    nb_inscrits = len([p for p in participants_raw if p['statut'] == 'INSCRIT'])
    nb_attente = len([p for p in participants_raw if p['statut'] == 'LISTE_ATTENTE'])

    documents = db.execute(
        'SELECT * FROM documents WHERE voyage_id = ? ORDER BY date_upload DESC', (voyage_id,)
    ).fetchall()

    modes_paiement = db.execute('SELECT * FROM modes_paiement ORDER BY libelle').fetchall()

    participants_details = []
    total_percu_voyage_cents = 0

    for participant in participants_raw:
        participant_dict = dict(participant)
        paiements = db.execute(
            'SELECT SUM(montant) as total FROM paiements WHERE creance_id = ?', (participant['creance_id'],)
        ).fetchone()
        total_paye_cents = paiements['total'] or 0
        solde_a_payer_cents = participant['montant_initial'] - participant['montant_remise']

        participant_dict['total_paye'] = total_paye_cents
        participant_dict['reste_a_payer'] = max(0, solde_a_payer_cents - total_paye_cents)
        remboursement_valide = participant['remboursement_validé'] if 'remboursement_validé' in participant.keys() else 0
        # Montant à rembourser pour un participant en A_REMBOURSER : rembourser ce qui a été payé
        if participant['statut'] == 'A_REMBOURSER' and remboursement_valide == 0:
            # Rembourser ce qui a été versé (total_paye_cents)
            participant_dict['a_rembourser'] = max(0, total_paye_cents)
        else:
            participant_dict['a_rembourser'] = 0
        participant_dict['remboursement_validé'] = remboursement_valide

        if participant['statut'] == 'INSCRIT':
            total_percu_voyage_cents += total_paye_cents

        participants_details.append(participant_dict)

    montant_total_attendu_cents = voyage['nb_participants_attendu'] * voyage['prix_eleve']

    return render_template('voyage_details.html', voyage=voyage, participants=participants_details, modes_paiement=modes_paiement,
                           documents=documents, nb_inscrits=nb_inscrits, total_percu_voyage=total_percu_voyage_cents,
                           montant_total_attendu=montant_total_attendu_cents, nb_attente=nb_attente)


@app.route('/voyage/<int:voyage_id>/liste_editable', methods=['GET'])
def liste_editable(voyage_id):
    """Affiche la liste des inscrits d'un voyage avec champs éditables (montant payé), puis permet de générer un PDF."""
    voyage = get_voyage(voyage_id)
    db = get_db()

    participants_raw = db.execute(
        """
        SELECT p.*, c.montant_initial, c.montant_remise, c.id as creance_id
        FROM participants p
        JOIN creances c ON p.id = c.participant_id
        WHERE p.voyage_id = ? AND p.statut = 'INSCRIT'
        ORDER BY p.nom, p.prenom
        """, (voyage_id,)
    ).fetchall()

    participants_details = []
    for participant in participants_raw:
        participant_dict = dict(participant)
        paiements = db.execute('SELECT SUM(montant) as total FROM paiements WHERE creance_id = ?', (participant['creance_id'],)).fetchone()
        total_paye_cents = paiements['total'] or 0
        solde_a_payer_cents = participant['montant_initial'] - participant['montant_remise']
        participant_dict['total_paye'] = total_paye_cents
        participant_dict['reste_a_payer'] = max(0, solde_a_payer_cents - total_paye_cents)
        participants_details.append(participant_dict)

    return render_template('liste_editable.html', voyage=voyage, participants=participants_details)


@app.route('/voyage/<int:voyage_id>/export_liste_pdf', methods=['GET'])
def export_liste_pdf(voyage_id):
    """Export PDF direct — liste des inscrits (Nom, Prénom, Classe, Reste à payer).
    Improved layout and uses 'EUR' to avoid font problems with the € glyph.
    """
    voyage = get_voyage(voyage_id)
    db = get_db()

    participants_raw = db.execute(
        """
        SELECT p.id, p.nom, p.prenom, p.classe, c.montant_initial, c.montant_remise, c.id as creance_id
        FROM participants p
        JOIN creances c ON p.id = c.participant_id
        WHERE p.voyage_id = ? AND p.statut = 'INSCRIT'
        ORDER BY p.nom, p.prenom
        """, (voyage_id,)
    ).fetchall()

    rows = []
    for participant in participants_raw:
        paiements = db.execute('SELECT SUM(montant) as total FROM paiements WHERE creance_id = ?', (participant['creance_id'],)).fetchone()
        total_paye_cents = paiements['total'] or 0
        solde_a_payer_cents = participant['montant_initial'] - participant['montant_remise']
        reste_cents = max(0, solde_a_payer_cents - total_paye_cents)
        rows.append({
            'nom': participant['nom'],
            'prenom': participant['prenom'],
            'classe': participant['classe'],
            'reste_a_payer': reste_cents
        })

    # PDF generation: short, tidy table
    pdf = PDF()
    pdf.add_page()

    # draw logo if present
    try:
        config_row = db.execute("SELECT * FROM config_etablissement WHERE id = 1").fetchone()
        config = dict(config_row) if config_row else {}
    except Exception:
        config = {}
        draw_logo_if_present(pdf, config)

    # Try to enable a unicode TTF to render accents and € correctly
    font_used = ensure_unicode_font(pdf)
    if font_used:
        pdf.set_font(font_used, 'B', 14)
        pdf.cell(0, 8, f"Liste des inscrits — {voyage['destination']}", 0, 1, 'C')
    else:
        pdf.set_font('Helvetica', 'B', 14)
        pdf.cell(0, 8, encode_str(f"Liste des inscrits - {voyage['destination']}"), 0, 1, 'C')
    pdf.ln(3)

    # header — use unicode font if available so accents and € render correctly
    if font_used:
        pdf.set_font(font_used, 'B', 11)
    else:
        pdf.set_font('Helvetica', 'B', 11)
    cw = content_width(pdf)
    col_w = [cw * 0.35, cw * 0.30, cw * 0.15, cw * 0.20]
    pdf.set_fill_color(240, 240, 240)
    headers = ['Nom', 'Prénom', 'Classe', 'Reste à payer (EUR)']
    for i, h in enumerate(headers):
        text = h if font_used else encode_str(h)
        pdf.cell(col_w[i], 8, text, border=1, align='C', fill=True)
    pdf.ln()

    if font_used:
        pdf.set_font(font_used, '', 11)
    else:
        pdf.set_font('Helvetica', '', 11)
    for r in rows:
        # new page if close to bottom
        if pdf.get_y() > pdf.h - pdf.b_margin - 20:
            pdf.add_page()
            pdf.set_font('Helvetica', 'B', 11)
            for i, h in enumerate(headers):
                pdf.cell(col_w[i], 8, encode_str(h), border=1, align='C', fill=True)
            pdf.ln()
            pdf.set_font('Helvetica', '', 11)

        pdf.cell(col_w[0], 7, (r['nom'] if font_used else encode_str(r['nom'])), border=1)
        pdf.cell(col_w[1], 7, (r['prenom'] if font_used else encode_str(r['prenom'])), border=1)
        pdf.cell(col_w[2], 7, (str(r['classe']) if font_used else encode_str(str(r['classe']))), border=1, align='C')
        # If we have a unicode font, include the EUR sign directly, otherwise use text 'EUR'
        if font_used:
            # Using unicode font — safe to add the euro symbol
            pdf.cell(col_w[3], 7, f"{r['reste_a_payer']/100:.2f} €", border=1, align='R')
        else:
            pdf.cell(col_w[3], 7, encode_str(f"{r['reste_a_payer']/100:.2f} EUR"), border=1, align='R')
        pdf.ln()

    output = pdf.output(dest='S')
    if isinstance(output, bytearray):
        output = bytes(output)
    resp = make_response(output)
    resp.headers.set('Content-Type', 'application/pdf')
    resp.headers.set('Content-Disposition', f'attachment; filename=liste_inscrits_{voyage["id"]}.pdf')
    return resp


@app.route('/voyage/<int:voyage_id>/liste_editable/generer', methods=['POST'])
def generer_liste_editable_pdf(voyage_id):
    """Génère un PDF avec les valeurs soumises dans la page d'édition (montant payé / reste à payer).
    Les valeurs envoyées doivent être arrays 'participant_id[]' et 'total_paye[]' (en euros, décimales).
    """
    voyage = get_voyage(voyage_id)
    db = get_db()

    ids = request.form.getlist('participant_id[]')
    totals = request.form.getlist('total_paye[]')

    # Build list of rows to print
    rows = []
    for idx, pid in enumerate(ids):
        try:
            pid_int = int(pid)
        except Exception:
            continue
        # fetch creance details
        cre = db.execute('SELECT montant_initial, montant_remise FROM creances WHERE participant_id = ?', (pid_int,)).fetchone()
        if not cre:
            continue
        montant_initial = cre['montant_initial'] or 0
        montant_remise = cre['montant_remise'] or 0

        # parse posted paid amount in euros -> cents
        try:
            paid_euros = float(totals[idx]) if idx < len(totals) else 0.0
        except Exception:
            paid_euros = 0.0
        paid_cents = int(round(paid_euros * 100))

        reste_cents = max(0, (montant_initial - montant_remise) - paid_cents)

        participant = db.execute('SELECT nom, prenom, classe FROM participants WHERE id = ?', (pid_int,)).fetchone()
        if participant:
            rows.append({
                'nom': participant['nom'],
                'prenom': participant['prenom'],
                'classe': participant['classe'],
                'montant_initial': montant_initial,
                'montant_remise': montant_remise,
                'total_paye': paid_cents,
                'reste_a_payer': reste_cents
            })

    # generate PDF
    pdf = PDF()
    pdf.add_page()
    # draw logo if present
    try:
        config_row = db.execute("SELECT * FROM config_etablissement WHERE id = 1").fetchone()
        config = dict(config_row) if config_row else {}
    except Exception:
        config = {}

    draw_logo_if_present(pdf, config)

    pdf.set_font('Helvetica', 'B', 14)
    pdf.cell(0, 8, encode_str(f"Liste éditée des inscrits - {voyage['destination']}"), 0, 1, 'C')
    pdf.ln(2)

    # Table header
    pdf.set_font('Helvetica', 'B', 11)
    # compute dynamic widths (proportional) using content width
    cw = content_width(pdf)
    # allocate widths: name 30%, prenom 25%, classe 10%, init 10%, remise 8%, payé 9%, reste 8% ~ total 100%
    col_w = [cw * 0.30, cw * 0.25, cw * 0.10, cw * 0.10, cw * 0.08, cw * 0.09, cw * 0.08]
    pdf.set_fill_color(240, 240, 240)
    headers = ['Nom', 'Prénom', 'Classe', 'Montant initial', 'Remise', 'Montant payé', 'Reste à payer']
    for i, h in enumerate(headers):
        pdf.cell(col_w[i], 8, encode_str(h), border=1, align='C', fill=True)
    pdf.ln()

    pdf.set_font('Helvetica', '', 10)
    # function to write a row and handle wrapping and page breaks
    def write_row(row):
        nonlocal pdf, col_w
        # check if near bottom, add page
        if pdf.get_y() > pdf.h - pdf.b_margin - 20:
            pdf.add_page()
            # rewrite header on new page
            pdf.set_font('Helvetica', 'B', 11)
            for i, h in enumerate(headers):
                pdf.cell(col_w[i], 7, encode_str(h), border=1, align='C', fill=True)
            pdf.ln()
            pdf.set_font('Helvetica', '', 10)

        # Name
        pdf.multi_cell(col_w[0], 6, encode_str(row['nom']), border=1)
        x_after_name = pdf.get_x()
        y_after_name = pdf.get_y()
        # Move to the right of name cell to continue on same line for next cells
        pdf.set_xy(pdf.l_margin + col_w[0], y_after_name - 6)
        pdf.multi_cell(col_w[1], 6, encode_str(row['prenom']), border=1)
        pdf.set_xy(pdf.l_margin + col_w[0] + col_w[1], y_after_name - 6)
        pdf.cell(col_w[2], 6, encode_str(str(row['classe'])), border=1, align='C')
        pdf.cell(col_w[3], 6, encode_str(f"{row['montant_initial']/100:.2f} €"), border=1, align='R')
        pdf.cell(col_w[4], 6, encode_str(f"{row['montant_remise']/100:.2f} €"), border=1, align='R')
        pdf.cell(col_w[5], 6, encode_str(f"{row['total_paye']/100:.2f} €"), border=1, align='R')
        pdf.cell(col_w[6], 6, encode_str(f"{row['reste_a_payer']/100:.2f} €"), border=1, align='R')
        pdf.ln()

    for r in rows:
        # ensure required numeric fields exist
        r.setdefault('montant_initial', 0)
        r.setdefault('montant_remise', 0)
        write_row(r)

    # Return PDF response
    output = pdf.output(dest='S')
    if isinstance(output, bytearray):
        output = bytes(output)
    resp = make_response(output)
    resp.headers.set('Content-Type', 'application/pdf')
    resp.headers.set('Content-Disposition', f'attachment; filename=liste_inscrits_{voyage["id"]}.pdf')
    return resp

# -------------------------------------------
#  Route pour valider le remboursement d'un élève
# -------------------------------------------
@app.route('/participant/<int:participant_id>/valider_remboursement', methods=['POST'])
def valider_remboursement(participant_id):
    """Valide le remboursement d'un élève (remboursement_validé=1)."""
    db = get_db()
    # Récupérer le participant et sa créance
    participant = db.execute('SELECT * FROM participants WHERE id = ?', (participant_id,)).fetchone()
    if not participant:
        abort(404, "Participant non trouvé")

    creance = db.execute('SELECT * FROM creances WHERE participant_id = ?', (participant_id,)).fetchone()
    if creance:
        paiements_sum = db.execute('SELECT SUM(montant) as total FROM paiements WHERE creance_id = ?', (creance['id'],)).fetchone()
        total_paye = paiements_sum['total'] or 0
    else:
        total_paye = 0

    # Si l'élève a des sommes versées et est à rembourser, créer un paiement négatif qui matérialise le remboursement
    if participant['statut'] == 'A_REMBOURSER' and (participant['remboursement_validé'] is None or participant['remboursement_validé'] == 0) and total_paye > 0:
        # S'assurer qu'il existe un mode de paiement 'Remboursement'
        mode = db.execute('SELECT id FROM modes_paiement WHERE libelle = ?', ('Remboursement',)).fetchone()
        if not mode:
            cur = db.execute("INSERT INTO modes_paiement (libelle) VALUES ('Remboursement')")
            mode_id = cur.lastrowid
        else:
            mode_id = mode['id']

        # Inscrire un paiement négatif pour matérialiser le remboursement
        db.execute('INSERT INTO paiements (creance_id, mode_paiement_id, montant, date, reference) VALUES (?, ?, ?, ?, ?)',
                   (creance['id'], mode_id, -int(total_paye), date.today(), f"Remboursement participant {participant_id}"))

    # Marquer remboursement validé et mettre le statut à ANNULÉ (fin du processus)
    db.execute('UPDATE participants SET remboursement_validé = 1, statut = ? WHERE id = ?', ('ANNULÉ', participant_id))
    db.commit()

    voyage_id = participant['voyage_id']
    return redirect(url_for('voyage_details', voyage_id=voyage_id))

# -------------------------------------------
#  Gestion des Fonds Sociaux
# -------------------------------------------

@app.route('/voyage/<int:voyage_id>/fonds_sociaux')
def fonds_sociaux(voyage_id):
    """Affiche la page de gestion des fonds sociaux pour un voyage."""
    voyage = get_voyage(voyage_id)
    db = get_db()
    
    participants = db.execute('SELECT * FROM participants WHERE voyage_id = ? AND statut = ? ORDER BY nom, prenom', (voyage_id, 'INSCRIT')).fetchall()
    
    demandes_raw = db.execute(
        """
        SELECT d.*, p.nom, p.prenom
        FROM demandes_fonds_sociaux d
        JOIN participants p ON d.participant_id = p.id
        WHERE p.voyage_id = ?
        ORDER BY p.nom, p.prenom
        """, (voyage_id,)
    ).fetchall()

    demandes_en_cours = [d for d in demandes_raw if d['statut'] == 'EN_COURS']
    demandes_traitees = [d for d in demandes_raw if d['statut'] in ('VALIDE', 'REFUSE')]
    date_du_jour = date.today().strftime('%Y-%m-%d')

    # Calculs pour l'entête récap
    participants_raw = db.execute(
        """
        SELECT p.*, c.montant_initial, c.montant_remise, c.id as creance_id
        FROM participants p
        JOIN creances c ON p.id = c.participant_id
        WHERE p.voyage_id = ?
        ORDER BY p.nom, p.prenom
        """, (voyage_id,)
    ).fetchall()
    nb_inscrits = len([p for p in participants_raw if p['statut'] == 'INSCRIT'])
    total_percu_voyage_cents = 0
    for participant in participants_raw:
        paiements = db.execute(
            'SELECT SUM(montant) as total FROM paiements WHERE creance_id = ?', (participant['creance_id'],)
        ).fetchone()
        total_paye_cents = paiements['total'] or 0
        if participant['statut'] == 'INSCRIT':
            total_percu_voyage_cents += total_paye_cents
    montant_total_attendu_cents = voyage['nb_participants_attendu'] * voyage['prix_eleve']
    return render_template('fonds_sociaux.html', voyage=voyage, participants=participants, 
                           demandes_en_cours=demandes_en_cours, demandes_traitees=demandes_traitees,
                           date_du_jour=date_du_jour,
                           total_percu_voyage=total_percu_voyage_cents,
                           montant_total_attendu=montant_total_attendu_cents,
                           nb_inscrits=nb_inscrits)

@app.route('/fonds_sociaux/ajouter', methods=['POST'])
def ajouter_demande_fonds_sociaux():
    """Ajoute une demande de fonds sociaux."""
    voyage_id = request.form['voyage_id']
    participant_id = request.form['participant_id']
    montant_demande = request.form['montant_demande']

    if not all([voyage_id, participant_id, montant_demande]):
        return redirect(url_for('fonds_sociaux', voyage_id=voyage_id))

    db = get_db()
    db.execute(
        "INSERT INTO demandes_fonds_sociaux (participant_id, montant_demande, statut) VALUES (?, ?, ?)",
        (participant_id, int(float(montant_demande) * 100), 'EN_COURS')
    )
    db.commit()
    return redirect(url_for('fonds_sociaux', voyage_id=voyage_id))

@app.route('/fonds_sociaux/valider/<int:demande_id>', methods=['POST'])
def valider_demande_fonds_sociaux(demande_id):
    """Valide ou refuse une demande de fonds sociaux."""
    voyage_id = request.form['voyage_id']
    statut = request.form['statut']
    
    db = get_db()
    demande = db.execute('SELECT * FROM demandes_fonds_sociaux WHERE id = ?', (demande_id,)).fetchone()
    if not demande:
        abort(404, "Demande non trouvée.")

    if demande['is_processed']: # Sécurité pour ne pas traiter deux fois
        return redirect(url_for('fonds_sociaux', voyage_id=voyage_id))

    montant_accorde_cents = 0
    if statut == 'VALIDE':
        montant_accorde_str = request.form.get('montant_accorde')
        if not montant_accorde_str or float(montant_accorde_str) < 0:
            # Idéalement, renvoyer un message d'erreur
            return redirect(url_for('fonds_sociaux', voyage_id=voyage_id))
        montant_accorde_cents = int(float(montant_accorde_str) * 100)
    
    date_commission_str = request.form.get('date_commission')
    date_commission = datetime.strptime(date_commission_str, '%Y-%m-%d').date() if date_commission_str else date.today()

    db.execute(
        "UPDATE demandes_fonds_sociaux SET montant_accorde = ?, date_commission = ?, statut = ?, is_processed = 1 WHERE id = ?",
        (montant_accorde_cents, date_commission, statut, demande_id)
    )
    
    # Si la demande est validée avec un montant, créer un paiement de type "FONDS_SOCIAL"
    if statut == 'VALIDE' and montant_accorde_cents > 0:
        creance = db.execute('SELECT id FROM creances WHERE participant_id = ?', (demande['participant_id'],)).fetchone()
        
        mode_paiement_fs = db.execute('SELECT id FROM modes_paiement WHERE libelle = ?', ('Fonds Social',)).fetchone()
        if not mode_paiement_fs:
            cursor = db.execute("INSERT INTO modes_paiement (libelle) VALUES ('Fonds Social')")
            mode_paiement_fs_id = cursor.lastrowid
        else:
            mode_paiement_fs_id = mode_paiement_fs['id']

        db.execute(
            "INSERT INTO paiements (creance_id, mode_paiement_id, montant, date, reference) VALUES (?, ?, ?, ?, ?)",
            (creance['id'], mode_paiement_fs_id, montant_accorde_cents, date_commission, f"Commission FS du {date_commission.strftime('%d/%m/%Y')}")
        )
        
        # Mettre à jour la remise dans la créance
        db.execute("UPDATE creances SET montant_remise = montant_remise + ? WHERE id = ?", (montant_accorde_cents, creance['id']))

    db.commit()
    return redirect(url_for('fonds_sociaux', voyage_id=voyage_id))

@app.route('/fonds_sociaux/attestation/<int:demande_id>/pdf')
def generer_attestation_fs_pdf(demande_id):
    """Génère une attestation de décision pour une demande de fonds social."""
    try:
        db = get_db()
        
        demande = db.execute("""
            SELECT d.*, p.nom, p.prenom, p.classe, p.type, v.destination, v.date_depart
            FROM demandes_fonds_sociaux d
            JOIN participants p ON d.participant_id = p.id
            JOIN voyages v ON p.voyage_id = v.id
            WHERE d.id = ?
        """, (demande_id,)).fetchone()
        
        if not demande:
            abort(404, "Demande de fonds social non trouvée.")
        
        config_row = db.execute("SELECT * FROM config_etablissement WHERE id = 1").fetchone()
        config = dict(config_row) if config_row else {}
        
        pdf = PDF(orientation='P', unit='mm', format='A4')
        pdf.add_page()
        # logo si présent (une seule fois)
        try:
            draw_logo_if_present(pdf, config)
        except Exception:
            pass
        
        # En-tête
        pdf.set_font('Helvetica', 'B', 14)
        pdf.cell(0, 10, encode_str(config.get('nom_etablissement', 'Nom du Collège')), 0, 1, 'L')
        pdf.set_font('Helvetica', '', 12)
        pdf.cell(0, 10, 'Service de Gestion', 0, 1, 'L')
        pdf.ln(15)
        
        # Titre du document
        pdf.set_font('Helvetica', 'B', 16)
        pdf.cell(0, 10, 'Notification de Decision - Fonds Sociaux', 0, 1, 'C')
        pdf.ln(10)
        
        # Informations
        pdf.set_font('Helvetica', '', 12)
        info_participant = f"Eleve {demande['prenom']} {demande['nom']} (Classe de {demande['classe']})" if demande['type'] == 'ELEVE' else f"{demande['prenom']} {demande['nom']}"
        pdf.multi_cell(content_width(pdf), 8, encode_str(f"Concerne : {info_participant}"))
        pdf.ln(2)
        date_depart_str = demande['date_depart'].strftime('%d/%m/%Y') if demande['date_depart'] else 'N/A'
        pdf.multi_cell(content_width(pdf), 8, encode_str(f"Voyage : {demande['destination']} (Depart le {date_depart_str})"))
        pdf.ln(15)
        
        # Corps du texte
        pdf.multi_cell(content_width(pdf), 7, "Madame, Monsieur,")
        pdf.ln(5)
        
        date_commission_str = demande['date_commission'].strftime('%d/%m/%Y') if demande['date_commission'] else 'non specifiee'
        
        if demande['statut'] == 'VALIDE':
            montant_accorde_cents = demande['montant_accorde'] if demande['montant_accorde'] is not None else 0
            montant_accorde_euros = montant_accorde_cents / 100.0
            texte = f"Suite a la commission du {date_commission_str}, nous avons le plaisir de vous informer qu'une aide financiere de {montant_accorde_euros:.2f} EUR vous a ete accordee pour la participation au voyage scolaire."
            pdf.multi_cell(content_width(pdf), 7, encode_str(texte))
        elif demande['statut'] == 'REFUSE':
            texte = f"Suite a la commission du {date_commission_str}, nous sommes au regret de vous informer que votre demande d'aide financiere n'a pas pu recevoir un avis favorable."
            pdf.multi_cell(content_width(pdf), 7, encode_str(texte))
        
        pdf.ln(10)
        if demande['statut'] == 'VALIDE':
            pdf.multi_cell(content_width(pdf), 7, encode_str("Cette somme sera directement deduite du montant total a votre charge."))
        pdf.ln(10)
        
        # Pied de page avec signatures
        pdf.set_font('Helvetica', '', 11)
        pdf.cell(0, 7, encode_str(f"Fait a {config.get('ville_signature', 'Ville')}, le {datetime.now().strftime('%d/%m/%Y')}"), 0, 1, 'R')
        pdf.ln(15)
        draw_signature_pair(pdf, config, 'ordonnateur_image', config.get('ordonnateur_nom', 'Le Principal,'),
                    'secretaire_image', config.get('secretaire_general_nom', 'Le Secrétaire Général,'), img_mm=22.6)
        
        filename = f"attestation_fs_{sanitize_filename(demande['nom'])}_{sanitize_filename(demande['prenom'])}.pdf"
        _buf = pdf.output(dest='S')
        if isinstance(_buf, (bytes, bytearray)):
            _data = bytes(_buf)
        else:
            _data = _buf.encode('latin-1')
        response = make_response(_data)
        response.headers.set('Content-Disposition', 'attachment', filename=filename)
        response.headers.set('Content-Type', 'application/pdf')
        return response
        
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return f"<pre>Erreur lors de la generation du PDF: {e}\n{traceback.format_exc()}</pre>", 500

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
        (destination, date_depart, int(float(prix_eleve) * 100), int(nb_participants), int(nb_accompagnateurs), int(duree_sejour_nuits))
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
            (destination, date_depart, int(float(prix_eleve) * 100), int(nb_participants), int(nb_accompagnateurs), int(duree_sejour_nuits), voyage_id)
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
#  Gestion des participants
# -------------------------------------------

@app.route('/participant/ajouter', methods=['POST'])
def ajouter_participant():
    """Ajoute un participant (élève) à un voyage."""
    voyage_id = int(request.form['voyage_id'])
    nom = request.form['nom']
    prenom = request.form['prenom']
    classe = request.form['classe']
    # Pour l'instant, on n'ajoute que des élèves
    type_participant = 'ELEVE'

    if not all([voyage_id, nom, prenom, classe]):
        # Redirection avec un message d'erreur serait mieux
        return redirect(url_for('voyage_details', voyage_id=voyage_id))

    db = get_db()
    voyage = get_voyage(voyage_id)
    nb_inscrits = db.execute(
        'SELECT COUNT(id) FROM participants WHERE voyage_id = ? AND statut = ?', (voyage_id, 'INSCRIT')
    ).fetchone()[0]

    # Si le nombre d'inscrits est déjà atteint, le nouvel élève passe en liste d'attente
    statut_initial = 'INSCRIT' if nb_inscrits < voyage['nb_participants_attendu'] else 'LISTE_ATTENTE'

    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO participants (voyage_id, nom, prenom, classe, type, statut) VALUES (?, ?, ?, ?, ?, ?)",
        (voyage_id, nom, prenom, classe, type_participant, statut_initial)
    )
    participant_id = cursor.lastrowid
    
    # Créer la créance associée
    montant_initial = voyage['prix_eleve']
    cursor.execute(
        "INSERT INTO creances (participant_id, montant_initial) VALUES (?, ?)",
        (participant_id, montant_initial)
    )
    
    db.commit()
    return redirect(url_for('voyage_details', voyage_id=voyage_id))

@app.route('/participant/statut', methods=['POST'])
def modifier_statut_participant():
    """Modifie le statut d'un participant (INSCRIT, ANNULÉ, A_REMBOURSER, LISTE_ATTENTE)."""
    voyage_id = request.form['voyage_id']
    participant_id = request.form['participant_id']
    nouveau_statut = request.form['statut']

    db = get_db()
    final_statut = nouveau_statut

    if nouveau_statut == 'ANNULÉ':
        creance = db.execute('SELECT id FROM creances WHERE participant_id = ?', (participant_id,)).fetchone()
        if creance:
            result = db.execute(
                'SELECT SUM(montant) as total FROM paiements WHERE creance_id = ?', (creance['id'],)
            ).fetchone()
            total_paye = result['total'] if result and result['total'] is not None else 0
            if total_paye > 0:
                final_statut = 'A_REMBOURSER'

    db.execute('UPDATE participants SET statut = ? WHERE id = ?', (final_statut, participant_id))
    db.commit()
    return redirect(url_for('voyage_details', voyage_id=voyage_id))

@app.route('/participant/toggle_validation', methods=['POST'])
def toggle_validation():
    """Met à jour une case à cocher de validation pour un participant (via JS)."""
    data = request.get_json()
    participant_id = data.get('participant_id')
    field = data.get('field')

    # Sécurité : ne permettre que la modification des champs prévus
    if field not in ['fiche_engagement', 'liste_definitive']:
        return {"status": "error", "message": "Champ non valide"}, 400

    if not participant_id:
        return {"status": "error", "message": "ID du participant manquant"}, 400

    db = get_db()
    # On récupère la valeur actuelle pour l'inverser (0 -> 1, 1 -> 0)
    current_value = db.execute(
        f'SELECT {field} FROM participants WHERE id = ?', (participant_id,)
    ).fetchone()[0]

    new_value = 1 - current_value

    db.execute(f'UPDATE participants SET {field} = ? WHERE id = ?', (new_value, participant_id))
    db.commit()

    return {"status": "success", "new_value": new_value}

@app.route('/participant/<int:participant_id>/paiements')
def participant_paiements(participant_id):
    """Affiche la liste des paiements pour un participant donné."""
    participant = get_participant(participant_id)
    voyage = get_voyage(participant['voyage_id'])
    db = get_db()
    
    creance = db.execute('SELECT * FROM creances WHERE participant_id = ?', (participant_id,)).fetchone()
    if not creance:
        abort(404, "Créance non trouvée pour ce participant.")

    paiements = db.execute(
        """
        SELECT p.id, p.montant, p.date, p.reference, mp.libelle as mode_paiement
        FROM paiements p
        JOIN modes_paiement mp ON p.mode_paiement_id = mp.id
        WHERE p.creance_id = ?
        ORDER BY p.date DESC
        """,
        (creance['id'],)
    ).fetchall()

    paiements_euros = [{'montant': p['montant'] / 100.0, **p} for p in paiements]
    total_paye_cents = sum(p['montant'] for p in paiements)
    solde_a_payer_cents = creance['montant_initial'] - creance['montant_remise']
    reste_a_payer_cents = max(0, solde_a_payer_cents - total_paye_cents)
    # Si le participant est à rembourser, la somme à rembourser est ce qu'il a déjà versé
    if participant['statut'] == 'A_REMBOURSER' and (participant['remboursement_validé'] is None or participant['remboursement_validé'] == 0):
        a_rembourser_cents = max(0, total_paye_cents)
    else:
        a_rembourser_cents = max(0, total_paye_cents - solde_a_payer_cents)

    modes_paiement = db.execute('SELECT * FROM modes_paiement ORDER BY libelle').fetchall()
    
    return render_template(
        'participant_paiements.html',
        participant=participant,
        voyage=voyage,
        paiements=paiements,
        total_paye=total_paye_cents,
        reste_a_payer=reste_a_payer_cents,
        a_rembourser=a_rembourser_cents,
        modes_paiement=modes_paiement
    )

@app.route('/attestation/<int:participant_id>/pdf')
def generer_attestation_pdf(participant_id):
    """Génère une attestation de paiement en PDF pour un participant."""
    try:
        db = get_db()
        participant = get_participant(participant_id)
        voyage = get_voyage(participant['voyage_id'])
        
        config_row = db.execute("SELECT * FROM config_etablissement WHERE id = 1").fetchone()
        config = dict(config_row) if config_row else {}
        
        creance = db.execute('SELECT id FROM creances WHERE participant_id = ?', (participant_id,)).fetchone()
        if not creance:
            abort(404, "Créance non trouvée.")

        paiements = db.execute(
            """
            SELECT p.montant, p.date, mp.libelle as mode_paiement
            FROM paiements p JOIN modes_paiement mp ON p.mode_paiement_id = mp.id
            WHERE p.creance_id = ? ORDER BY p.date
            """, (creance['id'],)
        ).fetchall()

        total_paye_cents = sum(p['montant'] for p in paiements)

        pdf = PDF(orientation='P', unit='mm', format='A4')
        pdf.add_page()
        try:
            draw_logo_if_present(pdf, config)
        except Exception:
            pass
        # Ne pas redéfinir set_auto_page_break pour éviter les conflits
        

        # En-tête amélioré
        pdf.set_font('Helvetica', 'B', 15)
        pdf.cell(0, 10, encode_str(config.get('nom_etablissement', 'Nom du Collège')), 0, 1, 'C')
        pdf.set_font('Helvetica', '', 12)
        pdf.cell(0, 8, 'Service de Gestion', 0, 1, 'C')
        pdf.ln(4)

        # Titre
        pdf.set_font('Helvetica', 'B', 16)
        pdf.cell(0, 12, 'Attestation de Paiement', 0, 1, 'C')
        pdf.ln(6)

        # Infos voyage et participant
        pdf.set_font('Helvetica', '', 12)
        pdf.cell(0, 8, encode_str(f"Voyage : {voyage['destination']}"), 0, 1)
        date_depart_str = voyage['date_depart'].strftime('%d/%m/%Y') if voyage['date_depart'] else 'N/A'
        pdf.cell(0, 8, f"Date du voyage : {date_depart_str}", 0, 1)
        pdf.cell(0, 8, encode_str(f"Participant : {participant['prenom']} {participant['nom']}"), 0, 1)
        if participant['type'] == 'ELEVE':
            pdf.cell(0, 8, encode_str(f"Classe : {participant['classe']}"), 0, 1)
        pdf.ln(8)

        # Texte de l'attestation en "paysage" (largeur max, style encadré)
        texte_attestation = config.get('texte_attestation', '')
        if texte_attestation:
            pdf.set_font('Helvetica', 'B', 13)
            y_before = pdf.get_y()
            # Encadré sur toute la largeur utile
            pdf.set_fill_color(240, 240, 240)
            pdf.multi_cell(content_width(pdf), 10, encode_str(texte_attestation), border=1, align='C', fill=True)
            y_after = pdf.get_y()
            pdf.ln(8)



        # Tableau des paiements : utiliser la largeur de contenu pour calculer les colonnes
        pdf.set_font('Helvetica', 'B', 11)
        cw = content_width(pdf)
        # Répartition raisonnable : date 20%, mode 60%, montant 20%
        date_w = round(cw * 0.20)
        mode_w = round(cw * 0.60)
        amount_w = cw - date_w - mode_w

        # Entêtes
        pdf.cell(date_w, 10, 'Date', 1, 0, 'C')
        pdf.cell(mode_w, 10, 'Mode de paiement', 1, 0, 'C')
        pdf.cell(amount_w, 10, 'Montant', 1, 1, 'C')

        pdf.set_font('Helvetica', '', 10)
        for p in paiements:
            pdf.cell(date_w, 10, p['date'].strftime('%d/%m/%Y'), 1, 0, 'C')
            pdf.cell(mode_w, 10, encode_str(p['mode_paiement']), 1, 0, 'L')
            pdf.cell(amount_w, 10, f"{p['montant'] / 100.0:.2f} EUR", 1, 1, 'R')

        # Total - aligné au tableau (cumuler date+mode pour la colonne label)
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(date_w + mode_w, 10, 'Total versé', 1, 0, 'R')
        pdf.cell(amount_w, 10, f"{total_paye_cents / 100.0:.2f} EUR", 1, 1, 'R')
        pdf.ln(15)


        # Footer
        pdf.set_font('Helvetica', '', 11)
        date_jour = date.today().strftime('%d/%m/%Y')
        pdf.ln(5)
        pdf.cell(0, 7, encode_str(f"Fait à {config.get('ville_signature', 'Ville')}, le {date_jour}"), 0, 1, 'R')
        pdf.ln(12)
        draw_signature_pair(pdf, config, 'ordonnateur_image', config.get('ordonnateur_nom', 'Le Principal,'),
                    'secretaire_image', config.get('secretaire_general_nom', 'Le Secrétaire Général,'), img_mm=22.6)

        _buf = pdf.output(dest='S')
        if isinstance(_buf, (bytes, bytearray)):
            _data = bytes(_buf)
        else:
            _data = _buf.encode('latin-1')
        response = make_response(_data)
        filename = f"attestation_{sanitize_filename(participant['nom'])}_{sanitize_filename(participant['prenom'])}.pdf"
        response.headers.set('Content-Disposition', 'attachment', filename=filename)
        response.headers.set('Content-Type', 'application/pdf')
        
        return response
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return f"<pre>Erreur lors de la génération du PDF: {e}\n{traceback.format_exc()}</pre>", 500


@app.route('/participant/<int:participant_id>/attestation_remboursement/pdf')
def generer_attestation_remboursement_pdf(participant_id):
    """Génère une attestation PDF de remboursement pour un participant (avant validation du remboursement)."""
    try:
        db = get_db()
        participant = get_participant(participant_id)
        voyage = get_voyage(participant['voyage_id'])

        creance = db.execute('SELECT * FROM creances WHERE participant_id = ?', (participant_id,)).fetchone()
        if not creance:
            abort(404, 'Créance non trouvée pour ce participant.')

        # Somme des paiements positifs (montants versés)
        paiements_sum_pos = db.execute('SELECT SUM(montant) as total FROM paiements WHERE creance_id = ? AND montant > 0', (creance['id'],)).fetchone()
        total_pos = paiements_sum_pos['total'] or 0
        # Somme des paiements négatifs correspondant à remboursement
        paiements_sum_neg = db.execute("SELECT SUM(montant) as total FROM paiements WHERE creance_id = ? AND montant < 0 AND reference LIKE '%Remboursement%'", (creance['id'],)).fetchone()
        total_neg = abs(paiements_sum_neg['total'] or 0)

        # Montant à afficher sur l'attestation : si remboursement déjà effectué -> montant remboursé, sinon montant versé
        if total_neg > 0:
            montant_a_attester_cents = total_neg
        else:
            montant_a_attester_cents = total_pos

        # Si rien à attester -> page utilisateur claire
        if montant_a_attester_cents <= 0:
            return render_template('message.html', title='Attestation indisponible',
                                   message='Aucun paiement trouvé à attester pour ce participant.'), 400

        config_row = db.execute('SELECT * FROM config_etablissement WHERE id = 1').fetchone()
        config = dict(config_row) if config_row else {}

        montant_euros = montant_a_attester_cents / 100.0

        pdf = PDF(orientation='P', unit='mm', format='A4')
        pdf.add_page()
        try:
            draw_logo_if_present(pdf, config)
        except Exception:
            pass
        pdf.set_font('Helvetica', 'B', 14)
        pdf.cell(0, 10, encode_str(config.get('nom_etablissement', 'Nom du Collège')), 0, 1, 'L')
        pdf.set_font('Helvetica', '', 12)
        pdf.cell(0, 8, 'Service de Gestion', 0, 1, 'L')
        pdf.ln(10)

        pdf.set_font('Helvetica', 'B', 16)
        pdf.cell(0, 12, 'Attestation de remboursement', 0, 1, 'C')
        pdf.ln(6)

        pdf.set_font('Helvetica', '', 12)
        pdf.multi_cell(content_width(pdf), 7, encode_str(
            f"Nous attestons que la somme de {montant_euros:.2f} EUR sera remboursée à Monsieur/Madame {participant['nom']} {participant['prenom']} pour le voyage {voyage['destination']} (départ {voyage['date_depart'].strftime('%d/%m/%Y') if voyage['date_depart'] else 'N/A'})."
        ))
        pdf.ln(8)
        pdf.multi_cell(content_width(pdf), 7, encode_str("Cette attestation certifie la prise en charge du remboursement par le service de gestion. Conservez-la pour vos archives."))
        pdf.ln(12)

        pdf.cell(0, 7, encode_str(f"Fait à {config.get('ville_signature', 'Ville')}, le {datetime.now().strftime('%d/%m/%Y')}"), 0, 1, 'R')
        pdf.ln(15)
        draw_signature_pair(pdf, config, 'ordonnateur_image', config.get('ordonnateur_nom', 'Le Principal,'),
                    'secretaire_image', config.get('secretaire_general_nom', 'Le Secrétaire Général,'), img_mm=22.6)

        filename = f"attestation_remboursement_{sanitize_filename(participant['nom'])}_{sanitize_filename(participant['prenom'])}.pdf"
        _buf = pdf.output(dest='S')
        if isinstance(_buf, (bytes, bytearray)):
            _data = bytes(_buf)
        else:
            _data = _buf.encode('latin-1')
        response = make_response(_data)
        response.headers.set('Content-Disposition', 'attachment', filename=filename)
        response.headers.set('Content-Type', 'application/pdf')
        return response

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return f"<pre>Erreur lors de la génération de l'attestation de remboursement: {e}\n{traceback.format_exc()}</pre>", 500

@app.route('/voyage/<int:voyage_id>/liste_participants_pdf', methods=['POST'])
def generer_liste_participants_pdf(voyage_id):
    """Génère une liste de participants en PDF avec des filtres."""
    filtre = request.form.get('filtre', 'tous')
    voyage = get_voyage(voyage_id)
    db = get_db()

    # 1. Récupérer tous les participants avec leurs détails financiers
    participants_raw = db.execute(
        """
        SELECT p.*, c.montant_initial, c.montant_remise, c.id as creance_id
        FROM participants p
        JOIN creances c ON p.id = c.participant_id
        WHERE p.voyage_id = ?
        ORDER BY p.nom, p.prenom
        """, (voyage_id,)
    ).fetchall()

    participants_details = []
    for p in participants_raw:
        p_dict = dict(p)
        paiements = db.execute('SELECT SUM(montant) as total FROM paiements WHERE creance_id = ?', (p['creance_id'],)).fetchone()
        total_paye_cents = paiements['total'] or 0
        solde_a_payer_cents = p['montant_initial'] - p['montant_remise']
        
        p_dict['total_paye'] = total_paye_cents / 100.0
        p_dict['reste_a_payer'] = max(0, (solde_a_payer_cents - total_paye_cents) / 100.0)
        participants_details.append(p_dict)
        
    # 2. Appliquer le filtre
    if filtre == 'paye':
        participants_filtres = [p for p in participants_details if p['statut'] == 'INSCRIT' and p['reste_a_payer'] <= 0]
        titre_filtre = " (Paiements soldés)"
    elif filtre == 'non_paye':
        participants_filtres = [p for p in participants_details if p['statut'] == 'INSCRIT' and p['reste_a_payer'] > 0]
        titre_filtre = " (Paiements en attente)"
    else: # 'tous'
        participants_filtres = participants_details
        titre_filtre = " (Tous les statuts)"

    # 3. Générer le PDF
    config_row = db.execute("SELECT * FROM config_etablissement WHERE id = 1").fetchone()
    config = dict(config_row) if config_row else {}
    pdf = PDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    try:
        draw_logo_if_present(pdf, config)
    except Exception:
        pass
    # Dessine une seule fois le logo si présent
    try:
        draw_logo_if_present(pdf, config)
    except Exception:
        pass
    pdf.set_font('Helvetica', 'B', 16)
    pdf.cell(0, 10, encode_str(f"Liste des participants - Voyage {voyage['destination']}"), 0, 1, 'C')
    pdf.set_font('Helvetica', 'I', 12)
    pdf.cell(0, 10, encode_str(f"Filtre appliqué : {titre_filtre}"), 0, 1, 'C')
    pdf.ln(10)

    # En-têtes du tableau
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(40, 10, 'Nom', 1, 0, 'C')
    pdf.cell(40, 10, 'Prénom', 1, 0, 'C')
    pdf.cell(30, 10, 'Classe/Fonction', 1, 0, 'C')
    pdf.cell(40, 10, 'Statut', 1, 0, 'C')
    pdf.cell(35, 10, 'Total Payé', 1, 0, 'C')
    pdf.cell(35, 10, 'Reste à Payer', 1, 1, 'C')

    # Lignes du tableau
    pdf.set_font('Helvetica', '', 10)
    for p in participants_filtres:
        pdf.cell(40, 10, encode_str(p['nom']), 1)
        pdf.cell(40, 10, encode_str(p['prenom']), 1)
        info = p['classe'] if p['type'] == 'ELEVE' else p['fonction']
        pdf.cell(30, 10, encode_str(info or ''), 1, 0, 'C')
        pdf.cell(40, 10, encode_str(p['statut'].replace('_', ' ').title()), 1, 0, 'C')
        pdf.cell(35, 10, f"{p['total_paye']:.2f} EUR", 1, 0, 'R')
        pdf.cell(35, 10, f"{p['reste_a_payer']:.2f} EUR", 1, 1, 'R')

    pdf.ln(8)
    pdf.set_font('Helvetica', '', 11)
    pdf.cell(0, 7, encode_str(f"Fait à {config.get('ville_signature', 'Ville')}, le {date.today().strftime('%d/%m/%Y')}"), 0, 1, 'R')
    pdf.ln(8)
    draw_signature_pair(pdf, config, 'ordonnateur_image', config.get('ordonnateur_nom', 'Le Principal,'),
                'secretaire_image', config.get('secretaire_general_nom', 'Le Secrétaire Général,'), img_mm=22.6)

    _buf = pdf.output(dest='S')
    if isinstance(_buf, (bytes, bytearray)):
        _data = bytes(_buf)
    else:
        _data = _buf.encode('latin-1')
    response = make_response(_data)
    response.headers.set('Content-Disposition', 'attachment', filename=f"liste_participants_{sanitize_filename(voyage['destination'])}_{filtre}.pdf")
    response.headers.set('Content-Type', 'application/pdf')
    return response

@app.route('/voyage/<int:voyage_id>/generer_echeancier_pdf', methods=['POST'])
def generer_echeancier_pdf(voyage_id):
    """Génère une lettre type pour les familles avec un échéancier de paiement."""
    voyage = get_voyage(voyage_id)
    db = get_db()

    config_row = db.execute("SELECT * FROM config_etablissement WHERE id = 1").fetchone()
    config = dict(config_row) if config_row else {}

    # Récupérer les données du formulaire
    methode_calcul = request.form.get('methode_calcul')
    prix_total_euros = voyage['prix_eleve'] / 100.0
    echeances = []

    if methode_calcul == 'nombre':
        nombre = int(request.form.get('nombre_echeances', 1))
        if nombre > 0:
            montant_echeance = prix_total_euros / nombre
            for i in range(nombre):
                echeances.append(f"Echéance {i+1}: {montant_echeance:.2f} EUR")
    elif methode_calcul == 'montant':
        montant = float(request.form.get('montant_echeance', prix_total_euros))
        if montant > 0:
            nombre_echeances = math.ceil(prix_total_euros / montant)
            for i in range(nombre_echeances):
                montant_a_afficher = montant if (i < nombre_echeances - 1) else prix_total_euros - (montant * (nombre_echeances - 1))
                echeances.append(f"Echéance {i+1}: {montant_a_afficher:.2f} EUR")

    # Récupérer la configuration pour le logo/signatures
    config_row = db.execute("SELECT * FROM config_etablissement WHERE id = 1").fetchone()
    config = dict(config_row) if config_row else {}

    # Génération du PDF
    pdf = PDF(orientation='P', unit='mm', format='A4')
    pdf.add_page()
    try:
        draw_logo_if_present(pdf, config)
    except Exception:
        pass

    # En-tête de l'établissement
    pdf.set_font('Helvetica', 'B', 14)
    pdf.cell(0, 10, encode_str(config.get('nom_etablissement', 'Nom du Collège')), 0, 1, 'L')
    pdf.set_font('Helvetica', '', 12)
    pdf.cell(0, 10, 'Service de Gestion', 0, 1, 'L')
    pdf.ln(15)

    # Titre
    pdf.set_font('Helvetica', 'B', 16)
    pdf.cell(0, 10, encode_str(f"Information - Voyage Scolaire : {voyage['destination']}"), 0, 1, 'C')
    pdf.ln(10)

    # Corps de la lettre
    pdf.set_font('Helvetica', '', 12)
    pdf.multi_cell(content_width(pdf), 7, encode_str(f"Madame, Monsieur,\n\n"
                         f"Nous avons le plaisir de vous informer de l'organisation d'un voyage scolaire à destination de {voyage['destination']}, "
                         f"qui se déroulera à partir du {voyage['date_depart'].strftime('%d/%m/%Y')}.\n\n"
                         f"Le coût total de la participation pour chaque élève a été fixé à {prix_total_euros:.2f} EUR."))
    pdf.ln(10)

    if echeances:
        pdf.set_font('Helvetica', 'B', 12)
        pdf.cell(0, 10, "Proposition d'échéancier de paiement :", 0, 1)
        pdf.set_font('Helvetica', '', 12)
        for echeance in echeances:
            pdf.cell(0, 7, f"- {echeance}", 0, 1)
        pdf.ln(5)
        pdf.set_font('Helvetica', 'I', 10)
        pdf.multi_cell(content_width(pdf), 5, encode_str("Veuillez noter que les dates limites pour chaque paiement vous seront communiquées ultérieurement. "
                              "N'hésitez pas à contacter le service de gestion pour toute question."))

    pdf.ln(20)
    pdf.set_font('Helvetica', '', 12)
    pdf.cell(0, 10, "Cordialement,", 0, 1)
    pdf.cell(0, 10, "L'équipe de gestion.", 0, 1)

    pdf.ln(10)
    pdf.set_font('Helvetica', '', 12)
    pdf.cell(0, 7, encode_str(f"Fait à {config.get('ville_signature', 'Ville')}, le {date.today().strftime('%d/%m/%Y')}"), 0, 1, 'R')
    pdf.ln(10)
    draw_signature_pair(pdf, config, 'ordonnateur_image', config.get('ordonnateur_nom', 'Le Principal,'),
                'secretaire_image', config.get('secretaire_general_nom', 'Le Secrétaire Général,'), img_mm=22.6)

    _buf = pdf.output(dest='S')
    if isinstance(_buf, (bytes, bytearray)):
        _data = bytes(_buf)
    else:
        _data = _buf.encode('latin-1')
    response = make_response(_data)
    response.headers.set('Content-Disposition', 'attachment', filename=f"echeancier_{sanitize_filename(voyage['destination'])}.pdf")
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
    
    # Récupérer la configuration pour le logo/signatures
    config_row = db.execute("SELECT * FROM config_etablissement WHERE id = 1").fetchone()
    config = dict(config_row) if config_row else {}

    items = db.execute(
        """
        SELECT bi.*, bc.nom as categorie_nom FROM budget_items bi
        JOIN budget_categories bc ON bi.categorie_id = bc.id
        WHERE bi.voyage_id = ? ORDER BY bi.type, bc.nom
        """, (voyage_id,)
    ).fetchall()

    depenses = [item for item in items if item['type'] == 'depense']
    recettes = [item for item in items if item['type'] == 'recette']

    total_depenses_cents = sum(item['montant'] for item in depenses)
    total_recettes_cents = sum(item['montant'] for item in recettes)
    solde_cents = total_recettes_cents - total_depenses_cents

    # Calculs pour l'entête récap
    participants_raw = db.execute(
        """
        SELECT p.*, c.montant_initial, c.montant_remise, c.id as creance_id
        FROM participants p
        JOIN creances c ON p.id = c.participant_id
        WHERE p.voyage_id = ?
        ORDER BY p.nom, p.prenom
        """, (voyage_id,)
    ).fetchall()
    nb_inscrits = len([p for p in participants_raw if p['statut'] == 'INSCRIT'])
    total_percu_voyage_cents = 0
    for participant in participants_raw:
        paiements = db.execute(
            'SELECT SUM(montant) as total FROM paiements WHERE creance_id = ?', (participant['creance_id'],)
        ).fetchone()
        total_paye_cents = paiements['total'] or 0
        if participant['statut'] == 'INSCRIT':
            total_percu_voyage_cents += total_paye_cents
    montant_total_attendu_cents = voyage['nb_participants_attendu'] * voyage['prix_eleve']
    return render_template('voyage_budget.html', voyage=voyage, categories=categories,
                           depenses=depenses, recettes=recettes, total_depenses=total_depenses_cents,
                           total_recettes=total_recettes_cents, solde=solde_cents,
                           total_percu_voyage=total_percu_voyage_cents,
                           montant_total_attendu=montant_total_attendu_cents,
                           nb_inscrits=nb_inscrits)

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
        (voyage_id, type, categorie_id, description, int(float(montant) * 100))
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
    voyage = get_voyage(voyage_id)
    db = get_db()
    # charger la configuration (logo/signatures)
    config_row = db.execute("SELECT * FROM config_etablissement WHERE id = 1").fetchone()
    config = dict(config_row) if config_row else {}

    items = db.execute(
        """
        SELECT bi.*, bc.nom as categorie_nom FROM budget_items bi
        JOIN budget_categories bc ON bi.categorie_id = bc.id
        WHERE bi.voyage_id = ? ORDER BY bi.type DESC, bc.nom
        """, (voyage_id,)
    ).fetchall()

    depenses_raw = [item for item in items if item['type'] == 'depense']
    recettes_raw = [item for item in items if item['type'] == 'recette']
    
    total_depenses_cents = sum(item['montant'] for item in depenses_raw)
    total_recettes_cents = sum(item['montant'] for item in recettes_raw)
    solde_cents = total_recettes_cents - total_depenses_cents

    # Conversion en euros pour affichage
    depenses = [{**d, 'montant': d['montant'] / 100.0} for d in depenses_raw]
    recettes = [{**r, 'montant': r['montant'] / 100.0} for r in recettes_raw]
    total_depenses = total_depenses_cents / 100.0
    total_recettes = total_recettes_cents / 100.0
    solde = solde_cents / 100.0

    # Calculs statistiques (basés sur les centimes pour la précision)
    # IMPORTANT : Les accompagnateurs sont gratuits, leur coût est réparti sur les élèves
    nb_eleves = voyage['nb_participants_attendu']
    nb_accompagnateurs = voyage['nb_accompagnateurs']
    duree = voyage['duree_sejour_nuits']

    # Le coût total doit être payé uniquement par les élèves
    prix_par_eleve_cents = total_depenses_cents / nb_eleves if nb_eleves > 0 else 0
    prix_moyen_nuite_cents = (total_depenses_cents / duree) / nb_eleves if duree > 0 and nb_eleves > 0 else 0
    
    # Les accompagnateurs ne payent rien, ils ne sont là que pour l'information
    prix_par_accompagnateur_cents = 0
    prix_moyen_participant_cents = prix_par_eleve_cents  # Même que par élève puisque accompagnateurs gratuits
    
    prix_moyen_nuite = prix_moyen_nuite_cents / 100.0
    prix_par_eleve = prix_par_eleve_cents / 100.0
    prix_par_accompagnateur = prix_par_accompagnateur_cents / 100.0
    prix_moyen_participant = prix_moyen_participant_cents / 100.0


    # Génération du PDF
    pdf = PDF(orientation='P', unit='mm', format='A4')
    pdf.add_page()
    try:
        draw_logo_if_present(pdf, config)
    except Exception:
        pass
    pdf.set_font('Helvetica', 'B', 16)
    pdf.cell(0, 10, encode_str(f"Budget prévisionnel - Voyage {voyage['destination']}"), 0, 1, 'C')
    pdf.ln(10)

    def draw_table(title, data, color):
        pdf.set_font('Helvetica', 'B', 12)
        pdf.set_fill_color(color[0], color[1], color[2])
        pdf.cell(0, 10, encode_str(title), 1, 1, 'C', 1)
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(130, 7, 'Description', 1)
        pdf.cell(60, 7, 'Montant', 1, 1, 'C')
        pdf.set_font('Helvetica', '', 10)
        for item in data:
            pdf.cell(130, 7, encode_str(f"{item['categorie_nom']} - {item['description']}"), 1)
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
    pdf.multi_cell(content_width(pdf), 7, f"- Coût total par élève : {prix_par_eleve:.2f} EUR\n"
                         f"- Coût total par accompagnateur : {prix_par_accompagnateur:.2f} EUR\n"
                         f"- Coût moyen par participant (tous inclus) : {prix_moyen_participant:.2f} EUR\n"
                         f"- Coût moyen par nuit et par participant : {prix_moyen_nuite:.2f} EUR")

    pdf.ln(8)
    pdf.set_font('Helvetica', '', 12)
    pdf.cell(0, 7, encode_str(f"Fait à {config.get('ville_signature', 'Ville')}, le {date.today().strftime('%d/%m/%Y')}"), 0, 1, 'R')
    pdf.ln(8)
    draw_signature_pair(pdf, config, 'ordonnateur_image', config.get('ordonnateur_nom', 'Le Principal,'),
                'secretaire_image', config.get('secretaire_general_nom', 'Le Secrétaire Général,'), img_mm=22.6)

    _buf = pdf.output(dest='S')
    if isinstance(_buf, (bytes, bytearray)):
        _data = bytes(_buf)
    else:
        _data = _buf.encode('latin-1')
    response = make_response(_data)
    response.headers.set('Content-Disposition', 'attachment', filename=f"budget_{sanitize_filename(voyage['destination'])}.pdf")
    response.headers.set('Content-Type', 'application/pdf')
    return response

# -------------------------------------------
#  Gestion des paiements
# -------------------------------------------

@app.route('/paiement/ajouter', methods=['POST'])
def ajouter_paiement():
    """Ajoute un paiement pour un participant."""
    voyage_id = request.form['voyage_id']
    participant_id = request.form['participant_id']
    mode_paiement_id = request.form['mode_paiement_id']
    montant = request.form['montant']
    date_paiement_str = request.form['date']
    reference = request.form.get('reference', '')

    if not all([voyage_id, participant_id, mode_paiement_id, montant, date_paiement_str]):
        return redirect(url_for('voyage_details', voyage_id=voyage_id))

    date_paiement = datetime.strptime(date_paiement_str, '%Y-%m-%d').date()

    db = get_db()
    
    # Récupérer la créance du participant
    creance = db.execute(
        'SELECT id FROM creances WHERE participant_id = ?', (participant_id,)
    ).fetchone()
    
    if creance is None:
        # Gérer le cas où aucune créance n'existe, bien que cela ne devrait pas arriver
        return "Erreur : aucune créance trouvée pour ce participant.", 500
        
    db.execute(
        'INSERT INTO paiements (creance_id, mode_paiement_id, montant, date, reference) VALUES (?, ?, ?, ?, ?)',
        (creance['id'], mode_paiement_id, int(float(montant) * 100), date_paiement, reference)
    )
    db.commit()
    return redirect(url_for('voyage_details', voyage_id=voyage_id))

@app.route('/paiement/<int:paiement_id>/modifier', methods=['GET', 'POST'])
def modifier_paiement(paiement_id):
    """Modifie un paiement existant."""
    paiement = get_paiement(paiement_id)
    db = get_db()
    
    # Retrouver le participant via la créance
    creance = db.execute('SELECT participant_id FROM creances WHERE id = ?', (paiement['creance_id'],)).fetchone()
    if not creance:
        abort(404, "Créance non trouvée pour ce paiement.")
    participant = get_participant(creance['participant_id'])

    if request.method == 'POST':
        montant = request.form['montant']
        mode_paiement_id = request.form['mode_paiement_id']
        date_paiement_str = request.form['date']
        reference = request.form.get('reference', '')

        if not all([montant, mode_paiement_id, date_paiement_str]):
            return redirect(url_for('modifier_paiement', paiement_id=paiement_id))

        date_paiement = datetime.strptime(date_paiement_str, '%Y-%m-%d').date()

        db.execute(
            """
            UPDATE paiements
            SET montant = ?, mode_paiement_id = ?, date = ?, reference = ?
            WHERE id = ?
            """,
            (int(float(montant) * 100), mode_paiement_id, date_paiement, reference, paiement_id)
        )
        db.commit()
        return redirect(url_for('participant_paiements', participant_id=participant['id']))

    modes_paiement = db.execute('SELECT * FROM modes_paiement ORDER BY libelle').fetchall()
    return render_template('modifier_paiement.html', paiement=paiement, participant=participant, modes_paiement=modes_paiement)

@app.route('/paiement/<int:paiement_id>/supprimer', methods=['POST'])
def supprimer_paiement(paiement_id):
    """Supprime un paiement."""
    paiement = get_paiement(paiement_id)
    db = get_db()
    
    creance = db.execute('SELECT participant_id FROM creances WHERE id = ?', (paiement['creance_id'],)).fetchone()
    if not creance:
        return redirect(url_for('index')) # Redirection de sécurité
    
    participant_id = creance['participant_id']
    
    db.execute('DELETE FROM paiements WHERE id = ?', (paiement_id,))
    db.commit()
    
    return redirect(url_for('participant_paiements', participant_id=participant_id))




# -------------------------------------------
#  Configuration
# -------------------------------------------

@app.route('/configuration')
def configuration():
    """Affiche la page de configuration."""
    db = get_db()
    modes = db.execute('SELECT * FROM modes_paiement ORDER BY libelle').fetchall()
    categories = db.execute('SELECT * FROM budget_categories ORDER BY nom').fetchall()
    config = db.execute("SELECT * FROM config_etablissement WHERE id = 1").fetchone()

    return render_template('configuration.html', modes=modes, categories=categories, config=config)


@app.route('/configuration/enregistrer', methods=['POST'])
def enregistrer_config():
    """Enregistre la configuration de l'établissement (texte + images si fournies)."""
    db = get_db()
    fields = [
        'nom_etablissement', 'adresse', 'ordonnateur_nom',
        'secretaire_general_nom', 'ville_signature', 'texte_attestation'
    ]

    query = f"UPDATE config_etablissement SET {', '.join([f'{field} = ?' for field in fields])} WHERE id = 1"
    values = [request.form.get(field) for field in fields]
    db.execute(query, values)

    # Handle file uploads (logo and signature images)
    logo_file = request.files.get('logo')
    ord_file = request.files.get('ordonnateur_image')
    sec_file = request.files.get('secretaire_image')

    if logo_file and logo_file.filename:
        saved = save_uploaded_file(logo_file, subfolder='config', prefix='logo')
        if saved:
            db.execute('UPDATE config_etablissement SET logo_path = ? WHERE id = 1', (saved,))
    if ord_file and ord_file.filename:
        saved = save_uploaded_file(ord_file, subfolder='config', prefix='ordonnateur')
        if saved:
            db.execute('UPDATE config_etablissement SET ordonnateur_image = ? WHERE id = 1', (saved,))
    if sec_file and sec_file.filename:
        saved = save_uploaded_file(sec_file, subfolder='config', prefix='secretaire')
        if saved:
            db.execute('UPDATE config_etablissement SET secretaire_image = ? WHERE id = 1', (saved,))
    db.commit()
    return redirect(url_for('configuration'))
# Backup feature removed by user request: no backup routes available.

@app.route('/configuration/ajouter_mode_paiement', methods=['POST'])
def ajouter_mode_paiement():
    """Ajoute un nouveau mode de paiement."""
    libelle = request.form['libelle']
    if libelle:
        db = get_db()
        try:
            db.execute('INSERT INTO modes_paiement (libelle) VALUES (?)', (libelle,))
            db.commit()
        except sqlite3.IntegrityError:
            pass
    return redirect(url_for('configuration'))

@app.route('/configuration/supprimer_mode_paiement/<int:mode_id>', methods=['POST'])
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
            pass
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

# -------------------------------------------
#  Fonctions Administrateur (Danger Zone)
# -------------------------------------------

@app.route('/admin/reset_db', methods=['POST'])
def reset_db_route():
    """Supprime et réinitialise la base de données."""
    close_db(None)
    db_path = app.config['DATABASE']
    if os.path.exists(db_path):
        os.remove(db_path)
    init_db()
    return redirect(url_for('configuration'))

@app.route('/admin/demo_data', methods=['POST'])
def demo_data_route():
    """Injecte un jeu de données de démonstration complet et réaliste."""
    db = get_db()
    try:
        # === VOYAGE 1: BERLIN (30 participants) ===
        cursor = db.execute(
            "INSERT INTO voyages (destination, date_depart, prix_eleve, nb_participants_attendu) VALUES (?, ?, ?, ?)",
            ('Berlin, Allemagne', date(2026, 6, 10), 62000, 30)
        )
        v1_id = cursor.lastrowid
        prix_v1 = 62000

        noms = ['Dupont', 'Martin', 'Bernard', 'Robert', 'Richard', 'Durand', 'Dubois', 'Moreau', 'Simon', 'Laurent']
        prenoms = ['Jean', 'Pierre', 'Marie', 'Lucas', 'Alice', 'Hugo', 'Chloé', 'Louis', 'Léa', 'Gabriel']
        classes = ['3A', '3B', '3C']

        for i in range(30):
            nom = random.choice(noms)
            prenom = random.choice(prenoms)
            p_cursor = db.execute("INSERT INTO participants (voyage_id, type, nom, prenom, classe, statut) VALUES (?, ?, ?, ?, ?, ?)", 
                                  (v1_id, 'ELEVE', f'{nom}{i}', f'{prenom}{i}', random.choice(classes), 'INSCRIT'))
            p_id = p_cursor.lastrowid
            
            db.execute("INSERT INTO creances (participant_id, montant_initial) VALUES (?, ?)", (p_id, prix_v1))
            creance_id = db.execute('SELECT id FROM creances WHERE participant_id = ?', (p_id,)).fetchone()['id']

            # Simuler des paiements et des statuts
            cas = random.randint(1, 10)
            if cas <= 5: # Paiement partiel
                montant_paye = random.randint(10000, 40000)
                db.execute("INSERT INTO paiements (creance_id, mode_paiement_id, montant, date) VALUES (?, ?, ?, ?)", 
                           (creance_id, 1, montant_paye, date.today()))
            elif cas <= 8: # Paiement complet
                db.execute("INSERT INTO paiements (creance_id, mode_paiement_id, montant, date) VALUES (?, ?, ?, ?)", 
                           (creance_id, 1, prix_v1, date.today()))
            elif cas == 9: # Annulation avec remboursement
                montant_paye = random.randint(10000, 40000)
                db.execute("INSERT INTO paiements (creance_id, mode_paiement_id, montant, date) VALUES (?, ?, ?, ?)", 
                           (creance_id, 1, montant_paye, date.today()))
                db.execute("UPDATE participants SET statut = ? WHERE id = ?", ('A_REMBOURSER', p_id))
            # Cas 10 = Pas de paiement

        # === VOYAGE 2: LONDRES (petit groupe) ===
        cursor = db.execute(
            "INSERT INTO voyages (destination, date_depart, prix_eleve, nb_participants_attendu) VALUES (?, ?, ?, ?)",
            ('Londres, Royaume-Uni', date(2026, 7, 5), 45000, 15)
        )
        v2_id = cursor.lastrowid
        prix_v2 = 45000
        
        for i in range(5):
            nom = random.choice(noms)
            prenom = random.choice(prenoms)
            p_cursor = db.execute("INSERT INTO participants (voyage_id, type, nom, prenom, classe, statut) VALUES (?, ?, ?, ?, ?, ?)", 
                                  (v2_id, 'ELEVE', f'{nom}_v2_{i}', f'{prenom}_v2_{i}', '4A', 'INSCRIT'))
            p_id = p_cursor.lastrowid
            db.execute("INSERT INTO creances (participant_id, montant_initial) VALUES (?, ?)", (p_id, prix_v2))

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Erreur lors de l'injection des données de démo : {e}")
    
    return redirect(url_for('index'))


@app.route('/admin/create_test_rembourse', methods=['POST'])
def create_test_rembourse():
    """Crée un cas de test simple : un voyage + un participant payé qui doit être remboursé."""
    db = get_db()
    # Créer un voyage de test
    cursor = db.execute(
        "INSERT INTO voyages (destination, date_depart, prix_eleve, nb_participants_attendu) VALUES (?, ?, ?, ?)",
        ('Test Remboursement', date.today(), 5000, 10)
    )
    voyage_id = cursor.lastrowid

    # Créer un participant
    cur = db.execute("INSERT INTO participants (voyage_id, type, nom, prenom, classe, statut) VALUES (?, ?, ?, ?, ?, ?)",
                    (voyage_id, 'ELEVE', 'Test', 'Remb', 'T1', 'A_REMBOURSER'))
    participant_id = cur.lastrowid

    # Créer une créance et un paiement (simulateur : la famille a payé 50,00 EUR)
    db.execute("INSERT INTO creances (participant_id, montant_initial) VALUES (?, ?)", (participant_id, 5000))
    creance_id = db.execute('SELECT id FROM creances WHERE participant_id = ?', (participant_id,)).fetchone()['id']
    # Simuler un paiement de 50 EUR
    mode = db.execute('SELECT id FROM modes_paiement WHERE libelle = ?', ('Espèces',)).fetchone()
    if not mode:
        curm = db.execute("INSERT INTO modes_paiement (libelle) VALUES ('Espèces')")
        mode_id = curm.lastrowid
    else:
        mode_id = mode['id']
    db.execute('INSERT INTO paiements (creance_id, mode_paiement_id, montant, date, reference) VALUES (?, ?, ?, ?, ?)',
               (creance_id, mode_id, 5000, date.today(), 'Paiement test'))

    db.commit()
    return redirect(url_for('voyage_details', voyage_id=voyage_id))

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
    # Ensure migration for configuration image columns
    try:
        ensure_config_columns()
    except Exception:
        pass
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    # Si pywebview est disponible, démarre Flask en thread et ouvre une fenêtre embarquée.
    if WEBVIEW_ENABLED:
        import socket
        import time
        from werkzeug.serving import make_server

        # Utiliser un objet pour stocker l'état partagé entre threads
        class ServerState:
            server = None
            ready = False
            error = None

        state = ServerState()

        def run_server():
            try:
                logger.info('[server] Creating Flask server on 127.0.0.1:5001')
                state.server = make_server('127.0.0.1', 5001, app, threaded=True)
                logger.info('[server] Server created, marking as ready')
                state.ready = True
                logger.info('[server] Flask server starting serve_forever()')
                state.server.serve_forever()
                logger.info('[server] serve_forever() ended')
            except Exception as e:
                logger.exception('[server] Exception while running Flask server:')
                state.error = str(e)
                state.ready = True  # Débloquer l'attente même en cas d'erreur

        # NE PAS utiliser daemon=True pour éviter que le thread soit tué prématurément
        t = Thread(target=run_server)
        t.start()

        # Attendre que le serveur soit prêt
        def wait_for_server(host='127.0.0.1', port=5001, timeout=15.0, interval=0.2):
            logger.info(f'[startup] Waiting for server on {host}:{port}...')
            deadline = time.time() + timeout
            while time.time() < deadline:
                if state.ready:
                    # Attendre un peu plus que le serveur soit vraiment prêt
                    time.sleep(0.5)
                    # Double-check avec une connexion TCP
                    for _ in range(3):
                        try:
                            with socket.create_connection((host, port), timeout=2):
                                logger.info('[startup] TCP connection successful')
                                return True
                        except Exception as e:
                            logger.warning(f'[startup] TCP connect failed: {e}')
                            time.sleep(0.3)
                time.sleep(interval)
            logger.error('[startup] Timeout waiting for server')
            return False

        logger.info('[startup] Waiting for Flask server to be ready...')
        if wait_for_server():
            try:
                logger.info('[startup] Server is reachable; opening embedded window')
                # Créer la fenêtre et démarrer webview
                window = webview.create_window(
                    'Gestion Voyages Scolaires',
                    'http://127.0.0.1:5001',
                    width=1200,
                    height=800
                )
                logger.info('[startup] Window created, starting webview...')
                webview.start()
                logger.info('[startup] webview.start() returned (window closed)')
            except Exception as e:
                logger.exception('[webview] Unable to create embedded window:')
                print('[webview] Falling back to system browser')
                webbrowser.open_new('http://127.0.0.1:5001/')
                t.join()
        else:
            logger.error('[startup] Server did not become reachable in time')
            if state.error:
                logger.error(f'[startup] Server error: {state.error}')
            # Fallback to system browser
            webbrowser.open_new('http://127.0.0.1:5001/')
            t.join()

        # Arrêter proprement le serveur quand la fenêtre webview se ferme
        if state.server:
            logger.info('[shutdown] Shutting down Flask server')
            state.server.shutdown()
        t.join(timeout=2)
    else:
        # Lance le navigateur 1 seconde après le démarrage du serveur
        Timer(1, open_browser).start()
        app.run(host='127.0.0.1', port=5001, debug=False)