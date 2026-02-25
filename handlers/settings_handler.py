"""
handlers/settings_handler.py
Settings section screens.
"""

from telegram import InlineKeyboardMarkup as IKM, InlineKeyboardButton as IKB
import db
import logging

log = logging.getLogger(__name__)


def _kb(rows):
    return IKM(rows)


def _btn(l, d):
    return IKB(l, callback_data=d)


async def _edit(query, text, kb):
    try:
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def show_settings(query, context):
    from security.key_manager import key_exists

    try:
        hl_ok = key_exists("hl_api_wallet")
        sol_ok = key_exists("sol_hot_wallet")
        poly_ok = key_exists("poly_hot_wallet")
    except Exception:
        hl_ok = sol_ok = poly_ok = False

    def dot(ok):
        return "🟢" if ok else "🔴"

    text = (
        f"⚙️ *Settings*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"*Connected Wallets*\n"
        f"  📈 Hyperliquid  {dot(hl_ok)}\n"
        f"  🔥 Solana       {dot(sol_ok)}\n"
        f"  🎯 Polymarket   {dot(poly_ok)}\n\n"
        f"Tap a section below to configure."
    )

    kb = _kb(
        [
            [_btn("🔑 Wallets", "settings:wallets"), _btn("🔔 Alerts", "settings:alerts")],
            [_btn("⚡ Buy Presets", "settings:presets"), _btn("💰 Risk", "settings:risk")],
            [_btn("🔐 Security", "settings:security"), _btn("📊 Limits", "settings:limits")],
            [_btn("🛡 MEV", "settings:mev"), _btn("🎨 Display", "settings:display")],
            [_btn("🏠 Home", "home")],
        ]
    )
    await _edit(query, text, kb)


async def show_wallet_status(query, context):
    from security.key_manager import key_exists

    try:
        hl_ok = key_exists("hl_api_wallet")
        sol_ok = key_exists("sol_hot_wallet")
        poly_ok = key_exists("poly_hot_wallet")
    except Exception:
        hl_ok = sol_ok = poly_ok = False

    def status(ok):
        return "🟢 Connected" if ok else "🔴 Not Connected"

    hl_addr = db.get_hl_address() or ""
    sol_addr = db.get_sol_wallet_address() or ""
    hl_short = f"{hl_addr[:8]}...{hl_addr[-6:]}" if hl_addr else "—"
    sol_short = f"{sol_addr[:8]}...{sol_addr[-6:]}" if sol_addr else "—"

    text = (
        f"🔑 *Connected Wallets*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"*📈 Hyperliquid*\n"
        f"   {status(hl_ok)}\n"
        f"   {hl_short}\n\n"
        f"*🔥 Solana*\n"
        f"   {status(sol_ok)}\n"
        f"   {sol_short}\n\n"
        f"*🎯 Polymarket*\n"
        f"   {status(poly_ok)}\n\n"
        f"Tap to connect or reconnect."
    )

    kb = _kb(
        [
            [_btn("📈 " + ("Reconnect HL" if hl_ok else "Connect HL"), "hl:connect")],
            [_btn("🔥 " + ("Reconnect Solana" if sol_ok else "Connect Solana"), "sol:connect")],
            [_btn("🎯 " + ("Reconnect Polymarket" if poly_ok else "Connect Polymarket"), "poly:connect")],
            [_btn("← Settings", "settings")],
        ]
    )
    await _edit(query, text, kb)


async def show_limits(query, context):
    from security.spending_limits import MAX_SINGLE_TRADE_USD, MAX_DAILY_SPEND_USD

    text = (
        f"📊 *Spending Limits*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"*Single Trade Max*\n"
        f"  Hyperliquid: ${MAX_SINGLE_TRADE_USD.get('hyperliquid', 1000):,.0f}\n"
        f"  Solana:      ${MAX_SINGLE_TRADE_USD.get('solana', 500):,.0f}\n"
        f"  Polymarket:  ${MAX_SINGLE_TRADE_USD.get('polymarket', 200):,.0f}\n\n"
        f"*Daily Spend Max*\n"
        f"  Hyperliquid: ${MAX_DAILY_SPEND_USD.get('hyperliquid', 3000):,.0f}\n"
        f"  Solana:      ${MAX_DAILY_SPEND_USD.get('solana', 1500):,.0f}\n"
        f"  Polymarket:  ${MAX_DAILY_SPEND_USD.get('polymarket', 500):,.0f}\n\n"
        f"_These limits are hard-coded for safety.\nContact admin to change._"
    )
    kb = _kb([[_btn("← Settings", "settings")]])
    await _edit(query, text, kb)


async def show_display_settings(query, context):
    from config import CHAT_ID

    settings = db.get_user_settings(int(CHAT_ID))
    chart_style = settings.get("chart_style", "detailed")
    alert_verbosity = settings.get("alert_verbosity", "full")
    emoji_density = settings.get("emoji_density", "normal")
    theme = settings.get("theme", "dark")

    chart_icon = "📊" if chart_style == "detailed" else "📉"
    alert_icon = "🔔" if alert_verbosity == "full" else "🔕" if alert_verbosity == "minimal" else "🔉"
    emoji_icon = "😀" if emoji_density == "normal" else "📝"
    theme_icon = "🌙" if theme == "dark" else "☀️"

    text = (
        f"🎨 *Display Settings*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{chart_icon} *Chart Style:* {chart_style.title()}\n"
        f"   How much detail in analysis messages\n\n"
        f"{alert_icon} *Alert Verbosity:* {alert_verbosity.title()}\n"
        f"   Amount of info in alerts\n\n"
        f"{emoji_icon} *Emoji Density:* {emoji_density.title()}\n"
        f"   Emoji usage in messages\n\n"
        f"{theme_icon} *Theme:* {theme.title()}\n"
        f"   Message formatting style\n"
    )

    chart_next = "compact" if chart_style == "detailed" else "detailed"
    alert_next = {"full": "compact", "compact": "minimal", "minimal": "full"}.get(alert_verbosity, "full")
    emoji_next = "minimal" if emoji_density == "normal" else "normal"
    theme_next = "light" if theme == "dark" else "dark"

    kb = _kb([
        [_btn(f"📊 Chart: {chart_next.title()}", f"display:set:chart_style:{chart_next}")],
        [_btn(f"🔔 Alerts: {alert_next.title()}", f"display:set:alert_verbosity:{alert_next}")],
        [_btn(f"😀 Emoji: {emoji_next.title()}", f"display:set:emoji_density:{emoji_next}")],
        [_btn(f"🌓 Theme: {theme_next.title()}", f"display:set:theme:{theme_next}")],
        [_btn("← Settings", "settings")],
    ])
    await _edit(query, text, kb)


async def handle_display_setting(query, context, key, value):
    from config import CHAT_ID

    try:
        db.update_user_setting(key, value, int(CHAT_ID))
        await query.answer(f"✅ {key.replace('_', ' ').title()} set to {value}", show_alert=False)
    except Exception as e:
        await query.answer(f"Failed: {e}", show_alert=True)
    await show_display_settings(query, context)
