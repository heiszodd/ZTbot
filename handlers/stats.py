import logging
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
        score -= 10 if v["violation"] in ("V1","V3","V4") else 5
    return max(0, score)


async def stats_cmd(update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    row      = db.get_stats_30d()
    tiers    = db.get_tier_breakdown()
    sessions = db.get_session_breakdown()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="nav:home")]])
    await update.message.reply_text(
        formatters.fmt_stats(row, tiers, sessions),
        reply_markup=kb, parse_mode="Markdown"
    )


async def discipline_cmd(update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    violations = db.get_violations_30d()
    score      = _disc_score(violations)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="nav:home")]])
    await update.message.reply_text(
        formatters.fmt_discipline(score, violations),
        reply_markup=kb, parse_mode="Markdown"
    )


async def result_cmd(update, context: ContextTypes.DEFAULT_TYPE):
    """
    /result <trade_id> <TP|SL>
    Mark a trade as won or lost.
    """
    if not _guard(update): return
    args = context.args
    if len(args) < 2 or args[1].upper() not in ("TP","SL"):
        await update.message.reply_text(
            "Usage: `/result <trade_id> TP`  or  `/result <trade_id> SL`",
            parse_mode="Markdown"
        )
        return
    try:
        trade_id = int(args[0])
        result   = args[1].upper()
        db.update_trade_result(trade_id, result)
        icon = "✅ Take Profit hit!" if result == "TP" else "🛑 Stop Loss hit."
        await update.message.reply_text(
            f"{icon}\nTrade `#{trade_id}` marked as *{result}*.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📊 View Stats", callback_data="nav:stats"),
                InlineKeyboardButton("🏠 Home",       callback_data="nav:home"),
            ]])
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
