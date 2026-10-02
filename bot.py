# -*- coding: utf-8 -*-
"""ربات تلگرام محاسبه نیازهای تغذیه‌ای - نسخه حرفه‌ای"""

import json
import os
import logging
from datetime import datetime
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove,
    LabeledPrice
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes, ConversationHandler,
    PreCheckoutQueryHandler, TypeHandler, ApplicationHandlerStop
)
from subscription import (
    can_start_trial, start_trial, has_access, get_access_status,
    is_trial_active, is_subscription_active, extend_subscription,
    format_trial_remaining, format_subscription_remaining,
    get_subscription_end, create_or_update_user, get_user,
    SUBSCRIPTION_PRICE, CURRENCY, TRIAL_HOURS
)
from nutrition_calculator import NutritionCalculator

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATA_FILE = "user_data.json"

(AGE, GENDER, HEIGHT, WEIGHT, ACTIVITY, LIFE_STAGE,
 FOOD_CATEGORY, FOOD_SELECT, FOOD_UNIT, FOOD_GRAMS, SLEEP_HOURS) = range(11)

BTN_CALCULATE = "🧮 محاسبه جدید"
BTN_PROFILE   = "👤 پروفایل من"
BTN_FOOD      = "🍽 دفترچه غذا"
BTN_WATER     = "💧 ثبت آب"
BTN_SLEEP     = "😴 خواب من"
BTN_MONTHLY   = "📅 گزارش ماهانه"
BTN_HISTORY   = "📊 تاریخچه"
BTN_EXPORT    = "📥 دانلود آرشیو"
BTN_SUBSCRIBE = "💎 خرید اشتراک"
BTN_HELP      = "ℹ️ راهنما"
BTN_ABOUT     = "📞 درباره ما"
BTN_CANCEL    = "❌ انصراف"

calc = NutritionCalculator("nutrition_db.json")
# لود دیتابیس غذاها
FOODS = []
try:
    with open("foods_db.json", "r", encoding="utf-8") as f:
        FOODS = json.load(f)["foods"]
except Exception as e:
    logger.error(f"Foods DB load error: {e}")

# ---------- User Data ----------
def load_user_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Load error: {e}")
    return {}

def save_user_data(data):
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Save error: {e}")

def get_user_record(user_id):
    return load_user_data().get(str(user_id), {})

def update_user_record(user_id, updates):
    data = load_user_data()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {}
    data[uid].update(updates)
    save_user_data(data)


# ---------- Keyboards ----------
def get_main_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton(BTN_CALCULATE), KeyboardButton(BTN_PROFILE)],
        [KeyboardButton(BTN_FOOD), KeyboardButton(BTN_WATER)],
        [KeyboardButton(BTN_SLEEP), KeyboardButton(BTN_MONTHLY)],
        [KeyboardButton(BTN_EXPORT), KeyboardButton(BTN_HISTORY)],
        [KeyboardButton(BTN_SUBSCRIBE), KeyboardButton(BTN_HELP)],
        [KeyboardButton(BTN_ABOUT)],
    ], resize_keyboard=True)

def get_cancel_menu():
    return ReplyKeyboardMarkup([[KeyboardButton(BTN_CANCEL)]], resize_keyboard=True)

def get_gender_menu():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("مرد"), KeyboardButton("زن")], [KeyboardButton(BTN_CANCEL)]],
        resize_keyboard=True
    )

def get_activity_menu():
    keyboard = []
    items = list(calc.db['activity_levels'].items())
    for i in range(0, len(items), 2):
        row = [KeyboardButton(items[j][1]['label']) for j in range(i, min(i + 2, len(items)))]
        keyboard.append(row)
    keyboard.append([KeyboardButton(BTN_CANCEL)])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_life_stage_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("عادی"), KeyboardButton("باردار"), KeyboardButton("شیرده")],
        [KeyboardButton(BTN_CANCEL)]
    ], resize_keyboard=True)

def get_result_inline():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💾 ذخیره در پروفایل", callback_data="save_profile")],
        [InlineKeyboardButton("🔄 محاسبه مجدد", callback_data="recalc"),
         InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
    ])


# ---------- Formatter ----------
# ============ دانشنامه هر ماده مغذی ============
NUTRIENT_KNOWLEDGE = {
    "vitamin_a": {
        "why": "بینایی، سیستم ایمنی، سلامت پوست و رشد",
        "tip": "با چربی سالم (روغن زیتون، آووکادو) بهتر جذب می‌شه."
    },
    "vitamin_c": {
        "why": "آنتی‌اکسیدان قوی، سیستم ایمنی، جذب آهن، ساخت کلاژن",
        "tip": "با حرارت از بین می‌ره؛ تازه یا کم‌پخته مصرف کن."
    },
    "vitamin_d": {
        "why": "جذب کلسیم، سلامت استخوان، سیستم ایمنی",
        "tip": "منبع اصلی نور آفتابه؛ کمبودش خیلی شایعه."
    },
    "vitamin_e": {
        "why": "آنتی‌اکسیدان، سلامت پوست و مو",
        "tip": "با چربی‌ها بهتر جذب می‌شه."
    },
    "vitamin_k": {
        "why": "انعقاد خون، سلامت استخوان",
        "tip": "افراد مصرف‌کننده رقیق‌کننده خون با پزشک مشورت کنن."
    },
    "vitamin_b1": {
        "why": "تبدیل غذا به انرژی، سلامت اعصاب",
        "tip": "در غلات کامل و حبوبات فراوانه."
    },
    "vitamin_b2": {
        "why": "انرژی، سلامت پوست و چشم",
        "tip": "با نور از بین می‌ره؛ شیر رو در ظرف تیره نگه‌دار."
    },
    "vitamin_b3": {
        "why": "سلامت پوست، گوارش و اعصاب",
        "tip": "مصرف زیادش (بیشتر از UL) باعث گرگرفتگی می‌شه."
    },
    "vitamin_b6": {
        "why": "سلامت اعصاب، ساخت گلبول قرمز، خلق‌وخو",
        "tip": "در گوشت، ماهی، حبوبات و موز فراوانه."
    },
    "vitamin_b9": {
        "why": "ساخت DNA، رشد، جلوگیری از نقص لوله عصبی در بارداری",
        "tip": "برای خانم‌های باردار یا در آستانه بارداری حیاتیه."
    },
    "vitamin_b12": {
        "why": "سلامت اعصاب، ساخت گلبول قرمز، انرژی",
        "tip": "گیاه‌خواران محض باید مکمل مصرف کنن."
    },
    "calcium": {
        "why": "استحکام استخوان و دندان، عملکرد عضلات",
        "tip": "با ویتامین D بهتر جذب می‌شه."
    },
    "iron": {
        "why": "ساخت هموگلوبین، انتقال اکسیژن، انرژی",
        "tip": "با ویتامین C بهتر جذب می‌شه؛ با چای و قهوه بدتر."
    },
    "magnesium": {
        "why": "عملکرد عضلات و اعصاب، خواب بهتر، کنترل قند",
        "tip": "استرس زیاد مصرف منیزیم بدن رو بالا می‌بره."
    },
    "zinc": {
        "why": "سیستم ایمنی، ترمیم زخم، سلامت پوست",
        "tip": "مصرف زیادش جذب مس رو کم می‌کنه."
    },
    "potassium": {
        "why": "فشار خون سالم، عملکرد قلب و عضلات",
        "tip": "افراد با مشکلات کلیوی با پزشک مشورت کنن."
    },
    "phosphorus": {
        "why": "استحکام استخوان، ذخیره انرژی",
        "tip": "در گوشت، لبنیات و غلات فراوانه."
    },
    "iodine": {
        "why": "عملکرد تیروئید، سوخت‌وساز، رشد",
        "tip": "نمک یددار بهترین منبع، ولی زیادیش مضره."
    },
    "selenium": {
        "why": "آنتی‌اکسیدان، عملکرد تیروئید، سیستم ایمنی",
        "tip": "آجیل برزیلی منبع فوق‌العاده‌ایه؛ ۲ عدد در روز کافیه."
    },
}


