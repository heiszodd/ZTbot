import asyncio
import logging

from telegram import InlineKeyboardButton as IKB, InlineKeyboardMarkup as IKM, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, ContextTypes, MessageHandler, filters

log = logging.getLogger(__name__)

HL_WAIT_CONFIRM = 1
HL_WAIT_KEY = 2
SOL_WAIT_CONFIRM = 3
SOL_WAIT_KEY = 4
POLY_WAIT_CONFIRM = 5
POLY_WAIT_WALLET_KEY = 6
POLY_WAIT_API = 7
POLY_WAIT_SECRET = 8
POLY_WAIT_PASS = 9


def _kb(rows):
    return IKM(rows)


async def _cancel(update, context):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text("Cancelled.")
    elif update.message:
        await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


async def hl_start_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        "📈 *Connect Hyperliquid*\n\n"
        "You can paste a seed phrase or private key.\n"
        "Your message will be deleted immediately.",
        parse_mode="Markdown",
        reply_markup=_kb([[IKB("✅ I have my key", callback_data="hl:setup:ask")], [IKB("❌ Cancel", callback_data="perps")]]),
    )
    return HL_WAIT_CONFIRM


async def hl_ask_for_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        "Send your Hyperliquid private key or seed phrase now.\n\n"
        "Use /cancel to stop.",
        reply_markup=_kb([[IKB("❌ Cancel", callback_data="perps")]]),
    )
    return HL_WAIT_KEY


async def hl_receive_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = (update.message.text or "").strip()
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception:
        pass

    status_msg = await update.message.reply_text("⏳ Processing key...")

    try:
        from security.key_manager import store_private_key

        result = await asyncio.wait_for(
            asyncio.to_thread(
                store_private_key,
                key_name="hl_api_wallet",
                raw_input=raw,
                label="Hyperliquid API Wallet",
                chain="hyperliquid",
            ),
            timeout=10.0,
        )
        address = result["address"]
        fmt = result["format"]

        import db

        db.save_hl_address(address)
        short = f"{address[:8]}...{address[-6:]}"

        await status_msg.edit_text(
            f"✅ *Hyperliquid Connected*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Address: `{short}`\n"
            f"Format:  {fmt}\n\n"
            f"Your key is encrypted and stored.\n"
            f"Your message was deleted.\n\n"
            f"Live trading is now enabled.",
            parse_mode="Markdown",
            reply_markup=_kb([[IKB("🔷 View Account", callback_data="perps:live"), IKB("🏠 Home", callback_data="home")]]),
        )

    except ValueError as e:
        await status_msg.edit_text(
            f"❌ *Could not store key*\n\n"
            f"{str(e)}\n\n"
            f"Please try again:",
            parse_mode="Markdown",
            reply_markup=_kb([[IKB("🔄 Try Again", callback_data="hl:connect"), IKB("❌ Cancel", callback_data="perps")]]),
        )
        return ConversationHandler.END
    except asyncio.TimeoutError:
        await status_msg.edit_text(
            "❌ *Timeout while processing key*\n\nPlease try again.",
            parse_mode="Markdown",
            reply_markup=_kb([[IKB("🔄 Try Again", callback_data="hl:connect"), IKB("❌ Cancel", callback_data="perps")]]),
        )
        return ConversationHandler.END
    except Exception as e:
        log.error("Wallet setup error: %s", e, exc_info=True)
        await status_msg.edit_text(
            f"❌ *Unexpected error*\n\n"
            f"`{str(e)[:300]}`\n\n"
            f"Please try again.",
            parse_mode="Markdown",
            reply_markup=_kb([[IKB("← Back", callback_data="perps")]]),
        )
        return ConversationHandler.END

    return ConversationHandler.END


async def sol_start_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        "🔥 *Connect Solana*\n\n"
        "You can paste a seed phrase or private key.\n"
        "Your message will be deleted immediately.",
        parse_mode="Markdown",
        reply_markup=_kb([[IKB("✅ I have my key", callback_data="sol:setup:ask")], [IKB("❌ Cancel", callback_data="degen")]]),
    )
    return SOL_WAIT_CONFIRM


async def sol_ask_for_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        "Send your Solana private key or seed phrase now.\n\n"
        "Use /cancel to stop.",
        reply_markup=_kb([[IKB("❌ Cancel", callback_data="degen")]]),
    )
    return SOL_WAIT_KEY


