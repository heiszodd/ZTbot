import logging

import db
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, ContextTypes, MessageHandler, filters
from telegram import Update

from engine.polymarket.demo_trading import open_poly_demo_trade
from engine.polymarket.market_reader import fetch_market_by_id, fetch_markets
from engine.polymarket.scanner import format_scanner_results, run_market_scanner
from engine.polymarket.sentiment import format_sentiment_dashboard, get_crypto_sentiment
from security.auth import require_auth, require_auth_callback
from security.rate_limiter import check_command_rate

log = logging.getLogger(__name__)

POLY_INTRO = 0
POLY_AWAIT_KEY = 1
POLY_AWAIT_APIKEY = 2
POLY_AWAIT_SECRET = 3
POLY_AWAIT_PASS = 4


async def show_polymarket_home(query, context):
    await show_predictions_live_home(query, context)


async def show_predictions_live_home(query, context) -> None:
    from security.key_manager import key_exists

    poly_connected = key_exists("poly_hot_wallet")
    if not poly_connected:
        text = (
            "💼 *Live Predictions*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Connect your Polymarket wallet to\n"
            "trade real prediction markets.\n\n"
            "*What you need:*\n"
            "• USDC on Polygon network\n"
            "• Polymarket account\n"
            "• Your wallet seed phrase or\n  private key\n\n"
            "*Setup takes about 5 minutes.*\nTap below to begin."
        )
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔑 Connect Polymarket Wallet", callback_data="poly:setup:start")],
                [InlineKeyboardButton("🎮 Use Demo Instead", callback_data="predictions:demo")],
                [InlineKeyboardButton("← Predictions", callback_data="predictions:home")],
            ]
        )
        try:
            await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
        except Exception:
            await query.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
        return

    try:
        from engine.polymarket.executor import get_poly_client

        client = await get_poly_client()
        balance = float(client.get_balance() or 0)
    except Exception as e:
        log.warning("Poly balance fetch: %s", e)
        balance = 0.0

    positions = db.get_open_poly_live_trades()
    text = f"💼 *Live Predictions*\n━━━━━━━━━━━━━━━━━━━━━━━━\nBalance: ${balance:.2f} USDC\nOpen:    {len(positions)} positions\n\n"
    if positions:
        text += "*Open Positions:*\n"
        for pos in positions[:5]:
            q = pos.get("question", "")
            short_q = q[:45] + "..." if len(q) > 45 else q
            position = pos.get("position", "YES")
            entry = float(pos.get("entry_price", 0))
            current = float(pos.get("current_price", entry))
            pnl = float(pos.get("pnl_usd", 0))
            text += f"\n{'🟢' if pnl >= 0 else '🔴'} *{position}* — {short_q}\n   Entry: {entry*100:.0f}%  Now: {current*100:.0f}%  PnL: ${pnl:+.2f}\n"
    else:
        text += "_No open positions.\nUse the Scanner to find markets._"

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔄 Refresh", callback_data="predictions:live"), InlineKeyboardButton("📊 All Positions", callback_data="predictions:live:positions")],
            [InlineKeyboardButton("🔍 Find Market", callback_data="predictions:scanner"), InlineKeyboardButton("📜 History", callback_data="predictions:live:history")],
            [InlineKeyboardButton("🔑 Wallet Settings", callback_data="predictions:live:wallet_settings")],
            [InlineKeyboardButton("← Predictions", callback_data="predictions:home")],
        ]
    )
    try:
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    except Exception:
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def show_poly_scanner(query, context):
    results = await run_market_scanner()
    await query.message.reply_text(format_scanner_results(results or {}), parse_mode="Markdown")


async def show_poly_sentiment(query, context):
    sentiment = await get_crypto_sentiment()
    await query.message.reply_text(format_sentiment_dashboard(sentiment), parse_mode="Markdown")


async def show_poly_demo_home(query, context):
    rows = db.get_poly_demo_trades()
    if not rows:
        return await query.message.reply_text("🎮 No Polymarket demo trades yet.")
    txt = "🎮 *Polymarket Demo Trades*\n━━━━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(
        [f"#{r['id']} {r['position']} {r.get('question','')[:45]} — {r['status']} {float(r.get('pnl_usd') or 0):+.2f}$" for r in rows[:20]]
    )
    await query.message.reply_text(txt, parse_mode="Markdown")


show_poly_watchlist = show_poly_sentiment


async def poly_setup_start(update, context) -> int:
    query = update.callback_query
    await query.answer()
    text = (
        "🎯 *Connect Polymarket*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*What you need before starting:*\n\n"
        "1️⃣ A wallet with USDC on Polygon\n\n"
        "2️⃣ Wallet connected to polymarket.com\n\n"
        "3️⃣ Polymarket API credentials\n\n"
        "*Ready? Tap Continue.*"
    )
    await query.message.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("✅ Continue — I'm ready", callback_data="poly:setup:key")],
                [InlineKeyboardButton("🎮 Use Demo Instead", callback_data="predictions:demo"), InlineKeyboardButton("❌ Cancel", callback_data="predictions:home")],
            ]
        ),
    )
    return POLY_INTRO


