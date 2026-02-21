import logging
from datetime import datetime, timedelta, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import db, formatters
from config import CHAT_ID

log = logging.getLogger(__name__)


def _guard(update) -> bool:
    return update.effective_chat.id == CHAT_ID


def _disc_score(violations):
    score = 100
    for v in violations:
        score -= 10 if v["violation"] in ("V1", "V3", "V4") else 5
    return max(0, score)


async def stats_cmd(update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update):
        return
    row = db.get_stats_30d()
    tiers = db.get_tier_breakdown()
    sessions = db.get_session_breakdown()
    summary = db.get_performance_summary()
    model_breakdown = db.get_performance_breakdown("model")
    combo_rows = db.get_conn()
    with combo_rows as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT model_id, pair, session,
                       ROUND(AVG(rr)::numeric, 3) AS expectancy,
                       COUNT(*) AS trades
                FROM trade_log
                GROUP BY model_id, pair, session
                ORDER BY expectancy DESC NULLS LAST, trades DESC
                LIMIT 1
                """
            )
            leader = dict(cur.fetchone() or {})
    underperforming = [x for x in model_breakdown if (x.get("trades") or 0) >= 20 and (x.get("expectancy") or 0) < 0]
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="nav:home")]])
    await update.message.reply_text(
        formatters.fmt_stats(row, tiers, sessions, summary, leader, underperforming, db.get_losing_streak()),
        reply_markup=kb,
        parse_mode="Markdown",
    )


async def discipline_cmd(update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update):
        return
    violations = db.get_violations_30d()
    score = _disc_score(violations)
    prefs = db.get_user_preferences(CHAT_ID)
    db.update_user_preferences(CHAT_ID, discipline_score=score)

    extra = ""
    if score < 40:
        lock_until = datetime.now(timezone.utc) + timedelta(hours=24)
        db.update_user_preferences(CHAT_ID, alert_lock_until=lock_until)
        extra = "\n\n⚠️ Discipline score <40. Alerts locked for 24 hours."
    elif score < 60:
        extra = "\n\n⚠️ Discipline score <60. Consider pausing for the day."

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="nav:home")]])
    await update.message.reply_text(
        formatters.fmt_discipline(score, violations) + extra,
        reply_markup=kb,
        parse_mode="Markdown",
    )


async def result_cmd(update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update):
        return
    args = context.args
    if len(args) < 2 or args[1].upper() not in ("TP", "SL"):
        await update.message.reply_text("Usage: `/result <trade_id> TP`  or  `/result <trade_id> SL`", parse_mode="Markdown")
        return
    try:
        trade_id = int(args[0])
        result = args[1].upper()
        db.update_trade_result(trade_id, result)
        icon = "✅ Take Profit hit!" if result == "TP" else "🛑 Stop Loss hit."
        await update.message.reply_text(
            f"{icon}\nTrade `#{trade_id}` marked as *{result}*.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("📊 View Stats", callback_data="nav:stats"), InlineKeyboardButton("🏠 Home", callback_data="nav:home")]]
            ),
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
