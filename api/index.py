import os
import logging
import datetime

from flask import Flask, request
from telegram import (
    Update,
    LabeledPrice,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# --- Configuration ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
# Define the price in Telegram Stars
SUBSCRIPTION_PRICE_STARS = 100 # Change this to your desired price in stars
SUBSCRIPTION_DAYS = 30

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- In-Memory "Database" for Demonstration ---
# IMPORTANT: For a real application, you MUST replace this with a persistent database
# like Vercel KV (Redis), Vercel Postgres, or another database service.
# Vercel's filesystem is ephemeral, so this dictionary will reset on each deployment.
user_subscriptions = {} # Stores {user_id: expiration_date}

def get_user_subscription_status(user_id: int) -> str:
    """Checks if a user's subscription is active."""
    expiration_date = user_subscriptions.get(user_id)
    if expiration_date and expiration_date > datetime.datetime.now():
        return f"✅ Active until {expiration_date.strftime('%Y-%m-%d %H:%M:%S')} UTC"
    return "❌ Inactive"

# --- Bot Command and Callback Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    user = update.effective_user
    status = get_user_subscription_status(user.id)
    
    keyboard = [
        [InlineKeyboardButton(f"🌟 Subscribe ({SUBSCRIPTION_PRICE_STARS} Stars)", callback_data="subscribe")],
        [InlineKeyboardButton("ℹ️ My Status", callback_data="status")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_html(
        rf"Hey {user.mention_html()}! Welcome to the Mini-App Subscription Bot.",
        reply_markup=reply_markup,
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parses the CallbackQuery and updates the message text."""
    query = update.callback_query
    await query.answer() # Acknowledge the button press
    
    if query.data == "subscribe":
        await send_invoice(update, context)
    elif query.data == "status":
        user_id = query.from_user.id
        status = get_user_subscription_status(user_id)
        await query.edit_message_text(text=f"Your current subscription status is: {status}")

async def send_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends an invoice for Telegram Stars."""
    chat_id = update.effective_chat.id
    title = f"{SUBSCRIPTION_DAYS}-Day Premium Subscription"
    description = f"Unlock all premium features of our Mini App for {SUBSCRIPTION_DAYS} days!"
    # The payload is a unique identifier for this invoice.
    # It will be returned in the successful payment update.
    payload = f"sub_{chat_id}_{datetime.datetime.now().timestamp()}"
    currency = "XTR" # XTR is the currency code for Telegram Stars
    prices = [LabeledPrice("Subscription", SUBSCRIPTION_PRICE_STARS)]

    await context.bot.send_invoice(
        chat_id=chat_id,
        title=title,
        description=description,
        payload=payload,
        provider_token="", # Must be empty for Telegram Stars
        currency=currency,
        prices=prices,
    )

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Answers the PreCheckoutQuery from Telegram."""
    query = update.pre_checkout_query
    # Check if the user is allowed to pay (e.g., not banned).
    # For this example, we'll always approve.
    if query.invoice_payload:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Something went wrong.")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirms the payment, updates the subscription, and notifies the user."""
    user_id = update.message.from_user.id
    
    # Update subscription in our "database"
    current_expiration = user_subscriptions.get(user_id, datetime.datetime.now())
    # If subscription is already active, extend it. Otherwise, start from now.
    start_date = max(current_expiration, datetime.datetime.now())
    new_expiration_date = start_date + datetime.timedelta(days=SUBSCRIPTION_DAYS)
    user_subscriptions[user_id] = new_expiration_date

    logger.info(f"User {user_id} successfully paid. New expiration: {new_expiration_date}")

    await update.message.reply_text(
        f"Thank you for your payment! Your subscription is now active for {SUBSCRIPTION_DAYS} days."
    )

# --- Flask App and Webhook Setup ---
app = Flask(__name__)
# Build the bot application
application = Application.builder().token(BOT_TOKEN).build()

# Add handlers
application.add_handler(CommandHandler("start", start_command))
application.add_handler(CallbackQueryHandler(button_callback))
application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))

@app.route("/", methods=["POST"])
async def process_update():
    """Vercel entry point. Processes a single update from Telegram."""
    try:
        json_update = request.get_json(force=True)
        update = Update.de_json(json_update, application.bot)
        await application.process_update(update)
        return "OK", 200
    except Exception as e:
        logger.error(f"Error processing update: {e}")
        return "Error", 500

# This part is optional but useful for setting the webhook initially.
@app.route("/set_webhook", methods=["GET"])
async def set_webhook():
    """Sets the webhook URL for the bot."""
    if WEBHOOK_URL:
        await application.bot.set_webhook(url=f"{WEBHOOK_URL}")
        return f"Webhook set to {WEBHOOK_URL}", 200
    else:
        return "WEBHOOK_URL environment variable not set!", 500
      
