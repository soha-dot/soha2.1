import telebot
from telebot import apihelper
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
import sqlite3
import time
import threading

# ==========================================
# 1. CORE CONFIGURATION
# ==========================================
apihelper.API_URL = "https://tapi.bale.ai/bot{0}/{1}"

ADMIN_ID = 604834400  
DEFAULT_BOT_TOKEN = "740198679:C9JGgeC9Bva7-ee6PzFDgls1HxvRsx7imT4"
DEFAULT_API_KEY = "sk-wyL1vkmWk1A0MBwsodR1E1oKRpLu8YvBR7JQRhv5NN4nOfs6"
DEFAULT_TEXT_MODEL = "gemini-2.5-flash-lite"
DEFAULT_IMAGE_MODEL = "gapgpt/z-image"
DEFAULT_API_BASE = "https://api.gapgpt.app/v1" 

DB_NAME = "soha_core.db"
user_states = {}
user_last_message_time = {}

# ==========================================
# 2. DATABASE ARCHITECTURE
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, username TEXT, joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
                      text_count INTEGER DEFAULT 0, image_count INTEGER DEFAULT 0, is_vip INTEGER DEFAULT 0, is_banned INTEGER DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS chat_history 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, message_text TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, error_text TEXT, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    default_configs = {
        "bot_token": DEFAULT_BOT_TOKEN,
        "api_key": DEFAULT_API_KEY,
        "text_model": DEFAULT_TEXT_MODEL,
        "image_model": DEFAULT_IMAGE_MODEL,
        "api_base": DEFAULT_API_BASE,
        "system_prompt": "تو سُها هستی، دستیار هوش مصنوعی تراز اول ایران. پاسخ‌هایت دقیق، لحنت محترمانه و ساختاریافته است.",
        "ad_text": "🌟 اسپانسر سُها: جای تبلیغ شما اینجا خالیست!",
        "ad_enabled": "1",
        "maintenance": "0",
        "anti_spam_delay": "3",
        "panic_mode": "0"
    }
    for k, v in default_configs.items():
        cursor.execute("INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()

def get_config(key):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM config WHERE key=?", (key,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def set_config(key, value):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE config SET value=? WHERE key=?", (value, key))
    conn.commit()
    conn.close()

def db_execute(query, params=(), fetchone=False, fetchall=False, commit=False):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(query, params)
        if commit: conn.commit()
        res = cursor.fetchone() if fetchone else cursor.fetchall() if fetchall else None
        conn.close()
        return res
    except Exception as e:
        return str(e)

init_db()
bot = telebot.TeleBot(get_config("bot_token"))

# ==========================================
# 3. BULLETPROOF AI ENGINES
# ==========================================
def call_text_llm(prompt, sys_override=None):
    if get_config("panic_mode") == "1": return "🚫 هسته هوش مصنوعی به دلایل امنیتی مسدود است."
    
    api_key, api_base, model = get_config("api_key"), get_config("api_base"), get_config("text_model")
    sys_prompt = sys_override if sys_override else get_config("system_prompt")
    
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = {"model": model, "messages": [{"role": "system", "content": sys_prompt}, {"role": "user", "content": prompt}]}
    
    try:
        response = requests.post(f"{api_base.rstrip('/')}/chat/completions", headers=headers, json=data, timeout=30)
        res_json = response.json()
        
        # رفع قطعیِ باگ KeyError
        if 'choices' in res_json and len(res_json['choices']) > 0:
            return res_json['choices'][0]['message']['content']
        else:
            print(f"\n[🚨 RAW API ERROR]: {res_json}")
            err_msg = res_json.get('error', {}).get('message', 'خطای ناشناخته از سمت سرور LLM')
            return f"❌ پاسخ نامعتبر از سرور هوش مصنوعی:\n`{err_msg}`"
            
    except Exception as e:
        print(f"\n[🚨 REQUEST CRASH]: {e}")
        return "⚠️ در برقراری ارتباط با پردازشگر مرکزی مشکلی رخ داد."

