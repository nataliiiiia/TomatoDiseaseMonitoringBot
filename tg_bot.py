import os
import logging
import uuid
import io
import base64
import supabase
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
)
from fastapi import FastAPI, HTTPException
from PIL import Image
import qrcode
from dotenv import load_dotenv

from db import (
    create_user_if_not_exists,
    get_user_db_id,
    bind_robot_to_user,
    get_robot_id_for_user,
    get_telegram_id_by_robot,
    get_all_plants,
    add_plant,
    delete_plant,
    set_qr_message_id,
    get_qr_message_id,
    set_command,
    get_command,
    clear_command,
    insert_scan,
    get_scan_history
)
from models import ScanData, CommandData

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

app = FastAPI()

SPECIES, LOCATION, BIND_ROBOT = range(3)


def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("Запустити сканування", callback_data="start_scan")],
        [InlineKeyboardButton("Додати рослину", callback_data="add_plant")],
        [InlineKeyboardButton("Мої рослини", callback_data="view_plants")],
        [InlineKeyboardButton("Перегляд історії", callback_data="history")],
    ]
    return InlineKeyboardMarkup(keyboard)


def plant_list_menu():
    keyboard = [
        [
            InlineKeyboardButton("Повернутися в меню", callback_data="return_menu"),
            InlineKeyboardButton("Видалити рослину", callback_data="delete_plant")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


async def show_plants_actions(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    user_db_id: str
) -> bool:
    plants = get_all_plants(user_db_id)
    if not plants:
        await query.message.reply_text(
            "У вас більше немає доданих рослин.",
            reply_markup=get_main_menu()
        )
        return False

    for p in plants:
        qr_btn = InlineKeyboardButton(
            "Показати QR-код",
            callback_data=f"view_qr:{p['plant_id']}"
        )
        await query.message.reply_text(
            f"Вид: {p['species']}\n"
            f"Локація: {p['location']}\n"
            f"Додано: {p['created_at']}",
            reply_markup=InlineKeyboardMarkup([[qr_btn]])
        )

    await query.message.reply_text(
        "Що ви хочете зробити з вашими рослинами?",
        reply_markup=plant_list_menu()
    )
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = str(update.effective_user.id)
    username = update.effective_user.username or ""
    user_db_id = create_user_if_not_exists(telegram_id, username)
    robot_id = get_robot_id_for_user(user_db_id)

    if not robot_id:
        kb = [[InlineKeyboardButton("Прив'язати робота", callback_data="bind_robot")]]
        await update.message.reply_text(
            "Для початку роботи необхідно прив'язати робоплатформу.",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return
    await update.message.reply_text(
        "Вітаю! Це TomatoDiseaseDetector бот. Оберіть дію:",
        reply_markup=get_main_menu()
    )


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
    await update.message.reply_text(
        f"Робоплатформу {robot_id} успішно прив’язано!",
        reply_markup=get_main_menu()
    )
    return ConversationHandler.END


async def add_plant_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Введіть назву виду Вашої рослини:")
    return SPECIES


async def species_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["species"] = update.message.text
    await update.message.reply_text("Введіть локацію рослини (наприклад, Ряд 1 Позиція 1):")
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
            f"Рослина додана!\n"
            f"Вид: {species}\n"
            f"Локація: {location}\n"
            "Роздрукуйте цей QR-код для сканування."
        )
    )
    set_qr_message_id(plant_id, qr_msg.message_id)

    await update.message.reply_text("Виберіть дію:", reply_markup=get_main_menu())
    return ConversationHandler.END


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    telegram_id = str(update.effective_user.id)
    user_db_id = get_user_db_id(telegram_id)
    robot_id = get_robot_id_for_user(user_db_id)

    if query.data == "start_scan":
        set_command(robot_id, "start")
        await query.message.reply_text(
            "Сканування розпочато.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Завершити сканування", callback_data="stop_scan")]]
            )
        )
        return

    if query.data == "stop_scan":
        set_command(robot_id, "stop")
        await query.message.reply_text("Сканування зупинено.", reply_markup=get_main_menu())
        return

    if query.data == "add_plant":
        return await add_plant_start(update, context)

    if query.data == "view_plants":
        await show_plants_actions(query, context, user_db_id)
        return

    if query.data.startswith("view_qr:"):
        plant_id = query.data.split(":", 1)[1]
        qr_msg_id = get_qr_message_id(plant_id)
        chat_id = query.message.chat_id
        await context.bot.copy_message(
            chat_id=chat_id,
            from_chat_id=chat_id,
            message_id=qr_msg_id
        )
        return

    if query.data == "return_menu":
        await query.message.reply_text("Оберіть дію:", reply_markup=get_main_menu())
        return

    if query.data == "delete_plant":
        plants = get_all_plants(user_db_id)
        buttons = [
            [InlineKeyboardButton(f"{p['species']} ({p['location']})",
            callback_data=f"prompt_delete:{p['plant_id']}"
        )]
            for p in plants
    ]
        menu_msg = await query.message.reply_text("Оберіть томат для видалення:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
        context.user_data['plants_menu_msg_id'] = menu_msg.message_id
        return


    if query.data.startswith("prompt_delete:"):
        plant_id = query.data.split(":", 1)[1]
        species = next((p['species'] for p in get_all_plants(user_db_id) if p['plant_id']==plant_id), "")
        confirm = await query.message.reply_text(
            f"Ви дійсно хочете видалити рослину «{species}»?",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Так", callback_data=f"delete_yes:{plant_id}"),
                InlineKeyboardButton("Ні", callback_data="delete_no")
            ]])
        )
        context.user_data['confirm_msg_id'] = confirm.message_id
        return

    if query.data.startswith("delete_yes:"):
        plant_id = query.data.split(":", 1)[1]
        delete_plant(user_db_id, plant_id)
        await context.bot.delete_message(query.message.chat_id, context.user_data.pop('plants_menu_msg_id'))
        await context.bot.delete_message(query.message.chat_id, context.user_data.pop('confirm_msg_id'))
        await show_plants_actions(query, context, user_db_id)
        return

    if query.data == "delete_no":
        chat_id = query.message.chat_id
        await context.bot.delete_message(chat_id, context.user_data.pop('plants_menu_msg_id'))
        await context.bot.delete_message(chat_id, context.user_data.pop('confirm_msg_id'))
        await query.message.reply_text("Видалення скасовано.", reply_markup=plant_list_menu())
        return

    if query.data == "history":
        plants = get_all_plants(user_db_id)
        if not plants:
            await query.message.reply_text("У вас ще немає доданих рослин.", reply_markup=get_main_menu())
            return
        buttons = [[
            InlineKeyboardButton(f"{p['species']} ({p['location']})",
                                 callback_data=f"view_history:{p['plant_id']}")
        ] for p in plants]
        await query.message.reply_text(
            "Виберіть рослину, історію якої хочете переглянути:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if query.data.startswith("view_history:"):
        plant_id = query.data.split(":", 1)[1]
        scans = get_scan_history(plant_id)
        if not scans:
            await query.message.reply_text("Сканувань ще немає.", reply_markup=get_main_menu())
            return
        for scan in scans:
            plant = scan["plants"]
            diseases = scan["diseases"] or []
            diseases_text = ", ".join(f"{d['name']} ({d['probability']*100:.1f}%)" for d in diseases) or "Немає хвороб"
            caption = (
                f"Рослина: {plant['species']}\n"
                f"Локація: {plant['location']}\n"
                f"Хвороби: {diseases_text}\n"
                f"Час: {scan['timestamp']}"
            )
            await query.message.reply_photo(photo=scan["image_url"], caption=caption)
        await query.message.reply_text("Оберіть дію:", reply_markup=get_main_menu())
        return


@app.get("/api/get_user")
async def get_user(robot_id: str):
    telegram_id = get_telegram_id_by_robot(robot_id)
    if not telegram_id:
        raise HTTPException(status_code=404, detail="Робоплатформа не знайдена")
    return {"telegram_id": telegram_id}


@app.post("/api/scan")
async def receive_scan(data: ScanData):
    telegram_id = get_telegram_id_by_robot(data.robot_id)
    if not telegram_id:
        raise HTTPException(status_code=404, detail="Робоплатформа не знайдена")

    image_data = base64.b64decode(data.image)
    image = Image.open(io.BytesIO(image_data))
    filename = f"scan_{data.robot_id}_{data.timestamp.replace(' ', '_')}.jpg"
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    buf.seek(0)
    supabase.storage.from_("plant_images").upload(filename, buf)
    url = f"{os.getenv('SUPABASE_URL')}/storage/v1/object/public/plant_images/{filename}"

    insert_scan(
        data.robot_id,
        data.analysis.get("plant_id"),
        data.analysis.get("diseases", []),
        data.timestamp,
        url
    )

    plant = next((p for p in get_all_plants(get_user_db_id(telegram_id)) if p["plant_id"] == data.analysis.get("plant_id")), None)
    species = plant["species"] if plant else "Невідомо"
    location = plant["location"] if plant else "Невідомо"
    diseases = data.analysis.get("diseases", []) or []
    diseases_text = ", ".join(f"{d['name']} ({d['probability']*100:.1f}%)" for d in diseases) or "Немає хвороб"
    caption = (
        f"Нове сканування:\n"
        f"Рослина: {species}\n"
        f"Локація: {location}\n"
        f"Хвороби: {diseases_text}\n"
        f"Час: {data.timestamp}"
    )
    await Application.builder().token(BOT_TOKEN).build().bot.send_photo(
        chat_id=telegram_id,
        photo=url,
        caption=caption
    )
    return {"status": "success"}


@app.get("/api/command")
async def get_command_endpoint(robot_id: str):
    cmd = get_command(robot_id)
    return {"command": cmd}


@app.post("/api/update_command")
async def update_command_endpoint(data: CommandData):
    set_command(data.robot_id, data.command, data.reason)
    if data.command == "stop":
        telegram_id = get_telegram_id_by_robot(data.robot_id)
        if telegram_id:
            if data.reason == "end_of_route":
                msg = "Робоплатформа зупинилася: кінець маршруту або втрата лінії."
            elif data.reason == "obstacle":
                msg = "Робоплатформа зупинилася: виявлено перешкоду на відстані менше 10 см."
            else:
                msg = "Робоплатформа зупинилася."
            await Application.builder().token(BOT_TOKEN).build().bot.send_message(
                chat_id=telegram_id,
                text=msg,
                reply_markup=get_main_menu()
            )
    return {"status": "updated"}


@app.post("/api/clear_command")
async def clear_command_endpoint(data: CommandData):
    clear_command(data.robot_id)
    return {"status": "cleared"}


def main():
    app_bot = Application.builder().token(BOT_TOKEN).build()

    conv_bind = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_bind, pattern="bind_robot")],
        states={BIND_ROBOT: [MessageHandler(filters.TEXT & ~filters.COMMAND, bind_input)]},
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )
    conv_plant = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_plant_start, pattern="add_plant")],
        states={
            SPECIES: [MessageHandler(filters.TEXT & ~filters.COMMAND, species_input)],
            LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, location_input)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(conv_bind)
    app_bot.add_handler(conv_plant)
    app_bot.add_handler(CallbackQueryHandler(button))
    app_bot.run_polling()


if __name__ == "__main__":
    main()
