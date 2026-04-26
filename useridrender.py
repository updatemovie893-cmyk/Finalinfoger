import json
import os
import random
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ------------------- CONFIG -------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Parse multiple admins from environment variable (comma-separated)
admin_ids_str = os.environ.get("ADMIN_IDS", "1930138915")
ADMINS = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip().isdigit()]
if not ADMINS:
    ADMINS = [1930138915]  # fallback

ADMIN_USERNAME = "KOEKOE4"   # still used for contact text
API_URL = "https://tgchatid.vercel.app/api/lookup"
DATA_FILE = "user_data.json"

WELCOME_POINTS = 3.0
REFERRAL_BONUS = 2.0
LOOKUP_COST = 1.0

# Random text effects
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

def get_user(user_id):
    data = load_data()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {
            "balance": WELCOME_POINTS,
            "referrals": 0,
            "referred_by": None,
            "joined_at": datetime.now().isoformat()
        }
        save_data(data)
    return data[uid]

def update_user(user_id, key, value):
    data = load_data()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {"balance": WELCOME_POINTS, "referrals": 0, "referred_by": None}
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

# ------------------- FORWARD TO ALL ADMINS -------------------
async def notify_admins(context: ContextTypes.DEFAULT_TYPE, text: str):
    for admin_id in ADMINS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=text)
        except Exception as e:
            print(f"Failed to notify admin {admin_id}: {e}")

# ------------------- REPLY KEYBOARD -------------------
def get_main_keyboard(user_id=None):
    buttons = [
        ["🏠 Menu", "👥 Referral"],
        ["💰 Balance", "🔍 Lookup Number"]
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

# ------------------- BOT HANDLERS -------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or "No username"

    # Referral logic (2 points)
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
                    msg = f"🎉 သင့် referral link မှ သုံးစွဲသူအသစ် ဝင်ရောက်လာပါပြီ။\n➕ {REFERRAL_BONUS} points ထည့်ပေးလိုက်ပါပြီ။\n💰 လက်ရှိ balance: {get_user(referrer_id)['balance']:.1f} pts\n💟 BUY Points ဝယ်ယူလိုပါက @{ADMIN_USERNAME}"
                    await context.bot.send_message(chat_id=referrer_id, text=msg)
                    await notify_admins(context, f"✅ Referral used: {referrer_id} referred {user_id}")
    
    user_data = get_user(user_id)
    balance = user_data["balance"]
    referrals = user_data["referrals"]
    invite_link = f"https://t.me/{context.bot.username}?start=ref_{user_id}"
    
    effect = get_random_effect()
    welcome_text = (
        f"{effect['emoji']} {effect['text']}\n\n"
        f"🇲🇲<b>WELCOME</b> 🇲🇲\n"
        f"🪪 <b>ID NUMBER TO PHONE NUMBER</b> 🤳\n\n"
        f"👤 <b>User:</b> @{username}\n"
        f"🆔 <b>UID:</b> <code>{user_id}</code>\n\n"
        f"💰 <b>Balance:</b> {balance:.1f} pts\n"
        f"👥 <b>Referrals:</b> {referrals}\n\n"
        f"🔗 <b>Your Referral Link:</b>\n<a href='{invite_link}'>{invite_link}</a>\n\n"
        f"<b>Earn more by inviting friends</b> ({REFERRAL_BONUS} point per referral)\n\n"
        f"📢 <b>Points / API Source Code</b> – ဝယ်ယူလိုပါက @{ADMIN_USERNAME} သို့ ဆက်သွယ်ပါ။"
    )
    await update.message.reply_text(welcome_text, parse_mode="HTML", reply_markup=get_main_keyboard(user_id))
    await notify_admins(context, f"👤 User {user_id} (@{username}) started bot")

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def referral_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    referrals = user_data["referrals"]
    invite_link = f"https://t.me/{context.bot.username}?start=ref_{user_id}"
    effect = get_random_effect()
    text = (
        f"{effect['emoji']} {effect['text']}\n\n"
        f"<b>Refer &amp; Earn</b>\n\n"
        f"🔗 <b>သင့် referral link:</b>\n{invite_link}\n\n"
        f"📊 <b>Referred:</b> {referrals}\n"
        f"🎁 တစ်ဦးကို refer → +{REFERRAL_BONUS} pts\n\n"
        f"သူငယ်ချင်းများထံ Share လုပ်ပြီး points ရယူပါ!\n\n"
        f"💟 BUY Points ဝယ်ယူလိုပါက @{ADMIN_USERNAME}\n\n"
        f"👇 <b>သူငယ်ချင်းထံရှဲမည်</b>"
    )
    await update.message.reply_text("📌 Use the buttons below to go back to menu.", reply_markup=get_main_keyboard(user_id))
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

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = get_user(user_id)["balance"]
    effect = get_random_effect()
    text = f"{effect['emoji']} {effect['text']}\n\n💰 သင့်လက်ရှိ balance: {bal:.1f} pts\n\n💟 BUY Points ဝယ်ယူလိုပါက @{ADMIN_USERNAME}"
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=get_main_keyboard(user_id))