def generate_image(prompt):
    if get_config("panic_mode") == "1": return None, None
    api_key, api_base, model = get_config("api_key"), get_config("api_base"), get_config("image_model")
    
    en_prompt = call_text_llm(f"Translate this to a hyper-realistic image generation prompt in English. ONLY output the prompt: {prompt}")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = {"model": model, "prompt": en_prompt, "n": 1, "size": "1024x1024"}
    try:
        response = requests.post(f"{api_base.rstrip('/')}/images/generations", headers=headers, json=data, timeout=60).json()
        return (response['data'][0]['url'], en_prompt) if 'data' in response else (None, None)
    except:
        return None, None

def analyze_user_personality(user_id):
    messages = db_execute("SELECT message_text FROM chat_history WHERE user_id=? ORDER BY id DESC LIMIT 15", (user_id,), fetchall=True)
    if not messages or len(messages) == 0:
        return "❌ این کاربر هنوز هیچ پیامی به ربات نداده است (برای تحلیل حداقل ۱ پیام نیاز است)."
    
    prompt_list = [m[0] for m in messages]
    analysis_sys_prompt = """تو یک روانشناس بالینی و تحلیلگر ارشد داده‌های رفتاری هستی. 
لیستی از آخرین پیام‌های یک کاربر به ربات هوش مصنوعی به تو داده می‌شود. یک پروفایل دقیق در ۳ بخش برای مدیر بنویس:

۱. [حوزه علایق]: (مثلا: درگیر مباحث برنامه نویسی، پیگیر اخبار گیمینگ)
۲. [تیپ شخصیتی و لحن]: (مثلا: کمال‌گرا، عجول، دارای لحن صمیمی یا خشک، سطح دانش فنی بالا)
۳. [هدف از کاربرد]: (مثلا: ابزاری برای حل تمرین / صرفاً سرگرمی و وقت‌گذرانی)

پاسخ را کوتاه، بولت‌بندی شده و بسیار جذاب ارائه کن."""
    
    user_data_str = "\n".join([f"{i+1}. {p}" for i, p in enumerate(prompt_list)])
    return call_text_llm(f"پیام‌های کاربر جهت کالبدشکافی:\n{user_data_str}", sys_override=analysis_sys_prompt)

# ==========================================
# 4. ADMIN OS & COMMANDS
# ==========================================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    db_execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (message.chat.id, message.from_user.username), commit=True)
    bot.reply_to(message, "سلام! 🌌 من **سُها** هستم؛ پرچمدار هوش مصنوعی.\nمتن بفرست یا بگو «یک عکس از ... بکش».", parse_mode="Markdown")

@bot.message_handler(commands=['admin'])
def admin_dashboard(message):
    if message.chat.id != ADMIN_ID: return
    show_main_admin_menu(message.chat.id)

def show_main_admin_menu(chat_id, message_id=None):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📊 آمار سیستم", callback_data="menu_stats"),
        InlineKeyboardButton("⚙️ تنظیمات هوش مصنوعی", callback_data="menu_ai"),
        InlineKeyboardButton("👥 کالبدشکافی کاربران", callback_data="menu_users"),
        InlineKeyboardButton("🛠 ابزارهای دیتابیس", callback_data="menu_tools"),
        InlineKeyboardButton("📢 مدیریت تبلیغات", callback_data="menu_ads")
    )
    text = "👑 **سیستم عامل فرماندهی سُها (Soha OS)**\nیک بخش را انتخاب کنید:"
    if message_id: bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode="Markdown")
    else: bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('menu_') or call.data == 'back_main')
