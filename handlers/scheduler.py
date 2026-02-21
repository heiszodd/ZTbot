from datetime import datetime, timedelta, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import db, engine, prices as px, context as mctx
from config import CHAT_ID

async def send_morning_briefing(context: ContextTypes.DEFAULT_TYPE):
    active = db.get_active_models()
    lines=["☀️ *Daily Briefing*", "━━━━━━━━━━━━━━━━━━━━━━━━", f"Session: `{engine.get_session()}` | UTC `{datetime.now(timezone.utc).strftime('%H:%M')}`", ""]
    lines.append("⚙️ *Active Models*")
    for m in active[:10]:
        lines.append(f"• {m['name']} | {m['pair']} | last setup: n/a")
    lines.append("\n📍 *Key Levels*")
    for m in active[:6]:
        for lv in (m.get('key_levels') or [])[:2]:
            lines.append(f"• {m['pair']} @ `{lv}`")
    y_r = 0.0
    lines.append(f"\n💰 Yesterday P&L: `{y_r:+.2f}R`")
    w = db.get_weekly_goal()
    if w:
        ach = db.update_weekly_achieved(); tgt = float(w.get('r_target') or 0)
        pct = int((ach / tgt) * 100) if tgt else 0
        bar = '█' * max(0, min(10, pct // 10)) + '░' * (10 - max(0, min(10, pct // 10)))
        lines.append(f"Week: `{ach:+.1f}R / +{tgt:.1f}R` target  [{bar}] {pct}%")
    prefs = db.get_user_preferences(CHAT_ID)
    lines.append(f"🛡️ Discipline: `{prefs.get('discipline_score', 100)}/100`")
    mg = db.get_monthly_goal() if hasattr(db, 'get_monthly_goal') else None
    if mg:
        ach = float(mg.get('r_achieved') or 0); tgt = float(mg.get('r_target') or 0); pct = int((ach/tgt)*100) if tgt else 0
        bar='█'*max(0,min(10,pct//10))+'░'*(10-max(0,min(10,pct//10)))
        lines.append(f"🎯 Monthly Goal: `{ach:+.1f}R / +{tgt:.1f}R` [{bar}] {pct}%")
    await context.application.bot.send_message(chat_id=CHAT_ID, text='\n'.join(lines), parse_mode='Markdown')

async def send_session_open(context: ContextTypes.DEFAULT_TYPE):
    await context.application.bot.send_message(chat_id=CHAT_ID, text="✅ *Session Open*", parse_mode="Markdown")

async def send_weekly_review_prompt(context: ContextTypes.DEFAULT_TYPE):
    summary = db.get_stats_30d()
    text = ("📋 Weekly Review — [Mon-Sun]\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"This week:\n📊 Trades: [{summary.get('total',0)}] | W [{summary.get('wins',0)}] L [{summary.get('losses',0)}]\n"
            f"💰 Total R: [{summary.get('total_r',0)}]\n"
            f"🛡️ Avg discipline: [{db.get_user_preferences(CHAT_ID).get('discipline_score',100)}]\n"
            "🔥 Best model: [N/A] ([0])\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Take 5 minutes to reflect:\nWhat worked? What didn't? Any rule changes needed?")
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("📝 Add Note", callback_data="weekly:add_note"), InlineKeyboardButton("✅ Done", callback_data="weekly:done")]])
    await context.application.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode='Markdown', reply_markup=kb)

async def send_monthly_report(context: ContextTypes.DEFAULT_TYPE):
    summary = db.get_performance_summary()
    await context.application.bot.send_message(chat_id=CHAT_ID, text=f"📊 *Monthly Report*\nTrades: {summary.get('total',0)}\nTotal R: {summary.get('total_r',0)}", parse_mode='Markdown')

async def send_end_of_day_summary(context: ContextTypes.DEFAULT_TYPE):
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) c FROM alert_log WHERE alerted_at::date=NOW()::date"); setups=int(cur.fetchone()['c'] or 0)
            cur.execute("SELECT COUNT(*) c, COALESCE(SUM(rr),0) r FROM trade_log WHERE logged_at::date=NOW()::date"); row=cur.fetchone(); trades=int(row['c'] or 0); r=float(row['r'] or 0)
    score = db.get_user_preferences(CHAT_ID).get('discipline_score',100)
    streak = db.get_losing_streak()
    mot = "Great execution today." if r>0 else "Flat day, stay consistent." if r==0 else "Protect capital and review mistakes."
    txt=(f"🌙 End of Day Summary — [{datetime.now(timezone.utc).date()}]\n━━━━━━━━━━━━━━━━━━━━━━━━\n📡 Setups fired:    [{setups}]\n✅ Trades taken:    [{trades}]\n💰 R today:         [{r:+.2f}]\n🛡️ Discipline:      [{score}]/100\n📉 Loss streak:     [{streak}]\n━━━━━━━━━━━━━━━━━━━━━━━━\n{mot}")
    await context.application.bot.send_message(chat_id=CHAT_ID, text=txt, parse_mode='Markdown')

async def send_news_pre_warning(context: ContextTypes.DEFAULT_TYPE):
    await context.application.bot.send_message(chat_id=CHAT_ID, text="📰 News Warning — NFP\nPair: [BTCUSDT] | Time: [12:00 UTC] | Impact: 🔴 High\n⚠️ Alerts for [BTCUSDT] will be suppressed from [11:30] to [12:15]", parse_mode='Markdown')