async def lookup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    prompt = (
        "📱 <b>Please send me a userID number</b>\n\n"
        "(သင်သိချင်သူအိုင်ဒီနံပါတ် ရိုက်ထည့်ပါ):\n\n"
        "👉 သင်မသိပါက User ID ကို သိရှိရန် @useridinfobot သို့ သွားပါ။\n\n"
        "Example: <code>1930138915</code>\n\n"
        "အခြားသူ၏ User ID ကို သိရှိလိုပါက ၎င်းကို @useridinfobot တွင် forward လုပ်ပါ။"
    )
    await update.message.reply_text(prompt, parse_mode="HTML", reply_markup=get_main_keyboard(user_id))
    context.user_data["awaiting_number"] = True

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Forward user's message to all admins
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
    elif text == "👑 Admin Panel":
        if user_id not in ADMINS:
            await update.message.reply_text("⚠️ မခိုးပါနှင့် @KOEKOE4 သိတယ်နော်", reply_markup=get_main_keyboard(user_id))
            return
        keyboard = [
            [InlineKeyboardButton("➕ Add Points (user)", callback_data="admin_add_user")],
            [InlineKeyboardButton("➖ Deduct Points (user)", callback_data="admin_deduct_user")],
            [InlineKeyboardButton("🌟 Add All Users", callback_data="admin_add_all")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ]
        await update.message.reply_text("👑 Admin Panel - ရွေးချယ်ပါ:", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    # If awaiting number for lookup
    if context.user_data.get("awaiting_number"):
        query_number = text.replace(" ", "").replace("-", "")
        if not query_number.isdigit() and not query_number.startswith("+"):
            await update.message.reply_text("❌ ကျေးဇူးပြု၍ နံပါတ် (သို့) ဖုန်းနံပါတ်သာ ထည့်ပါ။", reply_markup=get_main_keyboard(user_id))
            context.user_data["awaiting_number"] = False
            return
        
        if not deduct_points(user_id, LOOKUP_COST):
            await update.message.reply_text("❌ Balance မလုံလောက်ပါ။ Referral link မျှဝေပြီး points ရယူပါ။", reply_markup=get_main_keyboard(user_id))
            context.user_data["awaiting_number"] = False
            return
        
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        
        try:
            url = f"{API_URL}?number={query_number}"
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
                await show_main_menu(update, context, "🔙 မူရင်း Menu သို့ ပြန်ရောက်ပါပြီ။")
            else:
                raise Exception("API returned no data")
        except Exception as e:
            add_points(user_id, LOOKUP_COST)
            await update.message.reply_text(f"❌ Lookup failed: {str(e)}. Your {LOOKUP_COST} point has been refunded.", reply_markup=get_main_keyboard(user_id))
        
        context.user_data["awaiting_number"] = False
    else:
        await update.message.reply_text("ကျေးဇူးပြု၍ menu ရှိ ခလုတ်များကို နှိပ်ပါ။", reply_markup=get_main_keyboard(user_id))

# ------------------- ADMIN COMMANDS -------------------
async def addpoints_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("⚠️ မခိုးပါနှင့် @KOEKOE4 သိတယ်နော်")
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
            await context.bot.send_message(
                chat_id=target_id,
                text=f"🎁 Admin {user_id} ထံမှ လက်ဆောင် {points} points ရရှိပါသည်။\n💰 လက်ရှိ balance: {new_bal:.1f} pts\n💟 BUY Points ဝယ်ယူလိုပါက @{ADMIN_USERNAME}"
            )
        except:
            pass
    except:
        await update.message.reply_text("Invalid format.")

async def deductpoints_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("⚠️ မခိုးပါနှင့် @KOEKOE4 သိတယ်နော်")
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
                await context.bot.send_message(
                    chat_id=target_id,
                    text=f"⚠️ Admin {user_id} မှ {points} points နုတ်ယူသွားပါသည်။\n💰 လက်ရှိ balance: {new_bal:.1f} pts\n💟 BUY Points ဝယ်ယူလိုပါက @{ADMIN_USERNAME}"
                )
            except:
                pass
        else:
            await update.message.reply_text("❌ Insufficient balance for that user.")
    except:
        await update.message.reply_text("Invalid format.")

async def addallpoints_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("⚠️ မခိုးပါနှင့် @KOEKOE4 သိတယ်နော်")
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
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"🎁 Admin {user_id} ထံမှ လက်ဆောင် {points} points ရရှိပါသည်။\n💰 လက်ရှိ balance: {new_bal:.1f} pts\n💟 BUY Points ဝယ်ယူလိုပါက @{ADMIN_USERNAME}"
                )
            except:
                pass
        await update.message.reply_text(f"✅ Added {points} pts to all {count} users.")
    except:
        await update.message.reply_text("Invalid points.")

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id not in ADMINS:
        await query.edit_message_text("⚠️ မခိုးပါနှင့် @KOEKOE4 သိတယ်နော်")
        return
    data = query.data
    if data == "admin_back":
        await query.edit_message_text("Returned to main menu.")
        await context.bot.send_message(chat_id=user_id, text="Admin panel closed.", reply_markup=get_main_keyboard(user_id))
    elif data == "admin_add_user":
        await query.edit_message_text("Send user ID and points using command:\n/addpoints <user_id> <points>")
    elif data == "admin_deduct_user":
        await query.edit_message_text("Send user ID and points using command:\n/deductpoints <user_id> <points>")
    elif data == "admin_add_all":
        await query.edit_message_text("Send points for all users:\n/addallpoints <points>")

# ------------------- WEBHOOK SETUP (for Render) -------------------
application = None

async def webhook(request):
    global application
    update = Update.de_json(await request.json(), application.bot)
    await application.process_update(update)
    return {"ok": True}

def main():
    global application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CommandHandler("addpoints", addpoints_command))
    application.add_handler(CommandHandler("deductpoints", deductpoints_command))
    application.add_handler(CommandHandler("addallpoints", addallpoints_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(share_referral_callback, pattern="^(share_ref_|back_to_referral)"))
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    
    # Webhook mode (for Render)
    port = int(os.environ.get("PORT", 8443))
    webhook_url = os.environ.get("RENDER_EXTERNAL_URL")
    if not webhook_url:
        raise ValueError("RENDER_EXTERNAL_URL environment variable not set")
    
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"{webhook_url}/{BOT_TOKEN}"
    )

if __name__ == "__main__":
    main()