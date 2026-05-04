import os
import asyncio
import uuid
import re
from datetime import datetime
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, select, update, func, and_

# ======================= CONFIGURATION =======================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8783637703:AAEPEjD9tq-Ncfa1TsUy9s2skgN8KplNTQE")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
ADMIN_IDS = set(os.environ.get("ADMIN_IDS", "1930138915").split("1838854178,1930138915"))
LOOKUP_API_1 = "https://tgchatid.vercel.app/api/lookup?number="
LOOKUP_API_2 = "https://tg-to-num-vishal.vercel.app/api/search?number="
LOOKUP_COST = 1
VERIFY_AFTER_LOOKUPS = 3

# ======================= DATABASE MODELS =======================
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    telegram_id = Column(String, primary_key=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    username = Column(String, nullable=True)
    phone_number = Column(String, nullable=True)
    balance = Column(Integer, default=3)
    total_lookups = Column(Integer, default=0)
    referral_count = Column(Integer, default=0)
    badges = Column(Text, default="")
    daily_streak = Column(Integer, default=0)
    last_daily_bonus = Column(DateTime, nullable=True)
    last_activity = Column(DateTime, default=datetime.utcnow)
    banned = Column(Boolean, default=False)
    language = Column(String, default="en")
    created_at = Column(DateTime, default=datetime.utcnow)

class LookupHistory(Base):
    __tablename__ = "lookup_history"
    id = Column(String, primary_key=True)
    telegram_id = Column(String)
    query = Column(String)
    result_phone = Column(String, nullable=True)
    result_chat_id = Column(String, nullable=True)
    result_username = Column(String, nullable=True)
    result_country = Column(String, nullable=True)
    found = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class PhoneAlert(Base):
    __tablename__ = "phone_alerts"
    id = Column(String, primary_key=True)
    telegram_id = Column(String)
    phone_number = Column(String)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

# ======================= HELPER FUNCTIONS =======================
def clean_number(s: str) -> str:
    return re.sub(r"\D", "", s)

async def get_user(session: AsyncSession, telegram_id: str):
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()

async def notify_balance_change(telegram_id: str, change: int, reason: str, new_balance: int):
    try:
        async with AsyncSessionLocal() as sess:
            user = await get_user(sess, telegram_id)
            if user:
                lang = user.language
        # Simplified: actual message sending would be done elsewhere
    except:
        pass

async def check_achievements(telegram_id: str):
    # Placeholder – implement as needed
    pass

async def fire_alert_notifications(number: str, finder_id: str, source: str):
    cleaned = clean_number(number)
    async with AsyncSessionLocal() as session:
        alerts = await session.execute(
            select(PhoneAlert).where(and_(PhoneAlert.phone_number == cleaned, PhoneAlert.active == True))
        )
        for alert in alerts.scalars():
            if alert.telegram_id == finder_id:
                continue
            try:
                # In a real bot you would use context.bot; here we assume it's available
                # We'll set a global bot instance later
                pass
            except:
                pass

# ======================= KEYBOARDS =======================
def get_main_keyboard(telegram_id: str) -> ReplyKeyboardMarkup:
    base = [
        ["🔍 Lookup Number", "📋 Names History"],
        ["📊 Statistics", "👥 Invite & Earn"],
        ["🎟 Promo Code", "🦊 Support"],
        ["🎁 Daily Bonus", "👤 My Profile"],
        ["📜 History", "🏆 Leaderboard"],
        ["🎯 Milestones", "🏅 Achievements"],
        ["🔔 Phone Alert"],
        ["/start"],
    ]
    if telegram_id in ADMIN_IDS:
        base.append(["🔧 Admin Panel"])
    return ReplyKeyboardMarkup(base, resize_keyboard=True)

verify_contact_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("📱 Share My Contact", request_contact=True)],
    ["🔙 Back to Menu"]
], resize_keyboard=True)

# State tracking
waiting_lookup = set()

