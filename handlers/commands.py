import logging
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters

import db
import engine
import formatters
import prices as px
from config import CHAT_ID, SUPPORTED_PAIRS, SUPPORTED_TIMEFRAMES, SUPPORTED_SESSIONS, SUPPORTED_BIASES
from security.auth import require_auth, require_auth_callback, ALLOWED_USER_IDS
from security.rate_limiter import check_command_rate, get_rate_status

log = logging.getLogger(__name__)

MASTER_CATEGORY_LABELS = {
    "TC": "📈 Trend Continuation",
    "REV": "🔄 Reversal",
    "LIQ": "💧 Liquidity Grab",
    "OB": "📦 Order Block",
    "FVG": "⚡ Fair Value Gap",
    "SES": "⏰ Session-Specific",
    "MP": "🌐 Multi-Pair",
    "HTF": "📊 HTF Swing",
    "FX": "💱 Forex",
    "ADV": "🧠 Advanced Concepts",
}

QUICK_DEPLOY_PACKS = {
    "ICT_CORE": {
        "name": "Starter Pack 1 — ICT Core",
        "description": "The essential ICT concepts — OB, FVG, liquidity grabs",
        "models": ["MM_LIQ_01", "MM_LIQ_02", "MM_OB_01", "MM_OB_02", "MM_FVG_01", "MM_FVG_02"],
    },
    "LONDON": {
        "name": "Starter Pack 2 — London Specialist",
        "description": "All London session models for peak-hour trading",
        "models": ["MM_SES_01", "MM_SES_02", "MM_LIQ_03", "MM_LIQ_04", "MM_ADV_05", "MM_ADV_03"],
    },
    "SWING": {
        "name": "Starter Pack 4 — Swing Trader",
        "description": "Daily and 4H models for swing positions",
        "models": ["MM_HTF_01", "MM_HTF_02", "MM_HTF_03", "MM_REV_03", "MM_REV_04"],
    },
    "ADV": {
        "name": "Starter Pack 5 — Advanced ICT",
        "description": "All advanced ICT concept models",
        "models": [f"MM_ADV_0{i}" for i in range(1, 9)],
    },
}

GOAL_SELECT, GOAL_MANUAL = range(2)
BUDGET_TARGET_SELECT, BUDGET_TARGET_MANUAL, BUDGET_LOSS_SELECT, BUDGET_LOSS_MANUAL, BUDGET_CONFIRM = range(10, 15)


def _guard(update: Update) -> bool:
    return update.effective_chat and update.effective_chat.id == CHAT_ID


def landing_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Perps", callback_data="nav:perps_home"), InlineKeyboardButton("🔥 Degen", callback_data="nav:degen_home")],
        [InlineKeyboardButton("🎯 Polymarket", callback_data="nav:polymarket_home"), InlineKeyboardButton("🔑 Solana", callback_data="nav:solana_home")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="nav:status"), InlineKeyboardButton("❓ Help", callback_data="nav:guide")],
    ])


def perps_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Scanner", callback_data="nav:scan"), InlineKeyboardButton("📊 Models", callback_data="nav:models")],
        [InlineKeyboardButton("📓 Journal", callback_data="nav:journal"), InlineKeyboardButton("📖 Playbook", callback_data="nav:guide")],
        [InlineKeyboardButton("🌅 Briefing", callback_data="nav:news"), InlineKeyboardButton("📅 Weekly Review", callback_data="nav:rolling10")],
        [InlineKeyboardButton("🔥 Heatmap", callback_data="nav:heatmap"), InlineKeyboardButton("📍 Key Levels", callback_data="nav:session_journal")],
        [InlineKeyboardButton("🔍 Validate Idea", callback_data="nav:charts"), InlineKeyboardButton("🧠 Patterns", callback_data="nav:pending")],
        [InlineKeyboardButton("💰 Risk Settings", callback_data="nav:risk"), InlineKeyboardButton("✅ Checklist", callback_data="nav:checklist")],
        [InlineKeyboardButton("🌐 Market Regime", callback_data="nav:regime"), InlineKeyboardButton("🔔 Notif Filter", callback_data="nav:notif_filter")],
        [InlineKeyboardButton("🎮 Demo Trades", callback_data="demo:perps:home"), InlineKeyboardButton("⏳ Pending", callback_data="nav:pending")],
        [InlineKeyboardButton("🔷 Hyperliquid", callback_data="hl:home"), InlineKeyboardButton("📓 Session Log", callback_data="nav:session_journal")],
        [InlineKeyboardButton("🏠 Home", callback_data="nav:home")],
    ])


def degen_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 Degen Scanner", callback_data="scanner:run_now"), InlineKeyboardButton("⚙️ Scanner Settings", callback_data="degen:scanner_settings")],
        [InlineKeyboardButton("📄 Scan Contract", callback_data="degen:scan_prompt"), InlineKeyboardButton("🌊 Narratives", callback_data="degen:narratives")],
        [InlineKeyboardButton("📓 Degen Journal", callback_data="degen:journal_home"), InlineKeyboardButton("🧭 Exit Planner", callback_data="degen:exit_plan")],
        [InlineKeyboardButton("🎮 Demo Dashboard", callback_data="demo:degen:home"), InlineKeyboardButton("💼 Manage Positions", callback_data="demo:degen:open")],
        [InlineKeyboardButton("👤 Dev Wallets", callback_data="wallet:dash"), InlineKeyboardButton("📋 Watchlist", callback_data="degen:watchlist")],
        [InlineKeyboardButton("📊 Patterns", callback_data="degen:stats"), InlineKeyboardButton("🏠 Home", callback_data="nav:home")],
    ])


