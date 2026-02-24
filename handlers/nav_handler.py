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
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("← Perps", callback_data="perps:home")]])
    await _edit_or_send(query, "🔍 *Perps Scanner*\n\nScan job started.", kb)


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
    getattr(db, "expire_old_pending_signals", lambda: None)()
    rows = getattr(db, "get_pending_signals", lambda **_: [])(section="perps", active_only=True)
    lines = ["⏳ *Pending Signals*", "━━━━━━━━━━━━━━━━━━━━━━━━", ""]
    buttons = []
    if not rows:
        lines.append("No pending signals.")
    else:
        for r in rows[:20]:
            sid = int(r.get("id", 0))
            lines.append(f"• {r.get('pair','?')} | P{r.get('phase','?')} | {r.get('direction','?')} | {r.get('created_at','')}")
            buttons.append([
                InlineKeyboardButton("📋 View Plan", callback_data=f"pending:plan:{sid}"),
                InlineKeyboardButton("❌ Dismiss", callback_data=f"pending:dismiss:{sid}"),
            ])
    buttons.append([InlineKeyboardButton("← Perps", callback_data="perps:home")])
    await _edit_or_send(query, "\n".join(lines), InlineKeyboardMarkup(buttons))


async def show_perps_others(query, context):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("← Perps", callback_data="perps:home")]])
    await _edit_or_send(query, "📦 *Perps Others*", kb)


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
    count = len(getattr(db, "get_poly_positions", lambda: [])())
    txt = f"🎯 *Predictions*\n━━━━━━━━━━━━━━━━━━━━━━━━\nOpen positions: {count}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Scanner", callback_data="predictions:scanner"), InlineKeyboardButton("📋 Watchlist", callback_data="predictions:watchlist")],
        [InlineKeyboardButton("💼 Live", callback_data="predictions:live"), InlineKeyboardButton("🎮 Demo", callback_data="predictions:demo")],
        [InlineKeyboardButton("🧩 Models", callback_data="predictions:models"), InlineKeyboardButton("📦 Others", callback_data="predictions:others")],
        [InlineKeyboardButton("🏠 Home", callback_data="nav:home")],
    ])
    await _edit_or_send(query, txt, kb)


async def show_predictions_others(query, context):
    await _edit_or_send(query, "📦 *Predictions Others*", InlineKeyboardMarkup([[InlineKeyboardButton("← Predictions", callback_data="predictions:home")]]))


async def show_settings_home(query, context):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Connected Wallets", callback_data="settings:wallets"), InlineKeyboardButton("🔔 Notifications", callback_data="settings:notifications")],
        [InlineKeyboardButton("🧩 Presets", callback_data="settings:presets"), InlineKeyboardButton("🖥 Display", callback_data="settings:display")],
        [InlineKeyboardButton("🔒 Security", callback_data="settings:security"), InlineKeyboardButton("🗄 Data", callback_data="settings:data")],
        [InlineKeyboardButton("⚙️ Mode", callback_data="settings:mode"), InlineKeyboardButton("ℹ️ About", callback_data="settings:about")],
        [InlineKeyboardButton("🏠 Home", callback_data="nav:home")],
    ])
    await _edit_or_send(query, "⚙️ *Settings*", kb)


async def show_wallet_settings(query, context):
    hl = "🟢 Connected" if db.get_hl_address() else "🔴 Not connected"
    sol = "🟢 Connected" if db.get_solana_wallet() else "🔴 Not connected"
    poly = "🟢 Connected" if getattr(db, "get_poly_wallet", lambda: None)() else "🔴 Not connected"
    text = f"🔑 *Wallet Connections*\n\nHyperliquid: {hl}\nSolana: {sol}\nPolymarket: {poly}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("HL Fix", callback_data="hl:setup:start"), InlineKeyboardButton("SOL Fix", callback_data="sol:setup:start")],
        [InlineKeyboardButton("POLY Fix", callback_data="poly:setup:start")],
        [InlineKeyboardButton("← Settings", callback_data="settings:home")],
    ])
    await _edit_or_send(query, text, kb)


async def show_help_home(query, context):
    topics = ["perps", "degen", "predictions", "phases", "models", "risk", "wallets", "commands"]
    rows = [[InlineKeyboardButton(t.title(), callback_data=f"help:{t}")] for t in topics]
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="nav:home")])
    await _edit_or_send(query, "❓ *Help*", InlineKeyboardMarkup(rows))


async def show_help_topic(query, context, topic: str):
    await _edit_or_send(query, f"❓ *Help — {topic.title()}*", InlineKeyboardMarkup([[InlineKeyboardButton("← Help", callback_data="help:home")]]))
