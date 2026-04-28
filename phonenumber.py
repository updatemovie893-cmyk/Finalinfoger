import json
import os
import random
import requests
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ------------------- CONFIG -------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

admin_ids_str = os.environ.get("ADMIN_IDS", "1930138915")
ADMINS = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip().isdigit()]
if not ADMINS:
    ADMINS = [1930138915]

ADMIN_USERNAME = "KOEKOE4"
API_URL = "https://tgchatid.vercel.app/api/lookup"
DATA_FILE = "user_data.json"
PROMO_FILE = "promo_codes.json"

WELCOME_POINTS = 3.0
REFERRAL_BONUS = 2.0
LOOKUP_COST = 1.0
DAILY_BONUS_AMOUNT = 2.0

EFFECTS = [
    {"emoji": "🔥", "text": "Kbz Payလည်းရ"},
    {"emoji": "👍", "text": "Wave Payလည်းရ"},
    {"emoji": "👎", "text": "OK$ Payလည်းရ"},
    {"emoji": "❤️", "text": "CB Payလည်းရ"},
    {"emoji": "🎉", "text": "ဂုဏ်ယူပါတယ်"},
    {"emoji": "💩", "text": "သူငယ်ချင်းတွေစီရှဲလ်တိုငး်ရမည်"},
]

def get_random_effect():
    return random.choice(EFFECTS)

# ------------------- DATA MANAGEMENT -------------------
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_promos():
    if os.path.exists(PROMO_FILE):
        with open(PROMO_FILE, "r") as f:
            return json.load(f)
    return {}

def save_promos(promos):
    with open(PROMO_FILE, "w") as f:
        json.dump(promos, f, indent=2)

def get_user(user_id):
    data = load_data()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {
            "balance": WELCOME_POINTS,
            "referrals": 0,
            "referred_by": None,
            "joined_at": datetime.now().isoformat(),
            "daily_last_claim": None,
            "lookups_count": 0
        }
        save_data(data)
    return data[uid]

def update_user(user_id, key, value):
    data = load_data()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {"balance": WELCOME_POINTS, "referrals": 0, "referred_by": None, "daily_last_claim": None, "lookups_count": 0}
    data[uid][key] = value
    save_data(data)

def add_points(user_id, points):
    u = get_user(user_id)
    new_bal = u["balance"] + points
    update_user(user_id, "balance", new_bal)
    return new_bal

def deduct_points(user_id, points):
    u = get_user(user_id)
    if u["balance"] < points:
        return False
    new_bal = u["balance"] - points
    update_user(user_id, "balance", new_bal)
    return True

def get_total_users():
    return len(load_data())

def increment_lookup_count(user_id):
    u = get_user(user_id)
    new_count = u.get("lookups_count", 0) + 1
    update_user(user_id, "lookups_count", new_count)
    return new_count

def get_total_lookups():
    data = load_data()
    total = 0
    for uid, info in data.items():
        total += info.get("lookups_count", 0)
    return total

# ------------------- FORWARD TO ADMINS -------------------
async def notify_admins(context: ContextTypes.DEFAULT_TYPE, text: str):
    for admin_id in ADMINS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=text)
        except Exception as e:
            print(f"Failed to notify admin {admin_id}: {e}")

# ------------------- REPLY KEYBOARD -------------------
def get_main_keyboard(user_id=None):
    buttons = [
        ["🔍 Lookup Number", "📊 Statistics"],
        ["🎁 Daily Bonus", "🎫 Promo Code"],
        ["👥 Referral", "💰 Balance"],
    ]
    if user_id in ADMINS:
        buttons.append(["👑 Admin Panel"])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=False)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text=None):
    user_id = update.effective_user.id
    if message_text:
        await update.message.reply_text(message_text, reply_markup=get_main_keyboard(user_id))
    else:
        await update.message.reply_text("🏠 Main Menu", reply_markup=get_main_keyboard(user_id))