def main_kb():
    return perps_keyboard()


def _selected_pairs() -> list[str]:
    prefs = db.get_user_preferences(CHAT_ID) or {}
    preferred = [p for p in (prefs.get("preferred_pairs") or []) if p in SUPPORTED_PAIRS]
    return preferred or list(SUPPORTED_PAIRS[:1])


def _set_selected_pair(pair: str) -> None:
    if pair in SUPPORTED_PAIRS:
        db.update_user_preferences(CHAT_ID, preferred_pairs=[pair])


def _pair_select_kb(prefix: str, include_back: bool = True) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(pair, callback_data=f"{prefix}:{pair}")] for pair in SUPPORTED_PAIRS]
    if include_back:
        rows.append([InlineKeyboardButton("« Back", callback_data="nav:models")])
    return InlineKeyboardMarkup(rows)


@require_auth
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update):
        return
    await update.message.reply_text(formatters.fmt_landing(), reply_markup=landing_keyboard())


@require_auth
async def perps_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update):
        return
    active = db.get_active_models()
    recent = db.get_recent_alerts(hours=2, limit=3)
    pending = db.get_all_pending_setups(status="pending")
    await update.message.reply_text(formatters.fmt_perps_home(active, recent, engine.get_session(), formatters._wat_now().strftime("%H:%M"), pending_setups=pending), reply_markup=perps_keyboard())


@require_auth
async def guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update):
        return
    await update.message.reply_text(formatters.fmt_help(), parse_mode="Markdown", reply_markup=perps_keyboard())


@require_auth_callback
async def handle_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    allowed, reason = check_command_rate(uid)
    if not allowed:
        await q.answer(reason, show_alert=True)
        return
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
    elif dest == "polymarket_home":
        from handlers import polymarket_handler
        await polymarket_handler.show_polymarket_home(q, context)
    elif dest == "solana_home":
        from handlers import solana_handler
        await solana_handler.show_solana_home(q, context)
    elif dest == "models":
        await handle_models_list(update, context)
    elif dest == "simulator":
        from handlers import simulator_handler
        await simulator_handler.show_simulator_home(q.message.reply_text)
    elif dest == "stats":
        row, tiers, sessions = db.get_stats_30d(), db.get_tier_breakdown(), db.get_session_breakdown()
        conv = db.get_conversion_stats()
        txt = formatters.fmt_stats(row, tiers, sessions) + "\n\n" + formatters.fmt_rolling_10(db.get_rolling_10()) + f"\n\nConversion: {conv['total_trades']}/{conv['total_alerts']} alerts entered ({conv['ratio']}%) — {conv['would_win_skipped']} skipped setups would have won"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🕐 Heatmap", callback_data="nav:heatmap"), InlineKeyboardButton("📓 Journal", callback_data="nav:journal")], [InlineKeyboardButton("📈 Rolling 10", callback_data="nav:rolling10")], [InlineKeyboardButton("🏠 Home", callback_data="nav:home")]])
        await q.message.reply_text(txt, parse_mode="Markdown", reply_markup=kb)
    elif dest == "session_journal":
        rows = db.get_session_journal("BTCUSDT", days=7)
        lines = ["📓 *Session Journal*", "━━━━━━━━━━━━━━━━━━━━━━━━"]
        for r in rows:
            levels = ", ".join([f"${(lvl.get('price') or 0):.2f}" for lvl in (r.get("key_levels") or [])[:3]])
            lines.append(
                f"{r['session_date']} {r['pair']}\nAsian range: ${r.get('asian_low',0):.2f} — ${r.get('asian_high',0):.2f} ({r.get('asian_range_pts',0):.2f} pts)\nLondon swept: {r.get('london_swept') or 'neither'}\nKey levels: {levels}"
            )
        await q.message.reply_text("\n\n".join(lines), parse_mode="Markdown")
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
    elif dest == "guide":
        await q.message.reply_text(formatters.fmt_help(), parse_mode="Markdown")
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
    elif dest == "risk":
        from handlers import risk_handler
        await risk_handler.show_risk_home(q, context)
    elif dest == "checklist":
        from engine.session_checklist import run_pre_session_checklist
        await run_pre_session_checklist(context)
    elif dest == "regime":
        regime = db.get_latest_regime()
        models = db.get_all_models()
        active = [m for m in models if m.get("status") == "active"]
        if regime:
            await q.message.reply_text(f"🌐 *Market Regime*\n━━━━━━━━━━━━━━━━━━━━━━━━\nRegime: {regime.get('regime')}\nConfidence: {float(regime.get('confidence') or 0):.0%}\nActive models: {len(active)}/{len(models)}", parse_mode="Markdown")
        else:
            await q.message.reply_text("🌐 No regime detected yet.")
    elif dest == "notif_filter":
        from handlers import risk_handler
        await risk_handler.show_notification_filter(q)

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

