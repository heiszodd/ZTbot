from __future__ import annotations

from datetime import datetime, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import db


def _utc_now():
    return datetime.now(timezone.utc)


async def show_home(query, context):
    now = _utc_now()
    txt = (
        "🤖 Trading Intelligence Bot\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{now:%Y-%m-%d}  {now:%H:%M} UTC\n\n"
        "📈 Perps    🔴/🟢 +0.00\n"
        "🔥 Degen    🔴/🟢 +0.00\n"
        f"🎯 Predictions  {len(db.get_poly_positions()) if hasattr(db, 'get_poly_positions') else 0} open\n\n"
        "Regime: neutral"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Perps", callback_data="perps:home"), InlineKeyboardButton("🔥 Degen", callback_data="degen:home")],
        [InlineKeyboardButton("🎯 Predictions", callback_data="predictions:home"), InlineKeyboardButton("⚙️ Settings", callback_data="settings:home")],
        [InlineKeyboardButton("❓ Help", callback_data="help:home")],
    ])
    await query.message.edit_text(txt, reply_markup=kb)


async def show_perps_home(query, context):
    lines = ["📈 Perps", "━━━━━━━━━━━━━━━━━━━━━━━━"]
    if not db.get_hl_address():
        lines.append("⚠️ Connect HL wallet for live trading")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Scanner", callback_data="nav:scan"), InlineKeyboardButton("🧩 Models", callback_data="nav:models")],
        [InlineKeyboardButton("📓 Journal", callback_data="nav:journal"), InlineKeyboardButton("🔷 Live Account", callback_data="hl:home")],
        [InlineKeyboardButton("🎮 Demo Account", callback_data="demo:perps:home"), InlineKeyboardButton("💰 Risk Settings", callback_data="nav:risk")],
        [InlineKeyboardButton("⏳ Pending", callback_data="perps:pending"), InlineKeyboardButton("📦 Others", callback_data="perps:others")],
        [InlineKeyboardButton("🏠 Home", callback_data="nav:home")],
    ])
    await query.message.edit_text("\n".join(lines), reply_markup=kb)


async def show_pending(query, context):
    db.expire_old_pending_signals()
    rows = db.get_pending_signals(section="perps", active_only=True)
    if not rows:
        text = "⏳ Pending\n━━━━━━━━━━━━━━━━━━━━━━━━\n\nNo pending signals.\nPhase 4 signals will appear here."
    else:
        parts = ["⏳ Pending", "━━━━━━━━━━━━━━━━━━━━━━━━", ""]
        for r in rows[:15]:
            parts.append(f"{r.get('pair','?')} — Phase {r.get('phase',1)}")
            parts.append(f"{r.get('direction','?')}  {r.get('timeframe','?')}")
            parts.append("")
        text = "\n".join(parts)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("← Perps", callback_data="perps:home")]])
    await query.message.edit_text(text, reply_markup=kb)


async def handle_nav_cb(update, context):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "nav:home":
        return await show_home(q, context)
    if data == "perps:home":
        return await show_perps_home(q, context)
    if data == "perps:pending":
        return await show_pending(q, context)