def format_report(report, user):
    m = report['macros']
    g = 'مرد' if user['gender'] == 'male' else 'زن'

    t = "📊 *گزارش کامل نیازهای تغذیه‌ای روزانه*\n"
    t += "━━━━━━━━━━━━━━━━━━━━\n\n"

    t += "👤 *مشخصات شما:*\n"
    t += f"• سن: {user['age']} سال | جنسیت: {g}\n"
    t += f"• قد: {user['height_cm']} cm | وزن: {user['weight_kg']} kg\n"
    t += f"• سطح فعالیت: {user['activity_label']}\n\n"

    t += "ℹ️ *راهنمای خواندن گزارش:*\n"
    t += "• هر عدد = مقداری که *هر روز* باید بخوری\n"
    t += "• «حداکثر مجاز» = بیشتر از این مقدار *برات مضره*\n"
    t += "• در بخش غذاها، هر مقدار = *۱۰۰٪ نیاز روزانه* از اون غذا\n"
    t += "• می‌تونی چند غذا رو *ترکیب* کنی\n\n"

    t += "📏 *واحدها:*\n"
    t += "• µg = میکروگرم | mg = میلی‌گرم | g = گرم\n"
    t += "• RAE = معادل رتینول | DFE = معادل فولات | NE = معادل نیاسین\n\n"

    t += "🔥 *انرژی و درشت‌مغذی‌ها:*\n"
    t += "━━━━━━━━━━━━━━━━━━━━\n"
    t += f"• *کالری کل روزانه*: `{report['tdee_kcal']:,}`\n"
    t += f"  💡 برای *حفظ* وزن فعلی. برای کاهش ۲۰٪ کم کن، برای افزایش ۲۰٪ اضافه کن.\n\n"
    t += f"• *پروتئین*: `{m['protein_g']}g` ({m['protein_kcal']} کالری)\n"
    t += f"  💡 عضلات، مو و پوست. هر گرم ۴ کالری.\n\n"
    t += f"• *چربی*: `{m['fat_g']}g` (بازه {m['fat_range_g'][0]}-{m['fat_range_g'][1]}g)\n"
    t += f"  💡 هورمون‌ها و جذب ویتامین A,D,E,K. هر گرم ۹ کالری.\n\n"
    t += f"• *کربوهیدرات*: `{m['carb_g']}g` (بازه {m['carb_range_g'][0]}-{m['carb_range_g'][1]}g)\n"
    t += f"  💡 منبع اصلی انرژی. هر گرم ۴ کالری.\n\n"
    t += f"• *فیبر*: `{m['fiber_g']}g`\n"
    t += f"  💡 گوارش سالم و احساس سیری.\n\n"
    t += f"• *آب*: `{m['water_l']}` لیتر (حدود {int(m['water_l']*4)} لیوان)\n\n"

    t += "💊 *ریزمغذی‌ها (ویتامین‌ها و املاح):*\n"
    t += "━━━━━━━━━━━━━━━━━━━━\n"

    for n in report['nutrients']:
        info = NUTRIENT_KNOWLEDGE.get(n['id'], {})
        t += f"\n▸ *{n['name']}* ({n['unit']})\n"
        t += f"   📊 نیاز روزانه: `{n['required']}`\n"
        if n['ul']:
            t += f"   ⚠️ حداکثر مجاز: `{n['ul']}` (بیشتر مضره)\n"
        if info.get('why'):
            t += f"   💡 *چرا لازمه:* {info['why']}\n"
        t += f"   🍽 *منابع غذایی* (هر مقدار = ۱۰۰٪ نیاز روزانه):\n"
        for fs in n['food_suggestions'][:3]:
            t += f"      • {fs['food']}: `{fs['grams_needed']}g`\n"
        if info.get('tip'):
            t += f"   💬 *نکته:* {info['tip']}\n"

    t += "\n━━━━━━━━━━━━━━━━━━━━\n"
    t += "⚠️ اعداد *عمومی* برای افراد سالمه. برای شرایط خاص با پزشک مشورت کن.\n"
    return t


# ---------- Handlers ----------
async def start(update, context):
    user_id = str(update.effective_user.id)
    record = get_user_record(user_id)
    if record.get('age'):
        await update.message.reply_text(
            f"سلام {record.get('name','دوست عزیز')}! 👋\nخوش برگشتی:",
            reply_markup=get_main_menu()
        )
    else:
        await update.message.reply_text(
            "سلام! 👋\n\n"
            "من *ربات محاسبه نیازهای تغذیه‌ای* هستم 🥗\n\n"
            "با من می‌تونی:\n"
            "• کالری، پروتئین، ویتامین‌ها و املاح روزانه‌ت رو بفهمی\n"
            "• منابع غذایی هر ماده رو ببینی\n"
            "• پروفایلت رو ذخیره کنی\n\n"
            "از منوی پایین شروع کن 👇",
            reply_markup=get_main_menu(),
            parse_mode='Markdown'
        )
    return ConversationHandler.END

async def show_help(update, context):
    await update.message.reply_text(
        "ℹ️ *راهنما*\n━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔹 *محاسبه جدید*: اطلاعاتت رو وارد کن\n"
        "🔹 *پروفایل من*: اطلاعات ذخیره‌شده‌ت\n"
        "🔹 *تاریخچه*: ۵ محاسبه آخر\n"
        "🔹 *ثبت آب*: مصرف روزانه آب\n"
        "🔹 *انصراف*: لغو هر مرحله\n\n"
        "💡 اگه پروفایلت رو ذخیره کنی، دفعه بعد با یک کلیک گزارش می‌گیری.",
        parse_mode='Markdown', reply_markup=get_main_menu()
    )
# ==================== دفترچه غذا ====================
async def show_food_menu(update, context):
    user_id = str(update.effective_user.id)
    record = get_user_record(user_id)
    today = datetime.now().strftime('%Y-%m-%d')
    diary = record.get('food_diary', {})
    today_items = diary.get(today, [])
    kb = ReplyKeyboardMarkup([
        [KeyboardButton("➕ افزودن غذا")],
        [KeyboardButton("📊 مشاهده امروز"), KeyboardButton("🗑 پاک کردن امروز")],
        [KeyboardButton("🏠 منوی اصلی")],
    ], resize_keyboard=True)
    await update.message.reply_text(
        f"🍽 *دفترچه غذای امروز*\n\n"
        f"📅 تاریخ: `{today}`\n"
        f"🍴 تعداد آیتم: `{len(today_items)}`\n\n"
        "از منوی پایین انتخاب کن:",
        parse_mode='Markdown', reply_markup=kb
    )