# ------------------- DAILY BONUS -------------------
async def claim_daily_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    last_claim = user_data.get("daily_last_claim")
    
    if last_claim:
        last_date = datetime.fromisoformat(last_claim)
        if datetime.now() - last_date < timedelta(hours=24):
            remaining = timedelta(hours=24) - (datetime.now() - last_date)
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            await update.message.reply_text(
                f"⏳ You already claimed daily bonus.\nCome back after {hours}h {minutes}m.",
                reply_markup=get_main_keyboard(user_id)
            )
            return
    
    new_balance = add_points(user_id, DAILY_BONUS_AMOUNT)
    update_user(user_id, "daily_last_claim", datetime.now().isoformat())
    
    effect = get_random_effect()
    text = (
        f"{effect['emoji']} {effect['text']}\n\n"
        f"🎁 <b>DAILY BONUS CLAIMED!</b>\n\n"
        f"✨ You received: {DAILY_BONUS_AMOUNT} Credits\n"
        f"💰 New Balance: {new_balance:.2f}\n\n"
        f"Come back after 24 hours!"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=get_main_keyboard(user_id))

# ------------------- PROMO CODE -------------------
async def promo_code_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(
        "🎫 <b>Enter your promo code:</b>\n\nSend the code you have.",
        parse_mode="HTML",
        reply_markup=get_main_keyboard(user_id)
    )
    context.user_data["awaiting_promo"] = True

