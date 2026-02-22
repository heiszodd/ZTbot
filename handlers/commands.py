import logging
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters

import db
import engine
import formatters
import prices as px
from config import CHAT_ID, SUPPORTED_PAIRS, SUPPORTED_TIMEFRAMES, SUPPORTED_SESSIONS, SUPPORTED_BIASES

log = logging.getLogger(__name__)

GOAL_SELECT, GOAL_MANUAL = range(2)
BUDGET_TARGET_SELECT, BUDGET_TARGET_MANUAL, BUDGET_LOSS_SELECT, BUDGET_LOSS_MANUAL, BUDGET_CONFIRM = range(10, 15)


def _guard(update: Update) -> bool:
    return update.effective_chat and update.effective_chat.id == CHAT_ID


def landing_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Perps Trading", callback_data="nav:perps_home")],
        [InlineKeyboardButton("🎰 Degen Zone", callback_data="nav:degen_home")],
        [InlineKeyboardButton("⚡ System Status", callback_data="nav:status")],
    ])


def perps_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="nav:home"), InlineKeyboardButton("⚙️ Models", callback_data="nav:models")],
        [InlineKeyboardButton("🧪 Backtest", callback_data="backtest:start"), InlineKeyboardButton("📊 Stats", callback_data="nav:stats")],
        [InlineKeyboardButton("⏳ Pending", callback_data="nav:pending"), InlineKeyboardButton("🛡️ Discipline", callback_data="nav:discipline")],
        [InlineKeyboardButton("📋 Alert Log", callback_data="nav:alerts"), InlineKeyboardButton("🔍 Scan", callback_data="nav:scan")],
        [InlineKeyboardButton("📓 Journal", callback_data="nav:journal"), InlineKeyboardButton("📊 Charts", callback_data="nav:charts")],
        [InlineKeyboardButton("📰 News", callback_data="nav:news"), InlineKeyboardButton("🎮 Demo", callback_data="demo:perps:home")],
        [InlineKeyboardButton("➕ New Model", callback_data="wiz:start"), InlineKeyboardButton("⚡ Status", callback_data="nav:status")],
        [InlineKeyboardButton("🎰 Go to Degen", callback_data="nav:degen_home")],
    ])


def degen_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="nav:home"), InlineKeyboardButton("⚙️ Models", callback_data="degen_model:list")],
        [InlineKeyboardButton("🆕 Latest Finds", callback_data="wallet:activity"), InlineKeyboardButton("👀 Watchlist", callback_data="wallet:list")],
        [InlineKeyboardButton("🐋 Wallets", callback_data="wallet:dash"), InlineKeyboardButton("📰 News Trades", callback_data="nav:news")],
        [InlineKeyboardButton("📊 Degen Stats", callback_data="degen:stats"), InlineKeyboardButton("🎮 Demo", callback_data="demo:degen:home")],
        [InlineKeyboardButton("📊 Charts", callback_data="nav:charts")],
        [InlineKeyboardButton("🔍 Search Token", callback_data="wallet:activity"), InlineKeyboardButton("⚙️ Scanner Settings", callback_data="nav:status")],
        [InlineKeyboardButton("➕ New Model", callback_data="degen_model:new"), InlineKeyboardButton("⚖️ Compare", callback_data="degen:compare")],
        [InlineKeyboardButton("📈 Go to Perps", callback_data="nav:perps_home")],
    ])


def main_kb():
    return perps_keyboard()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update):
        return
    await update.message.reply_text(formatters.fmt_landing(), reply_markup=landing_keyboard())


async def perps_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update):
        return
    active = db.get_active_models()
    recent = db.get_recent_alerts(hours=2, limit=3)
    pending = db.get_all_pending_setups(status="pending")
    await update.message.reply_text(formatters.fmt_perps_home(active, recent, engine.get_session(), formatters._wat_now().strftime("%H:%M"), pending_setups=pending), reply_markup=perps_keyboard())


async def guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update):
        return
    await update.message.reply_text(formatters.fmt_help(), parse_mode="Markdown", reply_markup=perps_keyboard())