async def food_add_start(update, context):
    if not FOODS:
        await update.message.reply_text("❌ دیتابیس غذاها لود نشده.", reply_markup=get_main_menu())
        return ConversationHandler.END
    cats = sorted(set(f['category'] for f in FOODS))
    keyboard = []
    row = []
    for c in cats:
        row.append(KeyboardButton(c))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([KeyboardButton(BTN_CANCEL)])
    await update.message.reply_text("📂 دسته‌بندی غذا را انتخاب کن:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return FOOD_CATEGORY

async def food_get_category(update, context):
    cat = update.message.text
    if cat == BTN_CANCEL:
        return await cancel(update, context)
    if cat == "📊 مشاهده امروز":
        await food_show_today(update, context)
        return ConversationHandler.END
    matching = [f for f in FOODS if f['category'] == cat]
    if not matching:
        await update.message.reply_text("دسته نامعتبر. دوباره انتخاب کن.")
        return FOOD_CATEGORY
    context.user_data['food_cat'] = cat
    keyboard = []
    row = []
    for i, f in enumerate(matching):
        row.append(KeyboardButton(f['name']))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([KeyboardButton(BTN_CANCEL)])
    await update.message.reply_text('از ' + cat + ' انتخاب کن:',
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return FOOD_SELECT

async def food_get_select(update, context):
    name = update.message.text
    if name == BTN_CANCEL:
        return await cancel(update, context)
    food = next((f for f in FOODS if f['name'] == name), None)
    if not food:
        await update.message.reply_text("غذا پیدا نشد.")
        return FOOD_SELECT
    context.user_data['food_sel'] = food
    if food.get('unit'):
        uname = food['unit']['name']
        ug = food['unit']['grams']
        kb = ReplyKeyboardMarkup([
            [KeyboardButton(uname + " (هر " + uname + " ~ " + str(ug) + "g)")],
            [KeyboardButton("گرم")],
            [KeyboardButton(BTN_CANCEL)]
        ], resize_keyboard=True)
        await update.message.reply_text(
            "*" + food['name'] + "*" + chr(10) + chr(10) + "چطور مقدار را وارد می‌کنی؟",
            parse_mode='Markdown', reply_markup=kb)
        return FOOD_UNIT
    else:
        await update.message.reply_text(
            "*" + food['name'] + "*" + chr(10) + chr(10) + "مقدار به گرم وارد کن (مثلاً 150):",
            parse_mode='Markdown', reply_markup=get_cancel_menu())
        return FOOD_GRAMS



async def food_get_unit(update, context):
    choice = update.message.text
    if choice == BTN_CANCEL:
        return await cancel(update, context)
    food = context.user_data.get('food_sel')
    if not food or not food.get('unit'):
        await update.message.reply_text("خطا")
        return ConversationHandler.END
    uname = food['unit']['name']
    if choice == "گرم":
        context.user_data['food_unit'] = None
        await update.message.reply_text("مقدار به گرم وارد کن:", reply_markup=get_cancel_menu())
        return FOOD_GRAMS
    elif uname in choice:
        context.user_data['food_unit'] = food['unit']
        await update.message.reply_text("چند " + uname + "؟ (مثلاً 2)", reply_markup=get_cancel_menu())
        return FOOD_GRAMS
    else:
        await update.message.reply_text("از دکمه‌ها انتخاب کن.")
        return FOOD_UNIT


async def food_get_grams(update, context):
    try:
        val = float(update.message.text.strip())
        if not 0.1 <= val <= 5000:
            raise ValueError
    except ValueError:
        await update.message.reply_text("عدد معتبر وارد کن:", reply_markup=get_cancel_menu())
        return FOOD_GRAMS
    food = context.user_data['food_sel']
    unit = context.user_data.get('food_unit')
    if unit:
        grams = val * unit['grams']
        vs = str(val)
        if vs.endswith('.0'):
            vs = vs[:-2]
        display = vs + ' ' + unit['name']
    else:
        grams = val
        gs = str(grams)
        if gs.endswith('.0'):
            gs = gs[:-2]
        display = gs + 'g'
    user_id = str(update.effective_user.id)
    today = datetime.now().strftime('%Y-%m-%d')
    record = get_user_record(user_id)
    diary = record.get('food_diary', {})
    items = diary.get(today, [])
    items.append({'id': food['id'], 'name': food['name'], 'grams': grams, 'display': display})
    diary[today] = items
    update_user_record(user_id, {'food_diary': diary})
    kcal = int(food['per_100g']['calories'] * grams / 100)
    txt = '✅ ' + food['name'] + ' (' + display + ') اضافه شد'
    txt += chr(10) + 'کالری: ' + str(kcal)
    txt += chr(10) + chr(10) + 'غذای بعدی را از دسته‌بندی‌های زیر انتخاب کن:'
    cats = sorted(set(f['category'] for f in FOODS))
    keyboard = []
    row = []
    for c in cats:
        row.append(KeyboardButton(c))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([KeyboardButton("📊 مشاهده امروز")])
    keyboard.append([KeyboardButton(BTN_CANCEL)])
    await update.message.reply_text(txt,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return FOOD_CATEGORY



async def food_show_today(update, context):
    user_id = str(update.effective_user.id)
    record = get_user_record(user_id)
    today = datetime.now().strftime('%Y-%m-%d')
    items = record.get('food_diary', {}).get(today, [])
    if not items:
        await update.message.reply_text("امروز هنوز چیزی اضافه نکردی.", reply_markup=get_main_menu())
        return
    if not record.get('age'):
        await update.message.reply_text("اول پروفایلت رو بساز.", reply_markup=get_main_menu())
        return
    user = {'age': record['age'], 'gender': record['gender'],
        'height_cm': record['height_cm'], 'weight_kg': record['weight_kg'],
        'activity': record['activity'],
        'activity_label': calc.db['activity_levels'][record['activity']]['label'],
        'life_stage': record.get('life_stage', 'normal')}
    report = calc.build_report(user)
    targets = {'calories': report['tdee_kcal'], 'protein': report['macros']['protein_g'],
        'carbs': report['macros']['carb_g'], 'fat': report['macros']['fat_g'],
        'fiber': report['macros']['fiber_g']}
    for n in report['nutrients']:
        targets[n['id']] = n['required']
    consumed = {k: 0 for k in targets}
    details = []
    for it in items:
        food = next((f for f in FOODS if f['id'] == it['id']), None)
        if not food:
            continue
        factor = it['grams'] / 100
        details.append({'name': food['name'], 'grams': it['grams'],
            'kcal': food['per_100g']['calories'] * factor})
        for k in targets:
            if k in food['per_100g']:
                consumed[k] += food['per_100g'][k] * factor
    L = []
    L.append("*گزارش امروز*")
    L.append("=" * 18)
    L.append("")
    L.append("📅 " + today)
    L.append("")
    L.append("🍽 *غذاهای خورده‌شده* (" + str(len(details)) + " آیتم):")
    for i, it in enumerate(details, 1):
        L.append("   " + str(i) + ". " + it['name'] + " - " + str(it['grams']) + "g (کالری: " + str(int(it['kcal'])) + ")")
    L.append("")
    L.append("=" * 18)
    L.append("")
    L.append("🔥 *کالری و درشت‌مغذی‌ها:*")
    pct = int(consumed['calories'] / targets['calories'] * 100) if targets['calories'] else 0
    d = consumed['calories'] - targets['calories']
    st = "OK" if abs(d / targets['calories']) < 0.1 else ("کمبود" if d < 0 else "اضافه")
    L.append("کالری: " + str(int(consumed['calories'])) + " از " + str(int(targets['calories'])) + " (" + str(pct) + "%) - " + st + " (" + str(int(d)) + ")")
    L.append("")
    for k, lbl, u in [('protein', 'پروتئین', 'g'), ('carbs', 'کربوهیدرات', 'g'),
                       ('fat', 'چربی', 'g'), ('fiber', 'فیبر', 'g')]:
        c = consumed[k]
        tg = targets[k]
        dd = c - tg
        p = int(c / tg * 100) if tg else 0
        s = "OK" if abs(dd / tg) < 0.1 else ("کمبود" if dd < 0 else "اضافه")
        L.append(lbl + ": " + str(int(c)) + " از " + str(int(tg)) + " " + u + " (" + str(p) + "%) - " + s + " (" + str(int(dd)) + ")")
    L.append("")
    L.append("=" * 18)
    L.append("")
    problems = []
    for n in report['nutrients']:
        c = consumed.get(n['id'], 0)
        tg = targets[n['id']]
        if tg and (c / tg * 100 < 70 or c / tg * 100 > 130):
            problems.append((n, c, tg, c / tg * 100))
    L.append("💊 *ریزمغذی‌های خارج از محدوده:*")
    if problems:
        problems.sort(key=lambda x: abs(x[3] - 100), reverse=True)
        for n, c, tg, pc in problems[:12]:
            ic = "کمبود" if pc < 70 else "اضافه"
            L.append("")
            L.append("▸ *" + n['name'] + "*")
            if pc < 70:
                status_txt = "کمبود " + str(round(tg - c, 1)) + " " + n['unit']
            else:
                status_txt = "اضافه " + str(round(c - tg, 1)) + " " + n['unit']
            L.append("   " + str(round(c, 1)) + " از " + str(tg) + " " + n['unit'] + " (" + str(int(pc)) + "%) - " + status_txt)
    else:
        L.append("همه در محدوده نرمال!")
    t = chr(10).join(L)
    context.user_data['last_diary_analysis'] = (targets, consumed, report, problems)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("پیشنهاد اصلاحی", callback_data="show_suggest")]])
    await update.message.reply_text(t, parse_mode='Markdown', reply_markup=kb)



