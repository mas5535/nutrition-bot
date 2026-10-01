import os
from telegram.request import HTTPXRequest
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# فرض بر این است که فایل nutrition_calculator.py و nutrition_db.json در همان پوشه هستند
from nutrition_calculator import NutritionCalculator

# تنظیم لاگ‌ها برای دیدن خطاها
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# مراحل گفتگو
AGE, GENDER, HEIGHT, WEIGHT, ACTIVITY = range(5)

# توکن ربات خود را اینجا قرار بده
BOT_TOKEN = os.environ.get("BOT_TOKEN")

calc = NutritionCalculator("nutrition_db.json")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام! 👋\n"
        "من ربات محاسبه نیازهای تغذیه‌ای هستم.\n"
        "لطفاً سن خود را به سال وارد کنید (مثلاً ۲۵):"
    )
    return AGE

async def get_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        age = int(update.message.text)
        if not (1 <= age <= 120): raise ValueError
        context.user_data['age'] = age
        reply_keyboard = [['مرد', 'زن']]
        await update.message.reply_text(
            "جنسیت خود را انتخاب کنید:",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return GENDER
    except ValueError:
        await update.message.reply_text("لطفاً یک عدد معتبر بین ۱ تا ۱۲۰ وارد کنید:")
        return AGE

async def get_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gender_text = update.message.text
    if gender_text not in ['مرد', 'زن']:
        await update.message.reply_text("لطفاً یکی از گزینه‌های 'مرد' یا 'زن' را انتخاب کنید.")
        return GENDER
    context.user_data['gender'] = 'male' if gender_text == 'مرد' else 'female'
    await update.message.reply_text("قد خود را به سانتی‌متر وارد کنید (مثلاً ۱۷۵):")
    return HEIGHT

async def get_height(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        height = float(update.message.text)
        if not (50 <= height <= 250): raise ValueError
        context.user_data['height'] = height
        await update.message.reply_text("وزن خود را به کیلوگرم وارد کنید (مثلاً ۷۰):")
        return WEIGHT
    except ValueError:
        await update.message.reply_text("لطفاً یک عدد معتبر بین ۵۰ تا ۲۵۰ وارد کنید:")
        return HEIGHT

async def get_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        weight = float(update.message.text)
        if not (10 <= weight <= 400): raise ValueError
        context.user_data['weight'] = weight
        
        # دکمه‌های سطح فعالیت
        activity_keys = list(calc.db['activity_levels'].keys())
        activity_labels = [calc.db['activity_levels'][k]['label'] for k in activity_keys]
        
        # ساخت دکمه‌ها به صورت دو ستونه
        keyboard = []
        for i in range(0, len(activity_labels), 2):
            row = activity_labels[i:i+2]
            keyboard.append(row)
            
        await update.message.reply_text(
            "سطح فعالیت روزانه خود را انتخاب کنید:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return ACTIVITY
    except ValueError:
        await update.message.reply_text("لطفاً یک عدد معتبر بین ۱۰ تا ۴۰۰ وارد کنید:")
        return WEIGHT

async def get_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    activity_label = update.message.text
    # پیدا کردن کلید متناظر با برچسب
    activity_key = None
    for key, value in calc.db['activity_levels'].items():
        if value['label'] == activity_label:
            activity_key = key
            break
            
    if not activity_key:
        await update.message.reply_text("لطفاً یکی از گزینه‌های نمایش داده شده را انتخاب کنید.")
        return ACTIVITY

    user_data = context.user_data
    user = {
        "age": user_data['age'],
        "gender": user_data['gender'],
        "height_cm": user_data['height'],
        "weight_kg": user_data['weight'],
        "activity": activity_key,
        "activity_label": activity_label,
        "life_stage": "normal"
    }

    # ارسال پیام در حال محاسبه
    processing_msg = await update.message.reply_text("در حال محاسبه نیازهای شما... ⏳")

    try:
        report = calc.build_report(user)
        m = report['macros']
        
        # ساخت متن گزارش
        text = "📊 **گزارش نیازهای تغذیه‌ای روزانه شما**\n\n"
        text += f"🔥 **انرژی و درشت‌مغذی‌ها**\n"
        text += f"• کالری کل روزانه: {report['tdee_kcal']:,} کالری\n"
        text += f"• پروتئین: {m['protein_g']} گرم\n"
        text += f"• چربی: {m['fat_g']} گرم\n"
        text += f"• کربوهیدرات: {m['carb_g']} گرم\n"
        text += f"• فیبر: {m['fiber_g']} گرم\n"
        text += f"• آب: {m['water_l']} لیتر\n\n"
        
        text += "💊 **ریزمغذی‌ها (منابع غذایی پیشنهادی)**\n"
        for n in report['nutrients']:
            text += f"\n▸ **{n['name']}**: {n['required']} {n['unit']}\n"
            for fs in n['food_suggestions']:
                text += f"  • {fs['food']}: ~{fs['grams_needed']} گرم\n"
        
        text += "\n⚠️ این اعداد عمومی هستند. برای شرایط خاص با پزشک مشورت کنید."

        # حذف پیام "در حال محاسبه"
        await processing_msg.delete()
        
        # ارسال گزارش نهایی
        await update.message.reply_text(text, parse_mode='Markdown')
        
    except Exception as e:
        logging.error(f"Error building report: {e}")
        await update.message.reply_text("متأسفانه خطایی رخ داد. لطفاً دوباره تلاش کنید.")

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("عملیات لغو شد.")
    return ConversationHandler.END

def main():
    # تنظیم پروکسی با پورت HTTP سایفون
    request = HTTPXRequest(proxy_url="socks5://127.0.0.1:1080")
    
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .request(request)
        .get_updates_request(request)
        .build()
    )

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_age)],
            GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_gender)],
            HEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_height)],
            WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_weight)],
            ACTIVITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_activity)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    app.add_handler(conv_handler)
    print("ربات در حال اجراست...")
    app.run_polling()

if __name__ == '__main__':
    main()