@require_auth_callback
async def handle_models_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    try:
        all_models = db.get_all_models()
    except Exception as e:
        log.error(f"Failed to fetch models: {e}")
        await query.message.edit_text(
            "❌ Failed to load models. Check database connection.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Retry", callback_data="nav:models"),
                InlineKeyboardButton("🏠 Home", callback_data="nav:perps_home")
            ]])
        )
        return

    if not all_models:
        await query.message.edit_text(
            "📭 *No models found*\n\n"
            "Tap ➕ to create your first model\n"
            "or tap 🏆 to view Master Models",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ New Model", callback_data="wizard:start")],
                [InlineKeyboardButton("🏆 Master Models", callback_data="model:master_list")],
                [InlineKeyboardButton("🏠 Home", callback_data="nav:perps_home")]
            ])
        )
        return

    master_models = [m for m in all_models if m["id"].startswith("MM_")]
    user_models = [m for m in all_models if not m["id"].startswith("MM_")]

    text = "*⚙️ Your Models*\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    if user_models:
        text += f"\n*Custom Models ({len(user_models)})*\n"
        for m in user_models:
            status_dot = "🟢" if m["status"] == "active" else "⚫"
            text += f"{status_dot} {m['name']} — {m['pair']} {m['timeframe']}\n"
    else:
        text += "\n_No custom models yet_\n"

    text += f"\n*🏆 Master Models ({len(master_models)})*\n"
    if master_models:
        active_mm = sum(1 for m in master_models if m["status"] == "active")
        text += f"_{len(master_models)} models available, {active_mm} active_\n"
    else:
        text += "_Run create_master_models.py to install_\n"

    buttons = []
    for m in user_models:
        status_dot = "🟢" if m["status"] == "active" else "⚫"
        buttons.append([InlineKeyboardButton(
            f"{status_dot} {m['name']} — {m['pair']}",
            callback_data=f"model:detail:{m['id']}"
        )])

    buttons.append([
        InlineKeyboardButton("🏆 Master Models", callback_data="model:master_list"),
        InlineKeyboardButton("➕ New Model", callback_data="wizard:start")
    ])
    buttons.append([InlineKeyboardButton("🗑 Delete All Models", callback_data="model:delete_all_confirm")])
    buttons.append([InlineKeyboardButton("🏠 Home", callback_data="nav:perps_home")])

    await query.message.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


def _master_models_grouped(models):
    grouped = {k: [] for k in MASTER_CATEGORY_LABELS.keys()}
    for m in models:
        if not str(m.get("id", "")).startswith("MM_"):
            continue
        key = m["id"].split("_")[1]
        if key in grouped:
            grouped[key].append(m)
    return grouped


async def handle_master_models_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    all_models = db.get_all_models()
    master_models = [m for m in all_models if m["id"].startswith("MM_")]

    if not master_models:
        await query.message.edit_text(
            "❌ *Master Models not found*\n\n"
            "The master models have not been installed yet.\n\n"
            "Run this command in your terminal:\n"
            "`python create_master_models.py`\n\n"
            "Then come back here and tap Refresh.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data="model:master_list")],
                [InlineKeyboardButton("« Back", callback_data="nav:models")]
            ])
        )
        return

    grouped = _master_models_grouped(master_models)
    active_count = sum(1 for m in master_models if m["status"] == "active")
    text = (
        f"🏆 *MASTER MODELS*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Total: {len(master_models)} models\n"
        f"Active: {active_count} / {len(master_models)}\n\n"
        f"Select a category to browse models:"
    )

    buttons = []
    for cat_key, cat_label in MASTER_CATEGORY_LABELS.items():
        models_in_cat = grouped.get(cat_key, [])
        if models_in_cat:
            active_in_cat = sum(1 for m in models_in_cat if m["status"] == "active")
            buttons.append([InlineKeyboardButton(
                f"{cat_label} ({active_in_cat}/{len(models_in_cat)} active)",
                callback_data=f"model:master_cat:{cat_key}"
            )])

    buttons.append([
        InlineKeyboardButton("⚡ Quick Deploy", callback_data="model:quick_deploy"),
        InlineKeyboardButton("✅ Activate All", callback_data="model:activate_all_mm")
    ])
    buttons.append([InlineKeyboardButton("« Back to Models", callback_data="nav:models")])

    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))


async def handle_master_category(update: Update, context: ContextTypes.DEFAULT_TYPE, cat_key: str):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    all_models = db.get_all_models()
    cat_models = [m for m in all_models if m["id"].startswith(f"MM_{cat_key}_")]

    cat_label = MASTER_CATEGORY_LABELS.get(cat_key, cat_key)
    text = f"{cat_label}\n━━━━━━━━━━━━━━━━━━━━━━━━\n"

    buttons = []
    for m in cat_models:
        status_dot = "🟢" if m["status"] == "active" else "⚫"
        rule_count = len(m.get("rules", []))
        buttons.append([InlineKeyboardButton(
            f"{status_dot} {m['timeframe']} — Adaptive direction/pair ({rule_count} rules)",
            callback_data=f"model:detail:{m['id']}"
        )])

    buttons.append([InlineKeyboardButton("✅ Activate All in Category", callback_data=f"model:activate_cat:{cat_key}")])
    buttons.append([InlineKeyboardButton("« Back", callback_data="model:master_list")])

    await query.message.edit_text(
        text + f"{len(cat_models)} models in this category",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def handle_activate_all_master(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        "Select the live activation pair for master models.",
        reply_markup=_pair_select_kb("model:activate_all_pair"),
    )


async def handle_activate_category(update: Update, context: ContextTypes.DEFAULT_TYPE, cat_key: str):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        f"Select live pair for category `{cat_key}`:",
        parse_mode="Markdown",
        reply_markup=_pair_select_kb(f"model:activate_cat_pair:{cat_key}", include_back=False),
    )