async def food_clear_today(update, context):
    user_id = str(update.effective_user.id)
    today = datetime.now().strftime('%Y-%m-%d')
    record = get_user_record(user_id)
    diary = record.get('food_diary', {})
    diary[today] = []
    update_user_record(user_id, {'food_diary': diary})
    await update.message.reply_text("🗑 دفترچه امروز پاک شد.", reply_markup=get_main_menu())

async def food_suggest(update, context):
    q = update.callback_query
    data = context.user_data.get('last_diary_analysis')
    if not data:
        if q:
            await q.answer("اول مشاهده امروز رو بزن", show_alert=True)
        return
    targets, consumed, report, problems = data
    if not problems:
        txt = "همه چیز نرماله! نیازی به اصلاح نیست."
    else:
        L = []
        L.append("*پیشنهاد اصلاحی*")
        L.append("=" * 18)
        L.append("")
        deficits = [p for p in problems if p[3] < 70]
        excesses = [p for p in problems if p[3] > 130]
        if deficits:
            L.append("*کمبودها - اینا رو اضافه کن:*")
            L.append("")
            for n, c, tg, pc in deficits[:5]:
                need = tg - c
                L.append("▸ *" + n['name'] + "* - کمبود " + str(round(need, 1)) + " " + n['unit'])
                for fs in n['food_suggestions'][:3]:
                    g = (need / fs['per_100g']) * 100
                    L.append("   - " + fs['food'] + ": " + str(round(g)) + "g")
                L.append("")
        if excesses:
            L.append("*اضافه‌ها - اینا رو کم کن:*")
            L.append("")
            for n, c, tg, pc in excesses[:3]:
                L.append("▸ " + n['name'] + ": " + str(round(c - tg, 1)) + " " + n['unit'] + " بیشتر از نیاز")
        txt = chr(10).join(L)
    if q:
        await q.message.reply_text(txt, parse_mode='Markdown', reply_markup=get_main_menu())
    else:
        await update.message.reply_text(txt, parse_mode='Markdown', reply_markup=get_main_menu())



async def show_sleep(update, context):
    user_id = str(update.effective_user.id)
    record = get_user_record(user_id)
    night = record.get('sleep_night')
    day = record.get('sleep_day')
    if night is None:
        txt = "😴 *خواب* \n\nهنوز اطلاعات خواب ثبت نکردی.\nبرای ثبت، دکمه *ثبت خواب* رو بزن."
    else:
        total = (night or 0) + (day or 0)
        status = "✅ خوب" if 7 <= total <= 9 else ("⚠️ کم" if total < 7 else "⚠️ زیاد")
        txt = (f"😴 *گزارش خواب*\n━━━━━━━━━━━━━━━━━━━━\n\n"
               f"🌙 شبانه: `{night}` ساعت\n"
               f"☀️ روزانه: `{day or 0}` ساعت\n"
               f"📊 مجموع: `{total}` ساعت ({status})\n\n"
               f"💡 توصیه: ۷ تا ۹ ساعت خواب باکیفیت در شب.\n"
               f"کم‌خوابی متابولیسم و اشتها رو مختل می‌کنه.")
    kb = ReplyKeyboardMarkup([
        [KeyboardButton("📝 ثبت خواب")],
        [KeyboardButton("🏠 منوی اصلی")],
    ], resize_keyboard=True)
    await update.message.reply_text(txt, parse_mode='Markdown', reply_markup=kb)

async def sleep_start(update, context):
    await update.message.reply_text(
        "🌙 چند ساعت خواب *شبانه* داشتی؟ (مثلاً 7.5)",
        parse_mode='Markdown', reply_markup=get_cancel_menu()
    )
    return SLEEP_HOURS

async def sleep_get_night(update, context):
    try:
        h = float(update.message.text.strip())
        if not 0 <= h <= 24:
            raise ValueError
        context.user_data['sleep_night'] = h
        await update.message.reply_text(
            "☀️ چند ساعت خواب *روزانه* داشتی؟ (اگه نداشتی 0 بنویس)",
            parse_mode='Markdown', reply_markup=get_cancel_menu()
        )
        return SLEEP_HOURS + 1
    except ValueError:
        await update.message.reply_text("⚠️ عدد بین ۰ تا ۲۴ وارد کن:", reply_markup=get_cancel_menu())
        return SLEEP_HOURS

async def sleep_get_day(update, context):
    try:
        h = float(update.message.text.strip())
        if not 0 <= h <= 24:
            raise ValueError
        user_id = str(update.effective_user.id)
        update_user_record(user_id, {
            'sleep_night': context.user_data['sleep_night'],
            'sleep_day': h
        })
        total = context.user_data['sleep_night'] + h
        await update.message.reply_text(
            f"✅ ثبت شد!\n\n🌙 شبانه: {context.user_data['sleep_night']}h\n"
            f"☀️ روزانه: {h}h\n📊 مجموع: {total}h",
            reply_markup=get_main_menu()
        )
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("⚠️ عدد بین ۰ تا ۲۴ وارد کن:", reply_markup=get_cancel_menu())
        return SLEEP_HOURS + 1

async def show_about(update, context):
    await update.message.reply_text(
        "📞 *درباره ما*\n━━━━━━━━━━━━━━━━━━━━\n\n"
        "این ربات بر اساس جداول *US DRI* ساخته شده.\n\n"
        "📊 محاسبات:\n"
        "• فرمول Mifflin-St Jeor\n"
        "• ضریب فعالیت\n"
        "• RDA ویتامین‌ها و املاح\n\n"
        "⚠️ این اعداد عمومی هستند. برای شرایط خاص با پزشک مشورت کن.",
        parse_mode='Markdown', reply_markup=get_main_menu()
    )

async def show_profile(update, context):
    user_id = str(update.effective_user.id)
    record = get_user_record(user_id)
    if not record.get('age'):
        await update.message.reply_text(
            "❌ هنوز پروفایلی نداری!\n\n"
            "اول *محاسبه جدید* انجام بده و بعدش *ذخیره در پروفایل* رو بزن.",
            reply_markup=get_main_menu(), parse_mode='Markdown'
        )
        return
    g = 'مرد' if record['gender'] == 'male' else 'زن'
    a = calc.db['activity_levels'][record['activity']]['label']
    text = (
        "👤 *پروفایل من*\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎂 سن: {record['age']} سال\n"
        f"⚧ جنسیت: {g}\n"
        f"📏 قد: {record['height_cm']} cm\n"
        f"⚖️ وزن: {record['weight_kg']} kg\n"
        f"🏃 فعالیت: {a}\n"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧮 محاسبه با این اطلاعات", callback_data="calc_from_profile")],
        [InlineKeyboardButton("🗑 حذف پروفایل", callback_data="delete_profile")],
    ])
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=kb)

async def show_history(update, context):
    user_id = str(update.effective_user.id)
    history = get_user_record(user_id).get('history', [])
    if not history:
        await update.message.reply_text(
            "📊 هنوز تاریخچه‌ای نداری.\nبعد از هر محاسبه خودکار ذخیره می‌شه.",
            reply_markup=get_main_menu()
        )
        return
    text = "📊 *۵ محاسبه آخر*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, h in enumerate(history[-5:][::-1], 1):
        text += f"*{i}.* {h['date']}\n"
        text += f"   کالری: `{h['tdee']:,}` | پروتئین: `{h['protein']}g`\n"
        text += f"   وزن: {h['weight']}kg | سن: {h['age']}\n\n"
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=get_main_menu())

