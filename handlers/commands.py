import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import db, engine, formatters
from config import CHAT_ID

log = logging.getLogger(__name__)


def _guard(update: Update) -> bool:
    """Only respond to the authorised chat."""
    return update.effective_chat.id == CHAT_ID


# ── /start ────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    await update.message.reply_text(formatters.fmt_start())


# ── /help ─────────────────────────────────────────────
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    await update.message.reply_text(formatters.fmt_help())


# ── /status ───────────────────────────────────────────
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    session = engine.get_session()
    try:
        db.get_conn().close()
        db_ok = True
    except Exception:
        db_ok = False
    active = len(db.get_active_models())
    await update.message.reply_text(formatters.fmt_status(session, db_ok, active))


# ── /menu ─────────────────────────────────────────────
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Models",     callback_data="menu:models"),
            InlineKeyboardButton("📊 Stats",      callback_data="menu:stats"),
        ],
        [
            InlineKeyboardButton("🛡️ Discipline",  callback_data="menu:discipline"),
            InlineKeyboardButton("🔍 Scan",        callback_data="menu:scan"),
        ],
        [
            InlineKeyboardButton("⚙️ Status",      callback_data="menu:status"),
            InlineKeyboardButton("📖 Help",        callback_data="menu:help"),
        ],
    ])
    await update.message.reply_text("📡 Main Menu — choose an option:", reply_markup=keyboard)


async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.split(":")[1]

    if action == "models":
        models = db.get_all_models()
        for m in models:
            m["rules"] = m["rules"] if isinstance(m["rules"], list) else []
        await query.message.reply_text(formatters.fmt_models(models))

    elif action == "stats":
        row      = db.get_stats_30d()
        tiers    = db.get_tier_breakdown()
        sessions = db.get_session_breakdown()
        await query.message.reply_text(formatters.fmt_stats(row, tiers, sessions))

    elif action == "discipline":
        violations = db.get_violations_30d()
        score      = _calc_discipline_score(violations)
        await query.message.reply_text(formatters.fmt_discipline(score, violations))

    elif action == "scan":
        await query.message.reply_text("Send /scan PAIR  e.g.  /scan EURUSD")

    elif action == "status":
        session = engine.get_session()
        try:
            db.get_conn().close(); db_ok = True
        except Exception:
            db_ok = False
        active = len(db.get_active_models())
        await query.message.reply_text(formatters.fmt_status(session, db_ok, active))

    elif action == "help":
        await query.message.reply_text(formatters.fmt_help())


# ── /models ───────────────────────────────────────────
async def list_models(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    models = db.get_all_models()
    for m in models:
        m["rules"] = m["rules"] if isinstance(m["rules"], list) else []
    text = formatters.fmt_models(models)

    # Add per-model detail buttons
    buttons = []
    for m in models:
        buttons.append([InlineKeyboardButton(
            f"{'🟢' if m['status']=='active' else '⚪'} {m['name']}",
            callback_data=f"model:detail:{m['id']}"
        )])
    keyboard = InlineKeyboardMarkup(buttons) if buttons else None
    await update.message.reply_text(text, reply_markup=keyboard)


async def handle_model_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    action = parts[1]

    if action == "detail":
        model_id = parts[2]
        m = db.get_model(model_id)
        if not m:
            await query.message.reply_text("Model not found.")
            return
        m["rules"] = m["rules"] if isinstance(m["rules"], list) else []
        text = formatters.fmt_model_detail(m)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "✅ Activate" if m["status"] != "active" else "⏸ Deactivate",
                callback_data=f"model:toggle:{model_id}"
            )
        ]])
        await query.message.reply_text(text, reply_markup=keyboard)

    elif action == "toggle":
        model_id = parts[2]
        m = db.get_model(model_id)
        if not m:
            await query.message.reply_text("Model not found.")
            return
        new_status = "inactive" if m["status"] == "active" else "active"
        db.set_model_status(model_id, new_status)
        icon = "✅ Activated" if new_status == "active" else "⏸ Deactivated"
        await query.message.reply_text(f"{icon}: {m['name']}")


# ── /activate /deactivate ────────────────────────────
async def activate_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    if not context.args:
        await update.message.reply_text("Usage: /activate MODEL_ID")
        return
    model_id = context.args[0]
    m = db.get_model(model_id)
    if not m:
        await update.message.reply_text(f"Model '{model_id}' not found.")
        return
    db.set_model_status(model_id, "active")
    await update.message.reply_text(f"✅ Activated: {m['name']}")


async def deactivate_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    if not context.args:
        await update.message.reply_text("Usage: /deactivate MODEL_ID")
        return
    model_id = context.args[0]
    m = db.get_model(model_id)
    if not m:
        await update.message.reply_text(f"Model '{model_id}' not found.")
        return
    db.set_model_status(model_id, "inactive")
    await update.message.reply_text(f"⏸ Deactivated: {m['name']}")


# ── /scan ─────────────────────────────────────────────
async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    pair = context.args[0].upper() if context.args else "EURUSD"

    active_models = db.get_active_models()
    if not active_models:
        await update.message.reply_text("No active models. Use /activate MODEL_ID first.")
        return

    await update.message.reply_text(f"🔍 Scanning {pair}...")

    for m in active_models:
        m["rules"] = m["rules"] if isinstance(m["rules"], list) else []

        # Build a live setup dict — wire in real rule evaluation here
        setup = _build_live_setup(pair, m)
        scored = engine.score_setup(setup, m)

        text = formatters.fmt_scan_result(pair, scored, m)
        await update.message.reply_text(text)

        db.log_alert(pair, m["id"], scored["final_score"],
                     scored["tier"], scored["valid"], scored["invalid_reason"])


# ── /alerts ───────────────────────────────────────────
async def list_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT pair, tier, valid, score, reason, alerted_at
                FROM alert_log
                WHERE alerted_at > NOW() - INTERVAL '24 hours'
                ORDER BY alerted_at DESC
                LIMIT 20
            """)
            alerts = cur.fetchall()
    await update.message.reply_text(formatters.fmt_alert_log(alerts))


# ── Helpers ───────────────────────────────────────────
def _calc_discipline_score(violations):
    score = 100
    for v in violations:
        score -= 10 if v["violation"] in ("V1","V3","V4") else 5
    return max(0, score)


def _build_live_setup(pair: str, model: dict) -> dict:
    """
    Stub — replace each field with real candle/rule evaluation.
    See data.py for the ATR calculation and ccxt integration.
    """
    return {
        "pair":            pair,
        "passed_rule_ids": [],   # ← populate from real rule checks
        "atr_ratio":       1.0,  # ← from data.get_atr_ratio(pair, tf)
        "htf_1h":          "Neutral",
        "htf_4h":          "Neutral",
        "news_minutes":    None, # ← from news.get_next_event(pair)
        "sl":              "0.0000",
        "tp":              "0.0000",
        "rr":              "0.0",
        "direction":       "BUY",
    }
