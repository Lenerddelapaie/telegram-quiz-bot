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
from sqlalchemy.exc import IntegrityError

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
_raw_db_url = os.environ.get("DATABASE_URL", "")
if _raw_db_url.startswith("postgres://"):
    _raw_db_url = _raw_db_url.replace("postgres://", "postgresql://", 1)
SQLALCHEMY_DATABASE_URI = _raw_db_url or "sqlite:///dev.db"  # fallback dev local

# Systeme.io (configurable)
SYSTEMEIO_EMAIL = os.environ.get("SYSTEMEIO_EMAIL", "")
SYSTEMEIO_TOKEN = os.environ.get("SYSTEMEIO_TOKEN", "")
SYSTEMEIO_TAG_ID = os.environ.get("SYSTEMEIO_TAG_ID", "")
SYSTEMEIO_API_BASE = os.environ.get("SYSTEMEIO_API_BASE", "https://api.systeme.io")  # ajuste si besoin
SYSTEMEIO_TIMEOUT = float(os.environ.get("SYSTEMEIO_TIMEOUT", "8.0"))  # secondes

# Validation e-mail simple (suffisante pour capter des leads)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# =====================================================
# 🏗️ App & DB
# =====================================================
app = Flask(__name__, template_folder="templates")
app.config["SQLALCHEMY_DATABASE_URI"] = SQLALCHEMY_DATABASE_URI
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


class EmailLead(db.Model):
    __tablename__ = "email_leads"
    id = db.Column(db.Integer, primary_key=True)
    ts_utc = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    profile = db.Column(db.String(80), nullable=True)
    source_ip = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.Text, nullable=True)

    pushed_to_systemeio = db.Column(db.Boolean, default=False, nullable=False)
    systemeio_status = db.Column(db.String(40), nullable=True)
    systemeio_error = db.Column(db.Text, nullable=True)

    def as_dict(self):
        return {
            "id": self.id,
            "ts_utc": self.ts_utc.isoformat() + "Z",
            "email": self.email,
            "profile": self.profile,
            "pushed_to_systemeio": self.pushed_to_systemeio,
            "systemeio_status": self.systemeio_status,
            "systemeio_error": self.systemeio_error,
        }


with app.app_context():
    db.create_all()
    logger.info("DB initialisée: %s", SQLALCHEMY_DATABASE_URI)


# =====================================================
# 🔌 Helpers
# =====================================================
def _client_ip() -> str:
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
    # Selon les versions d’API, le schéma d’auth diffère.
    # On part sur un header Bearer standard. Ajustable via env si besoin.
    return {
        "Authorization": f"Bearer {SYSTEMEIO_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": f"{APP_NAME}/1.0",
    }


def push_to_systemeio(email: str, tag_id: Optional[str], profile: Optional[str]) -> tuple[bool, str, Optional[str]]:
    """
    Envoie le contact vers Systeme.io avec un tag. Retourne (ok, status, error).
    NB: L’endpoint précis peut varier. Laisse SYSTEMEIO_API_BASE configurable.
    """
    if not (SYSTEMEIO_EMAIL and SYSTEMEIO_TOKEN and tag_id):
        return False, "skipped_missing_config", "SYSTEMEIO_EMAIL/TOKEN/TAG_ID manquants"

    # Exemples courants (à ajuster selon ton compte/plan) :
    # - v1 (privée/pro) : /public/v1/contacts
    # - ou /contacts
    endpoint = f"{SYSTEMEIO_API_BASE.rstrip('/')}/public/v1/contacts"

    payload = {
        "email": email,
        # Informations supplémentaires si l’API les accepte (optionnel):
        "first_name": profile or "",
        "tags": [tag_id],
    }

    # Petit retry exponentiel 3 tentatives
    last_error = None
    for attempt in range(1, 4):
        try:
            resp = requests.post(endpoint, json=payload, headers=_systemeio_headers(), timeout=SYSTEMEIO_TIMEOUT)
            if 200 <= resp.status_code < 300:
                return True, f"{resp.status_code}", None
            # Conflit/Already exists : on considère comme OK (contact déjà créé)
            if resp.status_code in (200, 201, 202, 409):
                return True, f"{resp.status_code}", None
            last_error = f"HTTP {resp.status_code}: {resp.text[:500]}"
            logger.warning("Systeme.io tentative %s/3 KO: %s", attempt, last_error)
        except requests.RequestException as e:
            last_error = str(e)
            logger.warning("Systeme.io tentative %s/3 exception: %s", attempt, last_error)
        time.sleep(0.8 * attempt)  # backoff simple
    return False, "error", last_error or "unknown_error"


# =====================================================
# 🌐 Routes
# =====================================================
@app.get("/")
def index():
    return render_template("index.html")


@app.get("/healthz")
def healthz():
    return jsonify({
        "status": "ok",
        "app": APP_NAME,
        "time": datetime.utcnow().isoformat() + "Z",
        "db": "connected" if db.session.execute(db.select(db.func.count(EmailLead.id))).scalar() is not None else "unknown",
    })


@app.post("/submit-email")
def submit_email():
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
    db.session.add(lead)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        # Déjà vu : récupère l’existant pour mettre à jour le statut Systeme.io
        lead = db.session.execute(db.select(EmailLead).where(EmailLead.email == email)).scalar_one()

    ok, status, err = push_to_systemeio(email=email, tag_id=SYSTEMEIO_TAG_ID, profile=profile)
    lead.pushed_to_systemeio = bool(ok)
    lead.systemeio_status = status
    lead.systemeio_error = err
    db.session.commit()

    logger.info(
        "lead: email=%s profile=%s pushed=%s status=%s err=%s ip=%s",
        email, profile or "-", lead.pushed_to_systemeio, status, (err or "-")[:120], ip
    )
    return jsonify({"ok": True})


# =====================================================
# 🔌 Run local dev
# =====================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    logger.info("Dev server http://127.0.0.1:%s", port)
    app.run(host="0.0.0.0", port=port, debug=True)

