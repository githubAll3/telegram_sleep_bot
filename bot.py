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
    keyboard = [[InlineKeyboardButton(child['name'], callback_data=f'select_child_{child["id"]}')] for child in children]
    return InlineKeyboardMarkup(keyboard)

async def get_user_children_for_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    children = database.get_user_children(user_id)
    if not children:
        await update.message.reply_text("У вас нет детей. Добавьте ребенка командой /addchild <имя>", reply_markup=reply_keyboard)
        return None
    if len(children) == 1:
        return children[0]
    await update.message.reply_text("Выберите ребенка:", reply_markup=get_child_selection_keyboard(children))
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
        if action == 'start':
            await handle_start_with_child(update, context, child)
        elif action == 'sleep':
            await sleep_button_with_child(update, context, child)
        elif action == 'awake':
            await awake_button_with_child(update, context, child)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = None
    result = await get_user_children_for_selection(update, context)
    if result == 'awaiting_selection':
        context.user_data['pending_action'] = 'start'
    elif result:
        await handle_start_with_child(update, context, result)

async def handle_start_with_child(update: Update, context: ContextTypes.DEFAULT_TYPE, child):
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

    await update.message.reply_text(
        f"Новый день начат для {child['name']}! Предыдущий ночной сон: {night_sleep_str}",
        reply_markup=reply_keyboard
    )
    await update.message.reply_photo(photo=chart_buf, caption=f'Сон за последние 7 дней для {child["name"]}')
    chart_buf.close()

async def sleep_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = None
    result = await get_user_children_for_selection(update, context)
    if result == 'awaiting_selection':
        context.user_data['pending_action'] = 'sleep'
    elif result:
        await sleep_button_with_child(update, context, result)

async def sleep_button_with_child(update: Update, context: ContextTypes.DEFAULT_TYPE, child):
    current_day = database.get_current_day(child['id'])
    if not current_day:
        await update.message.reply_text(f"Сначала нажмите start для начала дня для {child['name']}.", reply_markup=reply_keyboard)
        return
    ongoing_session = database.get_ongoing_sleep_session(child['id'], current_day['id'])
    if ongoing_session:
        await update.message.reply_text(f"Ребенок {child['name']} уже спит! Сначала нажмите awake.", reply_markup=reply_keyboard)
        return
    database.add_sleep_session(child['id'], current_day['id'], get_utc_iso())
    logger.info(f"Sleep session started for child {child['name']}")
    await update.message.reply_text(f"Сон начат для {child['name']}. Хорошего сна!", reply_markup=reply_keyboard)

async def awake_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = None
    result = await get_user_children_for_selection(update, context)
    if result == 'awaiting_selection':
        context.user_data['pending_action'] = 'awake'
    elif result:
        await awake_button_with_child(update, context, result)

