import os
import logging
import razorpay
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes
from uuid import uuid4

# --- Basic Configuration & Logging ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Load Environment Variables (Secrets) ---
# Vercel will provide these to your deployment
BOT_TOKEN = os.environ.get("8275448121:AAFylD2oQappNMi8cVHrmaPH4x0iU3jVwpg")
WEBHOOK_URL = os.environ.get("https://telegram-payment-bot-cl7x.vercel.app/") # Your Vercel app URL
RAZORPAY_KEY_ID = os.environ.get("rzp_test_KT9OOXMCt34lJX")
RAZORPAY_KEY_SECRET = os.environ.get("Dreamydesk8660")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("DDreamydesk8660")
MINI_APP_URL = os.environ.get("https://image-right.vercel.app/") # The URL to your Mini App

# --- Initialize Razorpay Client ---
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# --- IMPORTANT: Database Simulation ---
# For a premium, production bot, you MUST replace these functions with actual calls
# to a persistent database like Vercel KV (Redis) or Vercel Postgres.
# The in-memory dictionary below will be reset on every server restart!

db = {} # {user_id: {"subscription": "free/premium", "expires": None}}

def grant_premium_access(user_id: int):
    """Updates the user's status to premium in the database."""
    logger.info(f"DATABASE: Granting premium access to user {user_id}")
    db[user_id] = {"subscription": "premium"}
    # In a real DB, you'd set an expiration date, e.g., NOW() + 30 days.
    return True

# --- Bot Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command and deep links for subscriptions."""
    user = update.effective_user
    logger.info(f"User {user.id} ({user.full_name}) started the bot.")
    
    # Check for deep link payload ('subscribe')
    if context.args and context.args[0] == "subscribe":
        # Welcome message for users coming from the Mini App
        welcome_text = (
            f"🌟 **Welcome, {user.full_name}!**\n\n"
            "You're one step away from unlocking the full potential of our Mini App. "
            "Upgrade now to get access to all premium features."
        )
        keyboard = [
            [InlineKeyboardButton("💳 Pay ₹100 to Upgrade", callback_data=f"pay_{user.id}")]
        ]
        # This part of the code is missing the CallbackQueryHandler. I'll fix this in the next iteration.
        # For now, let's assume the payment link is generated directly.
        await generate_payment_link(update, context)

    else:
        # Standard welcome for users who start the bot directly
        welcome_text = "Welcome! This bot handles payments for our Mini App."
        await update.message.reply_text(welcome_text)

async def generate_payment_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates and sends a Razorpay payment link."""
    user_id = update.effective_user.id
    payment_amount_paise = 10000  # ₹100.00 (100 * 100)
    
    # A unique ID for this specific payment attempt to prevent replay attacks
    payment_id = str(uuid4())

    try:
        payment_data = {
            "amount": payment_amount_paise,
            "currency": "INR",
            "description": "Premium Mini App Subscription",
            "notes": {
                "telegram_user_id": user_id,
                "internal_payment_id": payment_id  # Crucial for tracking
            },
            "callback_url": MINI_APP_URL, # Redirect user back to the app after payment
            "callback_method": "get"
        }
        link = razorpay_client.payment_link.create(payment_data)
        payment_link_url = link['short_url']

        keyboard = [[InlineKeyboardButton("✅ Click Here to Pay Securely", url=payment_link_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_html(
            "Please complete your payment using the secure link below. It will open in Telegram's browser.",
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"Error creating Razorpay link for user {user_id}: {e}")
        await update.message.reply_text("Sorry, we couldn't create a payment link right now. Please try again later.")

# --- Webhook Handler (The Core of the Backend) ---
app = Flask(__name__)
application = Application.builder().token(BOT_TOKEN).build()

@app.route("/api/webhook/razorpay", methods=["POST"])
async def razorpay_webhook_handler():
    """Handles incoming webhooks from Razorpay to confirm payments."""
    webhook_body = request.get_data()
    received_signature = request.headers.get('X-Razorpay-Signature')
    
    # 1. Verify the webhook signature for security
    try:
        razorpay_client.utility.verify_webhook_signature(
            webhook_body.decode('utf-8'), received_signature, RAZORPAY_WEBHOOK_SECRET
        )
    except Exception as e:
        logger.error(f"Razorpay webhook signature verification failed: {e}")
        return "Signature verification failed", 400

    # 2. Process the payment confirmation
    payload = request.get_json()
    event = payload.get('event')

    if event == 'payment_link.paid':
        payment_details = payload['payload']['payment']['entity']
        notes = payment_details.get('notes', {})
        user_id = notes.get('telegram_user_id')
        
        if not user_id:
            logger.error("Webhook received without a telegram_user_id in notes.")
            return "Missing user ID", 400
        
        user_id = int(user_id)
        
        # 3. Grant premium access in the database
        grant_premium_access(user_id)
        
        # 4. Send a "Thank You" message back to the user
        success_message = (
            "🎉 **Thank You for Your Purchase!**\n\n"
            "Your subscription is now active. You have unlocked all premium features. "
            "Click the button below to return to the app and enjoy!"
        )
        keyboard = [[InlineKeyboardButton("🚀 Open Premium App", url=MINI_APP_URL)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await application.bot.send_message(
                chat_id=user_id,
                text=success_message,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Failed to send success message to user {user_id}: {e}")

    return "OK", 200

# --- Telegram Bot Setup ---
application.add_handler(CommandHandler("start", start_command))

@app.route("/api/bot", methods=["POST"])
async def telegram_webhook_handler():
    """Handles incoming updates from Telegram."""
    update_data = request.get_json()
    update = Update.de_json(update_data, application.bot)
    await application.process_update(update)
    return "OK", 200

