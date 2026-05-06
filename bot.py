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
    text = text.lower().strip()
    if not text or text.startswith('-'):
        return None
    total_minutes = 0
    hour_matches = re.findall(r'(\d+\.?\d*)\s*(?:ч|h)', text)
    for match in hour_matches:
        val = float(match)
        if val < 0:
            return None
        total_minutes += val * 60
    minute_matches = re.findall(r'(\d+\.?\d*)\s*(?:м|m)', text)
    for match in minute_matches:
        val = float(match)
        if val < 0:
            return None
        total_minutes += val
    if not hour_matches and not minute_matches:
        try:
            val = float(text)
            if val < 0:
                return None
            total_minutes = val
        except ValueError:
            return None
    return int(total_minutes) if total_minutes > 0 else None

def get_utc_iso():
    return datetime.now(timezone.utc).isoformat()

reply_keyboard = ReplyKeyboardMarkup(
    [['sleep', 'awake', 'start']],
    resize_keyboard=True,
    one_time_keyboard=False
)

def get_child_selection_keyboard(children):
    keyboard = [[InlineKeyboardButton(child['name'], callback_data=f"select_child_{child['id']}")] for child in children]
    return InlineKeyboardMarkup(keyboard)

async def get_children_for_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    children = database.get_user_children(user_id)
    if not children:
        await update.effective_message.reply_text("У вас нет детей. Добавьте ребенка командой /addchild <имя>")
        return None
    if len(children) == 1:
        return children[0]
    await update.effective_message.reply_text("Выберите ребенка:", reply_markup=get_child_selection_keyboard(children))
    return 'awaiting_selection'

async def handle_child_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    data = query.data
    if not data.startswith('select_child_'):
        return

    child_id = int(data.split('_')[-1])
    child = database.get_child_by_id(child_id, user_id)
    if not child:
        await query.edit_message_text("Ошибка: ребенок не найден или нет доступа.")
        return

    await query.edit_message_text(f"Выбран ребенок: {child['name']}")

    if 'pending_action' in context.user_data:
        action = context.user_data.pop('pending_action')
        msg = query.message
        if action == 'start':
            await handle_start_with_child(msg, child)
        elif action == 'sleep':
            await sleep_with_child(msg, child)
        elif action == 'awake':
            await awake_with_child(msg, child)

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("handle_start called")
    user_id = update.effective_user.id
    user_states[user_id] = None
    result = await get_children_for_selection(update, context)
    if result == 'awaiting_selection':
        context.user_data['pending_action'] = 'start'
    elif result:
        await handle_start_with_child(update.effective_message, result)

async def handle_start_with_child(msg, child):
    current_day = database.get_current_day(child['id'])
    night_sleep_str = "0ч 0м"
    if current_day:
        ongoing_session = database.get_ongoing_sleep_session(child['id'], current_day['id'])
        if ongoing_session:
            sleep_start_utc = datetime.fromisoformat(ongoing_session['sleep_start'])
            sleep_end_utc = datetime.now(timezone.utc)
            duration_minutes = int((sleep_end_utc - sleep_start_utc).total_seconds() / 60)
            database.close_sleep_session(ongoing_session['id'], sleep_end_utc.isoformat(), duration_minutes, 'night')
            night_sleep_str = f"{duration_minutes // 60}ч {duration_minutes % 60}м"

    database.create_day(child['id'], get_utc_iso())
    logger.info(f"New day started for child {child['name']}")

    sleep_data = database.get_7_day_sleep_data(child['id'])
    chart_buf = plot.generate_sleep_chart(sleep_data, child['name'])

    await msg.reply_text(
        f"Новый день начат для {child['name']}! Предыдущий ночной сон: {night_sleep_str}",
        reply_markup=reply_keyboard
    )
    await msg.reply_photo(photo=chart_buf, caption=f"Сон за последние 7 дней для {child['name']}")
    chart_buf.close()

async def handle_sleep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("handle_sleep called")
    user_id = update.effective_user.id
    user_states[user_id] = None
    result = await get_children_for_selection(update, context)
    if result == 'awaiting_selection':
        context.user_data['pending_action'] = 'sleep'
    elif result:
        await sleep_with_child(update.effective_message, result)

async def sleep_with_child(msg, child):
    current_day = database.get_current_day(child['id'])
    if not current_day:
        await msg.reply_text(f"Сначала нажмите start для начала дня для {child['name']}.", reply_markup=reply_keyboard)
        return
    ongoing_session = database.get_ongoing_sleep_session(child['id'], current_day['id'])
    if ongoing_session:
        await msg.reply_text(f"Ребенок {child['name']} уже спит! Сначала нажмите awake.", reply_markup=reply_keyboard)
        return
    database.add_sleep_session(child['id'], current_day['id'], get_utc_iso())
    await msg.reply_text(f"Сон начат для {child['name']}. Хорошего сна!", reply_markup=reply_keyboard)

