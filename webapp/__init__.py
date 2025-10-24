import os
from flask import Flask, send_from_directory, request, jsonify

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "..", "templates")

app = Flask(__name__)

@app.get("/")
def index():
    return send_from_directory(TEMPLATES_DIR, "index.html")

@app.post("/submit-email")
def submit_email():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip()
    profile = (data.get("profile") or "").strip()
    if not email:
        return jsonify({"ok": False, "error": "email manquant"}), 400
    # TODO: intégration Systeme.io ici
    return jsonify({"ok": True})

@app.get("/healthz")
def healthz():
    return "ok", 200