async def sol_receive_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = (update.message.text or "").strip()

    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception:
        pass

    status_msg = await update.message.reply_text("⏳ Processing key...")

    try:
        from security.key_manager import store_private_key
        import db

        result = await asyncio.wait_for(
            asyncio.to_thread(
                store_private_key,
                key_name="sol_hot_wallet",
                raw_input=raw,
                label="Solana Hot Wallet",
                chain="solana",
            ),
            timeout=10.0,
        )
        address = result["address"]
        fmt = result["format"]
        db.save_sol_wallet_address(address)

        short = f"{address[:8]}...{address[-6:]}"
        await status_msg.edit_text(
            f"✅ *Solana Connected*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Address: `{short}`\n"
            f"Format:  {fmt}\n\n"
            f"Your key is encrypted and stored.\n"
            f"Your message was deleted.",
            parse_mode="Markdown",
            reply_markup=_kb([[IKB("🔥 View Degen", callback_data="degen"), IKB("🏠 Home", callback_data="home")]]),
        )
    except ValueError as e:
        await status_msg.edit_text(
            f"❌ *Could not store key*\n\n{str(e)}\n\nPlease try again:",
            parse_mode="Markdown",
            reply_markup=_kb([[IKB("🔄 Try Again", callback_data="sol:connect"), IKB("❌ Cancel", callback_data="degen")]]),
        )
        return ConversationHandler.END
    except asyncio.TimeoutError:
        await status_msg.edit_text(
            "❌ *Timeout while processing key*\n\nPlease try again.",
            parse_mode="Markdown",
            reply_markup=_kb([[IKB("🔄 Try Again", callback_data="sol:connect"), IKB("❌ Cancel", callback_data="degen")]]),
        )
        return ConversationHandler.END
    except Exception as e:
        log.error("Solana setup error: %s", e, exc_info=True)
        await status_msg.edit_text(
            f"❌ *Unexpected error*\n\n`{str(e)[:300]}`\n\nPlease try again.",
            parse_mode="Markdown",
            reply_markup=_kb([[IKB("← Back", callback_data="degen")]]),
        )
        return ConversationHandler.END

    return ConversationHandler.END


async def poly_start_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        "🎯 *Connect Polymarket*\n\n"
        "Step 1/4: wallet key\n"
        "Step 2/4: API key\n"
        "Step 3/4: API secret\n"
        "Step 4/4: API passphrase",
        parse_mode="Markdown",
        reply_markup=_kb([[IKB("✅ I have my key", callback_data="poly:setup:ask")], [IKB("❌ Cancel", callback_data="predictions")]]),
    )
    return POLY_WAIT_CONFIRM


async def poly_ask_for_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        "Send your Polymarket wallet private key or seed phrase.",
        reply_markup=_kb([[IKB("❌ Cancel", callback_data="predictions")]]),
    )
    return POLY_WAIT_WALLET_KEY


async def poly_receive_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = (update.message.text or "").strip()
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception:
        pass

    status_msg = await update.message.reply_text("⏳ Processing wallet key...")
    try:
        from security.key_manager import store_private_key
        import db

        result = await asyncio.wait_for(
            asyncio.to_thread(
                store_private_key,
                key_name="poly_hot_wallet",
                raw_input=raw,
                label="Polymarket Wallet",
                chain="polymarket",
            ),
            timeout=10.0,
        )
        db.save_poly_wallet_address(result.get("address", ""))
        await status_msg.edit_text("✅ Wallet saved.\nNow send your *Polymarket API key*.", parse_mode="Markdown")
        return POLY_WAIT_API
    except ValueError as e:
        await status_msg.edit_text(
            f"❌ *Could not store key*\n\n{str(e)}\n\nPlease try again:",
            parse_mode="Markdown",
            reply_markup=_kb([[IKB("🔄 Try Again", callback_data="poly:connect"), IKB("❌ Cancel", callback_data="predictions")]]),
        )
        return ConversationHandler.END
    except asyncio.TimeoutError:
        await status_msg.edit_text(
            "❌ *Timeout while processing key*\n\nPlease try again.",
            parse_mode="Markdown",
            reply_markup=_kb([[IKB("🔄 Try Again", callback_data="poly:connect"), IKB("❌ Cancel", callback_data="predictions")]]),
        )
        return ConversationHandler.END
    except Exception as e:
        log.error("Polymarket wallet setup error: %s", e, exc_info=True)
        await status_msg.edit_text(
            f"❌ *Unexpected error*\n\n`{str(e)[:300]}`\n\nPlease try again.",
            parse_mode="Markdown",
            reply_markup=_kb([[IKB("← Back", callback_data="predictions")]]),
        )
        return ConversationHandler.END


