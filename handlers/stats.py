import logging
from datetime import datetime, timedelta, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import db, formatters
from config import CHAT_ID

log = logging.getLogger(__name__)

def _guard(update) -> bool: return update.effective_chat.id == CHAT_ID

def _disc_score(violations):
    score = 100
    for v in violations:
        score -= 10 if v["violation"] in ("V1", "V3", "V4") else 5
    return max(0, score)

async def stats_cmd(update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    row, tiers, sessions = db.get_stats_30d(), db.get_tier_breakdown(), db.get_session_breakdown()
    msg = formatters.fmt_stats(row, tiers, sessions) + "\n\n" + formatters.fmt_rolling_10(db.get_rolling_10())
    await update.message.reply_text(msg, parse_mode="Markdown")

async def discipline_cmd(update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    v = db.get_violations_30d(); score=_disc_score(v)
    db.update_user_preferences(CHAT_ID, discipline_score=score)
    await update.message.reply_text(formatters.fmt_discipline(score, v), parse_mode="Markdown")

async def result_cmd(update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    args = context.args
    if len(args)<2 or args[1].upper() not in ("TP","SL"):
        return await update.message.reply_text("Usage: `/result <trade_id> TP` or `/result <trade_id> SL`", parse_mode="Markdown")
    trade_id, result = int(args[0]), args[1].upper()
    db.update_trade_result(trade_id, result)
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT model_id, pair FROM trade_log WHERE id=%s", (trade_id,))
            tr = dict(cur.fetchone() or {})
    if tr.get("model_id"):
        if result == "SL":
            streak = db.increment_consecutive_losses(tr["model_id"])
            m = db.get_model(tr["model_id"])
            if m and streak >= int(m.get("auto_deactivate_threshold") or 5):
                db.set_model_status(tr["model_id"], "inactive")
                await update.message.reply_text(f"🛑 Model Auto-Deactivated: {m['name']}\nReason: {streak} consecutive losses reached the threshold.\nReview and reactivate manually when ready.", parse_mode="Markdown")
        else:
            db.reset_consecutive_losses(tr["model_id"])
    await update.message.reply_text(f"{'✅' if result=='TP' else '🛑'} Trade `#{trade_id}` marked as *{result}*.", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📊 View Stats", callback_data="nav:stats")]]))
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✍️ Add Note", callback_data=f"journal:add:{trade_id}"), InlineKeyboardButton("😤 Emotional", callback_data=f"journal:emotional:{trade_id}"), InlineKeyboardButton("✅ Skip", callback_data=f"journal:skip:{trade_id}")]])
    await update.message.reply_text(f"📝 Trade Journal — {tr.get('pair','')} {result}\nTake 30 seconds to log this trade.\nWhat did you see? What did you feel?", parse_mode="Markdown", reply_markup=kb)

async def handle_journal_cb(update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer(); d=q.data
    if d.startswith("journal:add:"):
        context.user_data["journal_trade_id"] = int(d.split(":")[-1])
        await q.message.reply_text("Send your note.", parse_mode="Markdown")
    elif d.startswith("journal:emotional:"):
        tid=int(d.split(":")[-1]); db.add_journal_entry(tid, "Emotional state flagged", emotion="emotional")
        await q.message.reply_text("⚠️ You flagged this as an emotional trade. Consider reviewing your process before the next entry.", parse_mode="Markdown")
    else:
        await q.message.reply_text("✅ Noted.", parse_mode="Markdown")

async def handle_journal_text(update, context: ContextTypes.DEFAULT_TYPE):
    tid=context.user_data.get("journal_trade_id")
    if not tid: return
    db.add_journal_entry(tid, update.message.text.strip())
    context.user_data.pop("journal_trade_id", None)
    await update.message.reply_text("📝 Saved.", parse_mode="Markdown")
