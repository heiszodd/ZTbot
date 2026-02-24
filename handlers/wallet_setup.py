from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, ContextTypes, MessageHandler, filters

HL_AWAIT = 1
SOL_AWAIT = 2
POLY_AWAIT_KEY = 3
POLY_AWAIT_API = 4
POLY_AWAIT_SECRET = 5
POLY_AWAIT_PASS = 6


async def hl_start_setup(query, context):
    await query.message.reply_text("Send Hyperliquid private key or seed phrase. /cancel to abort.")
    return HL_AWAIT


async def hl_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text or ""
    from security.key_manager import store_private_key
    result = store_private_key("hl_api_wallet", raw, "Hyperliquid API Wallet", chain="ethereum")
    if result.get("address"):
        import db
        db.save_hl_address(result["address"])
    await update.message.reply_text("✅ Hyperliquid wallet stored.")
    return ConversationHandler.END


async def sol_start_setup(query, context):
    await query.message.reply_text("Send Solana private key or seed phrase. /cancel to abort.")
    return SOL_AWAIT


async def sol_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text or ""
    from security.key_manager import store_private_key
    result = store_private_key("sol_hot_wallet", raw, "Solana Hot Wallet", chain="solana")
    if result.get("address"):
        import db
        db.save_sol_wallet_address(result["address"])
    await update.message.reply_text("✅ Solana wallet stored.")
    return ConversationHandler.END


async def poly_start_setup(query, context):
    await query.message.reply_text("Send Polymarket wallet private key/seed phrase.")
    return POLY_AWAIT_KEY


async def poly_receive_key(update, context):
    from security.key_manager import store_private_key
    result = store_private_key("poly_hot_wallet", update.message.text or "", "Polymarket Wallet", chain="polymarket")
    if result.get("address"):
        import db
        db.save_poly_wallet_address(result["address"])
    await update.message.reply_text("Send Polymarket API key.")
    return POLY_AWAIT_API


async def poly_receive_api(update, context):
    from security.key_manager import store_private_key
    store_private_key("poly_api_key", update.message.text or "", "Polymarket API Key", chain="polymarket")
    await update.message.reply_text("Send Polymarket API secret.")
    return POLY_AWAIT_SECRET


async def poly_receive_secret(update, context):
    from security.key_manager import store_private_key
    store_private_key("poly_api_secret", update.message.text or "", "Polymarket API Secret", chain="polymarket")
    await update.message.reply_text("Send Polymarket API passphrase.")
    return POLY_AWAIT_PASS


async def poly_receive_pass(update, context):
    from security.key_manager import store_private_key
    store_private_key("poly_api_passphrase", update.message.text or "", "Polymarket API Passphrase", chain="polymarket")
    await update.message.reply_text("✅ Polymarket credentials stored.")
    return ConversationHandler.END


async def setup_cancel(update, context):
    if update.callback_query:
        await update.callback_query.answer()
    else:
        await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


hl_setup_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(hl_start_setup, pattern=r"^hl:connect$")],
    states={HL_AWAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, hl_receive)]},
    fallbacks=[CommandHandler("cancel", setup_cancel)],
)

sol_setup_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(sol_start_setup, pattern=r"^sol:connect$")],
    states={SOL_AWAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, sol_receive)]},
    fallbacks=[CommandHandler("cancel", setup_cancel)],
)

poly_setup_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(poly_start_setup, pattern=r"^poly:connect$")],
    states={
        POLY_AWAIT_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, poly_receive_key)],
        POLY_AWAIT_API: [MessageHandler(filters.TEXT & ~filters.COMMAND, poly_receive_api)],
        POLY_AWAIT_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, poly_receive_secret)],
        POLY_AWAIT_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, poly_receive_pass)],
    },
    fallbacks=[CommandHandler("cancel", setup_cancel)],
)
