import os
import logging
import uuid
import io
import base64
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
)
from fastapi import FastAPI, HTTPException, Request
from PIL import Image
import qrcode
from dotenv import load_dotenv
from supabase import create_client

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
    insert_scan,
    get_scan_history,
    set_scan_status,
    get_scan_status,
)
from models import ScanData

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

app = FastAPI()
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Ініціалізація Telegram Application
app_bot = Application.builder().token(BOT_TOKEN).build()

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
    logger.info(f"Отримано команду /start від telegram_id: {update.effective_user.id}")
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
    set_scan_status(robot_id, "stop")
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
    logger.info(f"Отримано callback: {query.data} від telegram_id: {telegram_id}")
    if not robot_id:
        await query.message.reply_text("Спочатку прив’яжіть робоплатформу.")
        return

    try:
        if query.data == "start_scan":
            set_scan_status(robot_id, "start")
            await query.message.reply_text(
                "Сканування розпочато.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Завершити сканування", callback_data="stop_scan")]]
                )
            )
            return

        if query.data == "stop_scan":
            set_scan_status(robot_id, "stop")
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
            if qr_msg_id:
                await context.bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=chat_id,
                    message_id=qr_msg_id
                )
            else:
                await query.message.reply_text("QR-код не знайдено.")
            return

        if query.data == "return_menu":
            await query.message.reply_text("Оберіть дію:", reply_markup=get_main_menu())
            return

        if query.data == "delete_plant":
            plants = get_all_plants(user_db_id)
            buttons = [
                [InlineKeyboardButton(f"{p['species']} ({p['location']})",
                                     callback_data=f"prompt_delete:{p['plant_id']}")]
                for p in plants
            ]
            menu_msg = await query.message.reply_text("Оберіть томат для видалення:",
                                                     reply_markup=InlineKeyboardMarkup(buttons))
            context.user_data['plants_menu_msg_id'] = menu_msg.message_id
            return

        if query.data.startswith("prompt_delete:"):
            plant_id = query.data.split(":", 1)[1]
            species = next((p['species'] for p in get_all_plants(user_db_id) if p['plant_id'] == plant_id), "")
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
            await context.bot.delete_message(query.message.chat_id, context.user_data.pop('plants_menu_msg_id', None))
            await context.bot.delete_message(query.message.chat_id, context.user_data.pop('confirm_msg_id', None))
            await show_plants_actions(query, context, user_db_id)
            return

        if query.data == "delete_no":
            chat_id = query.message.chat_id
            await context.bot.delete_message(chat_id, context.user_data.pop('plants_menu_msg_id', None))
            await context.bot.delete_message(chat_id, context.user_data.pop('confirm_msg_id', None))
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
    except Exception as e:
        logger.error(f"Помилка в обробці кнопки: {e}")
        await query.message.reply_text("Виникла помилка. Спробуйте ще раз.")

@app.get("/api/get_user")
async def get_user(robot_id: str):
    try:
        telegram_id = get_telegram_id_by_robot(robot_id)
        if not telegram_id:
            raise HTTPException(status_code=404, detail="Робоплатформа не знайдена")
        return {"telegram_id": telegram_id}
    except Exception as e:
        logger.error(f"Помилка в /api/get_user: {e}")
        raise HTTPException(status_code=500, detail="Внутрішня помилка сервера")

@app.post("/api/scan")
async def receive_scan(data: ScanData):
    try:
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
        await app_bot.bot.send_photo(
            chat_id=telegram_id,
            photo=url,
            caption=caption
        )
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Помилка в /api/scan: {e}")
        raise HTTPException(status_code=500, detail="Внутрішня помилка сервера")

@app.post("/api/scan_status")
async def get_scan_status(data: dict):
    try:
        robot_id = data.get("robot_id")
        logger.info(f"Запит до /api/scan_status для robot_id: {robot_id}")
        if not robot_id:
            raise HTTPException(status_code=404, detail="Робоплатформа не знайдена")
        status = get_scan_status(robot_id)
        return {"status": status}
    except Exception as e:
        logger.error(f"Помилка в /api/scan_status: {e}")
        raise HTTPException(status_code=500, detail="Внутрішня помилка сервера")

@app.post("/api/update_status")
async def update_status(data: dict):
    try:
        robot_id = data.get("robot_id")
        status = data.get("status")
        reason = data.get("reason", "manual")
        logger.info(f"Запит до /api/update_status для robot_id: {robot_id}, status: {status}, reason: {reason}")
        if not robot_id:
            raise HTTPException(status_code=404, detail="Робоплатформа не знайдена")
        set_scan_status(robot_id, status)
        if status == "stop":
            telegram_id = get_telegram_id_by_robot(robot_id)
            if telegram_id:
                if reason == "end_of_route":
                    msg = "Робоплатформа зупинилася: кінець маршруту або втрата лінії."
                elif reason == "obstacle":
                    msg = "Робоплатформа зупинилася: виявлено перешкоду на відстані менше 10 см."
                else:
                    msg = "Робоплатформа зупинилася."
                await app_bot.bot.send_message(
                    chat_id=telegram_id,
                    text=msg,
                    reply_markup=get_main_menu()
                )
        return {"status": "updated"}
    except Exception as e:
        logger.error(f"Помилка в /api/update_status: {e}")
        raise HTTPException(status_code=500, detail="Внутрішня помилка сервера")

@app.post("/webhook")
async def webhook(request: Request):
    try:
        logger.info("Отримано Webhook-запит")
        update = Update.de_json(await request.json(), app_bot.bot)
        if update:
            logger.info(f"Обробка оновлення: {update}")
            await app_bot.process_update(update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Помилка в /webhook: {e}")
        return {"status": "error"}

def setup_handlers():
    logger.info("Налаштування обробників Telegram")
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
    logger.info("Обробники налаштовано")

if __name__ == "__main__":
    import uvicorn
    setup_handlers()
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))