async def show_water(update, context):
    await send_water_view(update, context)

async def send_water_view(update, context, edit=False):
    user_id = str(update.effective_user.id)
    record = get_user_record(user_id)
    today = datetime.now().strftime('%Y-%m-%d')
    if record.get('water_date') != today:
        update_user_record(user_id, {'water_date': today, 'water_ml': 0})
        cur = 0
    else:
        cur = record.get('water_ml', 0)
    target = 2500
    pct = min(100, int(cur / target * 100))
    filled = int(pct / 10)
    bar = "█" * filled + "░" * (10 - filled)
    text = (
        "💧 *ثبت آب روزانه*\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 امروز: {today}\n\n"
        f"🥤 مصرف شده: `{cur}` ml\n"
        f"🎯 هدف: `{target}` ml\n\n"
        f"`{bar}` {pct}%\n\n"
        "برای ثبت دکمه بزن:"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("+۲۵۰ml", callback_data="water_250"),
         InlineKeyboardButton("+۵۰۰ml", callback_data="water_500")],
        [InlineKeyboardButton("🔄 ریست", callback_data="water_reset")],
    ])
    if edit:
        await update.callback_query.edit_message_text(text, parse_mode='Markdown', reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=kb)


# ---------- Calculation Flow ----------
async def ask_age(update, context):
    context.user_data['calc'] = {}
    await update.message.reply_text(
        "🧮 *محاسبه جدید*\n\nلطفاً سن خود را وارد کنید (مثلاً 28):",
        parse_mode='Markdown', reply_markup=get_cancel_menu()
    )
    return AGE

async def get_age(update, context):
    try:
        age = int(update.message.text.strip())
        if not 1 <= age <= 120:
            raise ValueError
        context.user_data['calc']['age'] = age
        await update.message.reply_text("⚧ جنسیت خود را انتخاب کنید:", reply_markup=get_gender_menu())
        return GENDER
    except ValueError:
        await update.message.reply_text("⚠️ عدد معتبر بین ۱ تا ۱۲۰ وارد کن:", reply_markup=get_cancel_menu())
        return AGE

async def get_gender(update, context):
    text = update.message.text
    if text not in ['مرد', 'زن']:
        await update.message.reply_text("⚠️ «مرد» یا «زن» را انتخاب کن.")
        return GENDER
    context.user_data['calc']['gender'] = 'male' if text == 'مرد' else 'female'
    await update.message.reply_text(
        "📏 قد خود را به سانتی‌متر وارد کن (مثلاً 178):",
        parse_mode='Markdown', reply_markup=get_cancel_menu()
    )
    return HEIGHT

async def get_height(update, context):
    try:
        h = float(update.message.text.strip())
        if not 50 <= h <= 250:
            raise ValueError
        context.user_data['calc']['height_cm'] = h
        await update.message.reply_text(
            "⚖️ وزن خود را به کیلوگرم وارد کن (مثلاً 75):",
            parse_mode='Markdown', reply_markup=get_cancel_menu()
        )
        return WEIGHT
    except ValueError:
        await update.message.reply_text("⚠️ عدد معتبر بین ۵۰ تا ۲۵۰ وارد کن:", reply_markup=get_cancel_menu())
        return HEIGHT

async def get_weight(update, context):
    try:
        w = float(update.message.text.strip())
        if not 10 <= w <= 400:
            raise ValueError
        context.user_data['calc']['weight_kg'] = w
        await update.message.reply_text(
            "🏃 سطح فعالیت روزانه‌ات را انتخاب کن:", reply_markup=get_activity_menu()
        )
        return ACTIVITY
    except ValueError:
        await update.message.reply_text("⚠️ عدد معتبر بین ۱۰ تا ۴۰۰ وارد کن:", reply_markup=get_cancel_menu())
        return WEIGHT

async def get_activity(update, context):
    label = update.message.text
    key = None
    for k, v in calc.db['activity_levels'].items():
        if v['label'] == label:
            key = k
            break
    if not key:
        await update.message.reply_text("⚠️ از دکمه‌های نمایش داده‌شده انتخاب کن.")
        return ACTIVITY
    context.user_data['calc']['activity'] = key
    context.user_data['calc']['activity_label'] = label
    u = context.user_data['calc']
    if u['gender'] == 'female' and 14 <= u['age'] <= 50:
        await update.message.reply_text("🤰 وضعیت خود را انتخاب کن:", reply_markup=get_life_stage_menu())
        return LIFE_STAGE
    u['life_stage'] = 'normal'
    return await finalize(update, context)

async def get_life_stage(update, context):
    text = update.message.text
    mapping = {'عادی': 'normal', 'باردار': 'pregnancy', 'شیرده': 'lactation'}
    if text not in mapping:
        await update.message.reply_text("⚠️ از دکمه‌های نمایش داده‌شده انتخاب کن.")
        return LIFE_STAGE
    context.user_data['calc']['life_stage'] = mapping[text]
    return await finalize(update, context)

async def finalize(update, context):
    msg = await update.message.reply_text("⏳ در حال محاسبه...", reply_markup=ReplyKeyboardRemove())
    try:
        user = context.user_data['calc']
        report = calc.build_report(user)

        user_id = str(update.effective_user.id)
        history = get_user_record(user_id).get('history', [])
        history.append({
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'tdee': report['tdee_kcal'],
            'protein': report['macros']['protein_g'],
            'weight': user['weight_kg'],
            'age': user['age'],
        })
        history = history[-10:]
        update_user_record(user_id, {'history': history})

        context.user_data['last_user'] = user
        await msg.delete()

        full = format_report(report, user)

        # تقسیم هوشمند بر اساس خطوط
        if len(full) > 4000:
            chunks = []
            lines = full.split('\n')
            current = ""
            for line in lines:
                if len(current) + len(line) + 1 > 3800:
                    chunks.append(current)
                    current = line
                else:
                    current = (current + '\n' + line) if current else line
            if current:
                chunks.append(current)

            for i, c in enumerate(chunks):
                if i == len(chunks) - 1:
                    await update.message.reply_text(c, parse_mode='Markdown', reply_markup=get_result_inline())
                else:
                    await update.message.reply_text(c, parse_mode='Markdown')
        else:
            await update.message.reply_text(full, parse_mode='Markdown', reply_markup=get_result_inline())
    except Exception as e:
        logger.error(f"finalize error: {e}")
        await update.message.reply_text(f"❌ خطا: {e}", reply_markup=get_main_menu())
    return ConversationHandler.END

async def cancel(update, context):
    context.user_data.pop('calc', None)
    context.user_data.pop('food_cat', None)
    context.user_data.pop('food_sel', None)
    context.user_data.pop('sleep_night', None)
    try:
        await update.message.reply_text(
            "❌ لغو شد. به منوی اصلی برگشتی.",
            reply_markup=get_main_menu()
        )
    except Exception as e:
        logger.error(f"cancel error: {e}")
    return ConversationHandler.END

# ============================================================
# کنترل دسترسی
# ============================================================
async def check_access(update, context):
    """
    این تابع قبل از هر دستور اصلی چک می‌کنه کاربر مجاز هست یا نه.
    اگر نبود، پیام می‌ده و False برمی‌گردونه.
    """
    user_id = update.effective_user.id
    status = get_access_status(user_id)

    if status in ("trial", "subscription"):
        return True

    if status == "new":
        # کاربر جدید، پیشنهاد شروع trial
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🎁 شروع {TRIAL_HOURS} ساعت تست رایگان", callback_data="start_trial")]
        ])
        await update.message.reply_text(
            f"سلام! 👋\n\n"
            f"شما می‌توانید {TRIAL_HOURS} ساعت به صورت رایگان از تمام امکانات ربات استفاده کنید.\n"
            f"پس از پایان این مدت، برای ادامه استفاده نیاز به خرید اشتراک دارید.",
            reply_markup=keyboard
        )
        return False

    # status == "expired"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"💎 خرید اشتراک ({SUBSCRIPTION_PRICE // 100} {CURRENCY})", callback_data="buy_subscription")]
    ])
    await update.message.reply_text(
        "⛔ دوره تست رایگان شما به پایان رسیده است.\n\n"
        "برای ادامه استفاده از امکانات ربات، لطفاً اشتراک تهیه کنید.",
        reply_markup=keyboard
    )
    return False