async def redeem_promo(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    user_id = update.effective_user.id
    promos = load_promos()
    code_upper = code.upper()
    
    if code_upper not in promos:
        await update.message.reply_text("❌ Invalid or expired promo code.", reply_markup=get_main_keyboard(user_id))
        return
    
    promo = promos[code_upper]
    if promo["uses_left"] <= 0:
        await update.message.reply_text("❌ This promo code has already been fully used.", reply_markup=get_main_keyboard(user_id))
        return
    
    points = promo["points"]
    promo["uses_left"] -= 1
    if promo["uses_left"] == 0:
        del promos[code_upper]
    else:
        promos[code_upper] = promo
    save_promos(promos)
    
    add_points(user_id, points)
    effect = get_random_effect()
    await update.message.reply_text(
        f"{effect['emoji']} {effect['text']}\n\n"
        f"✅ Promo code redeemed!\n➕ +{points} points added to your balance.\n"
        f"💰 Current balance: {get_user(user_id)['balance']:.2f} pts",
        reply_markup=get_main_keyboard(user_id)
    )

# ------------------- STATISTICS -------------------
async def statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    total_users = get_total_users()
    total_lookups = get_total_lookups()
    user_lookups = get_user(user_id).get("lookups_count", 0)
    
    text = (
        "📊 <b>Statistics</b>\n\n"
        f"👥 Total users: {total_users}\n"
        f"🔍 Total lookups performed: {total_lookups}\n"
        f"📱 Your lookups: {user_lookups}\n\n"
        f"💟 Buy more points: @{ADMIN_USERNAME}"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=get_main_keyboard(user_id))

# ------------------- LOOKUP WITH TARGET BUTTON -------------------
# We'll use context.user_data for temporary state: "awaiting_target" = True

async def lookup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the Target button."""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Target", callback_data="target_lookup")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_lookup")]
    ])
    await update.message.reply_text(
        "📱 <b>Choose an option:</b>",
        parse_mode="HTML",
        reply_markup=keyboard
    )

async def target_lookup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User pressed Target -> set state and show prompt."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    context.user_data["awaiting_target"] = True  # state flag
    await query.edit_message_text(
        "🔍 <b>LOOKUP DATABASE</b>\n\n"
        "Tap the Target button below to share a user, or send the User ID directly in chat.\n\n"
        "👉 Forward a message from the target user (any message they sent), or type their numeric User ID.\n"
        "Each lookup costs 1 point.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_lookup")]
        ])
    )

async def cancel_lookup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    context.user_data.pop("awaiting_target", None)
    await query.edit_message_text("❌ Lookup cancelled.", reply_markup=get_main_keyboard(user_id))

async def perform_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE, target_id_str: str, user_id: int):
    """Core lookup logic: deduct points, call API, show result."""
    if not target_id_str.isdigit():
        await update.message.reply_text("❌ Invalid user ID. Please send only numbers.", reply_markup=get_main_keyboard(user_id))
        return False
    
    if not deduct_points(user_id, LOOKUP_COST):
        await update.message.reply_text("❌ Balance insufficient. Invite friends to earn points.", reply_markup=get_main_keyboard(user_id))
        return False
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    try:
        url = f"{API_URL}?number={target_id_str}"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get("success") and data.get("data"):
            info = data["data"]
            effect = get_random_effect()
            current_username = update.effective_user.username or "unknown"
            result_text = (
                f"{effect['emoji']} {effect['text']}\n\n"
                f"📱သင်သိချင်သောသူ၏ အချက်အလက်များမှာ📱\n\n"
                f"📞 <b>Number:</b> {info.get('number', 'N/A')}\n"
                f"🌍 <b>Country:</b> {info.get('country', 'N/A')}\n"
                f"📞 <b>Country Code:</b> {info.get('country_code', 'N/A')}\n"
                f"🆔 <b>API Chat ID:</b> <code>{info.get('chat_id', 'N/A')}</code>\n"
                f"💌 <b>Name:</b> @{current_username}\n\n"
                f"✅ Lookup completed! {LOOKUP_COST} point deducted.\n"
                f"💰 New balance: {get_user(user_id)['balance']:.1f} pts"
            )
            await update.message.reply_text(result_text, parse_mode="HTML")
            increment_lookup_count(user_id)
            await show_main_menu(update, context, "🔙 Back to main menu.")
            return True
        else:
            raise Exception("API returned no data")
    except Exception as e:
        add_points(user_id, LOOKUP_COST)
        await update.message.reply_text(f"❌ Lookup failed: {str(e)}. Your {LOOKUP_COST} point has been refunded.", reply_markup=get_main_keyboard(user_id))
        return False

# ------------------- REFERRAL -------------------
async def referral_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    referrals = user_data["referrals"]
    invite_link = f"https://t.me/{context.bot.username}?start=ref_{user_id}"
    effect = get_random_effect()
    text = (
        f"{effect['emoji']} {effect['text']}\n\n"
        f"<b>Refer &amp; Earn</b>\n\n"
        f"🔗 <b>Your referral link:</b>\n{invite_link}\n\n"
        f"📊 <b>Referred:</b> {referrals}\n"
        f"🎁 +{REFERRAL_BONUS} pts per referral\n\n"
        f"Share with friends to earn points!\n\n"
        f"💟 Buy points: @{ADMIN_USERNAME}"
    )
    inline_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Share Referral Link", callback_data=f"share_ref_{user_id}")]
    ])
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=inline_keyboard)

async def share_referral_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("share_ref_"):
        owner_id = int(data.split("_")[2])
        invite_link = f"https://t.me/{context.bot.username}?start=ref_{owner_id}"
        await query.edit_message_text(
            text=f"🔗 <b>Your referral link to share:</b>\n\n{invite_link}\n\n<i>Forward this message to your friend or tap the link to copy it.</i>\n\nAfter your friend starts the bot, you will get {REFERRAL_BONUS} points!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 Forward this message", switch_inline_query="")],
                [InlineKeyboardButton("🔙 Back", callback_data="back_to_referral")]
            ])
        )
    elif data == "back_to_referral":
        await query.message.delete()
        await query.message.reply_text("Please click '👥 Referral' button again from the main menu.")

# ------------------- BALANCE -------------------
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = get_user(user_id)["balance"]
    effect = get_random_effect()
    text = f"{effect['emoji']} {effect['text']}\n\n💰 Your balance: {bal:.1f} pts\n\n💟 Buy points: @{ADMIN_USERNAME}"
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=get_main_keyboard(user_id))

# ------------------- START & MENU -------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or "No username"

    # Referral logic
    args = context.args
    if args and args[0].startswith("ref_"):
        referrer_id_str = args[0][4:]
        if referrer_id_str.isdigit():
            referrer_id = int(referrer_id_str)
            if referrer_id != user_id:
                curr = get_user(user_id)
                if curr["referred_by"] is None:
                    add_points(referrer_id, REFERRAL_BONUS)
                    update_user(referrer_id, "referrals", get_user(referrer_id)["referrals"] + 1)
                    update_user(user_id, "referred_by", referrer_id)
                    msg = f"🎉 New user joined via your link!\n➕ +{REFERRAL_BONUS} points.\n💰 New balance: {get_user(referrer_id)['balance']:.1f} pts"
                    await context.bot.send_message(chat_id=referrer_id, text=msg)
                    await notify_admins(context, f"✅ Referral used: {referrer_id} referred {user_id}")
    
    user_data = get_user(user_id)
    balance_val = user_data["balance"]
    referrals = user_data["referrals"]
    invite_link = f"https://t.me/{context.bot.username}?start=ref_{user_id}"
    
    effect = get_random_effect()
    welcome_text = (
        f"{effect['emoji']} {effect['text']}\n\n"
        f"🇲🇲<b>WELCOME</b> 🇲🇲\n"
        f"🪪 <b>ID NUMBER TO PHONE NUMBER</b> 🤳\n\n"
        f"👤 <b>User:</b> @{username}\n"
        f"🆔 <b>UID:</b> <code>{user_id}</code>\n\n"
        f"💰 <b>Balance:</b> {balance_val:.1f} pts\n"
        f"👥 <b>Referrals:</b> {referrals}\n\n"
        f"🔗 <b>Your Referral Link:</b>\n<a href='{invite_link}'>{invite_link}</a>\n\n"
        f"<b>Earn more by inviting friends</b> ({REFERRAL_BONUS} point per referral)\n\n"
        f"📢 <b>Points / API Source Code</b> – contact @{ADMIN_USERNAME} to purchase."
    )
    await update.message.reply_text(welcome_text, parse_mode="HTML", reply_markup=get_main_keyboard(user_id))
    await notify_admins(context, f"👤 User {user_id} (@{username}) started bot")

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# ------------------- ADMIN COMMANDS -------------------
async def addpoints_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("⚠️ Unauthorized.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /addpoints <user_id> <points>")
        return
    try:
        target_id = int(args[0])
        points = float(args[1])
        new_bal = add_points(target_id, points)
        await update.message.reply_text(f"✅ Added {points} pts to {target_id}. New balance: {new_bal:.1f}")
        try:
            await context.bot.send_message(chat_id=target_id, text=f"🎁 You received {points} points from admin.\n💰 New balance: {new_bal:.1f} pts")
        except:
            pass
    except:
        await update.message.reply_text("Invalid format.")

async def deductpoints_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("⚠️ Unauthorized.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /deductpoints <user_id> <points>")
        return
    try:
        target_id = int(args[0])
        points = float(args[1])
        if deduct_points(target_id, points):
            new_bal = get_user(target_id)["balance"]
            await update.message.reply_text(f"✅ Deducted {points} pts from {target_id}. New balance: {new_bal:.1f}")
            try:
                await context.bot.send_message(chat_id=target_id, text=f"⚠️ Admin deducted {points} points.\n💰 New balance: {new_bal:.1f} pts")
            except:
                pass
        else:
            await update.message.reply_text("❌ Insufficient balance for that user.")
    except:
        await update.message.reply_text("Invalid format.")

async def addallpoints_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("⚠️ Unauthorized.")
        return
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("Usage: /addallpoints <points>")
        return
    try:
        points = float(args[0])
        data = load_data()
        count = 0
        for uid_str in data:
            uid = int(uid_str)
            new_bal = add_points(uid, points)
            count += 1
            try:
                await context.bot.send_message(chat_id=uid, text=f"🎁 Admin gave everyone {points} points!\n💰 New balance: {new_bal:.1f} pts")
            except:
                pass
        await update.message.reply_text(f"✅ Added {points} pts to all {count} users.")
    except:
        await update.message.reply_text("Invalid points.")

async def create_promo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("⚠️ Unauthorized.")
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Usage: /createpromo <code> <points> <max_uses>\nExample: /createpromo WELCOME10 10 50")
        return
    code = args[0].upper()
    try:
        points = float(args[1])
        uses = int(args[2])
    except:
        await update.message.reply_text("Invalid points or max uses.")
        return
    promos = load_promos()
    promos[code] = {"points": points, "uses_left": uses, "total_uses": uses}
    save_promos(promos)
    await update.message.reply_text(f"✅ Promo code `{code}` created: {points} points, {uses} uses.", parse_mode="Markdown")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("⚠️ Unauthorized.")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Points (user)", callback_data="admin_add_user")],
        [InlineKeyboardButton("➖ Deduct Points (user)", callback_data="admin_deduct_user")],
        [InlineKeyboardButton("🌟 Add All Users", callback_data="admin_add_all")],
        [InlineKeyboardButton("🎫 Create Promo Code", callback_data="admin_create_promo")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
    ])
    await update.message.reply_text("👑 Admin Panel - Choose:", reply_markup=keyboard)

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id not in ADMINS:
        await query.edit_message_text("⚠️ Unauthorized.")
        return
    data = query.data
    if data == "admin_back":
        await query.edit_message_text("Admin panel closed.")
        await context.bot.send_message(chat_id=user_id, text="Returned to main menu.", reply_markup=get_main_keyboard(user_id))
    elif data == "admin_add_user":
        await query.edit_message_text("Use: /addpoints <user_id> <points>")
    elif data == "admin_deduct_user":
        await query.edit_message_text("Use: /deductpoints <user_id> <points>")
    elif data == "admin_add_all":
        await query.edit_message_text("Use: /addallpoints <points>")
    elif data == "admin_create_promo":
        await query.edit_message_text("Use: /createpromo <code> <points> <max_uses>")

# ------------------- MESSAGE HANDLER -------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip() if update.message.text else ""
    
    # Forward to admins (optional)
    await notify_admins(context, f"👤 User {user_id}: {text}")
    
    # Handle keyboard buttons
    if text == "🏠 Menu":
        await menu(update, context)
        return
    elif text == "👥 Referral":
        await referral_info(update, context)
        return
    elif text == "💰 Balance":
        await balance(update, context)
        return
    elif text == "🔍 Lookup Number":
        await lookup_start(update, context)
        return
    elif text == "📊 Statistics":
        await statistics(update, context)
        return
    elif text == "🎁 Daily Bonus":
        await claim_daily_bonus(update, context)
        return
    elif text == "🎫 Promo Code":
        await promo_code_start(update, context)
        return
    elif text == "👑 Admin Panel":
        await admin_panel(update, context)
        return
    
    # Handle promo code waiting
    if context.user_data.get("awaiting_promo"):
        context.user_data["awaiting_promo"] = False
        await redeem_promo(update, context, text)
        return
    
    # Handle lookup state: awaiting_target
    if context.user_data.get("awaiting_target"):
        # Clear state after processing
        context.user_data.pop("awaiting_target")
        # Check if it's a forwarded message
        if update.message.forward_from:
            target_id = update.message.forward_from.id
            await perform_lookup(update, context, str(target_id), user_id)
        elif text.isdigit():
            await perform_lookup(update, context, text, user_id)
        else:
            await update.message.reply_text("❌ Please forward a message from the user OR send a numeric User ID.", reply_markup=get_main_keyboard(user_id))
        return
    
    # Fallback
    await update.message.reply_text("Please use the buttons from the menu.", reply_markup=get_main_keyboard(user_id))

# ------------------- MAIN -------------------
def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CommandHandler("addpoints", addpoints_command))
    application.add_handler(CommandHandler("deductpoints", deductpoints_command))
    application.add_handler(CommandHandler("addallpoints", addallpoints_command))
    application.add_handler(CommandHandler("createpromo", create_promo_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(share_referral_callback, pattern="^(share_ref_|back_to_referral)"))
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(target_lookup_callback, pattern="^target_lookup$"))
    application.add_handler(CallbackQueryHandler(cancel_lookup_callback, pattern="^cancel_lookup$"))
    
    # Start polling (for Render, you can also use webhook)
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