async def handle_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    dest = q.data.split(":")[1]
    if dest == "home":
        await q.message.reply_text(formatters.fmt_landing(), reply_markup=landing_keyboard())
    elif dest == "perps_home":
        msg = await q.message.reply_text("📈 Perps Trading\n━━━━━━━━━━━━━━━━\n⏳ Loading live data...", reply_markup=perps_keyboard())
        active = db.get_active_models()
        recent = db.get_recent_alerts(hours=2, limit=3)
        pending = db.get_all_pending_setups(status="pending")
        await msg.edit_text(formatters.fmt_perps_home(active, recent, engine.get_session(), formatters._wat_now().strftime("%H:%M"), pending_setups=pending), reply_markup=perps_keyboard())
    elif dest == "degen_home":
        from handlers import degen_handler
        await degen_handler.degen_home(update, context)
    elif dest == "models":
        await _render_models(q)
    elif dest == "stats":
        row, tiers, sessions = db.get_stats_30d(), db.get_tier_breakdown(), db.get_session_breakdown()
        conv = db.get_conversion_stats()
        txt = formatters.fmt_stats(row, tiers, sessions) + "\n\n" + formatters.fmt_rolling_10(db.get_rolling_10()) + f"\n\nConversion: {conv['total_trades']}/{conv['total_alerts']} alerts entered ({conv['ratio']}%) — {conv['would_win_skipped']} skipped setups would have won"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🕐 Heatmap", callback_data="nav:heatmap"), InlineKeyboardButton("📓 Journal", callback_data="nav:journal")], [InlineKeyboardButton("📈 Rolling 10", callback_data="nav:rolling10")], [InlineKeyboardButton("🏠 Home", callback_data="nav:home")]])
        await q.message.reply_text(txt, parse_mode="Markdown", reply_markup=kb)
    elif dest == "discipline":
        from handlers.stats import _disc_score

        v = db.get_violations_30d()
        await q.message.reply_text(formatters.fmt_discipline(_disc_score(v), v), parse_mode="Markdown")
    elif dest == "alerts":
        await q.message.reply_text(formatters.fmt_alert_log(db.get_recent_alerts(hours=24, limit=20)), parse_mode="Markdown")
    elif dest == "prices":
        msg = await q.message.reply_text("💹 Live Prices\n━━━━━━━━━━━━━━━━\n⏳ Loading live data...")
        live_px = await px.fetch_prices(SUPPORTED_PAIRS)
        lines = ["💹 *Live Prices*", "━━━━━━━━━━━━━━━━━━━━━━━━"]
        for pair in SUPPORTED_PAIRS:
            if pair in live_px:
                lines.append(f"`{pair}` {px.fmt_price(live_px[pair])}")
        await msg.edit_text("\n".join(lines), parse_mode="Markdown")
    elif dest == "status":
        await q.message.reply_text(formatters.fmt_status(engine.get_session(), True, len(db.get_active_models()), True), parse_mode="Markdown")
    elif dest == "news":
        from handlers import news_handler
        await news_handler._send_news_screen(q.message.reply_text)
    elif dest == "journal":
        await journal_cmd_like(q.message.reply_text)
    elif dest == "heatmap":
        await q.message.reply_text(formatters.fmt_heatmap(db.get_hourly_breakdown()), parse_mode="Markdown")
    elif dest == "rolling10":
        await q.message.reply_text(formatters.fmt_rolling_10(db.get_rolling_10()), parse_mode="Markdown")
    elif dest == "pending":
        pending = db.get_all_pending_setups(status="pending")
        lines = [
            "⏳ *Pending Setups*",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            "Setups that are partially meeting criteria.",
            "Updated live every 30 seconds.",
            "",
        ]
        kb_rows = []
        if not pending:
            lines.append("📭 No pending setups right now.")
            lines.append("The scanner is watching all active models.")
        else:
            lines.append(f"{len(pending)} setup(s) being tracked:")
            for p in pending:
                pct = float(p.get("score_pct") or 0)
                bar = "█" * round(min(100, pct) / 10) + "░" * (10 - round(min(100, pct) / 10))
                passed = len(p.get("passed_rules") or [])
                total = passed + len(p.get("failed_rules") or [])
                lines.extend([
                    "",
                    f"⚙️ {p.get('model_name')}",
                    f"🪙 {p.get('pair')}   {p.get('timeframe')}   {p.get('direction')}",
                    f"[{bar}] {pct:.0f}%",
                    f"✅ {passed}/{max(total,1)} rules   ⏱ {int((formatters._wat_now().replace(tzinfo=None) - p['first_detected_at']).total_seconds()//60)}m",
                    "➡️ Stable",
                ])
                kb_rows.append([InlineKeyboardButton(f"🔍 View {p.get('pair')} Setup", callback_data=f"pending:model:{p['id']}")])
        kb_rows.extend([[InlineKeyboardButton("🔄 Refresh", callback_data="nav:pending"), InlineKeyboardButton("🏠 Home", callback_data="nav:home")]])
        await q.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb_rows))

    elif dest == "charts":
        rows = db.get_chart_analyses(limit=20)
        lines = [
            "📊 *Chart Analysis History*",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            f"Your last {len(rows)} chart analyses:",
            "",
        ]
        for r in rows:
            action = str(r.get("action") or "wait").lower()
            action_emoji = {"buy": "📈", "sell": "📉", "wait": "⏳", "avoid": "🚫"}.get(action, "⏳")
            ago = formatters._fmt_age(int(((formatters._wat_now().replace(tzinfo=None) - r.get("analysed_at")).total_seconds()) // 60)) if r.get("analysed_at") else "just now"
            lines.extend([
                f"{action_emoji} {r.get('pair_estimate','unknown')} {r.get('timeframe','unknown')}   {action.upper()}",
                f"   Setup: {r.get('setup_type') or 'none'}   Confluence: {r.get('confluence_score',0)}/10",
                f"   {ago} ago",
                "",
            ])
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 New Analysis", callback_data="chart:resend"), InlineKeyboardButton("🏠 Home", callback_data="nav:home")]])
        await q.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=kb)
    elif dest == "scan":
        pairs = [[InlineKeyboardButton(p, callback_data=f"scan:{p}")] for p in SUPPORTED_PAIRS]
        await q.message.reply_text("Choose pair to scan", reply_markup=InlineKeyboardMarkup(pairs))




def _model_edit_kb(model_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🪙 Pair", callback_data=f"model:edit_field:{model_id}:pair"), InlineKeyboardButton("⏱ Timeframe", callback_data=f"model:edit_field:{model_id}:timeframe")],
        [InlineKeyboardButton("🧭 Session", callback_data=f"model:edit_field:{model_id}:session"), InlineKeyboardButton("📈 Bias", callback_data=f"model:edit_field:{model_id}:bias")],
        [InlineKeyboardButton("« Back", callback_data=f"model:detail:{model_id}")],
    ])


