import os
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler
)
from dotenv import load_dotenv
from handlers import (
    start, start_bind, bind_input,
    add_plant_start, species_input, location_input, cancel_add,
    button, SPECIES, LOCATION, BIND_ROBOT)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_bind = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_bind, pattern="bind_robot")],
        states={BIND_ROBOT: [MessageHandler(filters.TEXT & ~filters.COMMAND, bind_input)]},
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)])

    conv_plant = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_plant_start, pattern="add_plant")],
        states={
            SPECIES:  [MessageHandler(filters.TEXT & ~filters.COMMAND, species_input)],
            LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, location_input)],},
        fallbacks=[
            CallbackQueryHandler(cancel_add, pattern="cancel_add"),
            CommandHandler("cancel", lambda u, c: ConversationHandler.END)])

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_bind)
    app.add_handler(conv_plant)
    app.add_handler(CallbackQueryHandler(button))
    app.run_polling()

if __name__ == "__main__":
    main()