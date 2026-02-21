from datetime import datetime, timezone
from telegram.ext import ContextTypes
import db, engine, prices as px
from config import CHAT_ID


async def send_morning_briefing(context: ContextTypes.DEFAULT_TYPE):
    prefs = db.get_user_preferences(CHAT_ID)
    active = db.get_active_models()
    pairs = [m["pair"] for m in active] or ["BTCUSDT", "ETHUSDT"]
    htf_lines = []
    for pair in pairs[:6]:
        h1, h4 = engine.get_session(), engine.get_session()
        htf_lines.append(f"{pair}: {h1}/{h4}")
    daily_loss = db.get_daily_realized_loss_pct()
    text = (
        "📊 *Morning Briefing*\n"
        f"Session: {engine.get_session()}\n"
        f"Active models: {len(active)}\n"
        f"Yesterday P&L proxy: {-daily_loss:.2f}%\n"
        "Key levels/news: source unavailable in this environment.\n"
        + "\n".join(htf_lines)
    )
    await context.application.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")


async def send_session_open(context: ContextTypes.DEFAULT_TYPE):
    active = db.get_active_models()
    pairs = sorted({m["pair"] for m in active})
    bias_lines = []
    for pair in pairs[:8]:
        p = px.get_price(pair)
        bias_lines.append(f"{pair}: {px.fmt_price(p) if p else 'n/a'}")
    text = "✅ *Session Open*\n" + "\n".join(bias_lines or ["No active pairs."])
    await context.application.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")


async def send_weekly_review_prompt(context: ContextTypes.DEFAULT_TYPE):
    summary = db.get_performance_summary()
    prefs = db.get_user_preferences(CHAT_ID)
    text = (
        "📊 *Weekly Review Prompt*\n"
        f"Total R: {summary.get('total_r') or 0}R\n"
        f"Discipline score: {prefs.get('discipline_score', 100)}\n"
        "Any rule changes needed this week?"
    )
    await context.application.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")


async def send_monthly_report(context: ContextTypes.DEFAULT_TYPE):
    summary = db.get_performance_summary()
    text = (
        "📊 *Monthly Report*\n"
        f"Trades: {summary.get('total') or 0}\n"
        f"Win/Loss: {summary.get('wins') or 0}/{summary.get('losses') or 0}\n"
        f"Total R: {summary.get('total_r') or 0}R\n"
        f"Max DD: {summary.get('max_drawdown_r') or 0}R"
    )
    await context.application.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")
