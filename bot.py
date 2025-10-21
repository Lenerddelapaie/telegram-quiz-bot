# -*- coding: utf-8 -*-
import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

# =====================================================
# 🔧 Configuration
# =====================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
APP_URL = os.environ.get("APP_URL", "").rstrip("/")  # ex: https://your-app.onrender.com
MODE = os.environ.get("MODE", "polling").lower()     # "webhook" ou "polling"
PORT = int(os.environ.get("PORT", "8000"))           # Render/Railway exposent PORT
LISTEN = os.environ.get("LISTEN", "0.0.0.0")         # Adresse d’écoute
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "/telegram/webhook")
# 🔐 Telegram enverra un header X-Telegram-Bot-Api-Secret-Token qu’on valide côté lib
SECRET_TOKEN = os.environ.get("SECRET_TOKEN", "change-me-please")

# (Optionnel) URL du quiz — si tu veux l’exposer aussi depuis le bot
QUIZ_URL = os.environ.get("QUIZ_URL", APP_URL or "https://example.com")

# Logging propre
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("lpf-telegram-bot")

WELCOME_TEXT = (
    "Bienvenue sur le quiz La Paie Facile !\n\n"
    "Cliquez ci-dessous pour découvrir si le métier de gestionnaire de paie "
    "est fait pour vous 👇"
)

# =====================================================
# 🎯 Handlers
# =====================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info("/start par %s (id=%s)", getattr(user, "first_name", "?"), getattr(user, "id", "?"))
    btn = InlineKeyboardButton(text="🚀 Passer le test", url=QUIZ_URL)
    await update.message.reply_text(WELCOME_TEXT, reply_markup=InlineKeyboardMarkup([[btn]]))

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Erreur inattendue", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(update.effective_chat.id, "Une erreur interne est survenue. Réessayez plus tard.")
        except Exception as e:
            logger.error("Échec d’envoi du message d’erreur: %s", e)

# =====================================================
# 🚀 Boot
# =====================================================
def main():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN manquant dans les variables d'environnement")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_error_handler(error_handler)

    if MODE == "webhook":
        if not APP_URL:
            raise SystemExit("APP_URL est requis en mode webhook (ex: https://ton-app.com)")
        webhook_url = APP_URL + WEBHOOK_PATH
        logger.info("Démarrage en WEBHOOK → listen=%s port=%s url=%s", LISTEN, PORT, webhook_url)
        # PTB gère l’aiohttp serveur + la vérification du secret
        app.run_webhook(
            listen=LISTEN,
            port=PORT,
            url=webhook_url,
            secret_token=SECRET_TOKEN,
            drop_pending_updates=True,
        )
    else:
        logger.info("Démarrage en POLLING…")
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

