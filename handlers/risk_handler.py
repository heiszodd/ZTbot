import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import db
from engine.notification_filter import get_pattern_keys
from engine.risk_engine import calculate_position_size, calculate_rr
from engine.session_checklist import run_pre_session_checklist

log = logging.getLogger(__name__)

RISK_CYCLES = {
    "risk_pct": ("risk_per_trade_pct", [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]),
    "daily_limit": ("max_daily_loss_pct", [2.0, 3.0, 5.0, 10.0]),
    "max_trades": ("max_open_trades", [1, 2, 3, 4, 5]),
    "min_rr": ("risk_reward_min", [1.0, 1.5, 2.0, 2.5, 3.0]),
    "min_grade": ("min_quality_grade", ["D", "C", "B", "A", "A+"]),
}


async def show_risk_home(query, context):
    settings = db.get_risk_settings()
    tracker = db.get_daily_tracker()
    open_trades = db.get_open_demo_trades()
    account = settings["account_size"]
    risk_pct = settings["risk_per_trade_pct"]
    daily_limit = settings["max_daily_loss_pct"]
    max_trades = settings["max_open_trades"]
    min_grade = settings.get("min_quality_grade", "C")
    daily_used = tracker.get("realised_pnl", 0)
    daily_pct = abs(daily_used) / account * 100 if daily_used < 0 and account > 0 else 0
    risk_per_trade = account * risk_pct / 100
    text = (
        f"💰 *Risk Management*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Account size:    ${account:,.2f}\n"
        f"Risk per trade:  {risk_pct}% (${risk_per_trade:.2f})\n"
        f"Daily loss max:  {daily_limit}%\n"
        f"Max open trades: {max_trades}\n"
        f"Min RR:          {settings['risk_reward_min']}:1\n"
        f"Min alert grade: {min_grade} (lower grades suppressed)\n\n"
        f"*Today*\n"
        f"Open trades: {len(open_trades)}/{max_trades}\n"
        f"Daily P&L:   ${daily_used:+.2f} ({daily_pct:.1f}% of limit used)\n"
        f"Limit hit:   {'🚫 YES' if tracker.get('daily_loss_hit') else '✅ No'}\n\n"
        f"Risk checks: {'✅ Enabled' if settings['enabled'] else '⚠️ Disabled'}"
    )
    buttons = [
        [InlineKeyboardButton(f"💵 Account Size: ${account:,.0f}", callback_data="risk:set:account_size")],
        [InlineKeyboardButton(f"📊 Risk/Trade: {risk_pct}%", callback_data="risk:cycle:risk_pct")],
        [InlineKeyboardButton(f"🛑 Daily Limit: {daily_limit}%", callback_data="risk:cycle:daily_limit")],
        [InlineKeyboardButton(f"📂 Max Trades: {max_trades}", callback_data="risk:cycle:max_trades")],
        [InlineKeyboardButton(f"⚖️ Min RR: {settings['risk_reward_min']}:1", callback_data="risk:cycle:min_rr")],
        [InlineKeyboardButton(f"🎯 Min Grade: {min_grade}", callback_data="risk:cycle:min_grade")],
        [InlineKeyboardButton("✅ Enable" if not settings["enabled"] else "⏸ Disable", callback_data="risk:toggle")],
        [InlineKeyboardButton("🔄 Reset Daily Tracker", callback_data="risk:reset_daily")],
        [InlineKeyboardButton("🏠 Perps Home", callback_data="nav:perps_home")],
    ]
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))