def _model_edit_value_kb(model_id: str, field: str, options: list[str]) -> InlineKeyboardMarkup:
    rows=[]
    for i in range(0, len(options), 3):
        rows.append([InlineKeyboardButton(v, callback_data=f"model:set:{model_id}:{field}:{v}") for v in options[i:i+3]])
    rows.append([InlineKeyboardButton("« Back", callback_data=f"model:edit:{model_id}")])
    return InlineKeyboardMarkup(rows)

async def _render_models(q):
    models = db.get_all_models()
    rows = [[InlineKeyboardButton(f"{'🟢' if m['status'] == 'active' else '⚫'} {m['name']} ({m['pair']})", callback_data=f"model:detail:{m['id']}")] for m in models]
    rows.append([InlineKeyboardButton("🗑 Delete All Models", callback_data="model:delete_all_confirm")])
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="nav:home")])
    await q.message.reply_text(formatters.fmt_models(models), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))


async def handle_model_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    parts = q.data.split(":")
    action = parts[1]

    if action == "delete_all_confirm":
        await q.message.reply_text(
            "⚠️ Delete *all* perps models? This cannot be undone.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 Yes, Delete All", callback_data="model:delete_all")],
                [InlineKeyboardButton("Cancel", callback_data="nav:models")],
            ]),
        )
        return
    if action == "delete_all":
        db.delete_all_models()
        await q.message.reply_text("✅ All perps models deleted.", parse_mode="Markdown")
        await _render_models(q)
        return

    model_id = parts[2]
    m = db.get_model(model_id)
    if not m:
        return
    if action == "detail":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏸ Deactivate" if m['status'] == 'active' else "✅ Activate", callback_data=f"model:toggle:{model_id}"), InlineKeyboardButton("🗑 Delete", callback_data=f"model:delete:{model_id}")],
            [InlineKeyboardButton("✏️ Edit", callback_data=f"model:edit:{model_id}"), InlineKeyboardButton("📋 Clone", callback_data=f"model:clone:{model_id}")],
            [InlineKeyboardButton("📜 History", callback_data=f"model:history:{model_id}"), InlineKeyboardButton("📊 Rule Analysis", callback_data=f"model:rules:{model_id}")],
        ])
        await q.message.reply_text(formatters.fmt_model_detail(m, px.get_price(m['pair'])), parse_mode="Markdown", reply_markup=kb)
    elif action == "edit":
        await q.message.reply_text("✏️ *Edit Model*\nSelect what to change.", parse_mode="Markdown", reply_markup=_model_edit_kb(model_id))
    elif action == "edit_field" and len(parts) > 3:
        field = parts[3]
        if field == "pair":
            opts = SUPPORTED_PAIRS
        elif field == "timeframe":
            opts = SUPPORTED_TIMEFRAMES
        elif field == "session":
            opts = SUPPORTED_SESSIONS
        elif field == "bias":
            opts = SUPPORTED_BIASES
        else:
            await q.message.reply_text("Unsupported field.")
            return
        await q.message.reply_text(f"Choose new {field}:", reply_markup=_model_edit_value_kb(model_id, field, opts))
    elif action == "set" and len(parts) > 4:
        field = parts[3]
        value = parts[4]
        db.save_model_version(model_id)
        ok = db.update_model_fields(model_id, {field: value})
        if ok:
            await q.message.reply_text(f"✅ Updated *{field}* to `{value}`.", parse_mode="Markdown")
            m = db.get_model(model_id)
            await q.message.reply_text(formatters.fmt_model_detail(m, px.get_price(m['pair'])), parse_mode="Markdown", reply_markup=_model_edit_kb(model_id))
        else:
            await q.message.reply_text("❌ Update failed.")
    elif action == "toggle":
        db.set_model_status(model_id, "inactive" if m['status'] == 'active' else "active")
        await q.message.reply_text("Updated.", parse_mode="Markdown")
    elif action == "delete":
        db.delete_model(model_id)
        await q.message.reply_text("Deleted.", parse_mode="Markdown")
    elif action == "history":
        vs = db.get_model_versions(model_id, 5)
        await q.message.reply_text("\n".join(["📜 *History*"] + [f"v{v['version']} - {v['saved_at']}" for v in vs]), parse_mode="Markdown")
    elif action == "clone":
        c = db.clone_model(model_id)
        await q.message.reply_text(f"📋 {c['name']} cloned successfully. Tap to edit the copy.", parse_mode="Markdown")
    elif action == "rules":
        rp = db.get_rule_performance(model_id)
        await q.message.reply_text("\n".join(["📊 *Rule Analysis*"] + [f"• {r['name']} | Pass {r['pass_rate']}% | Win {r['win_rate']}%" for r in rp]), parse_mode="Markdown")