async def handle_activate_all_master_for_pair(update: Update, context: ContextTypes.DEFAULT_TYPE, pair: str):
    query = update.callback_query
    await query.answer("Activating and optimizing master models...")
    _set_selected_pair(pair)
    updated = db.activate_all_master_models()
    all_models = db.get_all_models()
    optimized = 0
    for model in all_models:
        if not str(model.get("id", "")).startswith("MM_"):
            continue
        opt = engine.optimize_model_for_pair(model, pair, days=30)
        if opt.get("optimized"):
            db.update_model_fields(
                model["id"],
                {
                    "tier_a": opt["tier_a"],
                    "tier_b": opt["tier_b"],
                    "tier_c": opt["tier_c"],
                    "min_score": opt["min_score"],
                    "pair": "ALL",
                    "bias": "Both",
                },
            )
            optimized += 1
    await query.message.edit_text(
        f"✅ *{updated} Master Models Activated*\n"
        f"Live pair: `{pair}`\n"
        f"Optimized: `{optimized}` models",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ View Models", callback_data="nav:models")],
            [InlineKeyboardButton("🏠 Home", callback_data="nav:perps_home")]
        ])
    )


async def handle_activate_category_for_pair(update: Update, context: ContextTypes.DEFAULT_TYPE, cat_key: str, pair: str):
    query = update.callback_query
    await query.answer(f"Activating {cat_key}...")
    _set_selected_pair(pair)
    updated = db.activate_master_models_by_category(cat_key)
    all_models = [m for m in db.get_all_models() if str(m.get("id", "")).startswith(f"MM_{cat_key}_")]
    optimized = 0
    for model in all_models:
        opt = engine.optimize_model_for_pair(model, pair, days=30)
        if opt.get("optimized"):
            db.update_model_fields(
                model["id"],
                {
                    "tier_a": opt["tier_a"],
                    "tier_b": opt["tier_b"],
                    "tier_c": opt["tier_c"],
                    "min_score": opt["min_score"],
                    "pair": "ALL",
                    "bias": "Both",
                },
            )
            optimized += 1
    await query.message.edit_text(
        f"✅ *{updated} models activated*\n"
        f"Category: `{cat_key}`\n"
        f"Live pair: `{pair}`\n"
        f"Optimized: `{optimized}` models",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data=f"model:master_cat:{cat_key}")]])
    )


def _pack_btc_all(models):
    return [m["id"] for m in models if m.get("id", "").startswith("MM_") and m.get("timeframe") in {"1h", "4h"}]


async def _render_quick_deploy(q):
    models = db.get_all_models()
    packs = dict(QUICK_DEPLOY_PACKS)
    packs["BTC_ALL"] = {
        "name": "Starter Pack 3 — BTC All Scenarios",
        "description": "Every BTC model — bullish and bearish coverage",
        "models": _pack_btc_all(models),
    }
    rows = [[InlineKeyboardButton(p["name"], callback_data=f"model:deploy:{k}")] for k, p in packs.items()]
    rows.append([InlineKeyboardButton("« Back", callback_data="model:master_list")])
    await q.message.reply_text("⚡ *Quick Deploy*\nChoose a starter pack:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))


@require_auth_callback
async def handle_model_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    allowed, reason = check_command_rate(uid)
    if not allowed:
        await q.answer(reason, show_alert=True)
        return
    data = q.data

    if data == "nav:models" or data == "model:list":
        await handle_models_list(update, context)
        return
    if data == "model:master_list" or data == "model:master":
        await handle_master_models_list(update, context)
        return
    if data.startswith("model:master_cat:"):
        await handle_master_category(update, context, data.split(":")[2])
        return
    if data.startswith("model:mastercat:"):
        await handle_master_category(update, context, data.split(":")[2])
        return
    if data == "model:activate_all_mm":
        await handle_activate_all_master(update, context)
        return
    if data.startswith("model:activate_all_pair:"):
        await handle_activate_all_master_for_pair(update, context, data.split(":")[2])
        return
    if data.startswith("model:activate_cat:"):
        await handle_activate_category(update, context, data.split(":")[2])
        return
    if data.startswith("model:activate_cat_pair:"):
        parts = data.split(":")
        if len(parts) > 3:
            await handle_activate_category_for_pair(update, context, parts[2], parts[3])
        return
    if data == "model:quick_deploy" or data == "model:quickdeploy":
        await q.answer()
        await _render_quick_deploy(q)
        return

    await q.answer()
    parts = data.split(":")
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
    if action == "deploy" and len(parts) > 2:
        key = parts[2]
        packs = dict(QUICK_DEPLOY_PACKS)
        packs["BTC_ALL"] = {
            "name": "Starter Pack 3 — BTC All Scenarios",
            "description": "Every BTC model — bullish and bearish coverage",
            "models": _pack_btc_all(db.get_all_models()),
        }
        pack = packs.get(key)
        if not pack:
            await q.message.reply_text("❌ Unknown pack")
            return
        activated = []
        selected_pair = _selected_pairs()[0]
        for model_id in pack["models"]:
            m = db.get_model(model_id)
            if m:
                if str(m.get("id", "")).startswith("MM_"):
                    db.update_model_fields(model_id, {"pair": "ALL", "bias": "Both"})
                    opt = engine.optimize_model_for_pair(m, selected_pair, days=30)
                    if opt.get("optimized"):
                        db.update_model_fields(
                            model_id,
                            {
                                "tier_a": opt["tier_a"],
                                "tier_b": opt["tier_b"],
                                "tier_c": opt["tier_c"],
                                "min_score": opt["min_score"],
                            },
                        )
                db.set_model_status(model_id, "active")
                activated.append(model_id)
        await q.message.reply_text(
            f"✅ {pack['name']} deployed\n{pack['description']}\nLive pair: {selected_pair}\n\nActive models:\n" + "\n".join([f"• {x}" for x in activated]),
            parse_mode="Markdown",
        )
        return
    if action == "delete_all":
        db.delete_all_models()
        await q.message.reply_text("✅ All perps models deleted.", parse_mode="Markdown")
        await handle_models_list(update, context)
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
        price_pair = m["pair"] if m.get("pair") != "ALL" else _selected_pairs()[0]
        await q.message.reply_text(formatters.fmt_model_detail(m, px.get_price(price_pair)), parse_mode="Markdown", reply_markup=kb)
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


@require_auth_callback
async def handle_scan_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    allowed, reason = check_command_rate(uid)
    if not allowed:
        await q.answer(reason, show_alert=True)
        return
    await q.answer()
    pair = q.data.split(":")[1]
    models = [x for x in db.get_active_models() if x.get("pair") in {pair, "ALL"}]
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




@require_auth
async def buy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /buy {address} {amount}")
    address, amount = context.args[0], float(context.args[1])
    db.log_audit(action="cmd_buy", details={"address": address, "amount": amount, "user": update.effective_user.id}, success=True)
    await update.message.reply_text(f"✅ Buy queued: {address[:6]}... for ${amount:.2f}")


@require_auth
async def sell_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /sell {address} {pct}")
    db.log_audit(action="cmd_sell", details={"address": context.args[0], "pct": context.args[1]}, success=True)
    await update.message.reply_text("✅ Sell queued.")


@require_auth
async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /price {symbol}")
    symbol = context.args[0].upper()
    price = px.get_price(f"{symbol}USDT") if not symbol.endswith("USDT") else px.get_price(symbol)
    db.log_audit(action="cmd_price", details={"symbol": symbol}, success=True)
    await update.message.reply_text(f"{symbol}: ${float(price or 0):,.6f}")


@require_auth
async def pnl_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trades = db.get_recent_trades(limit=100) if hasattr(db, "get_recent_trades") else []
    pnl = sum(float(t.get("rr") or 0) for t in trades)
    db.log_audit(action="cmd_pnl", details={}, success=True)
    await update.message.reply_text(f"📊 PnL summary (R): {pnl:+.2f}")


@require_auth
async def positions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Use Degen/Hyperliquid positions views for full cards.")


@require_auth
async def generic_shortcut_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.log_audit(action="cmd_shortcut", details={"cmd": update.message.text}, success=True)
    await update.message.reply_text("✅ Command received.")

@require_auth
async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update):
        return
    await update.message.reply_text("Use Stats/Models screens.", parse_mode="Markdown")


