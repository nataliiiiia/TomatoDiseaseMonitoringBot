import os
import io
import uuid
import logging
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters
)
from PIL import Image
import qrcode
import base64
import requests

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
    insert_scan,
    get_scan_history,
    clear_command
)
from models import ScanData

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
BOT_TOKEN    = os.getenv("BOT_TOKEN")

app        = FastAPI()
app_bot    = Application.builder().token(BOT_TOKEN).build()
telegram_bot = app_bot.bot

SPECIES, LOCATION, BIND_ROBOT = range(3)


def get_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Запустити сканування", callback_data="start_scan")],
        [InlineKeyboardButton("Додати рослину",       callback_data="add_plant")],
        [InlineKeyboardButton("Мої рослини",          callback_data="view_plants")],
        [InlineKeyboardButton("Перегляд історії",     callback_data="history")],
    ])

def plant_list_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Повернутися в меню", callback_data="return_menu"),
            InlineKeyboardButton("Видалити рослину",    callback_data="delete_plant")
        ]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid       = str(update.effective_user.id)
    username  = update.effective_user.username or ""
    user_db   = create_user_if_not_exists(tid, username)
    robot_id  = get_robot_id_for_user(user_db)

    if not robot_id:
        kb = [[InlineKeyboardButton("Прив'язати робота", callback_data="bind_robot")]]
        await update.message.reply_text("Вкажіть код вашої машини:", reply_markup=InlineKeyboardMarkup(kb))
        return

    await update.message.reply_text("Оберіть дію:", reply_markup=get_main_menu())

async def start_bind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Введіть код вашого робота:")
    return BIND_ROBOT

async def bind_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid      = str(update.effective_user.id)
    user_db  = get_user_db_id(tid)
    robot_id = update.message.text.strip()

    bind_robot_to_user(user_db, robot_id)
    await update.message.reply_text(f"Робота {robot_id} прив'язано!", reply_markup=get_main_menu())
    return ConversationHandler.END

async def add_plant_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Назва виду рослини:")
    return SPECIES

async def species_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['species'] = update.message.text
    await update.message.reply_text("Локація (Ряд 1 Позиція 1):")
    return LOCATION

async def location_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid      = str(update.effective_user.id)
    user_db  = get_user_db_id(tid)
    species  = context.user_data['species']
    location = update.message.text
    plant_id = str(uuid.uuid4())

    add_plant(user_db, plant_id, species, location)

    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(plant_id)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    qr_msg = await update.message.reply_photo(photo=buf,
        caption=f"Рослина додана!\nВид: {species}\nЛокація: {location}")
    set_qr_message_id(plant_id, qr_msg.message_id)

    await update.message.reply_text("Готово", reply_markup=get_main_menu())
    return ConversationHandler.END

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    tid      = str(update.effective_user.id)
    user_db  = get_user_db_id(tid)
    robot_id = get_robot_id_for_user(user_db)
    data     = query.data

    if data == "start_scan":
        set_command(robot_id, "start", None)
        await query.message.reply_text("Сканування розпочато.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Стоп", callback_data="stop_scan")]]))
        return

    if data == "stop_scan":
        set_command(robot_id, "stop", None)
        await query.message.reply_text("Сканування зупинено.", reply_markup=get_main_menu())
        return

    if data == "add_plant":
        return await add_plant_start(update, context)

    if data == "view_plants":
        plants = get_all_plants(user_db)
        if not plants:
            await query.message.reply_text("Рослин немає.", reply_markup=get_main_menu())
            return
        for p in plants:
            btn = InlineKeyboardButton("QR-код", callback_data=f"view_qr:{p['plant_id']}")
            txt = f"{p['species']} @ {p['location']}"
            await query.message.reply_text(txt, reply_markup=InlineKeyboardMarkup([[btn]]))
        await query.message.reply_text("Дії:", reply_markup=plant_list_menu())
        return

    if data.startswith("view_qr:"):
        pid = data.split(":",1)[1]
        mid = get_qr_message_id(pid)
        await context.bot.copy_message(chat_id=query.message.chat_id,
            from_chat_id=query.message.chat_id, message_id=mid)
        return

    if data == "return_menu":
        await query.message.reply_text("Меню:", reply_markup=get_main_menu())
        return

    if data == "delete_plant":
        plants = get_all_plants(user_db)
        btns = [[InlineKeyboardButton(f"{p['species']} @ {p['location']}", callback_data=f"del:{p['plant_id']}")] for p in plants]
        await query.message.reply_text("Оберіть для видалення:", reply_markup=InlineKeyboardMarkup(btns))
        return

    if data.startswith("del:"):
        pid = data.split(":",1)[1]
        delete_plant(user_db, pid)
        await query.message.reply_text("Видалено.", reply_markup=get_main_menu())
        return

    if data == "history":
        plants = get_all_plants(user_db)
        btns = [[InlineKeyboardButton(f"{p['species']} @ {p['location']}", callback_data=f"hist:{p['plant_id']}")] for p in plants]
        await query.message.reply_text("Історія:", reply_markup=InlineKeyboardMarkup(btns))
        return

    if data.startswith("hist:"):
        pid   = data.split(":",1)[1]
        scans = get_scan_history(pid)
        if not scans:
            await query.message.reply_text("Немає сканів.", reply_markup=get_main_menu())
            return
        for s in scans:
            ds = s.get("diseases") or []
            txt = ", ".join(f"{d['name']}({d['probability']*100:.1f}%)" for d in ds) or "Немає"
            cap = f"{s['plants']['species']} @ {s['timestamp']}\n{txt}"
            await query.message.reply_photo(photo=s['image_url'], caption=cap)
        await query.message.reply_text("Готово", reply_markup=get_main_menu())
        return

@app.get("/api/get_user")
async def get_user(robot_id: str):
    tid = get_telegram_id_by_robot(robot_id)
    if not tid:
        raise HTTPException(404, "Не знайдено")
    return {"telegram_id": tid}

@app.post("/api/scan")
async def receive_scan(data: ScanData):
    tid = get_telegram_id_by_robot(data.robot_id)
    if not tid:
        raise HTTPException(404, "Не знайдено")

    img = base64.b64decode(data.image)
    im  = Image.open(io.BytesIO(img))
    fn  = f"scan_{data.robot_id}_{data.timestamp.replace(' ','_')}.jpg"
    buf = io.BytesIO(); im.save(buf, format="JPEG"); buf.seek(0)
 
    url = f"{os.getenv('SUPABASE_URL')}/storage/v1/object/public/plant_images/{fn}"

    insert_scan(data.robot_id, data.analysis.get("plant_id"), data.analysis.get("diseases", []), data.timestamp, url)

    await telegram_bot.send_photo(chat_id=tid, photo=url,
        caption=f"Скан: {data.timestamp}")
    clear_command(data.robot_id)
    return {"status": "ok"}


if __name__ == "__main__":
    conv_bind = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_bind, pattern="bind_robot")],
        states={BIND_ROBOT: [MessageHandler(filters.TEXT & ~filters.COMMAND, bind_input)]},
        fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)]
    )
    conv_plant = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_plant_start, pattern="add_plant")],
        states={SPECIES: [MessageHandler(filters.TEXT & ~filters.COMMAND, species_input)],
                LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, location_input)]},
        fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)]
    )

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(conv_bind)
    app_bot.add_handler(conv_plant)
    app_bot.add_handler(CallbackQueryHandler(button))

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
    app_bot.run_polling()