async def poly_setup_ask_key(update, context) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        "🎯 *Connect Polymarket*\nStep 5 of 5 — Enter Wallet Key\n\n"
        "Send your Polygon wallet seed phrase OR private key.\n\n"
        "*Option A — Seed Phrase*\nYour 12 or 24 word recovery phrase.\n\n"
        "*Option B — Private Key*\nHex private key (64 chars, 0x prefix).\n\n"
        "*How to get it in MetaMask:*\nAccount Details → Export Private Key\n\n"
        "⚠️ Message deleted immediately after sending.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="predictions:home")]]),
    )
    return POLY_AWAIT_KEY


async def poly_receive_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text or ""
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception as exc:
        log.warning("Could not delete poly key message: %s", exc)
    msg = await update.message.reply_text("⏳ Processing key...")
    try:
        from security.key_manager import store_private_key

        result = store_private_key("poly_hot_wallet", raw, "Polymarket Wallet", chain="polymarket")
        context.user_data["poly_address"] = result["address"]
        db.save_poly_wallet_address(result["address"])
        await msg.edit_text("✅ *Wallet Key Stored*\n\nNow send your Polymarket *API Key*.", parse_mode="Markdown")
        return POLY_AWAIT_APIKEY
    except ValueError as e:
        await msg.edit_text(f"❌ *Error*\n\n{e}", parse_mode="Markdown")
        return POLY_AWAIT_KEY


async def poly_receive_apikey(update, context) -> int:
    raw = (update.message.text or "").strip()
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception as exc:
        log.warning("Could not delete poly apikey message: %s", exc)
    from security.key_manager import store_private_key

    store_private_key("poly_api_key", raw, "Polymarket API Key", chain="polymarket")
    await update.message.reply_text("✅ API Key Stored. Now send API Secret.")
    return POLY_AWAIT_SECRET


async def poly_receive_secret(update, context) -> int:
    raw = (update.message.text or "").strip()
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception as exc:
        log.warning("Could not delete poly secret message: %s", exc)
    from security.key_manager import store_private_key

    store_private_key("poly_api_secret", raw, "Polymarket API Secret", chain="polymarket")
    await update.message.reply_text("✅ API Secret Stored. Now send API Passphrase.")
    return POLY_AWAIT_PASS


async def poly_receive_passphrase(update, context) -> int:
    raw = (update.message.text or "").strip()
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception as exc:
        log.warning("Could not delete poly passphrase message: %s", exc)

    from security.key_manager import store_private_key

    store_private_key("poly_api_passphrase", raw, "Polymarket API Passphrase", chain="polymarket")
    msg = await update.message.reply_text("⏳ Completing setup...")
    try:
        from engine.polymarket.executor import get_poly_client

        client = await get_poly_client()
        balance_line = f"Balance: ${float(client.get_balance() or 0):.2f} USDC"
    except Exception as e:
        log.warning("Poly connection test: %s", e)
        balance_line = "Balance: (check polymarket.com)"
    address = context.user_data.get("poly_address", "Connected")
    await msg.edit_text(
        f"✅ *Polymarket Connected!*\n━━━━━━━━━━━━━━━━━━━━━━━━\nAddress: `{address[:8]}...{address[-6:]}`\n{balance_line}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💼 Live Predictions", callback_data="predictions:live")], [InlineKeyboardButton("🏠 Home", callback_data="nav:home")]]),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def poly_setup_cancel(update, context) -> int:
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
    return ConversationHandler.END


poly_setup_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(poly_setup_start, pattern="^poly:setup:start$")],
    states={
        POLY_INTRO: [CallbackQueryHandler(poly_setup_ask_key, pattern="^poly:setup:key$")],
        POLY_AWAIT_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, poly_receive_key)],
        POLY_AWAIT_APIKEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, poly_receive_apikey)],
        POLY_AWAIT_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, poly_receive_secret)],
        POLY_AWAIT_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, poly_receive_passphrase)],
    },
    fallbacks=[CallbackQueryHandler(poly_setup_cancel, pattern="^predictions:home$"), CommandHandler("cancel", poly_setup_cancel)],
    per_message=False,
    per_chat=True,
)


@require_auth
async def handle_poly_text(update, context):
    return


@require_auth_callback
async def handle_polymarket_cb(update, context):
    q = update.callback_query
    uid = q.from_user.id if q and q.from_user else 0
    allowed, reason = check_command_rate(uid)
    if not allowed:
        await q.answer(reason, show_alert=True)
        return
    await q.answer()
    data = q.data
    if data in {"poly:home", "nav:polymarket_home"}:
        return await show_polymarket_home(q, context)
    if data == "poly:scanner":
        return await show_poly_scanner(q, context)
    if data == "poly:sentiment":
        return await show_poly_sentiment(q, context)
    if data == "poly:demo_trades":
        return await show_poly_demo_home(q, context)
