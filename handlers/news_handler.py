import logging
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import db
import news
import prices
from config import CHAT_ID, SUPPORTED_PAIRS, WAT

log = logging.getLogger(__name__)


def _active_pairs() -> list[str]:
    models = db.get_active_models()
    pairs = sorted({m.get("pair") for m in models if m.get("pair")})
    return pairs or list(SUPPORTED_PAIRS)


def _dir_icon(direction: str) -> str:
    d = (direction or "").lower()
    return "📈 Bullish" if d == "bullish" else "📉 Bearish" if d == "bearish" else "⚡ Volatile"


def _conf_icon(conf: str) -> str:
    c = (conf or "").lower()
    return "🟢 High" if c == "high" else "🟡 Medium" if c == "medium" else "🔴 Low"


def _fmt_time(dt_utc):
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc.astimezone(WAT).strftime("%H:%M"), dt_utc.astimezone(timezone.utc).strftime("%H:%M")


async def news_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or update.effective_chat.id != CHAT_ID:
        return
    await _send_news_screen(update.message.reply_text)


async def _send_news_screen(sender):
    events = news.get_upcoming_events(_active_pairs(), hours_ahead=24)
    lines = ["📰 News Trading", "━━━━━━━━━━━━━━━━━━━━━━━━", "Upcoming high-impact events for your active pairs:"]
    if not events:
        lines.append("\n📭 No high-impact events in the next 24 hours.")
    for ev in events[:20]:
        sent = news.get_event_sentiment(ev)
        wat, _ = _fmt_time(ev["time_utc"])
        lines += [
            f"\n[{_dir_icon(sent['direction']).split()[0]}] {ev['name']}",
            f"   🪙 {ev['pair']}   ⏰ {wat} WAT",
            f"   Forecast: {ev.get('forecast') or 'N/A'}  Previous: {ev.get('previous') or 'N/A'}",
            f"   Prediction: {sent['direction'].title()} ({sent['confidence'].title()} confidence)",
        ]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="news:refresh"), InlineKeyboardButton("📋 News History", callback_data="news:history")],
        [InlineKeyboardButton("🏠 Home", callback_data="nav:home")],
    ])
    await sender("\n".join(lines), reply_markup=kb)


async def news_briefing_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        pairs = _active_pairs()
        for ev in news.get_upcoming_events(pairs, hours_ahead=8):
            try:
                db.save_news_event(ev)
            except Exception as exc:
                log.error("save_news_event seed failed: %s", exc)
        pending = db.get_unsent_briefings(minutes_ahead=31)
        for event in pending:
            sentiment = news.get_event_sentiment(event)
            event_id = event["id"]
            wat, utc = _fmt_time(event["event_time_utc"])
            low_conf = "\n\n🔴 Low confidence — consider skipping this trade." if sentiment["confidence"] == "low" else ""
            msg = (
                "📰 Upcoming News Alert\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 {event['event_name']}\n"
                f"🪙 Affects: {event['pair']}\n"
                f"⏰ Time: {wat} WAT ({utc} UTC)\n"
                "💥 Impact: 🔴 High\n\n"
                "📊 Forecast vs Previous\n"
                f"   Forecast:  {event.get('forecast') or 'N/A'}\n"
                f"   Previous:  {event.get('previous') or 'N/A'}\n\n"
                "🧠 Predicted Outcome\n"
                f"   Direction:   {_dir_icon(sentiment['direction'])}\n"
                f"   Confidence:  {_conf_icon(sentiment['confidence'])}\n"
                f"   Reasoning:   {sentiment['reasoning']}\n\n"
                "⚠️ Trade alert will fire the moment this event goes live.\n"
                f"   Expected move: ~{sentiment['expected_move_pct']:.1f}%"
                "\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🔕 Suppress this event?"
                f"{low_conf}"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Watch this", callback_data=f"news:watch:{event_id}"), InlineKeyboardButton("🔕 Suppress", callback_data=f"news:suppress:{event_id}"), InlineKeyboardButton("📋 View all news", callback_data="news:refresh")]
            ])
            await context.application.bot.send_message(chat_id=CHAT_ID, text=msg, reply_markup=kb)
            db.mark_briefing_sent(event_id)
    except Exception as exc:
        log.error("news_briefing_job failed: %s", exc)