def handle_menu_navigation(call):
    if call.message.chat.id != ADMIN_ID: return
    markup = InlineKeyboardMarkup(row_width=2)
    if call.data == "back_main": show_main_admin_menu(call.message.chat.id, call.message.message_id); return
        
    elif call.data == "menu_stats":
        stats = db_execute("SELECT COUNT(*), SUM(text_count), SUM(image_count) FROM users", fetchone=True)
        text = f"📈 **آمار لحظه‌ای:**\n👥 کل کاربران: `{stats[0]}`\n💬 متون پردازش شده: `{stats[1] or 0}`\n🎨 رندرهای گرافیکی: `{stats[2] or 0}`"
        markup.add(InlineKeyboardButton("📦 دانلود دیتابیس (SQLite)", callback_data="tool_backup"), InlineKeyboardButton("🔙 بازگشت", callback_data="back_main"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif call.data == "menu_ai":
        markup.add(InlineKeyboardButton("🔑 تغییر API Key", callback_data="ai_api"), InlineKeyboardButton("🎭 تغییر شخصیت", callback_data="ai_sysprompt"), InlineKeyboardButton("🔙 بازگشت", callback_data="back_main"))
        bot.edit_message_text("⚙️ **تنظیمات مغز مصنوعی:**", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif call.data == "menu_users":
        markup.add(
            InlineKeyboardButton("🔍 استخراج پروفایل شناختی (AI)", callback_data="usr_inspect"),
            InlineKeyboardButton("✉️ ارسال پیام همگانی", callback_data="usr_broadcast"),
            InlineKeyboardButton("🌟 سوئیچ VIP", callback_data="usr_vip"),
            InlineKeyboardButton("⛔️ بن / آنبن", callback_data="usr_ban"),
            InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")
        )
        bot.edit_message_text("👥 **بخش رفتارشناسی و مدیریت کاربران:**", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif call.data == "menu_tools":
        markup.add(InlineKeyboardButton("💻 اجرای کوئری SQL", callback_data="tool_sql"), InlineKeyboardButton("🚨 دکمه وحشت (Panic)", callback_data="tool_panic"), InlineKeyboardButton("🔙 بازگشت", callback_data="back_main"))
        bot.edit_message_text("🛠 **ابزارهای سطح پایین:**", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif call.data == "menu_ads":
        markup.add(InlineKeyboardButton("تغییر وضعیت پخش تبلیغ", callback_data="ad_toggle"), InlineKeyboardButton("📝 ویرایش متن بنر", callback_data="ad_edit"), InlineKeyboardButton("🔙 بازگشت", callback_data="back_main"))
        bot.edit_message_text("📢 **کنترل پنل اسپانسر:**", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: not call.data.startswith('menu_') and call.data != 'back_main')
def handle_actions(call):
    if call.message.chat.id != ADMIN_ID: return
    action = call.data
    if action == "usr_inspect":
        bot.send_message(ADMIN_ID, "🔍 آیدی عددی کاربر مورد نظر را بفرست:")
        user_states[ADMIN_ID] = 'wait_inspect'
    elif action == "ai_sysprompt":
        bot.send_message(ADMIN_ID, f"پرامپت فعلی:\n`{get_config('system_prompt')}`\n\nپرامپت جدید را بفرست:", parse_mode="Markdown")
        user_states[ADMIN_ID] = 'wait_sysprompt'
    elif action == "usr_broadcast":
        bot.send_message(ADMIN_ID, "متن پیام همگانی را بفرست:"); user_states[ADMIN_ID] = 'wait_broadcast'
    elif action == "tool_backup":
        with open(DB_NAME, 'rb') as f: bot.send_document(ADMIN_ID, f, caption="📦 دیتابیس سُها")
    elif action == "tool_sql":
        bot.send_message(ADMIN_ID, "کوئری SQL را بنویس:"); user_states[ADMIN_ID] = 'wait_sql'

# ==========================================
# 5. STATE PROCESSOR
# ==========================================
def process_admin_states(message):
    state = user_states.get(ADMIN_ID)
    text = message.text
    if text == '/cancel': del user_states[ADMIN_ID]; bot.send_message(ADMIN_ID, "کنسل شد."); return True

    if state == 'wait_inspect':
        try:
            target_id = int(text)
            user_info = db_execute("SELECT username, joined_date, text_count, image_count, is_vip, is_banned FROM users WHERE user_id=?", (target_id,), fetchone=True)
            if not user_info: bot.send_message(ADMIN_ID, "❌ کاربری با این آیدی ثبت نشده.")
            else:
                wait_msg = bot.send_message(ADMIN_ID, f"⏳ در حال بازخوانی ۱۵ پیام آخر کاربر `{target_id}` و تحلیل توسط LLM...")
                ai_analysis = analyze_user_personality(target_id)
                info_text = (
                    f"👤 **گزارش کالبدشکافی (ID: `{target_id}`)**\n\n"
                    f"▫️ یوزرنیم: `@{user_info[0]}`\n▫️ تاریخ عضویت: `{user_info[1]}`\n"
                    f"▫️ وضعیت: {'🌟 VIP' if user_info[4]==1 else 'عادی'} | {'⛔️ بن' if user_info[5]==1 else 'فعال'}\n"
                    f"▫️ کل درخواست‌ها: `{user_info[2]} متن` | `{user_info[3]} تصویر`\n\n"
                    f"🧠 **پروفایل شناختی استخراج شده:**\n{ai_analysis}"
                )
                bot.delete_message(ADMIN_ID, wait_msg.message_id)
                bot.send_message(ADMIN_ID, info_text, parse_mode="Markdown")
        except ValueError: bot.send_message(ADMIN_ID, "❌ آیدی باید عدد باشد.")
        
    elif state == 'wait_sysprompt': set_config("system_prompt", text); bot.send_message(ADMIN_ID, "✅ انجام شد.")
    elif state == 'wait_sql': bot.send_message(ADMIN_ID, f"نتیجه:\n`{db_execute(text, fetchall=True)}`", parse_mode="Markdown")
    else: return False
    del user_states[ADMIN_ID]; return True

# ==========================================
# 6. MESSAGE HANDLER (LOGS EVERYONE NOW!)
# ==========================================
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.chat.id
    if user_id == ADMIN_ID and user_id in user_states:
        if process_admin_states(message): return

    if get_config("panic_mode") == "1" and user_id != ADMIN_ID: return

    # ===> قفل شکسته شد: حالا حرف‌های ادمین هم ذخیره می‌شود <===
    db_execute("INSERT INTO chat_history (user_id, message_text) VALUES (?, ?)", (user_id, message.text), commit=True)
    db_execute("DELETE FROM chat_history WHERE id NOT IN (SELECT id FROM chat_history WHERE user_id=? ORDER BY id DESC LIMIT 15)", (user_id,), commit=True)

    db_execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, message.from_user.username), commit=True)
    
    wait_msg = bot.reply_to(message, "⏳ پردازش...")

    if any(w in message.text.lower() for w in ["عکس", "تصویر", "بکش", "رسم کن"]):
        db_execute("UPDATE users SET image_count = image_count + 1 WHERE user_id=?", (user_id,), commit=True)
        img_url, _ = generate_image(message.text)
        if img_url: bot.delete_message(user_id, wait_msg.message_id); bot.send_photo(user_id, img_url, caption="✨ سُها")
        else: bot.edit_message_text("❌ خطا در رندر.", chat_id=user_id, message_id=wait_msg.message_id)
    else:
        db_execute("UPDATE users SET text_count = text_count + 1 WHERE user_id=?", (user_id,), commit=True)
        bot.edit_message_text(call_text_llm(message.text), chat_id=user_id, message_id=wait_msg.message_id)

if __name__ == "__main__":
    print("🚀 Soha OS v2.0 (Cognitive Edition) is online...")
    bot.polling(none_stop=True)