@require_auth_callback
async def handle_backtest_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    allowed, reason = check_command_rate(uid)
    if not allowed:
        await q.answer(reason, show_alert=True)
        return
    await q.answer()
    parts = q.data.split(":")
    action = parts[1] if len(parts) > 1 else "start"

    if action == "start" or action == "again":
        await _send_backtest_entry(q.message.reply_text)
    elif action == "model" and len(parts) > 2:
        await _send_backtest_pairs(q.message.reply_text, parts[2])
    elif action == "pair" and len(parts) > 3:
        await _send_backtest_days(q.message.reply_text, parts[2], parts[3])
    elif action == "days" and len(parts) > 3:
        await _run_backtest_selection(q.message.reply_text, parts[2], parts[3], parts[4] if len(parts) > 4 else "")


@require_auth
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
            "❌ Usage: `/backtest <model_id> <days> [pair]` (example: `/backtest model_abc 30 BTCUSDT`)\n"
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

    selected_pair = (args[2].strip().upper() if len(args) > 2 and args[2] else "").upper()
    if selected_pair and selected_pair not in SUPPORTED_PAIRS:
        await reply(f"❌ Pair must be one of: {', '.join(SUPPORTED_PAIRS)}")
        return
    pair = selected_pair or model.get("pair")
    if pair == "ALL" or not pair:
        pair = _selected_pairs()[0]

    run_model = dict(model)
    run_model["pair"] = pair
    optimization = engine.optimize_model_for_pair(run_model, pair, days=max(14, min(days, 30)))
    if optimization.get("optimized"):
        run_model["tier_a"] = optimization["tier_a"]
        run_model["tier_b"] = optimization["tier_b"]
        run_model["tier_c"] = optimization["tier_c"]
        run_model["min_score"] = optimization["min_score"]

    series = px.get_recent_series(pair, days=days)
    if len(series) < 40:
        await reply(
            "⚠️ Not enough price data was returned for this pair/range. Try a longer range.",
            reply_markup=_backtest_screen_kb(),
        )
        return

    result = engine.backtest_model(run_model, series)
    trades = int(result.get("trades") or 0)
    wins = int(result.get("wins") or 0)
    losses = int(result.get("losses") or 0)
    win_rate = float(result.get("win_rate") or 0)
    avg_rr = float(result.get("avg_rr") or 0)

    msg = (
        f"🧪 *Backtest — {model['name']}*\n"
        f"Pair: `{pair}`\n"
        f"Range: `{days}d`\n"
        f"Trades: `{trades}`\n"
        f"Wins/Losses: `{wins}/{losses}`\n"
        f"Win rate: `{win_rate:.2f}%`\n"
        f"Avg R/R: `{avg_rr:+.2f}R`"
    )
    if optimization.get("optimized"):
        msg += (
            f"\n\n⚙️ Optimized thresholds\n"
            f"Tier A/B/C: `{optimization['tier_a']}` / `{optimization['tier_b']}` / `{optimization['tier_c']}`"
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


async def _send_backtest_pairs(reply, model_id: str):
    model = db.get_model(model_id)
    if not model:
        await reply("❌ Model not found. Please choose again.", reply_markup=_backtest_screen_kb())
        return
    pair_buttons = [[InlineKeyboardButton(pair, callback_data=f"backtest:pair:{model_id}:{pair}")] for pair in SUPPORTED_PAIRS]
    pair_buttons.append([InlineKeyboardButton("🔄 Choose Another Model", callback_data="backtest:start")])
    await reply(
        f"🧪 *Backtest*\nModel: *{model['name']}* (`{model_id}`)\nPick a pair.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(pair_buttons),
    )


async def _send_backtest_days(reply, model_id: str, pair: str):
    model = db.get_model(model_id)
    if not model:
        await reply("❌ Model not found. Please choose again.", reply_markup=_backtest_screen_kb())
        return

    day_options = [7, 14, 30, 60]
    day_buttons = [
        InlineKeyboardButton(
            f"{days}d",
            callback_data=f"backtest:days:{model_id}:{pair}:{days}",
        )
        for days in day_options
    ]
    keyboard = [day_buttons[:2], day_buttons[2:]]
    keyboard.append([InlineKeyboardButton("🔁 Choose Another Pair", callback_data=f"backtest:model:{model_id}")])
    keyboard.append([InlineKeyboardButton("🔄 Choose Another Model", callback_data="backtest:start")])
    keyboard.append([InlineKeyboardButton("« Back to Perps", callback_data="nav:perps_home")])

    await reply(
        f"🧪 *Backtest*\nModel: *{model['name']}* (`{model_id}`)\nPair: `{pair}`\nPick a range to run now.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _run_backtest_selection(reply, model_id: str, pair: str, days_raw: str):
    try:
        days = int(days_raw)
    except Exception:
        await reply("❌ Invalid day range selected.", reply_markup=_backtest_screen_kb())
        return
    await _run_backtest_command(reply, [model_id, str(days), pair])


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


@require_auth
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


@require_auth_callback
async def goal_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    allowed, reason = check_command_rate(uid)
    if not allowed:
        await q.answer(reason, show_alert=True)
        return
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


@require_auth
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


@require_auth_callback
async def goal_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text("❌ Goal setup canceled.")
    else:
        await update.message.reply_text("❌ Goal setup canceled.")
    return ConversationHandler.END


@require_auth
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


@require_auth_callback
async def budget_target_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    allowed, reason = check_command_rate(uid)
    if not allowed:
        await q.answer(reason, show_alert=True)
        return
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


@require_auth
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


@require_auth_callback
async def budget_loss_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    allowed, reason = check_command_rate(uid)
    if not allowed:
        await q.answer(reason, show_alert=True)
        return
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


@require_auth
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


@require_auth_callback
async def budget_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    allowed, reason = check_command_rate(uid)
    if not allowed:
        await q.answer(reason, show_alert=True)
        return
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


@require_auth_callback
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


@require_auth
async def journal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update):
        return
    await journal_cmd_like(update.message.reply_text)


async def journal_cmd_like(reply_fn):
    entries = db.get_journal_entries(10)
    lines = ["📓 *Journal*", "━━━━━━━━━━━━━━━━━━━━━━━━"] + [f"[{e.get('pair', '?')}] [{e.get('result', '?')}] {e.get('entry_text', '')}" for e in entries]
    await reply_fn("\n".join(lines), parse_mode="Markdown")


_resume_tokens = {}
_addkey_state = {}
_deletekey_state = {}

@require_auth
async def handle_stop(update, context):
    from security.emergency_stop import halt_trading
    from security.audit import log_event
    user_id = update.effective_user.id
    halt_trading("User command /stop")
    log_event(action="emergency_stop", details={"trigger": "/stop command"}, user_id=user_id, success=True)
    await update.message.reply_text("🛑 *ALL TRADING HALTED*\n━━━━━━━━━━━━━━━━━━━━━━━━\nNo orders will be placed.\nKey cache cleared from memory.\n\nRun /resume to restart trading.\n_This persists across bot restarts._", parse_mode="Markdown")

@require_auth
async def handle_resume(update, context):
    import time
    from security.emergency_stop import resume_trading
    from security.audit import log_event
    uid = update.effective_user.id
    txt = (update.message.text or "").strip()
    now = time.time()
    token = _resume_tokens.get(uid)
    if txt != "/resume confirm":
        _resume_tokens[uid] = now
        reason = ""
        try:
            recent = db.get_recent_audit(hours=24, limit=20)
            for ev in recent:
                if ev.get("action") == "emergency_stop":
                    reason = ev.get("details", {}).get("trigger", "")
                    break
        except Exception:
            pass
        await update.message.reply_text(f"⚠️ Trading is halted. Last reason: {reason or 'unknown'}.\nSend `/resume confirm` within 30s to resume.", parse_mode="Markdown")
        return
    if not token or now - token > 30:
        await update.message.reply_text("Resume confirmation expired. Run /resume first, then /resume confirm within 30s.")
        return
    resume_trading("User command /resume confirm")
    log_event(action="trading_resumed", details={"trigger": "/resume confirm"}, user_id=uid, success=True)
    await update.message.reply_text("✅ Trading resumed.")

@require_auth
async def handle_security(update, context):
    from security.emergency_stop import is_halted
    from security.spending_limits import get_daily_summary
    from security.key_manager import list_stored_keys
    uid = update.effective_user.id
    halted = is_halted()
    spend = get_daily_summary()
    rate = get_rate_status(uid)
    keys = list_stored_keys()
    recent = db.get_recent_audit(hours=24, limit=3)
    lines=["🛡 *Security Dashboard*", "━━━━━━━━━━━━━━━━━━━━━━━━", f"Trading halted: {'✅ Yes' if halted else '❌ No'}", f"Auth whitelist: ✅ {len(ALLOWED_USER_IDS)} users", "", "*Today's Spend*"]
    for k,v in spend.items():
        lines.append(f"- {k}: ${v['spent']:.2f}/${v['limit']:.2f}")
    lines += ["", f"Rate: {rate['commands_last_minute']}/{rate['commands_limit']} cmd/min", f"Stored keys: {', '.join([r['key_name'] for r in keys]) or 'none'}", "", "Last audit events:"]
    for ev in recent:
        lines.append(f"- {ev.get('action')} ({'ok' if ev.get('success') else 'fail'})")
    lines.append(f"Last heartbeat time: {__import__('datetime').datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')

@require_auth
async def handle_limits(update, context):
    from security import spending_limits as sl
    text=(f"*Hard Limits*\nHyperliquid single: ${sl.MAX_SINGLE_TRADE_USD['hyperliquid']:.0f}\nSolana single: ${sl.MAX_SINGLE_TRADE_USD['solana']:.0f}\nPolymarket single: ${sl.MAX_SINGLE_TRADE_USD['polymarket']:.0f}")
    await update.message.reply_text(text, parse_mode='Markdown')

@require_auth
async def handle_audit(update, context):
    rows = db.get_recent_audit(hours=168, limit=20)
    if not rows:
        await update.message.reply_text('No audit events yet.')
        return
    lines=["*Recent Audit Log*", "━━━━━━━━━━━━━━━━━━━━━━━━"]
    for r in rows:
        lines.append(f"{r.get('timestamp')}: {r.get('action')} ({'ok' if r.get('success') else 'fail'})")
    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')

@require_auth
async def handle_keys(update, context):
    from security.key_manager import list_stored_keys
    rows = list_stored_keys()
    if not rows:
        await update.message.reply_text('No encrypted keys stored.')
        return
    await update.message.reply_text('\n'.join([f"- {r['key_name']} ({r.get('label','')})" for r in rows]))

@require_auth
async def handle_addkey(update, context):
    from security.key_manager import store_private_key
    uid = update.effective_user.id
    text = (update.message.text or '').strip()
    state = _addkey_state.get(uid, {"step": 0})

    # Fast path: /addkey <exact_key_name>
    parts = text.split(maxsplit=1)
    if len(parts) == 2 and parts[0] == '/addkey' and state.get('step', 0) == 0:
        _addkey_state[uid] = {"step": 99, "key_name": parts[1].strip(), "label": ""}
        await update.message.reply_text(f"Send private key for `{parts[1].strip()}` in next message.", parse_mode="Markdown")
        return

    if text == '/addkey':
        _addkey_state[uid] = {"step": 1}
        await update.message.reply_text('Section or key name? (hyperliquid/solana/polymarket OR hl_api_wallet/sol_hot_wallet/poly_hot_wallet/...)')
        return
    if state.get('step') == 1:
        raw = text.lower()
        if raw in {"hl_api_wallet", "sol_hot_wallet", "poly_hot_wallet", "poly_api_key", "poly_api_secret", "poly_api_passphrase"}:
            _addkey_state[uid] = {"step": 99, "key_name": raw}
            await update.message.reply_text('Label for this key?')
            return
        _addkey_state[uid] = {"step": 2, "section": raw}
        await update.message.reply_text('Label for this key?')
        return
    if state.get('step') == 2:
        state['label'] = text
        state['step'] = 3
        _addkey_state[uid] = state
        await update.message.reply_text('Send private key in next message.')
        return
    if state.get('step') == 3:
        key_name = state.get('key_name') or f"{state['section']}_main"
        store_private_key(key_name, text, state.get('label',''))
        _addkey_state.pop(uid, None)
        db.log_audit(action='key_stored', details={'key_name': key_name, 'label': state.get('label','')}, user_id=uid, success=True)
        await update.message.reply_text("✅ Key stored encrypted.\n⚠️ Please delete your previous message containing the key from this chat now.\nTap and hold the message → Delete.")
        return
    if state.get('step') == 99:
        # We already have explicit key_name, now collect either label or key body
        if state.get('label') is None:
            state['label'] = text
            _addkey_state[uid] = state
            await update.message.reply_text('Send private key in next message.')
            return
        key_name = state.get('key_name')
        store_private_key(key_name, text, state.get('label', ''))
        _addkey_state.pop(uid, None)
        db.log_audit(action='key_stored', details={'key_name': key_name, 'label': state.get('label','')}, user_id=uid, success=True)
        await update.message.reply_text("✅ Key stored encrypted.\n⚠️ Please delete your previous message containing the key from this chat now.\nTap and hold the message → Delete.")

@require_auth
async def handle_deletekey(update, context):
    from security.key_manager import list_stored_keys, delete_private_key
    from security.emergency_stop import is_halted
    uid = update.effective_user.id
    text = (update.message.text or '').strip()
    if text == '/deletekey':
        if not is_halted():
            await update.message.reply_text('Trading must be halted first. Run /stop.')
            return
        rows = list_stored_keys()
        await update.message.reply_text('Type key name to delete:\n' + '\n'.join([r['key_name'] for r in rows]))
        _deletekey_state[uid] = {'awaiting': True}
        return
    if _deletekey_state.get(uid, {}).get('awaiting'):
        delete_private_key(text)
        _deletekey_state.pop(uid, None)
        db.log_audit(action='key_deleted', details={'key_name': text}, user_id=uid, success=True)
        await update.message.reply_text(f'🗑 Key deleted: {text}')

@require_auth
async def handle_rotate(update, context):
    await update.message.reply_text('Key rotation process initiated. Use offline runbook to re-encrypt stored keys with rotate_encryption().')


@require_auth
async def handle_setup(update, context):
    text = (update.message.text or "").strip().lower()
    parts = text.split()
    if len(parts) < 2:
        await update.message.reply_text("Usage: /setup <hl|sol|poly>")
        return
    section = parts[1]
    if section == "hl":
        return await update.message.reply_text(
            "Hyperliquid Phase 2 Setup\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "1. Go to app.hyperliquid.xyz\n"
            "2. Settings → API → Generate API Wallet\n"
            "3. Copy the private key shown\n"
            "4. Send me: /addkey hl_api_wallet\n"
            "5. I'll walk you through storing it encrypted.\n\n"
            "⚠️ API wallet can TRADE only. Cannot withdraw."
        )
    if section == "sol":
        return await update.message.reply_text(
            "Solana Phase 2 Setup\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "1. Generate new keypair (dedicated bot wallet)\n"
            "2. Fund with max $500 USDC + 0.1 SOL\n"
            "3. Copy private key (base58 or byte-array)\n"
            "4. Send: /addkey sol_hot_wallet\n\n"
            "⚠️ Keep this wallet small. Only fund what you can risk."
            "1. Generate new keypair\n2. Fund with max $500 USDC + 0.1 SOL\n"
            "3. Copy private key\n4. Send: /addkey sol_hot_wallet"
        )
    if section == "poly":
        return await update.message.reply_text(
            "Polymarket Phase 2 Setup\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "1. Create Polygon hot wallet + fund with USDC\n"
            "2. polymarket.com → Profile → API Keys → Generate\n"
            "3. Store all credentials:\n"
            "/addkey poly_hot_wallet\n"
            "/addkey poly_api_key\n"
            "/addkey poly_api_secret\n"
            "/addkey poly_api_passphrase"
            "Run:\n/addkey poly_hot_wallet\n/addkey poly_api_key\n/addkey poly_api_secret\n/addkey poly_api_passphrase"
        )
    await update.message.reply_text("Unknown section. Use /setup hl, /setup sol, or /setup poly")


@require_auth_callback
async def handle_confirmation_callback(update, context):
    query = update.callback_query
    parts = (query.data or "").split(":")
    if len(parts) < 4:
        await query.answer("Invalid")
        return
    action, section, confirm_id = parts[1], parts[2], parts[3]
    if action == "cancel":
        from security.confirmation import cancel_confirmation
        cancel_confirmation(confirm_id)
        await query.message.edit_text("❌ Trade cancelled.", reply_markup=None)
        await query.answer("Cancelled")
        return
    if action == "execute":
        from security.confirmation import execute_confirmation
        await query.answer("⏳ Executing...", show_alert=False)
        await query.message.edit_text("⏳ *Executing trade...*\nPlease wait.", parse_mode="Markdown", reply_markup=None)
        success, result_or_error = await execute_confirmation(confirm_id)
        if success:
            tx_id = result_or_error.get("tx_id", "") if isinstance(result_or_error, dict) else ""
            await query.message.edit_text(f"✅ *Trade Executed*\nRef: `{tx_id}`\nCheck positions for details.", parse_mode="Markdown")
        else:
            await query.message.edit_text(f"❌ *Execution Failed*\n{result_or_error}", parse_mode="Markdown")

@require_auth
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point. Shows new homepage."""
    await show_home(update, context)


async def show_home(update, context) -> None:
    """Show the homepage for commands and callbacks."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    try:
        hl_pnl = db.get_hl_pnl_today() or 0.0
        sol_pnl = db.get_sol_pnl_today() or 0.0
        poly_open = db.count_open_poly_positions()
    except Exception:
        hl_pnl = 0.0
        sol_pnl = 0.0
        poly_open = 0

    hl_emoji = "🟢" if hl_pnl >= 0 else "🔴"
    sol_emoji = "🟢" if sol_pnl >= 0 else "🔴"

    try:
        from engine.regime_detector import get_current_regime

        regime = await get_current_regime()
        regime_line = f"Regime: {regime.get('label', '—')}"
    except Exception:
        regime_line = ""

    text = (
        "🤖 *Trading Intelligence*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{now.strftime('%b %d  %H:%M')} UTC\n\n"
        f"📈 Perps    {hl_emoji} ${hl_pnl:+.2f} today\n"
        f"🔥 Degen    {sol_emoji} ${sol_pnl:+.2f} today\n"
        f"🎯 Predictions  {poly_open} open\n"
    )
    if regime_line:
        text += f"\n_{regime_line}_\n"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Perps", callback_data="perps:home"), InlineKeyboardButton("🔥 Degen", callback_data="degen:home")],
        [InlineKeyboardButton("🎯 Predictions", callback_data="predictions:home"), InlineKeyboardButton("⚙️ Settings", callback_data="settings:home")],
        [InlineKeyboardButton("❓ Help", callback_data="help:home")],
    ])

    if update.callback_query:
        try:
            await update.callback_query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
        except Exception:
            await update.callback_query.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


start = handle_start


@require_auth
async def handle_setup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_setup(update, context)


@require_auth
async def handle_buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await buy_cmd(update, context)


@require_auth
async def handle_sell_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await sell_cmd(update, context)


@require_auth
async def handle_price_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await price_cmd(update, context)


@require_auth
async def handle_pnl_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await pnl_cmd(update, context)


@require_auth
async def handle_positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await positions_cmd(update, context)


@require_auth
async def handle_scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await scan(update, context)


@require_auth
async def handle_alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await generic_shortcut_cmd(update, context)


@require_auth
async def handle_trenches_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await generic_shortcut_cmd(update, context)


@require_auth
async def handle_settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await generic_shortcut_cmd(update, context)
