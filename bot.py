# -*- coding: utf-8 -*-
import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

# =====================================================
# 🔧 Config POLLING (Worker Render)
# =====================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
QUIZ_URL = os.environ.get("QUIZ_URL", "https://example.com")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=getattr(logging, LOG_LEVEL, logging.INFO),
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

# Petit /ping utile pour vérifier vite fait que le bot répond
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong")

# =====================================================
# 🚀 Boot (Polling)
# =====================================================
def main():
    if not BOT_TOKEN:
        raise SystemExit("❌ BOT_TOKEN manquant dans les variables d'environnement. Le bot ne peut pas démarrer.")
    logger.info("Initialisation du bot LPF en mode POLLING (Background Worker)…")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_error_handler(error_handler)

    # Moins d’événements à traiter = plus stable/économe
    app.run_polling(drop_pending_updates=True, allowed_updates=["message"])

if __name__ == "__main__":
    main()
