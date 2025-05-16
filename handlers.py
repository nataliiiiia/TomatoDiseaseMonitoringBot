import uuid
import io
import qrcode
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery
)
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
)
from db import (
    create_user_if_not_exists,
    get_user_db_id,
    bind_robot_to_user,
    get_robot_id_for_user,
    get_all_plants,
    add_plant,
    delete_plant,
    set_qr_message_id,
    get_qr_message_id,
    get_scan_history,
    get_scan_timestamps,
    get_scans_by_timestamp
)

SPECIES, LOCATION, BIND_ROBOT = range(3)

def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("Додати новий томат", callback_data="add_plant")],
        [InlineKeyboardButton("Мої томати", callback_data="view_plants")],
        [InlineKeyboardButton("Перегляд історії сканувань", callback_data="history")],
    ]
    return InlineKeyboardMarkup(keyboard)

def plant_list_menu():
    keyboard = [
        [
            InlineKeyboardButton("⬅️Назад в меню", callback_data="return_menu"),
            InlineKeyboardButton("Видалити томат", callback_data="delete_plant")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def show_plants_actions(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    user_db_id: str) -> bool:
    plants = get_all_plants(user_db_id)
    if not plants:
        await query.message.reply_text("У Вас більше немає доданих томатів.",
            reply_markup=get_main_menu())
        return False

    for p in plants:
        qr_btn = InlineKeyboardButton("Показати QR-код томата",
            callback_data=f"view_qr:{p['plant_id']}")
        await query.message.reply_text(
            f"Вид: {p['species']}\n"
            f"Локація: {p['location']}\n",
            reply_markup=InlineKeyboardMarkup([[qr_btn]]))

    await query.message.reply_text("Що ви хочете зробити з вашими томатами?",
        reply_markup=plant_list_menu())
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = str(update.effective_user.id)
    username = update.effective_user.username or ""
    user_db_id = create_user_if_not_exists(telegram_id, username)
    robot_id = get_robot_id_for_user(user_db_id)

    if not robot_id:
        kb = [[InlineKeyboardButton("Прив'язати робота", callback_data="bind_robot")]]
        await update.message.reply_text("Для початку роботи необхідно прив'язати робоплатформу.",
            reply_markup=InlineKeyboardMarkup(kb))
        return
    await update.message.reply_text("Вітаю! Це TomatoDiseaseDetector бот. Оберіть дію:",
        reply_markup=get_main_menu())

async def start_bind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Введіть ROBOT_ID, який зазначено в інструкції:")
    return BIND_ROBOT

async def bind_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = str(update.effective_user.id)
    robot_id = update.message.text.strip()
    user_db_id = get_user_db_id(telegram_id)
    if not user_db_id:
        await update.message.reply_text("Спочатку виконайте /start")
        return ConversationHandler.END

    bind_robot_to_user(user_db_id, robot_id)
    await update.message.reply_text(f"Робоплатформу {robot_id} успішно прив’язано!",
        reply_markup=get_main_menu())
    return ConversationHandler.END

async def add_plant_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.message.edit_text("Введіть назву виду Вашого томата:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Скасувати", callback_data="cancel_add")]]))
    return SPECIES