async def news_signal_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        for event in db.get_unsent_signals():
            sentiment = news.get_event_sentiment(event)
            direction = sentiment["direction"]
            event_id = event["id"]
            if direction == "volatile":
                await context.application.bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"⚡ {event['event_name']} is live — high volatility expected. No directional bias. Stay out until price confirms direction.",
                )
                db.mark_signal_sent(event_id)
                continue

            live = prices.get_price(event["pair"])
            if not live:
                log.warning("No live price for %s", event["pair"])
                continue

            if direction == "bullish":
                side = "LONG"
                entry = live
                sl = entry - (entry * 0.008)
                tp1 = entry + (entry * 0.008)
                tp2 = entry + (entry * 0.016)
                tp3 = entry + (entry * 0.024)
            else:
                side = "SHORT"
                entry = live
                sl = entry + (entry * 0.008)
                tp1 = entry - (entry * 0.008)
                tp2 = entry - (entry * 0.016)
                tp3 = entry - (entry * 0.024)

            low_conf = "\n🔴 Low confidence — consider skipping this trade." if sentiment["confidence"] == "low" else ""
            wat = datetime.now(timezone.utc).astimezone(WAT).strftime("%H:%M WAT")
            msg = (
                "🚨 NEWS TRADE SIGNAL\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 {event['event_name']} — LIVE NOW\n"
                f"🪙 {event['pair']}   {'📈 LONG' if side=='LONG' else '📉 SHORT'}\n"
                f"⏰ {wat}\n\n"
                "💹 Levels\n"
                f"   Entry   {prices.fmt_price(entry)}\n"
                f"   SL      {prices.fmt_price(sl)}   (0.8%)\n"
                f"   TP1     {prices.fmt_price(tp1)}   (1:1)\n"
                f"   TP2     {prices.fmt_price(tp2)}   (1:2)\n"
                f"   TP3     {prices.fmt_price(tp3)}   (1:3)\n\n"
                "🧠 Basis\n"
                f"   {sentiment['reasoning']}\n"
                f"   Confidence: {sentiment['confidence'].title()}\n"
                "\n⚠️ NEWS TRADE RISK WARNING\n"
                "   News trades are high risk. Price can\n"
                "   reverse instantly. Use reduced size.\n"
                "   Suggested risk: 0.5% max.\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Did you take this trade?"
                f"{low_conf}"
            )
            trade_id = db.log_news_trade(
                {
                    "news_event_id": event_id,
                    "pair": event["pair"],
                    "direction": "BUY" if side == "LONG" else "SELL",
                    "entry_price": entry,
                    "sl": sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "tp3": tp3,
                    "rr": 3.0,
                    "pre_news_price": entry,
                }
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Entered", callback_data=f"news:entered:{trade_id}"), InlineKeyboardButton("❌ Skipped", callback_data=f"news:skipped:{trade_id}"), InlineKeyboardButton("👀 Watching", callback_data=f"news:watching:{trade_id}")]
            ])
            await context.application.bot.send_message(chat_id=CHAT_ID, text=msg, reply_markup=kb)
            db.mark_signal_sent(event_id)
    except Exception as exc:
        log.error("news_signal_job failed: %s", exc)


async def handle_news_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    parts = q.data.split(":")
    action = parts[1]

    if action == "refresh":
        await _send_news_screen(q.message.reply_text)
    elif action == "history":
        rows = db.get_news_history(limit=10)
        lines = ["📋 News History", "━━━━━━━━━━━━━━━━━━━━━━━━"]
        if not rows:
            lines.append("No history yet.")
        for r in rows:
            lines.append(
                f"• {r['event_name']} | {r['pair']} | Pred: {str(r.get('direction') or '-').upper()} | Result: {r.get('result') or 'N/A'} | Correct: {'✅' if r.get('correct') else '❌' if r.get('correct') is not None else '—'}"
            )
        await q.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="nav:home")]]))
    elif action == "suppress" and len(parts) > 2:
        event_id = int(parts[2])
        db.suppress_news_event(event_id)
        await q.message.reply_text("🔕 Event suppressed. No trade signal will be sent for it.")
    elif action == "watch" and len(parts) > 2:
        event_id = int(parts[2])
        ev = db.get_news_event(event_id)
        if ev:
            wat = ev["event_time_utc"].replace(tzinfo=timezone.utc).astimezone(WAT).strftime("%H:%M WAT")
            await q.message.reply_text(f"👀 Watching {ev['event_name']} — signal fires at {wat}")
    elif action == "entered" and len(parts) > 2:
        trade_id = int(parts[2])
        tr = db.get_news_trade(trade_id)
        if tr:
            db.log_trade(
                {
                    "pair": tr["pair"],
                    "model_id": "NEWS",
                    "tier": "N",
                    "direction": tr["direction"],
                    "entry_price": tr["entry_price"],
                    "sl": tr["sl"],
                    "tp": tr["tp1"],
                    "rr": tr["rr"],
                    "session": "News",
                    "score": 0,
                    "risk_pct": 0.5,
                    "result": None,
                    "violation": None,
                }
            )
            await q.message.reply_text("✅ News trade logged. 📸 Screenshot reminder: capture your chart entry now.")
    elif action == "skipped":
        await q.message.reply_text("❌ News trade skipped.")
    elif action == "watching":
        await q.message.reply_text("👀 Watching — keep monitoring post-news candles.")