async def poly_receive_api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = (update.message.text or "").strip()
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception:
        pass

    status_msg = await update.message.reply_text("⏳ Processing API key...")
    try:
        from security.key_manager import store_private_key

        await asyncio.wait_for(
            asyncio.to_thread(
                store_private_key,
                key_name="poly_api_key",
                raw_input=raw,
                label="Polymarket API Key",
                chain="api",
            ),
            timeout=10.0,
        )
        await status_msg.edit_text("✅ API key saved.\nNow send your *Polymarket API secret*.", parse_mode="Markdown")
        return POLY_WAIT_SECRET
    except ValueError as e:
        await status_msg.edit_text(f"❌ Could not store API key:\n{str(e)}")
        return ConversationHandler.END
    except asyncio.TimeoutError:
        await status_msg.edit_text("❌ Timeout while processing API key.")
        return ConversationHandler.END
    except Exception as e:
        log.error("Polymarket API key setup error: %s", e, exc_info=True)
        await status_msg.edit_text(f"❌ Could not store API key:\n{str(e)}")
        return ConversationHandler.END


async def poly_receive_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = (update.message.text or "").strip()
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception:
        pass

    status_msg = await update.message.reply_text("⏳ Processing API secret...")
    try:
        from security.key_manager import store_private_key

        await asyncio.wait_for(
            asyncio.to_thread(
                store_private_key,
                key_name="poly_api_secret",
                raw_input=raw,
                label="Polymarket API Secret",
                chain="api",
            ),
            timeout=10.0,
        )
        await status_msg.edit_text("✅ API secret saved.\nNow send your *Polymarket API passphrase*.", parse_mode="Markdown")
        return POLY_WAIT_PASS
    except ValueError as e:
        await status_msg.edit_text(f"❌ Could not store API secret:\n{str(e)}")
        return ConversationHandler.END
    except asyncio.TimeoutError:
        await status_msg.edit_text("❌ Timeout while processing API secret.")
        return ConversationHandler.END
    except Exception as e:
        log.error("Polymarket API secret setup error: %s", e, exc_info=True)
        await status_msg.edit_text(f"❌ Could not store API secret:\n{str(e)}")
        return ConversationHandler.END


async def poly_receive_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = (update.message.text or "").strip()
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception:
        pass

    status_msg = await update.message.reply_text("⏳ Processing passphrase...")
    try:
        from security.key_manager import store_private_key

        await asyncio.wait_for(
            asyncio.to_thread(
                store_private_key,
                key_name="poly_api_passphrase",
                raw_input=raw,
                label="Polymarket API Passphrase",
                chain="api",
            ),
            timeout=10.0,
        )
        await status_msg.edit_text(
            "✅ *Polymarket Connected*\nAll credentials saved securely.",
            parse_mode="Markdown",
            reply_markup=_kb([[IKB("🎯 Open Predictions", callback_data="predictions"), IKB("🏠 Home", callback_data="home")]]),
        )
    except ValueError as e:
        await status_msg.edit_text(f"❌ Could not store passphrase:\n{str(e)}")
    except asyncio.TimeoutError:
        await status_msg.edit_text("❌ Timeout while processing passphrase.")
    except Exception as e:
        log.error("Polymarket passphrase setup error: %s", e, exc_info=True)
        await status_msg.edit_text(f"❌ Could not store passphrase:\n{str(e)}")
    return ConversationHandler.END


hl_setup_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(hl_start_setup, pattern=r"^hl:connect$")],
    states={
        HL_WAIT_CONFIRM: [CallbackQueryHandler(hl_ask_for_key, pattern=r"^hl:setup:ask$")],
        HL_WAIT_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, hl_receive_key)],
    },
    fallbacks=[CommandHandler("cancel", _cancel), CallbackQueryHandler(_cancel, pattern=r"^(perps|home)$")],
    conversation_timeout=120,
)

sol_setup_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(sol_start_setup, pattern=r"^sol:connect$")],
    states={
        SOL_WAIT_CONFIRM: [CallbackQueryHandler(sol_ask_for_key, pattern=r"^sol:setup:ask$")],
        SOL_WAIT_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, sol_receive_key)],
    },
    fallbacks=[CommandHandler("cancel", _cancel), CallbackQueryHandler(_cancel, pattern=r"^(degen|home)$")],
    conversation_timeout=120,
)

poly_setup_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(poly_start_setup, pattern=r"^poly:connect$")],
    states={
        POLY_WAIT_CONFIRM: [CallbackQueryHandler(poly_ask_for_key, pattern=r"^poly:setup:ask$")],
        POLY_WAIT_WALLET_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, poly_receive_key)],
        POLY_WAIT_API: [MessageHandler(filters.TEXT & ~filters.COMMAND, poly_receive_api)],
        POLY_WAIT_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, poly_receive_secret)],
        POLY_WAIT_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, poly_receive_pass)],
    },
    fallbacks=[CommandHandler("cancel", _cancel), CallbackQueryHandler(_cancel, pattern=r"^(predictions|home)$")],
    conversation_timeout=180,
)