async def handle_scan_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pair = q.data.split(":")[1]
    models = [x for x in db.get_active_models() if x['pair'] == pair]
    if not models:
        await q.message.reply_text(f"ℹ️ No active models for `{pair}`.", parse_mode="Markdown")
        return

    started = time.perf_counter()
    await q.message.reply_text(f"🔍 Scanning `{pair}` across `{len(models)}` active model(s)...", parse_mode="Markdown")
    from handlers.alerts import _evaluate_and_send

    sent = 0
    for m in models:
        if await _evaluate_and_send(q.get_bot(), m, force=True):
            sent += 1

    elapsed = time.perf_counter() - started
    await q.message.reply_text(
        f"✅ Scan complete for `{pair}`\n"
        f"• Models scanned: `{len(models)}`\n"
        f"• Alerts triggered: `{sent}`\n"
        f"• Time: `{elapsed:.1f}s`\n"
        + ("No setups matched right now." if sent == 0 else "Check alerts above for matches."),
        parse_mode="Markdown",
    )


async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update):
        return
    await update.message.reply_text("Use Stats/Models screens.", parse_mode="Markdown")


async def handle_backtest_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    parts = q.data.split(":")
    action = parts[1] if len(parts) > 1 else "start"

    if action == "start" or action == "again":
        await _send_backtest_entry(q.message.reply_text)
    elif action == "model" and len(parts) > 2:
        await _send_backtest_days(q.message.reply_text, parts[2])
    elif action == "days" and len(parts) > 3:
        await _run_backtest_selection(q.message.reply_text, parts[2], parts[3])