# ======================= LOOKUP BY PHONE NUMBER =======================
async def perform_lookup_by_phone(update: Update, context: ContextTypes.DEFAULT_TYPE, phone_input: str):
    telegram_id = str(update.effective_user.id)
    number = clean_number(phone_input)
    if len(number) < 7:
        await update.message.reply_text("❌ Invalid phone number (min 7 digits).", reply_markup=get_main_keyboard(telegram_id))
        return

    async with AsyncSessionLocal() as session:
        user = await get_user(session, telegram_id)
        if not user or user.balance < LOOKUP_COST:
            await update.message.reply_text(f"Insufficient balance. Need {LOOKUP_COST} pts.", reply_markup=get_main_keyboard(telegram_id))
            return
        if user.total_lookups >= VERIFY_AFTER_LOOKUPS and not user.phone_number:
            await update.message.reply_text("📱 Phone verification required. Please share your contact.", reply_markup=verify_contact_keyboard)
            return

    status_msg = await update.message.reply_text("🔍 Looking up phone number...")
    import aiohttp
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{LOOKUP_API_1}{number}") as resp1:
                data1 = await resp1.json() if resp1.status == 200 else None
            async with session.get(f"{LOOKUP_API_2}{number}") as resp2:
                data2 = await resp2.json() if resp2.status == 200 else None
        except Exception:
            data1 = data2 = None

    found1 = data1 and data1.get("success") and data1.get("data")
    found2 = data2 and (data2.get("success") or data2.get("found")) and data2.get("chat_id")

    if not found1 and not found2:
        await status_msg.edit_text(f"❌ No data found for `{phone_input}`", parse_mode="Markdown")
        return

    async with AsyncSessionLocal() as session:
        user = await get_user(session, telegram_id)
        if user:
            user.balance -= LOOKUP_COST
            user.total_lookups += 1
            await session.commit()
            new_balance = user.balance
        else:
            new_balance = 0

    lines = ["📱 *Lookup Result*", ""]
    phone_result = number
    country = ""
    country_code = ""
    chat_id_found = ""
    username_found = ""
    if found1:
        d = data1["data"]
        phone_result = d.get("number", number)
        country = d.get("country", "")
        country_code = d.get("country_code", "")
        chat_id_found = d.get("chat_id", "")
        username_found = d.get("Username", "")
        if country: lines.append(f"🌍 *Country:* {country}")
        if country_code: lines.append(f"📞 *Country Code:* +{country_code}")
        if chat_id_found: lines.append(f"🆔 *Chat ID:* `{chat_id_found}`")
        if username_found: lines.append(f"💌 *Username:* @{username_found}")
    if found2:
        d = data2
        if not found1:
            phone_result = d.get("phone", number)
        if d.get("username") and not username_found:
            username_found = d.get("username")
            lines.append(f"💌 *Username:* @{username_found}")
        if d.get("first_name") or d.get("last_name"):
            lines.append(f"👤 *Name:* {d.get('first_name','')} {d.get('last_name','')}".strip())
        if d.get("chat_id") and not chat_id_found:
            chat_id_found = d.get("chat_id")
            lines.append(f"🆔 *Chat ID:* `{chat_id_found}`")
    lines.append(f"\n✅ *-{LOOKUP_COST} pt* | 💎 New balance: {new_balance} pts")
    await status_msg.edit_text("\n".join(lines), parse_mode="Markdown")

    # Share with admin callback
    share_data = f"share:lookup:{phone_result}|{chat_id_found}|{username_found}|{country}|{country_code}"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📤 Share with Admin", callback_data=share_data)]])
    await update.message.reply_text("Do you want to share this result with admins? (You'll get +1 pt)", reply_markup=keyboard)

    # Save history
    async with AsyncSessionLocal() as session:
        history = LookupHistory(
            id=str(uuid.uuid4()),
            telegram_id=telegram_id,
            query=number,
            result_phone=phone_result,
            result_chat_id=chat_id_found or None,
            result_username=username_found or None,
            result_country=country or None,
            found="yes"
        )
        session.add(history)
        await session.commit()

    await fire_alert_notifications(phone_result, telegram_id, "📱 Phone Lookup")

