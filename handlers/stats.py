import logging
from telegram import Update
from telegram.ext import ContextTypes
import db, formatters
from config import CHAT_ID

log = logging.getLogger(__name__)


def _guard(update: Update) -> bool:
    return update.effective_chat.id == CHAT_ID


def _discipline_score(violations) -> int:
    score = 100
    for v in violations:
        score -= 10 if v["violation"] in ("V1","V3","V4") else 5
    return max(0, score)


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    row      = db.get_stats_30d()
    tiers    = db.get_tier_breakdown()
    sessions = db.get_session_breakdown()
    await update.message.reply_text(formatters.fmt_stats(row, tiers, sessions))


async def discipline_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    violations = db.get_violations_30d()
    score      = _discipline_score(violations)
    await update.message.reply_text(formatters.fmt_discipline(score, violations))


async def regime_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    from engine import get_session
    from datetime import datetime, timezone
    utc_hour = datetime.now(timezone.utc).hour
    session  = get_session(utc_hour)

    sessions = db.get_session_breakdown()
    lines = [
        "🌍 Regime Report\n" + "─"*22,
        f"Current session: {session}",
        "",
        "30-day win rate by session:",
    ]
    for s in sessions:
        sr  = s["total"] or 0
        sw  = s["wins"]  or 0
        swr = round((sw/sr)*100, 1) if sr else 0
        lines.append(f"  {s['session']:<10} {swr}%  ({sr} trades)")

    lines += [
        "",
        "Session windows (UTC):",
        "  Asia     23:00 – 08:00",
        "  London   08:00 – 16:00",
        "  Overlap  12:00 – 16:00",
        "  NY       13:00 – 21:00",
        "",
        "Volatility modifiers:",
        "  Low vol     0",
        "  Normal vol  0",
        "  High vol   +0.5",
        "  Extreme    −1.0",
        "",
        "HTF modifiers:",
        "  1H+4H aligned   +0.5",
        "  Either conflict −1.0",
        "  Neutral          0",
    ]
    await update.message.reply_text("\n".join(lines))