async def backtest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update):
        return
    if context.args:
        await _run_backtest_command(update.message.reply_text, context.args)
        return
    await _send_backtest_entry(update.message.reply_text)


async def _run_backtest_command(reply, args: list[str]):
    if len(args) < 2:
        await reply(
            "❌ Usage: `/backtest <model_id> <days>` (example: `/backtest model_abc 30`)\n"
            "You can also use the Backtest screen to autofill this command.",
            parse_mode="Markdown",
            reply_markup=_backtest_screen_kb(),
        )
        return

    model_id = args[0].strip()
    model = db.get_model(model_id)
    if not model:
        await reply("❌ Model not found. Choose one from the Backtest screen.", reply_markup=_backtest_screen_kb())
        return

    try:
        days = int(args[1])
    except Exception:
        await reply("❌ Days must be a whole number, e.g. `/backtest model_abc 30`.", parse_mode="Markdown")
        return

    if days < 1 or days > 90:
        await reply("❌ Days must be between 1 and 90.")
        return

    series = px.get_recent_series(model["pair"], days=days)
    if len(series) < 40:
        await reply(
            "⚠️ Not enough price data was returned for this pair/range. Try a longer range.",
            reply_markup=_backtest_screen_kb(),
        )
        return

    result = engine.backtest_model(model, series)
    trades = int(result.get("trades") or 0)
    wins = int(result.get("wins") or 0)
    losses = int(result.get("losses") or 0)
    win_rate = float(result.get("win_rate") or 0)
    avg_rr = float(result.get("avg_rr") or 0)

    msg = (
        f"🧪 *Backtest — {model['name']}*\n"
        f"Pair: `{model['pair']}`\n"
        f"Range: `{days}d`\n"
        f"Trades: `{trades}`\n"
        f"Wins/Losses: `{wins}/{losses}`\n"
        f"Win rate: `{win_rate:.2f}%`\n"
        f"Avg R/R: `{avg_rr:+.2f}R`"
    )
    await reply(msg, parse_mode="Markdown", reply_markup=_backtest_screen_kb())


def _backtest_screen_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Run Again", callback_data="backtest:again"), InlineKeyboardButton("⚙️ Models", callback_data="nav:models")],
        [InlineKeyboardButton("« Back to Perps", callback_data="nav:perps_home")],
    ])


async def _send_backtest_entry(reply):
    models = db.get_all_models()
    if not models:
        await reply("🧪 *Backtest*\nNo models found yet. Create one first from the Models screen.", parse_mode="Markdown", reply_markup=_backtest_screen_kb())
        return

    model_rows = [
        [InlineKeyboardButton(f"{'🟢' if m['status'] == 'active' else '⚫'} {m['name']}", callback_data=f"backtest:model:{m['id']}")]
        for m in models
    ]
    model_rows.append([InlineKeyboardButton("« Back to Perps", callback_data="nav:perps_home")])

    await reply(
        "🧪 *Backtest*\nSelect a model to generate a ready-to-send command.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(model_rows),
    )


async def _send_backtest_days(reply, model_id: str):
    model = db.get_model(model_id)
    if not model:
        await reply("❌ Model not found. Please choose again.", reply_markup=_backtest_screen_kb())
        return

    day_options = [7, 14, 30, 60]
    day_buttons = [
        InlineKeyboardButton(
            f"{days}d",
            callback_data=f"backtest:days:{model_id}:{days}",
        )
        for days in day_options
    ]
    keyboard = [day_buttons[:2], day_buttons[2:]]
    keyboard.append([InlineKeyboardButton("🔄 Choose Another Model", callback_data="backtest:start")])
    keyboard.append([InlineKeyboardButton("« Back to Perps", callback_data="nav:perps_home")])

    await reply(
        f"🧪 *Backtest*\nModel: *{model['name']}* (`{model_id}`)\nPick a range to run now.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _run_backtest_selection(reply, model_id: str, days_raw: str):
    try:
        days = int(days_raw)
    except Exception:
        await reply("❌ Invalid day range selected.", reply_markup=_backtest_screen_kb())
        return
    await _run_backtest_command(reply, [model_id, str(days)])


def _cancel_kb(scope: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"{scope}:cancel")]])