# ======================= LOOKUP BY USER ID (TARGET) =======================
async def perform_lookup_by_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    telegram_id = str(update.effective_user.id)
    async with AsyncSessionLocal() as session:
        user = await get_user(session, telegram_id)
        if not user or user.balance < LOOKUP_COST:
            await update.message.reply_text(f"Insufficient balance. Need {LOOKUP_COST} pts.", reply_markup=get_main_keyboard(telegram_id))
            return
        if user.total_lookups >= VERIFY_AFTER_LOOKUPS and not user.phone_number:
            await update.message.reply_text("📱 Phone verification required.", reply_markup=verify_contact_keyboard)
            return

    status_msg = await update.message.reply_text("🔍 Looking up user...")
    import aiohttp
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{LOOKUP_API_1}{user_id}") as resp1:
                data1 = await resp1.json() if resp1.status == 200 else None
            async with session.get(f"{LOOKUP_API_2}{user_id}") as resp2:
                data2 = await resp2.json() if resp2.status == 200 else None
        except:
            data1 = data2 = None

    found1 = data1 and data1.get("success") and data1.get("data")
    found2 = data2 and (data2.get("success") or data2.get("found")) and data2.get("chat_id")
    if not found1 and not found2:
        await status_msg.edit_text(f"❌ No data found for user ID {user_id}")
        return

    async with AsyncSessionLocal() as session:
        user = await get_user(session, telegram_id)
        if user:
            user.balance -= LOOKUP_COST
            user.total_lookups += 1
            await session.commit()
            new_balance = user.balance
        else:
            new_balance = 0

    lines = ["👤 *Target User Lookup Result*", ""]
    phone_result = ""
    country = ""
    country_code = ""
    chat_id_found = ""
    username_found = ""
    if found1:
        d = data1["data"]
        phone_result = d.get("number", "")
        country = d.get("country", "")
        country_code = d.get("country_code", "")
        chat_id_found = d.get("chat_id", "")
        username_found = d.get("Username", "")
        if phone_result: lines.append(f"📞 *Number:* {phone_result}")
        if country: lines.append(f"🌍 *Country:* {country}")
        if country_code: lines.append(f"📞 *Code:* +{country_code}")
        if chat_id_found: lines.append(f"🆔 *Chat ID:* `{chat_id_found}`")
        if username_found: lines.append(f"💌 *Username:* @{username_found}")
    if found2:
        d = data2
        if not found1:
            phone_result = d.get("phone", "")
        if d.get("username") and not username_found:
            username_found = d.get("username")
            lines.append(f"💌 *Username:* @{username_found}")
        if d.get("first_name") or d.get("last_name"):
            lines.append(f"👤 *Name:* {d.get('first_name','')} {d.get('last_name','')}".strip())
        if d.get("chat_id") and not chat_id_found:
            chat_id_found = d.get("chat_id")
            lines.append(f"🆔 *Chat ID:* `{chat_id_found}`")
    lines.append(f"\n✅ *-{LOOKUP_COST} pt* | 💎 New balance: {new_balance} pts")
    await status_msg.edit_text("\n".join(lines), parse_mode="Markdown")

    # Share with admin
    share_data = f"share:lookup:{user_id}|{chat_id_found}|{username_found}|{country}|{country_code}"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📤 Share with Admin", callback_data=share_data)]])
    await update.message.reply_text("Share with admins? (+1 pt)", reply_markup=keyboard)

    # Save history
    async with AsyncSessionLocal() as session:
        history = LookupHistory(
            id=str(uuid.uuid4()),
            telegram_id=telegram_id,
            query=str(user_id),
            result_phone=phone_result or None,
            result_chat_id=chat_id_found or None,
            result_username=username_found or None,
            result_country=country or None,
            found="yes"
        )
        session.add(history)
        await session.commit()

    if phone_result:
        await fire_alert_notifications(phone_result, telegram_id, "👤 User ID Lookup")

# ======================= HANDLER FOR LOOKUP MENU =======================
async def handle_lookup_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = str(update.effective_user.id)
    async with AsyncSessionLocal() as session:
        user = await get_user(session, telegram_id)
        if not user or user.balance < LOOKUP_COST:
            await update.message.reply_text(f"Insufficient balance. Need {LOOKUP_COST} pts.", reply_markup=get_main_keyboard(telegram_id))
            return
        if user.total_lookups >= VERIFY_AFTER_LOOKUPS and not user.phone_number:
            await update.message.reply_text("📱 Please verify your phone number first.", reply_markup=verify_contact_keyboard)
            return
    waiting_lookup.add(telegram_id)
    keyboard = ReplyKeyboardMarkup([
        [KeyboardButton("🎯 Target", request_users=True)],
        ["🔙 Back to Menu"]
    ], resize_keyboard=True)
    await update.message.reply_text(f"Send a phone number (cost {LOOKUP_COST} pt) or tap 🎯 Target to choose a user:", reply_markup=keyboard)