async def show_subscription(update, context):
    """نمایش وضعیت اشتراک کاربر"""
    user_id = update.effective_user.id
    status = get_access_status(user_id)

    if status == "subscription":
        remaining = format_subscription_remaining(user_id)
        end = get_subscription_end(user_id)
        text = (
            "💎 *وضعیت اشتراک شما*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ *اشتراک فعال*\n"
            f"📅 تاریخ انقضا: `{end.strftime('%Y-%m-%d')}`\n"
            f"⏳ باقی‌مانده: `{remaining}`\n\n"
            "برای تمدید، روی دکمه زیر بزنید."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تمدید اشتراک", callback_data="buy_subscription")]
        ])
    elif status == "trial":
        remaining = format_trial_remaining(user_id)
        text = (
            "🎁 *دوره تست رایگان*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ *تست فعال*\n"
            f"⏳ باقی‌مانده: `{remaining}`\n\n"
            "پس از پایان این مدت، برای ادامه استفاده اشتراک تهیه کنید."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 خرید اشتراک", callback_data="buy_subscription")]
        ])
    elif status == "new":
        text = (
            "🎁 *خوش آمدید!*\n\n"
            f"شما می‌توانید {TRIAL_HOURS} ساعت رایگان از ربات استفاده کنید."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🎁 شروع {TRIAL_HOURS} ساعت تست", callback_data="start_trial")]
        ])
    else:  # expired
        text = (
            "⛔ *دوره تست شما به پایان رسیده*\n\n"
            "برای ادامه استفاده، اشتراک تهیه کنید."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💎 خرید اشتراک ({SUBSCRIPTION_PRICE // 100} {CURRENCY})", callback_data="buy_subscription")]
        ])

    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)


# ============================================================
# توابع پرداخت
# ============================================================
PAYMENT_PROVIDER_TOKEN = os.environ.get("PAYMENT_PROVIDER_TOKEN")

async def start_trial_callback(update, context):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    if not can_start_trial(user_id):
        await q.edit_message_text("❌ شما قبلاً از دوره تست استفاده کرده‌اید.")
        return
    end = start_trial(user_id)
    await q.edit_message_text(
        f"✅ *دوره تست رایگان شما فعال شد!*\n\n"
        f"⏳ مدت: {TRIAL_HOURS} ساعت\n"
        f"📅 پایان: `{end.strftime('%Y-%m-%d %H:%M')}`\n\n"
        "از منوی پایین شروع کنید 👇",
        parse_mode='Markdown',
        reply_markup=get_main_menu()
    )