async def handle_awake(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = None
    result = await get_children_for_selection(update, context)
    if result == 'awaiting_selection':
        context.user_data['pending_action'] = 'awake'
    elif result:
        await awake_with_child(update.effective_message, result)

async def awake_with_child(msg, child):
    user_id = msg.chat_id
    current_day = database.get_current_day(child['id'])
    if not current_day:
        await msg.reply_text(f"Сначала нажмите start для начала дня для {child['name']}.", reply_markup=reply_keyboard)
        return
    ongoing_session = database.get_ongoing_sleep_session(child['id'], current_day['id'])
    if ongoing_session:
        sleep_start_utc = datetime.fromisoformat(ongoing_session['sleep_start'])
        sleep_end_utc = datetime.now(timezone.utc)
        duration_minutes = int((sleep_end_utc - sleep_start_utc).total_seconds() / 60)
        database.close_sleep_session(ongoing_session['id'], sleep_end_utc.isoformat(), duration_minutes, 'day')
        night_min, day_min = database.get_day_sleep_totals(current_day['id'])
        total_min = night_min + day_min
        duration_str = f"{duration_minutes // 60}ч {duration_minutes % 60}м"
        total_str = f"{total_min // 60}ч {total_min % 60}м"
        # day_str = f"{day_min // 60}ч {day_min % 60}м"
        await msg.reply_text(f"{child['name']} проспал: {duration_str}. Итого за день: {total_str}", reply_markup=reply_keyboard)
    else:
        user_states[user_id] = f"awaiting_manual_sleep_{child['id']}"
        cancel_keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton('Отмена', callback_data='cancel_manual_sleep')]]
        )
        await msg.reply_text(
            f"Нет активного сна для {child['name']}. Введите продолжительность дневного сна для учета (например: 1ч 30м, 90м, 1.5ч):",
            reply_markup=cancel_keyboard
        )

async def handle_manual_sleep_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    if not state or not state.startswith('awaiting_manual_sleep_'):
        return
    child_id = int(state.split('_')[-1])
    child = database.get_child_by_id(child_id, user_id)
    if not child:
        await update.effective_message.reply_text("Ошибка: ребенок не найден.", reply_markup=reply_keyboard)
        user_states[user_id] = None
        return
    current_day = database.get_current_day(child['id'])
    if not current_day:
        await update.effective_message.reply_text(f"Сначала нажмите start для начала дня для {child['name']}.", reply_markup=reply_keyboard)
        user_states[user_id] = None
        return
    duration_minutes = parse_duration(update.message.text)
    if not duration_minutes:
        cancel_keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton('Отмена', callback_data='cancel_manual_sleep')]]
        )
        await update.effective_message.reply_text("Неверный формат. Попробуйте еще раз (например: 1ч 30м, 90м, 1.5ч):", reply_markup=cancel_keyboard)
        return
    sleep_start_utc = get_utc_iso()
    session_id = database.add_sleep_session(child['id'], current_day['id'], sleep_start_utc)
    database.close_sleep_session(session_id, sleep_start_utc, duration_minutes, 'day')
    night_min, day_min = database.get_day_sleep_totals(current_day['id'])
    total_min = night_min + day_min
    total_str = f"{total_min // 60}ч {total_min % 60}м"
    day_str = f"{day_min // 60}ч {day_min % 60}м"
    user_states[user_id] = None
    await update.effective_message.reply_text(f"Дневной сон для {child['name']}: {day_str}. Итого за день: {total_str}", reply_markup=reply_keyboard)

async def cancel_manual_sleep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user_states[user_id] = None
    await query.edit_message_text("Ввод отменен.")
    await query.answer()

async def get_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.effective_message.reply_text(f"Ваш Telegram ID: `{user_id}`", parse_mode='Markdown')

async def add_child(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.effective_message.reply_text("Использование: /addchild <имя_ребенка>")
        return
    child_name = ' '.join(context.args)
    child_id = database.add_child(child_name, user_id)
    await update.effective_message.reply_text(f"Ребенок '{child_name}' добавлен (ID: {child_id})", reply_markup=reply_keyboard)

async def share_child(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if len(context.args) != 2:
        await update.effective_message.reply_text("Использование: /share <имя_ребенка> <telegram_user_id>")
        return
    child_name = context.args[0]
    try:
        shared_user_id = int(context.args[1])
    except ValueError:
        await update.effective_message.reply_text("Неверный Telegram ID. Используйте /get_user_id для получения ID.")
        return
    children = database.get_user_children(user_id)
    child = next((c for c in children if c['name'] == child_name and c['primary_user_id'] == user_id), None)
    if not child:
        await update.effective_message.reply_text(f"Ребенок '{child_name}' не найден или вы не являетесь его владельцем.")
        return
    if database.share_child(child['id'], user_id, shared_user_id):
        await update.effective_message.reply_text(f"Доступ к ребенку '{child_name}' предоставлен пользователю `{shared_user_id}`", parse_mode='Markdown')
    else:
        await update.effective_message.reply_text(f"Ошибка: доступ уже предоставлен или ребенок не найден.")

def is_button_text(text: str) -> bool:
    return text.lower() in ['start', 'sleep', 'awake']

async def unified_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text
    user_id = update.effective_user.id

    # Check if user is in manual sleep input mode
    state = user_states.get(user_id)
    if state and state.startswith('awaiting_manual_sleep_'):
        await handle_manual_sleep_input(update, context)
        return

    # Check if it's a button press
    if is_button_text(text):
        if text.lower() == 'start':
            await handle_start(update, context)
        elif text.lower() == 'sleep':
            await handle_sleep(update, context)
        elif text.lower() == 'awake':
            await handle_awake(update, context)
        return


def main():
    database.init_db()
    app = Application.builder().token(config.BOT_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler('start', handle_start))
    app.add_handler(CommandHandler('get_user_id', get_user_id))
    app.add_handler(CommandHandler('addchild', add_child))
    app.add_handler(CommandHandler('share', share_child))

    # Callback query handlers
    app.add_handler(CallbackQueryHandler(handle_child_selection, pattern='^select_child_'))
    app.add_handler(CallbackQueryHandler(cancel_manual_sleep, pattern='^cancel_manual_sleep$'))

    # Unified text handler - handles both buttons and manual input
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT, unified_text_handler))

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
