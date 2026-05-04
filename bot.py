import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import re

import config
import database
import plot

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

user_states = {}

def parse_duration(text: str):
    text = text.lower()
    total_minutes = 0
    hour_matches = re.findall(r'(\d+\.?\d*)\s*(?:ч|h)', text)
    for match in hour_matches:
        total_minutes += float(match) * 60
    minute_matches = re.findall(r'(\d+\.?\d*)\s*(?:м|m)', text)
    for match in minute_matches:
        total_minutes += float(match)
    if not hour_matches and not minute_matches:
        try:
            total_minutes = float(text.strip())
        except ValueError:
            return None
    return int(total_minutes) if total_minutes > 0 else None

reply_keyboard = ReplyKeyboardMarkup(
    [['sleep', 'awake', 'start']],
    resize_keyboard=True,
    one_time_keyboard=False
)

cancel_keyboard = InlineKeyboardMarkup(
    [[InlineKeyboardButton('Отмена', callback_data='cancel_manual_sleep')]]
)

def get_utc_iso():
    return datetime.now(timezone.utc).isoformat()

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = None
    await handle_start(update, context)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    user_id = update.effective_user.id
    user_states[user_id] = None
    if text == 'start':
        await handle_start(update, context)
    elif text == 'sleep':
        await sleep_button(update, context)
    elif text == 'awake':
        await awake_button(update, context)

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current_day = database.get_current_day()
    night_sleep_str = "0ч 0м"
    if current_day:
        ongoing_session = database.get_ongoing_sleep_session(current_day['id'])
        if ongoing_session:
            sleep_start_utc = datetime.fromisoformat(ongoing_session['sleep_start'])
            sleep_end_utc = datetime.now(timezone.utc)
            duration_minutes = int((sleep_end_utc - sleep_start_utc).total_seconds() / 60)
            database.close_sleep_session(ongoing_session['id'], sleep_end_utc.isoformat(), duration_minutes, 'night')
            night_sleep_str = f"{duration_minutes // 60}ч {duration_minutes % 60}м"

    new_day_id = database.create_day(get_utc_iso())
    logger.info(f"New day started: {new_day_id}")

    sleep_data = database.get_7_day_sleep_data()
    chart_buf = plot.generate_sleep_chart(sleep_data)

    await update.message.reply_text(
        f"Новый день начат! Предыдущий ночной сон: {night_sleep_str}",
        reply_markup=reply_keyboard
    )
    await update.message.reply_photo(photo=chart_buf, caption='Сон за последние 7 дней')
    chart_buf.close()

async def sleep_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = None
    current_day = database.get_current_day()
    if not current_day:
        await update.message.reply_text("Сначала нажмите Start для начала дня.", reply_markup=reply_keyboard)
        return
    ongoing_session = database.get_ongoing_sleep_session(current_day['id'])
    if ongoing_session:
        await update.message.reply_text("Ребенок уже спит! Сначала нажмите Awake.", reply_markup=reply_keyboard)
        return
    session_id = database.add_sleep_session(current_day['id'], get_utc_iso())
    logger.info(f"Sleep session started: {session_id}")
    await update.message.reply_text("Сон начат. Хорошего сна!", reply_markup=reply_keyboard)

async def awake_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = None
    current_day = database.get_current_day()
    if not current_day:
        await update.message.reply_text("Сначала нажмите Start для начала дня.", reply_markup=reply_keyboard)
        return
    ongoing_session = database.get_ongoing_sleep_session(current_day['id'])
    if ongoing_session:
        sleep_start_utc = datetime.fromisoformat(ongoing_session['sleep_start'])
        sleep_end_utc = datetime.now(timezone.utc)
        duration_minutes = int((sleep_end_utc - sleep_start_utc).total_seconds() / 60)
        database.close_sleep_session(ongoing_session['id'], sleep_end_utc.isoformat(), duration_minutes, 'day')
        night_min, day_min = database.get_day_sleep_totals(current_day['id'])
        total_min = night_min + day_min
        total_str = f"{total_min // 60}ч {total_min % 60}м"
        day_str = f"{day_min // 60}ч {day_min % 60}м"
        await update.message.reply_text(f"Дневной сон: {day_str}. Итого за день: {total_str}", reply_markup=reply_keyboard)
    else:
        user_states[user_id] = 'awaiting_manual_sleep'
        await update.message.reply_text(
            "Нет активного сна. Введите продолжительность дневного сна для учета (например: 1ч 30м, 90м, 1.5ч):",
            reply_markup=cancel_keyboard
        )

async def handle_manual_sleep_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    if state != 'awaiting_manual_sleep':
        return
    current_day = database.get_current_day()
    if not current_day:
        await update.message.reply_text("Сначала нажмите Start для начала дня.", reply_markup=reply_keyboard)
        user_states[user_id] = None
        return
    duration_minutes = parse_duration(update.message.text)
    if not duration_minutes:
        await update.message.reply_text("Неверный формат. Попробуйте еще раз (например: 1ч 30м, 90м, 1.5ч):", reply_markup=cancel_keyboard)
        return
    sleep_start_utc = get_utc_iso()
    session_id = database.add_sleep_session(current_day['id'], sleep_start_utc)
    database.close_sleep_session(session_id, sleep_start_utc, duration_minutes, 'day')
    night_min, day_min = database.get_day_sleep_totals(current_day['id'])
    total_min = night_min + day_min
    total_str = f"{total_min // 60}ч {total_min % 60}м"
    day_str = f"{day_min // 60}ч {day_min % 60}м"
    user_states[user_id] = None
    await update.message.reply_text(f"Дневной сон: {day_str}. Итого за день: {total_str}", reply_markup=reply_keyboard)

async def cancel_manual_sleep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user_states[user_id] = None
    await query.edit_message_text("Ввод отменен.")
    await query.answer()

def main():
    database.init_db()
    application = Application.builder().token(config.BOT_TOKEN).build()

    application.add_handler(CommandHandler('start', start_command))
    application.add_handler(CallbackQueryHandler(cancel_manual_sleep, pattern='^cancel_manual_sleep$'))
    application.add_handler(MessageHandler(filters.Text(['start', 'sleep', 'awake']) & filters.ChatType.PRIVATE, button_handler))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.Text(['start', 'sleep', 'awake']), handle_manual_sleep_input))

    logger.info("Bot started")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