def _goal_select_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("5R", callback_data="goal:preset:5"), InlineKeyboardButton("10R", callback_data="goal:preset:10"), InlineKeyboardButton("15R", callback_data="goal:preset:15")],
        [InlineKeyboardButton("20R", callback_data="goal:preset:20"), InlineKeyboardButton("25R", callback_data="goal:preset:25"), InlineKeyboardButton("30R", callback_data="goal:preset:30")],
        [InlineKeyboardButton("✏️ Enter manually", callback_data="goal:manual")],
        [InlineKeyboardButton("❌ Cancel", callback_data="goal:cancel")],
    ])


def _goal_edit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("✏️ Edit", callback_data="goal:edit")]])


def _budget_target_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("2R", callback_data="budget:target:2"), InlineKeyboardButton("3R", callback_data="budget:target:3"), InlineKeyboardButton("5R", callback_data="budget:target:5")],
        [InlineKeyboardButton("7R", callback_data="budget:target:7"), InlineKeyboardButton("10R", callback_data="budget:target:10"), InlineKeyboardButton("15R", callback_data="budget:target:15")],
        [InlineKeyboardButton("✏️ Enter manually", callback_data="budget:target:manual")],
        [InlineKeyboardButton("❌ Cancel", callback_data="budget:cancel")],
    ])


def _budget_loss_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("-1R", callback_data="budget:loss:1"), InlineKeyboardButton("-2R", callback_data="budget:loss:2"), InlineKeyboardButton("-3R", callback_data="budget:loss:3")],
        [InlineKeyboardButton("-4R", callback_data="budget:loss:4"), InlineKeyboardButton("-5R", callback_data="budget:loss:5"), InlineKeyboardButton("-7R", callback_data="budget:loss:7")],
        [InlineKeyboardButton("✏️ Enter manually", callback_data="budget:loss:manual")],
        [InlineKeyboardButton("❌ Cancel", callback_data="budget:cancel")],
    ])


def _budget_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Save", callback_data="budget:save"), InlineKeyboardButton("🔄 Change", callback_data="budget:change")],
        [InlineKeyboardButton("❌ Cancel", callback_data="budget:cancel")],
    ])


def _budget_edit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("✏️ Edit", callback_data="budget:edit")]])


def _to_float(raw: str):
    try:
        return float(raw.strip())
    except Exception:
        return None


def _goal_status_text() -> str:
    mg = db.get_monthly_goal()
    if not mg:
        return "🎯 Monthly goal not set yet."
    achieved = float(mg.get("r_achieved") or 0)
    target = float(mg.get("r_target") or 0)
    return f"🎯 Current monthly goal: +{target:g}R\nProgress: {achieved:+.1f}R"


def _budget_status_text() -> str:
    weekly = db.get_weekly_goal()
    if not weekly:
        return "💰 Weekly budget not set yet."
    achieved = db.update_weekly_achieved()
    target = float(weekly.get("r_target") or 0)
    loss_limit = abs(float(weekly.get("loss_limit") or 0))
    return f"💰 Current weekly budget:\n🎯 Target: +{target:g}R\n🛑 Loss limit: -{loss_limit:g}R\nProgress: {achieved:+.1f}R"


async def goal_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update):
        return ConversationHandler.END
    context.user_data.pop("goal_pending", None)
    msg = (
        "🎯 Set Monthly R Target\n"
        " ━━━━━━━━━━━━━━━━━━━━━━━━\n"
        " Choose a target or enter manually:"
    )
    target = update.callback_query.message.reply_text if update.callback_query else update.message.reply_text
    if update.callback_query:
        await update.callback_query.answer()
    await target(msg, reply_markup=_goal_select_kb())
    return GOAL_SELECT