async def awake_button_with_child(update: Update, context: ContextTypes.DEFAULT_TYPE, child):
    user_id = update.effective_user.id
    current_day = database.get_current_day(child['id'])
    if not current_day:
        await update.message.reply_text(f"Сначала нажмите start для начала дня для {child['name']}.", reply_markup=reply_keyboard)
        return
    ongoing_session = database.get_ongoing_sleep_session(child['id'], current_day['id'])
    if ongoing_session:
        sleep_start_utc = datetime.fromisoformat(ongoing_session['sleep_start'])
        sleep_end_utc = datetime.now(timezone.utc)
        duration_minutes = int((sleep_end_utc - sleep_start_utc).total_seconds() / 60)
        database.close_sleep_session(ongoing_session['id'], sleep_end_utc.isoformat(), duration_minutes, 'day')
        night_min, day_min = database.get_day_sleep_totals(current_day['id'])
        total_min = night_min + day_min
        total_str = f"{total_min // 60}ч {total_min % 60}м"
        day_str = f"{day_min // 60}ч {day_min % 60}м"
        await update.message.reply_text(f"Дневной сон для {child['name']}: {day_str}. Итого за день: {total_str}", reply_markup=reply_keyboard)
    else:
        user_states[user_id] = f'awaiting_manual_sleep_{child["id"]}'
        cancel_keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton('Отмена', callback_data='cancel_manual_sleep')]]
        )
        await update.message.reply_text(
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
        await update.message.reply_text("Ошибка: ребенок не найден.", reply_markup=reply_keyboard)
        user_states[user_id] = None
        return
    current_day = database.get_current_day(child['id'])
    if not current_day:
        await update.message.reply_text(f"Сначала нажмите start для начала дня для {child['name']}.", reply_markup=reply_keyboard)
        user_states[user_id] = None
        return
    duration_minutes = parse_duration(update.message.text)
    if not duration_minutes:
        cancel_keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton('Отмена', callback_data='cancel_manual_sleep')]]
        )
        await update.message.reply_text("Неверный формат. Попробуйте еще раз (например: 1ч 30м, 90м, 1.5ч):", reply_markup=cancel_keyboard)
        return
    sleep_start_utc = get_utc_iso()
    session_id = database.add_sleep_session(child['id'], current_day['id'], sleep_start_utc)
    database.close_sleep_session(session_id, sleep_start_utc, duration_minutes, 'day')
    night_min, day_min = database.get_day_sleep_totals(current_day['id'])
    total_min = night_min + day_min
    total_str = f"{total_min // 60}ч {total_min % 60}м"
    day_str = f"{day_min // 60}ч {day_min % 60}м"
    user_states[user_id] = None
    await update.message.reply_text(f"Дневной сон для {child['name']}: {day_str}. Итого за день: {total_str}", reply_markup=reply_keyboard)

async def cancel_manual_sleep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user_states[user_id] = None
    await query.edit_message_text("Ввод отменен.")
    await query.answer()

async def get_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(f"Ваш Telegram ID: `{user_id}`", parse_mode='Markdown')

async def add_child(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Использование: /addchild <имя_ребенка>")
        return
    child_name = ' '.join(context.args)
    child_id = database.add_child(child_name, user_id)
    await update.message.reply_text(f"Ребенок '{child_name}' добавлен (ID: {child_id})", reply_markup=reply_keyboard)

async def share_child(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if len(context.args) != 2:
        await update.message.reply_text("Использование: /share <имя_ребенка> <telegram_user_id>")
        return
    child_name = context.args[0]
    try:
        shared_user_id = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Неверный Telegram ID. Используйте /get_user_id для получения ID.")
        return
    children = database.get_user_children(user_id)
    child = next((c for c in children if c['name'] == child_name and c['primary_user_id'] == user_id), None)
    if not child:
        await update.message.reply_text(f"Ребенок '{child_name}' не найден или вы не являетесь его владельцем.")
        return
    if database.share_child(child['id'], user_id, shared_user_id):
        await update.message.reply_text(f"Доступ к ребенку '{child_name}' предоставлен пользователю `{shared_user_id}`", parse_mode='Markdown')
    else:
        await update.message.reply_text(f"Ошибка: доступ уже предоставлен или ребенок не найден.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    user_id = update.effective_user.id
    user_states[user_id] = None
    if text == 'start':
        await start_command(update, context)
    elif text == 'sleep':
        await sleep_button(update, context)
    elif text == 'awake':
        await awake_button(update, context)

def main():
    database.init_db()
    application = Application.builder().token(config.BOT_TOKEN).build()

    application.add_handler(CommandHandler('start', start_command))
    application.add_handler(CommandHandler('get_user_id', get_user_id))
    application.add_handler(CommandHandler('addchild', add_child))
    application.add_handler(CommandHandler('share', share_child))
    application.add_handler(CallbackQueryHandler(handle_child_selection, pattern='^select_child_'))
    application.add_handler(CallbackQueryHandler(cancel_manual_sleep, pattern='^cancel_manual_sleep$'))
    application.add_handler(MessageHandler(filters.Text(['start', 'sleep', 'awake']) & filters.ChatType.PRIVATE, button_handler))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.Text(['start', 'sleep', 'awake']), handle_manual_sleep_input))

    logger.info("Bot started")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