# ======================= MAIN HANDLER ROUTER =======================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = str(update.effective_user.id)
    text = update.message.text.strip() if update.message.text else ""

    # Handle user_shared / users_shared (Target button)
    if update.message.user_shared:
        user_id = update.message.user_shared.user_id
        await perform_lookup_by_user_id(update, context, user_id)
        return
    if update.message.users_shared and update.message.users_shared.users:
        user_id = update.message.users_shared.users[0].user_id
        await perform_lookup_by_user_id(update, context, user_id)
        return

    # Waiting for phone number input after clicking Lookup Number
    if telegram_id in waiting_lookup:
        waiting_lookup.discard(telegram_id)
        await perform_lookup_by_phone(update, context, text)
        return

    # If it's a command, let the command handlers take care
    if text.startswith("/"):
        return

    # Main menu buttons
    if text == "🔍 Lookup Number":
        await handle_lookup_menu(update, context)
    elif text == "🔙 Back to Menu":
        await update.message.reply_text("Main menu:", reply_markup=get_main_keyboard(telegram_id))
    else:
        # Auto-detect phone number
        num = clean_number(text)
        if len(num) >= 7:
            await perform_lookup_by_phone(update, context, text)
        else:
            await update.message.reply_text("Use the menu buttons.", reply_markup=get_main_keyboard(telegram_id))

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = str(update.effective_user.id)
    contact = update.message.contact
    if contact.user_id and str(contact.user_id) == telegram_id:
        # Own contact -> verify
        phone = contact.phone_number.lstrip("+")
        async with AsyncSessionLocal() as session:
            user = await get_user(session, telegram_id)
            if user:
                user.phone_number = phone
                await session.commit()
        await update.message.reply_text(f"✅ Verified! Phone: +{phone}", reply_markup=get_main_keyboard(telegram_id))
        await check_achievements(telegram_id)
    else:
        # Someone else's contact -> lookup
        await perform_lookup_by_phone(update, context, contact.phone_number)

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    telegram_id = str(update.effective_user.id)
    if data.startswith("share:lookup:"):
        parts = data.split("|")
        target = parts[0].replace("share:lookup:", "")
        chat_id2 = parts[1] if len(parts) > 1 else ""
        username = parts[2] if len(parts) > 2 else ""
        country = parts[3] if len(parts) > 3 else ""
        code = parts[4] if len(parts) > 4 else ""
        # Give +1 point to sharer
        async with AsyncSessionLocal() as session:
            user = await get_user(session, telegram_id)
            if user:
                user.balance += 1
                await session.commit()
        await query.edit_message_text("✅ Data shared with admins. You received +1 pt.")
        # Forward to admins
        msg = f"📱 Shared by {telegram_id}:\nTarget: {target}"
        if country: msg += f"\n🌍 Country: {country}"
        if code: msg += f"\n📞 Code: {code}"
        if chat_id2: msg += f"\n🆔 Chat ID: {chat_id2}"
        if username: msg += f"\n💌 Username: {username}"
        for admin in ADMIN_IDS:
            try:
                await context.bot.send_message(admin, msg, parse_mode="Markdown")
            except:
                pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = str(update.effective_user.id)
    first_name = update.effective_user.first_name
    async with AsyncSessionLocal() as session:
        user = await get_user(session, telegram_id)
        if not user:
            user = User(telegram_id=telegram_id, first_name=first_name, balance=3)
            session.add(user)
            await session.commit()
    await update.message.reply_text(
        f"Welcome {first_name}! 🤖\nYour balance: 3 pts.\nUse 🔍 Lookup Number to search phone numbers.",
        reply_markup=get_main_keyboard(telegram_id)
    )

# ======================= WEBHOOK & HTTP SERVER =======================
async def handle_webhook(request, app):
    data = await request.json()
    update = Update.de_json(data, app.bot)
    await app.process_update(update)
    return web.Response(text="OK")

async def health(request):
    return web.Response(text="OK")

async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    await application.initialize()
    await application.start()

    render_hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    if not render_hostname:
        raise RuntimeError("RENDER_EXTERNAL_HOSTNAME not set. Deploy on Render.")
    webhook_url = f"https://{render_hostname}/webhook"
    await application.bot.set_webhook(webhook_url)
    print(f"✅ Webhook set to {webhook_url}")

    web_app = web.Application()
    web_app.router.add_post("/webhook", lambda req: handle_webhook(req, application))
    web_app.router.add_get("/health", health)
    runner = web.AppRunner(web_app)
    await runner.setup()
    port = int(os.environ.get("PORT", 3000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Health check on port {port}")

    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())