async def goal_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "goal:cancel":
        return await goal_cancel(update, context)
    if q.data == "goal:manual":
        await q.message.reply_text("✏️ Type your monthly R target (numbers only, e.g. 12.5):", reply_markup=_cancel_kb("goal"))
        return GOAL_MANUAL
    if q.data.startswith("goal:preset:"):
        value = float(q.data.split(":")[-1])
        return await _save_goal_and_show(q.message.reply_text, value)
    return GOAL_SELECT


async def goal_manual_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = _to_float(update.message.text)
    if value is None or value < 1 or value > 200:
        await update.message.reply_text("❌ Invalid input. Please enter a number between 1 and 200.")
        await update.message.reply_text("✏️ Type your monthly R target (numbers only, e.g. 12.5):", reply_markup=_cancel_kb("goal"))
        return GOAL_MANUAL
    return await _save_goal_and_show(update.message.reply_text, value)


async def _save_goal_and_show(reply_fn, value: float):
    db.upsert_monthly_goal(float(value))
    await reply_fn(f"✅ Monthly goal set: +{value:g}R\nGood luck this month. 🎯")
    await reply_fn(_goal_status_text(), reply_markup=_goal_edit_kb())
    return ConversationHandler.END


async def goal_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text("❌ Goal setup canceled.")
    else:
        await update.message.reply_text("❌ Goal setup canceled.")
    return ConversationHandler.END


async def budget_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update):
        return ConversationHandler.END
    context.user_data.pop("budget_target", None)
    context.user_data.pop("budget_loss_limit", None)
    if update.callback_query:
        await update.callback_query.answer()
        reply_fn = update.callback_query.message.reply_text
    else:
        reply_fn = update.message.reply_text
    await reply_fn(
        "💰 Weekly Budget Setup\n"
        " ━━━━━━━━━━━━━━━━━━━━━━━━\n"
        " Step 1 of 2 — Set your weekly R target:",
        reply_markup=_budget_target_kb(),
    )
    return BUDGET_TARGET_SELECT


async def budget_target_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "budget:cancel":
        return await budget_cancel(update, context)
    if q.data == "budget:target:manual":
        await q.message.reply_text("✏️ Type your weekly R target (numbers only, e.g. 4.5):", reply_markup=_cancel_kb("budget"))
        return BUDGET_TARGET_MANUAL
    if q.data.startswith("budget:target:"):
        target = float(q.data.split(":")[-1])
        return await _set_budget_target_and_ask_loss(q.message.reply_text, context, target)
    return BUDGET_TARGET_SELECT


async def budget_target_manual_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = _to_float(update.message.text)
    if value is None or value < 0.5 or value > 50:
        await update.message.reply_text("❌ Invalid input. Please enter a number between 0.5 and 50.")
        await update.message.reply_text("✏️ Type your weekly R target (numbers only, e.g. 4.5):", reply_markup=_cancel_kb("budget"))
        return BUDGET_TARGET_MANUAL
    return await _set_budget_target_and_ask_loss(update.message.reply_text, context, value)


async def _set_budget_target_and_ask_loss(reply_fn, context: ContextTypes.DEFAULT_TYPE, target: float):
    context.user_data["budget_target"] = float(target)
    await reply_fn(
        "💰 Weekly Budget Setup\n"
        " ━━━━━━━━━━━━━━━━━━━━━━━━\n"
        " Step 2 of 2 — Set your weekly loss limit\n"
        " (bot will pause alerts when this is hit):",
        reply_markup=_budget_loss_kb(),
    )
    return BUDGET_LOSS_SELECT


async def budget_loss_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "budget:cancel":
        return await budget_cancel(update, context)
    if q.data == "budget:loss:manual":
        await q.message.reply_text("✏️ Type your weekly loss limit (numbers only, e.g. 2.5):", reply_markup=_cancel_kb("budget"))
        return BUDGET_LOSS_MANUAL
    if q.data.startswith("budget:loss:"):
        loss = float(q.data.split(":")[-1])
        return await _set_budget_loss_and_confirm(q.message.reply_text, context, loss)
    return BUDGET_LOSS_SELECT


async def budget_loss_manual_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = _to_float(update.message.text)
    if value is None or value < 0.5 or value > 20:
        await update.message.reply_text("❌ Invalid input. Please enter a number between 0.5 and 20.")
        await update.message.reply_text("✏️ Type your weekly loss limit (numbers only, e.g. 2.5):", reply_markup=_cancel_kb("budget"))
        return BUDGET_LOSS_MANUAL
    return await _set_budget_loss_and_confirm(update.message.reply_text, context, value)