async def species_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['species'] = update.message.text
    await update.message.reply_text("Введіть локацію посадки (наприклад, Ряд 1 Позиція 1, як Вам зручніше):",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Скасувати", callback_data="cancel_add")]]))
    return LOCATION

async def location_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = str(update.effective_user.id)
    user_db_id = get_user_db_id(telegram_id)
    species = context.user_data["species"]
    location = update.message.text
    plant_id = str(uuid.uuid4())
    add_plant(user_db_id, plant_id, species, location)
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(plant_id)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    qr_msg = await update.message.reply_photo(
        photo=buf,
        caption=(
            f"Новий томат додано!\n"
            f"Вид: {species}\n"
            f"Локація: {location}\n"
            "Роздрукуйте цей QR-код для ідентифікації робоплатформою."))
    set_qr_message_id(plant_id, qr_msg.message_id)
    await update.message.reply_text("Виберіть дію:", reply_markup=get_main_menu())
    return ConversationHandler.END

async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("Оберіть дію:",
        reply_markup=get_main_menu())
    context.user_data.clear()
    return ConversationHandler.END

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    telegram_id = str(update.effective_user.id)
    user_db_id = get_user_db_id(telegram_id)
    robot_id = get_robot_id_for_user(user_db_id)

    if query.data == "add_plant":
        return await add_plant_start(update, context)

    elif query.data == "view_plants":
        await show_plants_actions(query, context, user_db_id)
        return

    elif query.data.startswith("view_qr:"):
        plant_id = query.data.split(":", 1)[1]
        qr_msg_id = get_qr_message_id(plant_id)
        chat_id = query.message.chat_id
        plants = get_all_plants(user_db_id)
        plant = next((p for p in plants if p['plant_id'] == plant_id), None)
        if plant and qr_msg_id:
            caption = (
            f"Вид: {plant['species']}\n"
            f"Локація: {plant['location']}\n"
            "Роздрукуйте цей QR-код для ідентифікації робоплатформою.")
        await context.bot.copy_message(
            chat_id=chat_id,
            from_chat_id=chat_id,
            message_id=qr_msg_id,
            caption=caption)
        await query.message.reply_text("Оберіть дію:", reply_markup=get_main_menu())
        return

    elif query.data == "return_menu":
        await query.message.edit_text("Оберіть дію:", reply_markup=get_main_menu())
        return

    elif query.data == "delete_plant":
        plants = get_all_plants(user_db_id)
        buttons = [
        [InlineKeyboardButton(f"{p['species']} ({p['location']})",
                              callback_data=f"prompt_delete:{p['plant_id']}")] for p in plants]
        buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="delete_back")])
        menu_msg = await query.message.edit_text("Оберіть рослину для видалення:", reply_markup=InlineKeyboardMarkup(buttons))
        context.user_data['plants_menu_msg_id'] = menu_msg.message_id
        return

    elif query.data == "delete_back":
        await query.message.edit_text("Що ви хочете зробити з вашими томатами?", reply_markup=plant_list_menu())
        return

    elif query.data.startswith("prompt_delete:"):
        plant_id = query.data.split(":", 1)[1]
        species = next((p['species'] for p in get_all_plants(user_db_id) if p['plant_id']==plant_id), "")
        confirm = await query.message.edit_text(f"Ви дійсно хочете видалити томат «{species}»?",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Так", callback_data=f"delete_yes:{plant_id}"),
                InlineKeyboardButton("Ні", callback_data="delete_no")]]))
        context.user_data['confirm_msg_id'] = confirm.message_id
        return

    elif query.data.startswith("delete_yes:"):
        plant_id = query.data.split(":", 1)[1]
        delete_plant(user_db_id, plant_id)
        await show_plants_actions(query, context, user_db_id)
        return

    elif query.data == "delete_no":
        chat_id = query.message.chat_id
        await query.message.edit_text("Видалення скасовано.", reply_markup=plant_list_menu())
        return

    elif query.data == "history":
        keyboard = [
        [InlineKeyboardButton("Переглянути по конкретному томату", callback_data="history_by_plant")],
        [InlineKeyboardButton("Переглянути по даті сканування", callback_data="history_by_date")],
        [InlineKeyboardButton("⬅️Назад в меню", callback_data="return_menu")]]
        await query.message.edit_text("Виберіть спосіб перегляду історії:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "history_by_plant":
        buttons = [
        [InlineKeyboardButton(f"{p['species']} ({p['location']})", 
                              callback_data=f"view_history:{p['plant_id']}")]
        for p in get_all_plants(user_db_id)]
        buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="history")])
        await query.message.edit_text("Виберіть рослину, історію якої хочете переглянути:", reply_markup=InlineKeyboardMarkup(buttons))

    elif query.data == "history_by_date":
        raw_ts_list = get_scan_timestamps(user_db_id)
        buttons = []
        for raw_ts in raw_ts_list:
            dt = datetime.fromisoformat(raw_ts)
            label = dt.strftime("%d.%m.%Y %H:%M:%S")
            buttons.append([InlineKeyboardButton(label, callback_data=f"view_history_date:{raw_ts}")])
        buttons.append([InlineKeyboardButton("⬅️Назад", callback_data="history")])
        await query.message.edit_text("Оберіть дату та час сканування:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    elif query.data.startswith("view_history_date:"):
        selected_ts = query.data.split(":", 1)[1]
        scans = get_scans_by_timestamp(user_db_id, selected_ts)
        if not scans:
            await query.message.edit_text("Сканувань за цей час немає.", reply_markup=get_main_menu())
            return
        for scan in scans:
            plant = scan["plants"]
            diseases = scan["diseases"] or []
            diseases_text = ", ".join(f"{d['name']} ({d['probability']*100:.1f}%)" for d in diseases) or "Захворювання відсутні"
            dt = datetime.fromisoformat(scan["timestamp"])
            ts = dt.strftime("%d.%m.%Y %H:%M:%S")
            caption = (
                f"Рослина: {plant['species']}\n"
                f"Локація: {plant['location']}\n"
                f"Хвороби: {diseases_text}\n"
                f"Час: {ts}")
            await query.message.reply_photo(photo=scan["image_url"], caption=caption)
        await query.message.reply_text("Оберіть дію:", reply_markup=get_main_menu())
        return

    elif query.data.startswith("view_history:"):
        plant_id = query.data.split(":", 1)[1]
        scans = get_scan_history(plant_id)
        if not scans:
            await query.message.edit_text("Сканувань ще немає.", reply_markup=get_main_menu())
            return
        for scan in scans:
            plant = scan["plants"]
            diseases = scan["diseases"] or []
            diseases_text = ", ".join(f"{d['name']} ({d['probability']*100:.1f}%)" for d in diseases) or "Захворювання відсутні"
            dt = datetime.fromisoformat(scan["timestamp"])
            ts = dt.strftime("%d.%m.%Y %H:%M:%S")
            caption = (
                f"Рослина: {plant['species']}\n"
                f"Локація: {plant['location']}\n"
                f"Хвороби: {diseases_text}\n"
                f"Час: {ts}")
            await query.message.reply_photo(photo=scan["image_url"], caption=caption)
        await query.message.reply_text("Оберіть дію:", reply_markup=get_main_menu())
        return