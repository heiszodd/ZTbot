from __future__ import annotations

from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest

import db


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _edit_or_send(query, text: str, keyboard: InlineKeyboardMarkup) -> None:
    try:
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    except BadRequest as exc:
        if "Message is not modified" in str(exc):
            return
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    except Exception:
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def show_perps_home(query, context):
    hl = db.get_hl_address()
    pnl = (getattr(db, "get_hl_pnl_today", lambda: 0.0)() or 0.0)
    txt = (
        "📈 *Perps*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"HL Wallet: {'🟢 Connected' if hl else '🔴 Not connected'}\n"
        f"Today PnL: ${pnl:+.2f}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Scanner", callback_data="perps:scanner"), InlineKeyboardButton("🧩 Models", callback_data="perps:models")],
        [InlineKeyboardButton("📓 Journal", callback_data="perps:journal"), InlineKeyboardButton("🔷 Live Account", callback_data="perps:live")],
        [InlineKeyboardButton("🎮 Demo", callback_data="perps:demo"), InlineKeyboardButton("💰 Risk", callback_data="perps:risk")],
        [InlineKeyboardButton("⏳ Pending", callback_data="perps:pending"), InlineKeyboardButton("📦 Others", callback_data="perps:others")],
        [InlineKeyboardButton("🏠 Home", callback_data="nav:home")],
    ])
    await _edit_or_send(query, txt, kb)


async def show_perps_scanner(query, context):
    from handlers.alerts import run_scanner

    await run_scanner(context)
    await _edit_or_send(query, "🔍 *Perps Scanner*\n\nScan job started.", InlineKeyboardMarkup([[InlineKeyboardButton("← Perps", callback_data="perps:home")]]))


async def show_perps_models(query, context):
    from handlers.wizard import start_wizard

    context.user_data["in_conversation"] = True
    await start_wizard(query, context)


async def show_perps_demo(query, context):
    txt = "🎮 *Perps Demo*\n━━━━━━━━━━━━━━━━━━━━━━━━\nDemo account summary."
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("New Demo Trade", callback_data="hl:demo:0"), InlineKeyboardButton("Positions", callback_data="hl:positions")],
        [InlineKeyboardButton("History", callback_data="hl:history"), InlineKeyboardButton("Reset", callback_data="perps:demo")],
        [InlineKeyboardButton("← Perps", callback_data="perps:home")],
    ])
    await _edit_or_send(query, txt, kb)


async def show_perps_pending(query, context):
    await _edit_or_send(query, "⏳ *Pending Signals*", InlineKeyboardMarkup([[InlineKeyboardButton("← Perps", callback_data="perps:home")]]))


async def show_perps_others(query, context):
    await _edit_or_send(query, "📦 *Perps Others*", InlineKeyboardMarkup([[InlineKeyboardButton("← Perps", callback_data="perps:home")]]))


async def show_degen_home(query, context):
    wallet = db.get_solana_wallet()
    txt = "🔥 *Degen*\n━━━━━━━━━━━━━━━━━━━━━━━━\n" + ("🟢 Wallet connected" if wallet else "🔴 Wallet not connected")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Scanner", callback_data="degen:scanner"), InlineKeyboardButton("🔬 Scan Contract", callback_data="degen:scan_contract")],
        [InlineKeyboardButton("🧩 Models", callback_data="degen:models"), InlineKeyboardButton("💼 Live Wallet", callback_data="degen:live")],
        [InlineKeyboardButton("🎮 Demo", callback_data="degen:demo"), InlineKeyboardButton("👣 Wallet Tracking", callback_data="degen:wallet_tracking")],
        [InlineKeyboardButton("📋 Watchlist", callback_data="degen:watchlist"), InlineKeyboardButton("📦 Others", callback_data="degen:others")],
        [InlineKeyboardButton("🏠 Home", callback_data="nav:home")],
    ])
    await _edit_or_send(query, txt, kb)


async def show_degen_others(query, context):
    await _edit_or_send(query, "📦 *Degen Others*", InlineKeyboardMarkup([[InlineKeyboardButton("← Degen", callback_data="degen:home")]]))