async def _set_budget_loss_and_confirm(reply_fn, context: ContextTypes.DEFAULT_TYPE, loss_limit_abs: float):
    context.user_data["budget_loss_limit"] = -abs(float(loss_limit_abs))
    target = context.user_data.get("budget_target")
    loss_limit = abs(context.user_data.get("budget_loss_limit"))
    await reply_fn(
        "💰 Weekly Budget Configured\n"
        " ━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f" 🎯 Target:     +{target:g}R per week\n"
        f" 🛑 Loss limit: -{loss_limit:g}R per week\n"
        " 📅 Resets:     every Monday 00:00 UTC\n\n"
        " Confirm?",
        reply_markup=_budget_confirm_kb(),
    )
    return BUDGET_CONFIRM


async def budget_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "budget:cancel":
        return await budget_cancel(update, context)
    if q.data == "budget:change":
        return await budget_entry(update, context)
    if q.data == "budget:save":
        target = float(context.user_data.get("budget_target") or 0)
        loss_limit = float(context.user_data.get("budget_loss_limit") or 0)
        if target <= 0 or loss_limit >= 0:
            await q.message.reply_text("❌ Missing budget values. Please start again.")
            return await budget_entry(update, context)
        db.upsert_weekly_goal(target, loss_limit)
        await q.message.reply_text("✅ Weekly budget saved.")
        await q.message.reply_text(_budget_status_text(), reply_markup=_budget_edit_kb())
        return ConversationHandler.END
    return BUDGET_CONFIRM


async def budget_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text("❌ Budget setup canceled.")
    else:
        await update.message.reply_text("❌ Budget setup canceled.")
    return ConversationHandler.END


def build_goal_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("goal", goal_entry),
            CallbackQueryHandler(goal_entry, pattern=r"^(nav:goal|goal:edit)$"),
        ],
        states={
            GOAL_SELECT: [
                CallbackQueryHandler(goal_select, pattern=r"^goal:(preset:\d+(?:\.\d+)?|manual|cancel)$"),
            ],
            GOAL_MANUAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, goal_manual_input),
                CallbackQueryHandler(goal_cancel, pattern=r"^goal:cancel$"),
            ],
        },
        fallbacks=[CallbackQueryHandler(goal_cancel, pattern=r"^goal:cancel$")],
        name="goal_conversation",
        persistent=False,
    )


def build_budget_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("budget", budget_entry),
            CallbackQueryHandler(budget_entry, pattern=r"^(nav:budget|budget:edit)$"),
        ],
        states={
            BUDGET_TARGET_SELECT: [
                CallbackQueryHandler(budget_target_select, pattern=r"^budget:(target:(?:\d+(?:\.\d+)?|manual)|cancel)$"),
            ],
            BUDGET_TARGET_MANUAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, budget_target_manual_input),
                CallbackQueryHandler(budget_cancel, pattern=r"^budget:cancel$"),
            ],
            BUDGET_LOSS_SELECT: [
                CallbackQueryHandler(budget_loss_select, pattern=r"^budget:(loss:(?:\d+(?:\.\d+)?|manual)|cancel)$"),
            ],
            BUDGET_LOSS_MANUAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, budget_loss_manual_input),
                CallbackQueryHandler(budget_cancel, pattern=r"^budget:cancel$"),
            ],
            BUDGET_CONFIRM: [
                CallbackQueryHandler(budget_confirm, pattern=r"^budget:(save|change|cancel)$"),
            ],
        },
        fallbacks=[CallbackQueryHandler(budget_cancel, pattern=r"^budget:cancel$")],
        name="budget_conversation",
        persistent=False,
    )


async def journal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update):
        return
    await journal_cmd_like(update.message.reply_text)


async def journal_cmd_like(reply_fn):
    entries = db.get_journal_entries(10)
    lines = ["📓 *Journal*", "━━━━━━━━━━━━━━━━━━━━━━━━"] + [f"[{e.get('pair', '?')}] [{e.get('result', '?')}] {e.get('entry_text', '')}" for e in entries]
    await reply_fn("\n".join(lines), parse_mode="Markdown")