async def handle_risk_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "nav:risk":
        await show_risk_home(q, context)
        return
    if data.startswith("risk:cycle:"):
        key = data.split(":")[-1]
        field, values = RISK_CYCLES[key]
        settings = db.get_risk_settings()
        cur = settings.get(field)
        idx = values.index(cur) if cur in values else 0
        db.update_risk_settings({field: values[(idx + 1) % len(values)]})
        await show_risk_home(q, context)
        return
    if data == "risk:toggle":
        settings = db.get_risk_settings()
        db.update_risk_settings({"enabled": not settings.get("enabled", True)})
        await show_risk_home(q, context)
        return
    if data == "risk:reset_daily":
        settings = db.get_risk_settings()
        db.update_daily_tracker({"realised_pnl": 0, "open_risk": 0, "trades_taken": 0, "daily_loss_hit": False, "starting_balance": settings.get("account_size"), "current_balance": settings.get("account_size")})
        await show_risk_home(q, context)
        return
    if data == "risk:set:account_size":
        context.user_data["risk_waiting_account"] = True
        await q.message.reply_text("💵 Enter your account size in USD:\nExample: 500 or 1000 or 5000")
        return
    if data == "nav:checklist":
        await run_pre_session_checklist(context)
        return
    if data == "nav:notif_filter":
        await show_notification_filter(q)
        return
    if data.startswith("filter:override:"):
        _, _, model_id, pair = data.split(":", 3)
        key = f"model_{model_id}"
        db.update_notification_pattern(key, {"override": True, "suppressed": False})
        await q.message.reply_text(f"✅ Override enabled for {pair}/{model_id}. Next matching alert will pass.")
        return
    if data.startswith("filter:toggle:"):
        key = data.replace("filter:toggle:", "")
        pattern = db.get_notification_pattern(key)
        db.update_notification_pattern(key, {"override": not pattern.get("override", False), "suppressed": False if pattern.get("override") else pattern.get("suppressed", False)})
        await show_notification_filter(q)


async def handle_risk_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if context.user_data.get("risk_waiting_account"):
        try:
            value = float(text.replace(",", ""))
            if value <= 0:
                raise ValueError
            db.update_risk_settings({"account_size": value})
            context.user_data["risk_waiting_account"] = False
            await update.message.reply_text(f"✅ Account size updated to ${value:,.2f}")
        except Exception:
            await update.message.reply_text("❌ Invalid number. Please enter a numeric account size like 1000")
        return

    if not text.lower().startswith("risk "):
        return
    parts = text.split()
    if len(parts) != 6:
        await update.message.reply_text("Usage: risk BTCUSDT 43200 42800 44500 long")
        return
    _, pair, entry, sl, tp1, direction = parts
    try:
        entry_f, sl_f, tp_f = float(entry), float(sl), float(tp1)
        direction_fmt = "Bullish" if direction.lower() in {"long", "bullish", "buy"} else "Bearish"
        settings = db.get_risk_settings()
        pos = calculate_position_size(settings["account_size"], settings["risk_per_trade_pct"], entry_f, sl_f)
        rr = calculate_rr(entry_f, sl_f, tp_f, direction_fmt)
        if "error" in pos:
            await update.message.reply_text(f"❌ {pos['error']}")
            return
        await update.message.reply_text(
            f"💳 *Risk Card*\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Pair: {pair}\nDirection: {direction_fmt}\n"
            f"Entry: {entry_f}\nSL: {sl_f}\nTP1: {tp_f}\n"
            f"Position Size: {pos['position_size']:.4f} units\n"
            f"Risk Amount: ${pos['risk_amount']:.2f}\n"
            f"Leverage Needed: {pos['leverage_needed']:.2f}x\n"
            f"RR: {rr:.2f}:1",
            parse_mode="Markdown",
        )
    except Exception:
        await update.message.reply_text("❌ Could not parse risk command. Example: risk BTCUSDT 43200 42800 44500 long")


async def show_notification_filter(query):
    patterns = [p for p in db.get_all_notification_patterns() if p.get("suppressed")]
    if not patterns:
        await query.message.edit_text("🔔 *Notification Filter*\n━━━━━━━━━━━━━━━━━━━━━━━━\nNo suppressed patterns yet.", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Perps Home", callback_data="nav:perps_home")]]))
        return
    lines = ["🔔 *Notification Filter*", "━━━━━━━━━━━━━━━━━━━━━━━━", "Suppressed patterns:", ""]
    rows = []
    for p in patterns[:20]:
        lines.append(f"• `{p['pattern_key']}` — {p.get('action_rate',0):.0%} action ({p.get('total_alerts',0)} alerts)")
        rows.append([InlineKeyboardButton(f"{'✅' if p.get('override') else '🚫'} {p['pattern_key'][:28]}", callback_data=f"filter:toggle:{p['pattern_key']}")])
    rows.append([InlineKeyboardButton("🏠 Perps Home", callback_data="nav:perps_home")])
    await query.message.edit_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
