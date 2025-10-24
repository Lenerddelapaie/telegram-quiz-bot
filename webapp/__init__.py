# webapp/__init__.py
import os
from flask import Flask, send_from_directory, request, jsonify

app = Flask(__name__, static_folder="../templates")

@app.get("/")
def index():
    return send_from_directory("../templates", "index.html")

@app.post("/submit-email")
def submit_email():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip()
    profile = (data.get("profile") or "").strip()
    if not email:
        return jsonify({"ok": False, "error": "email manquant"}), 400
    # TODO: intégrer Systeme.io ici si besoin
    return jsonify({"ok": True})

@app.get("/healthz")
def healthz():
    return "ok", 200