async def show_predictions_home(query, context):
    from security.key_manager import key_exists

    poly_connected = key_exists("poly_hot_wallet")
    try:
        open_live = db.count_open_poly_positions()
        open_demo = db.count_open_poly_demo_trades()
        active_models = db.count_active_prediction_models()
    except Exception:
        open_live = open_demo = active_models = 0

    wallet_line = "⚠️ _Live trading not connected_\n"
    if poly_connected:
        try:
            from engine.polymarket.executor import get_poly_client

            client = await get_poly_client()
            wallet_line = f"💰 Balance: ${float(client.get_balance() or 0):.2f} USDC\n"
        except Exception:
            wallet_line = "💰 Balance: checking...\n"

    text = (
        "🎯 *Predictions*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{wallet_line}"
        f"Live Positions: {open_live}\n"
        f"Demo Positions: {open_demo}\n"
        f"Active Models:  {active_models}\n"
    )
    if not poly_connected:
        text += "\nTap *Live Predictions* to connect\nyour Polymarket wallet and start\ntrading prediction markets."

    keyboard_rows = [
        [InlineKeyboardButton("🔍 Scanner", callback_data="predictions:scanner"), InlineKeyboardButton("⭐ Watchlist", callback_data="predictions:watchlist")],
        [InlineKeyboardButton("💼 Live Predictions" + (" ✅" if poly_connected else " 🔴"), callback_data="predictions:live")],
        [InlineKeyboardButton("🎮 Demo Predictions", callback_data="predictions:demo"), InlineKeyboardButton("🧩 Models", callback_data="predictions:models")],
        [InlineKeyboardButton("📦 Others", callback_data="predictions:others"), InlineKeyboardButton("🏠 Home", callback_data="nav:home")],
    ]
    await _edit_or_send(query, text, InlineKeyboardMarkup(keyboard_rows))


async def show_predictions_others(query, context):
    await _edit_or_send(query, "📦 *Predictions Others*", InlineKeyboardMarkup([[InlineKeyboardButton("← Predictions", callback_data="predictions:home")]]))


async def show_settings_home(query, context):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Connected Wallets", callback_data="settings:wallets"), InlineKeyboardButton("🔔 Notifications", callback_data="settings:notifications")],
        [InlineKeyboardButton("🏠 Home", callback_data="nav:home")],
    ])
    await _edit_or_send(query, "⚙️ *Settings*", kb)


async def show_wallet_settings(query, context):
    from security.key_manager import key_exists

    hl_ok = key_exists("hl_api_wallet")
    sol_ok = key_exists("sol_hot_wallet")
    poly_ok = key_exists("poly_hot_wallet")

    def status(ok):
        return "🟢 Connected" if ok else "🔴 Not Connected"

    text = (
        "🔑 *Connected Wallets*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📈 *Hyperliquid (Perps)*\n"
        f"   {status(hl_ok)}\n\n"
        "🔥 *Solana (Degen)*\n"
        f"   {status(sol_ok)}\n\n"
        "🎯 *Polymarket (Predictions)*\n"
        f"   {status(poly_ok)}\n\n"
        "_Tap a wallet to connect or\nview details._"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 " + status(hl_ok), callback_data="perps:live" if hl_ok else "hl:setup:start")],
        [InlineKeyboardButton("🔥 " + status(sol_ok), callback_data="degen:live" if sol_ok else "sol:setup:start")],
        [InlineKeyboardButton("🎯 " + status(poly_ok), callback_data="predictions:live" if poly_ok else "poly:setup:start")],
        [InlineKeyboardButton("← Settings", callback_data="settings:home")],
    ])
    await _edit_or_send(query, text, keyboard)


async def show_help_home(query, context):
    await _edit_or_send(query, "❓ *Help*", InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="nav:home")]]))


async def show_help_topic(query, context, topic: str):
    await _edit_or_send(query, f"❓ *Help — {topic.title()}*", InlineKeyboardMarkup([[InlineKeyboardButton("← Help", callback_data="help:home")]]))
