# -*- coding: utf-8 -*-
import logging
import os
import re
import time
from datetime import datetime
from ipaddress import ip_address
from typing import Optional

import requests
from flask import Flask, jsonify, render_template, request, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError, OperationalError

# =====================================================
# 🔧 Config & logging
# =====================================================
APP_NAME = os.environ.get("APP_NAME", "lpf-quiz")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=getattr(logging, LOG_LEVEL, logging.INFO),
)
logger = logging.getLogger(APP_NAME)

# DB: Render/Railway fournissent DATABASE_URL. On normalise en postgresql+psycopg2
# Le fallback local utilise sqlite pour le développement si aucune URL n'est trouvée
_raw_db_url = os.environ.get("DATABASE_URL", "")
if _raw_db_url.startswith("postgres://"):
    # Fixe le schéma pour SQLAlchemy
    _raw_db_url = _raw_db_url.replace("postgres://", "postgresql://", 1)
SQLALCHEMY_DATABASE_URI = _raw_db_url or "sqlite:///dev.db"  

# Systeme.io (configurable)
SYSTEMEIO_EMAIL = os.environ.get("SYSTEMEIO_EMAIL", "")
SYSTEMEIO_TOKEN = os.environ.get("SYSTEMEIO_TOKEN", "")
SYSTEMEIO_TAG_ID = os.environ.get("SYSTEMEIO_TAG_ID", "")
SYSTEMEIO_API_BASE = os.environ.get("SYSTEMEIO_API_BASE", "https://api.systeme.io")  
SYSTEMEIO_TIMEOUT = float(os.environ.get("SYSTEMEIO_TIMEOUT", "8.0"))

# Validation e-mail simple
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# =====================================================
# 🏗️ App & DB
# =====================================================
# __name__ est le dossier parent, donc Flask cherche 'templates' à la racine de webapp/
app = Flask(__name__, template_folder="templates")
app.config["SQLALCHEMY_DATABASE_URI"] = SQLALCHEMY_DATABASE_URI
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


class EmailLead(db.Model):
    """ Modèle pour stocker les leads (emails) dans PostgreSQL """
    __tablename__ = "email_leads"
    id = db.Column(db.Integer, primary_key=True)
    ts_utc = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    profile = db.Column(db.String(80), nullable=True) # Ex: Résultat du quiz
    source_ip = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.Text, nullable=True)

    # Statut d'intégration Systeme.io
    pushed_to_systemeio = db.Column(db.Boolean, default=False, nullable=False)
    systemeio_status = db.Column(db.String(40), nullable=True)
    systemeio_error = db.Column(db.Text, nullable=True)


with app.app_context():
    # Crée les tables si elles n'existent pas (nécessaire pour SQLite, et inoffensif pour Postgres)
    try:
        db.create_all()
        logger.info("DB initialisée: %s", SQLALCHEMY_DATABASE_URI)
    except OperationalError as e:
        # Ceci peut arriver si la DB n'est pas encore prête ou mal configurée
        logger.error("Erreur de connexion à la DB au démarrage: %s", e)


# =====================================================
# 🔌 Helpers
# =====================================================
def _client_ip() -> str:
    """ Récupère l'IP du client de manière sécurisée (gère les proxys comme Render/Railway) """
    # Render/Railway passent X-Forwarded-For
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        ip = xff.split(",")[0].strip()
    else:
        ip = request.remote_addr or "-"
    try:
        ip_address(ip)  # validation basique
    except Exception:
        ip = "-"
    return ip


def _systemeio_headers() -> dict:
    """ Construit les headers d'autorisation pour l'API Systeme.io """
    return {
        "Authorization": f"Bearer {SYSTEMEIO_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": f"{APP_NAME}/1.0 (Integration)",
    }


