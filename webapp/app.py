# -*- coding: utf-8 -*-
import logging
import os
import sys

# Si le bot est lancé en tant que worker, il a besoin de connaître l'URL du Quiz.
# QUIZ_URL doit être défini dans les variables d'environnement de votre Worker.
QUIZ_URL = os.environ.get("QUIZ_URL")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Vérification obligatoire des variables d'environnement
if not BOT_TOKEN:
    sys.exit("Erreur fatale: BOT_TOKEN n'est pas défini. Le bot ne peut pas démarrer.")
if not QUIZ_URL:
    logging.warning("Attention: QUIZ_URL n'est pas défini. Le bouton 'Démarrer le Quiz' ne fonctionnera pas.")

# Importations python-telegram-bot
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
except ImportError:
    sys.exit("Erreur fatale: La bibliothèque 'python-telegram-bot' est manquante. Assurez-vous qu'elle est dans requirements.txt.")


# Configuration du logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# =====================================================
# Command Handlers
# =====================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Répond à la commande /start et envoie un bouton vers le Quiz."""
    
    # Message de bienvenue
    message = (
        f"Bienvenue {update.effective_user.first_name} !\n\n"
        "Êtes-vous prêt à découvrir votre profil de productivité et recevoir des astuces personnalisées ? "
        "Cliquez sur le bouton ci-dessous pour commencer le Quiz !"
    )
    
    # Création du bouton en ligne (Inline Keyboard)
    keyboard = [
        [
            InlineKeyboardButton("▶️ Démarrer le Quiz", url=QUIZ_URL)
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(message, reply_markup=reply_markup)
    logger.info("Commande /start reçue de %s. Quiz URL envoyée: %s", update.effective_user.id, QUIZ_URL)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Répond à la commande /help."""
    await update.message.reply_text(
        "Ce bot vous permet d'accéder à un Quiz. Utilisez la commande /start pour obtenir le lien."
    )


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Répond aux messages inconnus par un message d'aide."""
    await update.message.reply_text("Désolé, je ne comprends pas cette commande. Utilisez /start ou /help.")


# =====================================================
# Main application
# =====================================================

def main() -> None:
    """Démarre le Bot en mode Polling (recommandé pour un Worker)."""
    
    # Crée l'Application Bot
    application = Application.builder().token(BOT_TOKEN).build()

    # Lie les Handlers aux commandes et messages
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    
    # Répond aux messages inconnus (toujours en dernier)
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Lance le bot en Polling
    logger.info("Démarrage du bot en Polling. Quiz URL cible: %s", QUIZ_URL)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