async def send_invoice(update, context):
    """ارسال فاکتور برای خرید اشتراک"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    await context.bot.send_invoice(
        chat_id=user_id,
        title="اشتراک یک‌ماهه ربات تغذیه",
        description=f"دسترسی کامل به تمام امکانات ربات به مدت {SUBSCRIPTION_DAYS if False else 30} روز",
        payload=f"sub_{user_id}_{int(datetime.now().timestamp())}",
        provider_token=PAYMENT_PROVIDER_TOKEN,
        currency=CURRENCY,
        prices=[LabeledPrice("اشتراک ماهانه", SUBSCRIPTION_PRICE)],
        start_parameter="subscription",
    )


async def precheckout_callback(update, context):
    """تأیید نهایی قبل از پرداخت"""
    query = update.pre_checkout_query
    if not query.invoice_payload.startswith("sub_"):
        await query.answer(ok=False, error_message="خطایی رخ داد.")
    else:
        await query.answer(ok=True)


async def successful_payment_callback(update, context):
    """پرداخت موفق - فعال‌سازی اشتراک"""
    payment = update.message.successful_payment
    user_id = update.effective_user.id
    new_end = extend_subscription(user_id, days=30)
    await update.message.reply_text(
        f"✅ *پرداخت با موفقیت انجام شد!*\n\n"
        f"📅 اشتراک شما تا `{new_end.strftime('%Y-%m-%d')}` فعال شد.\n"
        f"از منوی پایین استفاده کنید 👇",
        parse_mode='Markdown',
        reply_markup=get_main_menu()
    )


# ---------- Callback Handler ----------
async def on_callback(update, context):
    q = update.callback_query
    try:
        await q.answer()
    except Exception as e:
        logger.error(f"answer error: {e}")

    data = q.data
    user_id = str(q.from_user.id)
    logger.info(f"Callback received: {data} from {user_id}")

    try:
        if data == "save_profile":
            u = context.user_data.get('last_user')
            if not u:
                await q.answer("❌ اطلاعاتی یافت نشد", show_alert=True)
                return
            update_user_record(user_id, {
                'age': u['age'], 'gender': u['gender'],
                'height_cm': u['height_cm'], 'weight_kg': u['weight_kg'],
                'activity': u['activity'], 'life_stage': u.get('life_stage', 'normal'),
            })
            # حذف دکمه‌ها از پیام قبلی
            try:
                await q.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            # پیام تایید + منوی اصلی
            await context.bot.send_message(
                chat_id=q.message.chat_id,
                text="✅ *در پروفایل ذخیره شد!*",
                parse_mode='Markdown',
                reply_markup=get_main_menu()
            )

        elif data == "recalc":
            try:
                await q.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            await context.bot.send_message(
                chat_id=q.message.chat_id,
                text="🔄 برای محاسبه جدید، روی دکمه *🧮 محاسبه جدید* در منوی پایین بزن.",
                parse_mode='Markdown',
                reply_markup=get_main_menu()
            )
        elif data == "show_suggest":
            await food_suggest(update, context)

        elif data == "main_menu":
            try:
                await q.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            await context.bot.send_message(
                chat_id=q.message.chat_id,
                text="🏠 منوی اصلی:",
                reply_markup=get_main_menu()
            )

        elif data == "delete_profile":
            d = load_user_data()
            if user_id in d:
                del d[user_id]
                save_user_data(d)
            try:
                await q.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            await context.bot.send_message(
                chat_id=q.message.chat_id,
                text="🗑 پروفایل حذف شد.",
                reply_markup=get_main_menu()
            )

        elif data == "calc_from_profile":
            rec = get_user_record(user_id)
            if not rec.get('age'):
                await q.answer("❌ پروفایلی یافت نشد", show_alert=True)
                return
            user = {
                'age': rec['age'], 'gender': rec['gender'],
                'height_cm': rec['height_cm'], 'weight_kg': rec['weight_kg'],
                'activity': rec['activity'],
                'activity_label': calc.db['activity_levels'][rec['activity']]['label'],
                'life_stage': rec.get('life_stage', 'normal'),
            }
            report = calc.build_report(user)
            context.user_data['last_user'] = user
            text = format_report(report, user)
            # تقسیم اگه بلند بود
            if len(text) > 4000:
                chunks = []
                lines = text.split('\n')
                current = ""
                for line in lines:
                    if len(current) + len(line) + 1 > 3800:
                        chunks.append(current)
                        current = line
                    else:
                        current = (current + '\n' + line) if current else line
                if current:
                    chunks.append(current)
                for i, c in enumerate(chunks):
                    if i == len(chunks) - 1:
                        await context.bot.send_message(chat_id=q.message.chat_id, text=c,
                            parse_mode='Markdown', reply_markup=get_result_inline())
                    else:
                        await context.bot.send_message(chat_id=q.message.chat_id, text=c, parse_mode='Markdown')
            else:
                await context.bot.send_message(chat_id=q.message.chat_id, text=text,
                    parse_mode='Markdown', reply_markup=get_result_inline())
            await context.bot.send_message(chat_id=q.message.chat_id, text="🏠 منوی اصلی:",
                reply_markup=get_main_menu())

        elif data.startswith("water_"):
            today = datetime.now().strftime('%Y-%m-%d')
            rec = get_user_record(user_id)
            if data == "water_reset":
                update_user_record(user_id, {'water_ml': 0, 'water_date': today})
            else:
                amt = int(data.split("_")[1])
                if rec.get('water_date') != today:
                    update_user_record(user_id, {'water_date': today, 'water_ml': amt})
                else:
                    update_user_record(user_id, {'water_ml': rec.get('water_ml', 0) + amt})
            await send_water_view(update, context, edit=True)

    except Exception as e:
        logger.error(f"Callback error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        try:
            await context.bot.send_message(
                chat_id=q.message.chat_id,
                text=f"❌ خطا: {e}"
            )
        except Exception:
            pass


# ---------- Main ----------
async def show_monthly(update, context):
    user_id = str(update.effective_user.id)
    record = get_user_record(user_id)
    diary = record.get('food_diary', {})
    if not diary:
        await update.message.reply_text("هنوز هیچ غذایی ثبت نکردی.", reply_markup=get_main_menu())
        return
    from datetime import datetime as dt
    now = dt.now()
    prefix = now.strftime('%Y-%m')
    month_days = {k: v for k, v in diary.items() if k.startswith(prefix)}
    if not month_days:
        await update.message.reply_text("این ماه هنوز چیزی ثبت نکردی.", reply_markup=get_main_menu())
        return
    def sum_kcal(items):
        total = 0
        for it in items:
            food = next((f for f in FOODS if f['id'] == it['id']), None)
            if food:
                total += food['per_100g']['calories'] * it['grams'] / 100
        return int(total)
    total_days = len(month_days)
    total_items = sum(len(v) for v in month_days.values())
    total_kcal = sum(sum_kcal(v) for v in month_days.values())
    avg_kcal = int(total_kcal / total_days) if total_days else 0
    sorted_days = sorted(month_days.items(), reverse=True)
    lines = []
    lines.append('📅 گزارش ماهانه')
    lines.append('=' * 18)
    lines.append('')
    lines.append('ماه: ' + prefix)
    lines.append('روزهای ثبت‌شده: ' + str(total_days))
    lines.append('کل آیتم‌ها: ' + str(total_items))
    lines.append('میانگین کالری روزانه: ' + str(avg_kcal) + ' کالری')
    lines.append('')
    lines.append('=' * 18)
    lines.append('')
    lines.append('📋 روزهای این ماه:')
    for day, items in sorted_days[:15]:
        kcal = sum_kcal(items)
        lines.append('')
        lines.append('▸ ' + day)
        lines.append('   ' + str(len(items)) + ' آیتم — ' + str(kcal) + ' کالری')
    if len(sorted_days) > 15:
        lines.append('')
        lines.append('... و ' + str(len(sorted_days) - 15) + ' روز دیگر')
    txt = chr(10).join(lines)
    await update.message.reply_text(txt, reply_markup=get_main_menu())


async def export_archive(update, context):
    import csv, io
    user_id = str(update.effective_user.id)
    record = get_user_record(user_id)
    diary = record.get('food_diary', {})
    if not diary:
        await update.message.reply_text("هنوز چیزی برای دانلود نداری.", reply_markup=get_main_menu())
        return
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(['تاریخ', 'نام غذا', 'مقدار', 'گرم', 'کالری'])
    sorted_days = sorted(diary.items(), reverse=True)
    for day, items in sorted_days:
        for it in items:
            food = next((f for f in FOODS if f['id'] == it['id']), None)
            if not food:
                continue
            kcal = int(food['per_100g']['calories'] * it['grams'] / 100)
            display = it.get('display', str(it['grams']) + 'g')
            writer.writerow([day, it['name'], display, round(it['grams'], 1), kcal])
    output.seek(0)
    now_str = datetime.now().strftime('%Y-%m-%d')
    fname = 'food_archive_' + now_str + '.csv'
    bio = io.BytesIO(output.getvalue().encode("utf-8"))
    bio.name = fname
    await update.message.reply_document(document=bio, filename=fname,
        caption="📥 آرشیو کامل غذاها (CSV) — قابل باز کردن در Excel")
    await update.message.reply_text("منوی اصلی:", reply_markup=get_main_menu())

# ============================================================
# ========== سیستم اشتراک و کنترل دسترسی =====================
# ============================================================

PAYMENT_PROVIDER_TOKEN = "توکن_درگاه_پرداخت_خودت"


async def access_gate(update, context):
    """
    این تابع به عنوان اولین handler اجرا می‌شه.
    اگه کاربر دسترسی نداشت، جلوی ادامه پردازش رو می‌گیره.
    """
    if not update.effective_user:
        return

    user_id = update.effective_user.id

    # --- مواردی که باید بدون بررسی رد شن ---
    if update.pre_checkout_query:
        return
    if update.message and update.message.successful_payment:
        return
    if update.callback_query:
        data = update.callback_query.data or ""
        if data in ("start_trial", "buy_subscription"):
            return

    text = update.effective_message.text if update.effective_message else ""
    if text.startswith("/start") or text in (BTN_HELP, BTN_ABOUT, BTN_SUBSCRIBE):
        return

    # --- حالا بررسی دسترسی ---
    status = get_access_status(user_id)

    if status in ("trial", "subscription"):
        return  # اجازه بده ادامه بده

    if status == "new":
        # کاربر جدید: پیشنهاد شروع trial
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🎁 شروع {TRIAL_HOURS} ساعت تست رایگان",
                                  callback_data="start_trial")]
        ])
        msg = (
            f"👋 خوش آمدید!\n\n"
            f"شما می‌توانید {TRIAL_HOURS} ساعت به صورت *رایگان* از تمام "
            f"امکانات ربات استفاده کنید.\n\n"
            "برای شروع، روی دکمه زیر بزنید:"
        )
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(
                msg, parse_mode='Markdown', reply_markup=keyboard)
        else:
            await update.message.reply_text(
                msg, parse_mode='Markdown', reply_markup=keyboard)
        raise ApplicationHandlerStop

    # status == "expired"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 خرید اشتراک", callback_data="buy_subscription")]
    ])
    msg = (
        "⛔ *دوره تست رایگان شما به پایان رسیده است*\n\n"
        "برای ادامه استفاده از امکانات ربات، لطفاً اشتراک تهیه کنید."
    )
    if update.callback_query:
        await update.callback_query.answer("دوره تست شما به پایان رسیده", show_alert=True)
        await update.callback_query.message.reply_text(
            msg, parse_mode='Markdown', reply_markup=keyboard)
    else:
        await update.message.reply_text(
            msg, parse_mode='Markdown', reply_markup=keyboard)
    raise ApplicationHandlerStop


async def show_subscription(update, context):
    """نمایش وضعیت اشتراک کاربر"""
    user_id = update.effective_user.id
    status = get_access_status(user_id)

    if status == "subscription":
        remaining = format_subscription_remaining(user_id)
        end = get_subscription_end(user_id)
        text = (
            "💎 *وضعیت اشتراک شما*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ *اشتراک فعال*\n"
            f"📅 انقضا: `{end.strftime('%Y-%m-%d')}`\n"
            f"⏳ باقی‌مانده: `{remaining}`\n\n"
            "برای تمدید روی دکمه زیر بزنید."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تمدید اشتراک", callback_data="buy_subscription")]
        ])
    elif status == "trial":
        remaining = format_trial_remaining(user_id)
        text = (
            "🎁 *دوره تست رایگان*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ *تست فعال*\n"
            f"⏳ باقی‌مانده: `{remaining}`\n\n"
            "پس از پایان این مدت، برای ادامه استفاده اشتراک تهیه کنید."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 خرید اشتراک", callback_data="buy_subscription")]
        ])
    elif status == "new":
        text = (
            "🎁 *خوش آمدید!*\n\n"
            f"شما می‌توانید {TRIAL_HOURS} ساعت رایگان از ربات استفاده کنید."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🎁 شروع {TRIAL_HOURS} ساعت تست",
                                  callback_data="start_trial")]
        ])
    else:  # expired
        text = (
            "⛔ *دوره تست شما به پایان رسیده*\n\n"
            "برای ادامه استفاده، اشتراک تهیه کنید."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 خرید اشتراک", callback_data="buy_subscription")]
        ])

    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)


async def start_trial_callback(update, context):
    """شروع دوره trial"""
    q = update.callback_query
    user_id = q.from_user.id
    if not can_start_trial(user_id):
        await q.answer("شما قبلاً از دوره تست استفاده کرده‌اید.", show_alert=True)
        return
    await q.answer()
    end = start_trial(user_id)
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    await context.bot.send_message(
        chat_id=q.message.chat_id,
        text=(
            f"✅ *دوره تست رایگان شما فعال شد!*\n\n"
            f"⏳ مدت: {TRIAL_HOURS} ساعت\n"
            f"📅 پایان: `{end.strftime('%Y-%m-%d %H:%M')}`\n\n"
            "از منوی پایین شروع کنید 👇"
        ),
        parse_mode='Markdown',
        reply_markup=get_main_menu()
    )


async def send_invoice(update, context):
    """ارسال فاکتور برای خرید اشتراک"""
    q = update.callback_query
    user_id = q.from_user.id
    if is_subscription_active(user_id):
        await q.answer("شما اشتراک فعال دارید.", show_alert=True)
        return
    await q.answer()
    try:
        await context.bot.send_invoice(
            chat_id=user_id,
            title="اشتراک یک‌ماهه ربات تغذیه",
            description="دسترسی کامل به تمام امکانات ربات به مدت ۳۰ روز",
            payload=f"sub_{user_id}_{int(datetime.now().timestamp())}",
            provider_token=PAYMENT_PROVIDER_TOKEN,
            currency=CURRENCY,
            prices=[LabeledPrice("اشتراک ماهانه", SUBSCRIPTION_PRICE)],
            start_parameter="subscription",
        )
    except Exception as e:
        logger.error(f"Invoice error: {e}")
        await q.message.reply_text(f"❌ خطا در ارسال فاکتور: {e}")


async def precheckout_callback(update, context):
    """تأیید نهایی قبل از پرداخت"""
    q = update.pre_checkout_query
    if q.invoice_payload.startswith("sub_"):
        await q.answer(ok=True)
    else:
        await q.answer(ok=False, error_message="خطای پرداخت.")


async def successful_payment_callback(update, context):
    """پرداخت موفق — فعال‌سازی اشتراک"""
    user_id = update.effective_user.id
    new_end = extend_subscription(user_id, days=30)
    await update.message.reply_text(
        f"✅ *پرداخت با موفقیت انجام شد!*\n\n"
        f"📅 اشتراک شما تا `{new_end.strftime('%Y-%m-%d')}` فعال شد.\n\n"
        "از منوی پایین استفاده کنید 👇",
        parse_mode='Markdown',
        reply_markup=get_main_menu()
    )

# ============================================================
# ============ پایان سیستم اشتراک ============================
# ============================================================


def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN not set!")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    cancel_filter = filters.Regex(f"^{BTN_CANCEL}$")

    # ============================================================
    # گام ۱: دروازه کنترل دسترسی (اول از همه اجرا می‌شه)
    # ============================================================
    app.add_handler(TypeHandler(Update, access_gate), group=-1)

    # ============================================================
    # گام ۲: Handlerهای پرداخت (باید بدون گیت اجرا بشن)
    # ============================================================
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    app.add_handler(CallbackQueryHandler(start_trial_callback, pattern="^start_trial$"))
    app.add_handler(CallbackQueryHandler(send_invoice, pattern="^buy_subscription$"))

    # ============================================================
    # گام ۳: دستور /start و دکمه‌های منو
    # ============================================================
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_SUBSCRIBE}$"), show_subscription))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_HELP}$"), show_help))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_ABOUT}$"), show_about))

    # ============================================================
    # گام ۴: ConversationHandlerها (محاسبه، غذا، خواب)
    # ============================================================
    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_CALCULATE}$"), ask_age)],
        states={
            AGE:        [MessageHandler(cancel_filter, cancel),
                         MessageHandler(filters.TEXT & ~filters.COMMAND, get_age)],
            GENDER:     [MessageHandler(cancel_filter, cancel),
                         MessageHandler(filters.TEXT & ~filters.COMMAND, get_gender)],
            HEIGHT:     [MessageHandler(cancel_filter, cancel),
                         MessageHandler(filters.TEXT & ~filters.COMMAND, get_height)],
            WEIGHT:     [MessageHandler(cancel_filter, cancel),
                         MessageHandler(filters.TEXT & ~filters.COMMAND, get_weight)],
            ACTIVITY:   [MessageHandler(cancel_filter, cancel),
                         MessageHandler(filters.TEXT & ~filters.COMMAND, get_activity)],
            LIFE_STAGE: [MessageHandler(cancel_filter, cancel),
                         MessageHandler(filters.TEXT & ~filters.COMMAND, get_life_stage)],
        },
        fallbacks=[MessageHandler(cancel_filter, cancel)],
        allow_reentry=True,
    )

    food_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("افزودن غذا"), food_add_start)],
        states={
            FOOD_CATEGORY: [MessageHandler(cancel_filter, cancel),
                            MessageHandler(filters.TEXT & ~filters.COMMAND, food_get_category)],
            FOOD_SELECT:   [MessageHandler(cancel_filter, cancel),
                            MessageHandler(filters.TEXT & ~filters.COMMAND, food_get_select)],
            FOOD_UNIT:     [MessageHandler(cancel_filter, cancel),
                            MessageHandler(filters.TEXT & ~filters.COMMAND, food_get_unit)],
            FOOD_GRAMS:    [MessageHandler(cancel_filter, cancel),
                            MessageHandler(filters.TEXT & ~filters.COMMAND, food_get_grams)],
        },
        fallbacks=[MessageHandler(cancel_filter, cancel)],
        allow_reentry=True,
        conversation_timeout=180,
    )

    sleep_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 ثبت خواب$"), sleep_start)],
        states={
            SLEEP_HOURS:     [MessageHandler(cancel_filter, cancel),
                              MessageHandler(filters.TEXT & ~filters.COMMAND, sleep_get_night)],
            SLEEP_HOURS + 1: [MessageHandler(cancel_filter, cancel),
                              MessageHandler(filters.TEXT & ~filters.COMMAND, sleep_get_day)],
        },
        fallbacks=[MessageHandler(cancel_filter, cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(food_conv)
    app.add_handler(sleep_conv)

    # ============================================================
    # گام ۵: دکمه‌های منو (مستقیم)
    # ============================================================
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_PROFILE}$"), show_profile))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_HISTORY}$"), show_history))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_WATER}$"), show_water))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_FOOD}$"), show_food_menu))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_SLEEP}$"), show_sleep))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_MONTHLY}$"), show_monthly))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_EXPORT}$"), export_archive))

    # دکمه‌های داخلی دفترچه غذا
    app.add_handler(MessageHandler(filters.Regex("^📊 مشاهده امروز$"), food_show_today))
    app.add_handler(MessageHandler(filters.Regex("^🗑 پاک کردن امروز$"), food_clear_today))
    app.add_handler(MessageHandler(filters.Regex("^پیشنهاد اصلاحی$"), food_suggest))
    app.add_handler(MessageHandler(filters.Regex("^🏠 منوی اصلی$"),
        lambda u, c: u.message.reply_text("🏠 منوی اصلی:", reply_markup=get_main_menu())))

    # ============================================================
    # گام ۶: Callbackهای inline عمومی
    # ============================================================
    app.add_handler(CallbackQueryHandler(on_callback))

    print("✅ ربات در حال اجراست...")
    app.run_polling()


if __name__ == '__main__':
    main()