def push_to_systemeio(email: str, tag_id: Optional[str], profile: Optional[str]) -> tuple[bool, str, Optional[str]]:
    """ Tente d'envoyer le contact vers Systeme.io avec un tag (avec retry). """
    if not (SYSTEMEIO_TOKEN and tag_id):
        return False, "skipped", "SYSTEMEIO_TOKEN/TAG_ID manquants"

    endpoint = f"{SYSTEMEIO_API_BASE.rstrip('/')}/public/v1/contacts" 
    payload = {
        "email": email,
        "tags": [tag_id],
        "custom_fields": {
             # Utilisez ici les champs personnalisés que l'API accepte (ex: profile)
             # S'ils ne sont pas supportés ou non configurés, vous pouvez les laisser vides.
             "profile": profile or ""
        }
    }

    last_error = None
    for attempt in range(1, 4):
        try:
            resp = requests.post(endpoint, json=payload, headers=_systemeio_headers(), timeout=SYSTEMEIO_TIMEOUT)
            
            # 2xx: Succès | 409: Conflit (déjà existant) -> On considère que le contact est créé/tagué
            if 200 <= resp.status_code < 300 or resp.status_code == 409:
                return True, f"HTTP {resp.status_code}", None
            
            # Échec API
            last_error = f"HTTP {resp.status_code}: {resp.text[:500]}..."
            logger.warning("Systeme.io tentative %s/3 KO: %s", attempt, last_error)
        
        except requests.RequestException as e:
            # Échec réseau/timeout
            last_error = str(e)
            logger.warning("Systeme.io tentative %s/3 exception: %s", attempt, last_error)
        
        time.sleep(0.8 * attempt)  # Backoff: 0.8s, 1.6s, 2.4s

    return False, "error", last_error or "unknown_api_error"


# =====================================================
# 🌐 Routes
# =====================================================
@app.get("/")
def index():
    """ Sert la page quiz (webapp/templates/index.html). """
    logger.debug("GET / -> index.html")
    # Pour le moment, index.html n'existe pas, mais Flask le cherchera ici.
    return render_template("index.html")


@app.get("/healthz")
def healthz():
    """ Endpoint de supervision pour le PaaS (Render/Railway). """
    # Vérifie la connexion à la base de données
    db_status = "connected"
    try:
        db.session.execute(db.select(db.func.count(EmailLead.id))).scalar()
    except OperationalError:
        db_status = "disconnected"
    
    return jsonify({
        "status": "ok",
        "app": APP_NAME,
        "time": datetime.utcnow().isoformat() + "Z",
        "db": db_status,
    })


@app.post("/submit-email")
def submit_email():
    """ Reçoit l'email et le profil, l'enregistre dans la DB et pousse vers Systeme.io. """
    try:
        data = request.get_json(force=True, silent=False) or {}
    except Exception:
        abort(400, description="invalid_json")

    email = (data.get("email") or "").strip().lower()
    profile = (data.get("profile") or "").strip() or None
    ua = request.headers.get("User-Agent", "-")
    ip = _client_ip()

    if not email:
        return jsonify({"ok": False, "error": "email_required"}), 400
    if not EMAIL_RE.match(email):
        return jsonify({"ok": False, "error": "email_invalid"}), 400

    lead = EmailLead(email=email, profile=profile, source_ip=ip, user_agent=ua)
    
    # 1. Sauvegarde/Mise à jour dans la base de données (PostgreSQL)
    try:
        db.session.add(lead)
        db.session.commit()
    except IntegrityError:
        # L'email existe déjà (unique=True dans le modèle)
        db.session.rollback()
        # Récupère l'enregistrement existant pour mettre à jour son statut Systeme.io
        lead = db.session.execute(db.select(EmailLead).filter_by(email=email)).scalar_one()

    # 2. Tentative d'envoi à Systeme.io
    ok, status, err = push_to_systemeio(email=email, tag_id=SYSTEMEIO_TAG_ID, profile=profile)
    
    # 3. Mise à jour du statut d'envoi dans la DB
    lead.pushed_to_systemeio = bool(ok)
    lead.systemeio_status = status
    lead.systemeio_error = err
    db.session.commit()

    logger.info(
        "lead: email=%s profile=%s pushed=%s status=%s ip=%s",
        email, profile or "-", lead.pushed_to_systemeio, status, ip
    )
    return jsonify({"ok": True})


# =====================================================
# 🔌 Run local dev
# =====================================================
if __name__ == "__main__":
    # Démarre uniquement l'app Flask. Pour la production, Gunicorn est utilisé.
    port = int(os.environ.get("PORT", "5000"))
    # Le logger ne s'affiche pas correctement avec Flask en debug, mais c'est bien pour les traces générales.
    logger.info("Dev server http://127.0.0.1:%s", port)
    app.run(host="0.0.0.0", port=port, debug=True)
