import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import db, engine, formatters, prices as px
from config import CHAT_ID, SUPPORTED_PAIRS

log = logging.getLogger(__name__)

def _guard(update: Update) -> bool: return update.effective_chat.id == CHAT_ID

def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="nav:home"), InlineKeyboardButton("⚙️ Models", callback_data="nav:models")],
        [InlineKeyboardButton("📊 Stats", callback_data="nav:stats"), InlineKeyboardButton("🛡️ Discipline", callback_data="nav:discipline")],
        [InlineKeyboardButton("📋 Alerts", callback_data="nav:alerts"), InlineKeyboardButton("💹 Prices", callback_data="nav:prices")],
        [InlineKeyboardButton("🎯 Goal", callback_data="nav:goal"), InlineKeyboardButton("💰 Budget", callback_data="nav:budget")],
        [InlineKeyboardButton("📓 Journal", callback_data="nav:journal"), InlineKeyboardButton("⚡ Status", callback_data="nav:status")],
        [InlineKeyboardButton("➕ New Model", callback_data="wiz:start")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    await update.message.reply_text(formatters.fmt_home(db.get_active_models(), db.get_recent_alerts(hours=2, limit=5)), parse_mode="Markdown", reply_markup=main_kb())

async def guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    await update.message.reply_text(formatters.fmt_help(), parse_mode="Markdown", reply_markup=main_kb())

async def handle_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); dest=q.data.split(":")[1]
    if dest == "home":
        await q.message.reply_text(formatters.fmt_home(db.get_active_models(), db.get_recent_alerts(hours=2, limit=5)), parse_mode="Markdown", reply_markup=main_kb())
    elif dest == "models":
        await _render_models(q)
    elif dest == "stats":
        row, tiers, sessions = db.get_stats_30d(), db.get_tier_breakdown(), db.get_session_breakdown()
        conv = db.get_conversion_stats()
        txt = formatters.fmt_stats(row, tiers, sessions) + "\n\n" + formatters.fmt_rolling_10(db.get_rolling_10()) + f"\n\nConversion: {conv['total_trades']}/{conv['total_alerts']} alerts entered ({conv['ratio']}%) — {conv['would_win_skipped']} skipped setups would have won"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🕐 Heatmap", callback_data="nav:heatmap"), InlineKeyboardButton("📓 Journal", callback_data="nav:journal")],[InlineKeyboardButton("📈 Rolling 10", callback_data="nav:rolling10")],[InlineKeyboardButton("🏠 Home", callback_data="nav:home")]])
        await q.message.reply_text(txt, parse_mode="Markdown", reply_markup=kb)
    elif dest == "discipline":
        from handlers.stats import _disc_score
        v = db.get_violations_30d()
        await q.message.reply_text(formatters.fmt_discipline(_disc_score(v), v), parse_mode="Markdown")
    elif dest == "alerts":
        await q.message.reply_text(formatters.fmt_alert_log(db.get_recent_alerts(hours=24, limit=20)), parse_mode="Markdown")
    elif dest == "prices":
        live_px = px.fetch_prices(SUPPORTED_PAIRS)
        lines=["💹 *Live Prices*", "━━━━━━━━━━━━━━━━━━━━━━━━"]
        for pair in SUPPORTED_PAIRS:
            if pair in live_px: lines.append(f"`{pair}` {px.fmt_price(live_px[pair])}")
        await q.message.reply_text("\n".join(lines), parse_mode="Markdown")
    elif dest == "status":
        await q.message.reply_text(formatters.fmt_status(engine.get_session(), True, len(db.get_active_models()), True), parse_mode="Markdown")
    elif dest == "budget":
        await q.message.reply_text("Use `/budget <targetR> <loss_limitR>`", parse_mode="Markdown")
    elif dest == "goal":
        await q.message.reply_text("Use `/goal <monthly_target_R>`", parse_mode="Markdown")
    elif dest == "journal":
        await journal_cmd_like(q.message.reply_text)
    elif dest == "heatmap":
        await q.message.reply_text(formatters.fmt_heatmap(db.get_hourly_breakdown()), parse_mode="Markdown")
    elif dest == "rolling10":
        await q.message.reply_text(formatters.fmt_rolling_10(db.get_rolling_10()), parse_mode="Markdown")

async def _render_models(q):
    models = db.get_all_models()
    rows=[[InlineKeyboardButton(f"{'🟢' if m['status']=='active' else '⚫'} {m['name']} ({m['pair']})", callback_data=f"model:detail:{m['id']}")] for m in models]
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="nav:home")])
    await q.message.reply_text(formatters.fmt_models(models), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))

async def handle_model_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); parts=q.data.split(":"); action=parts[1]; model_id=parts[2]
    m = db.get_model(model_id)
    if not m: return
    if action == "detail":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⏸ Deactivate" if m['status']=='active' else "✅ Activate", callback_data=f"model:toggle:{model_id}"), InlineKeyboardButton("🗑 Delete", callback_data=f"model:delete:{model_id}")],[InlineKeyboardButton("📜 History", callback_data=f"model:history:{model_id}"), InlineKeyboardButton("📋 Clone", callback_data=f"model:clone:{model_id}")],[InlineKeyboardButton("📊 Rule Analysis", callback_data=f"model:rules:{model_id}")]])
        await q.message.reply_text(formatters.fmt_model_detail(m, px.get_price(m['pair'])), parse_mode="Markdown", reply_markup=kb)
    elif action == "toggle":
        db.set_model_status(model_id, "inactive" if m['status']=='active' else "active")
        await q.message.reply_text("Updated.", parse_mode="Markdown")
    elif action == "delete":
        db.delete_model(model_id); await q.message.reply_text("Deleted.", parse_mode="Markdown")
    elif action == "history":
        vs=db.get_model_versions(model_id,5); await q.message.reply_text("\n".join(["📜 *History*"]+[f"v{v['version']} - {v['saved_at']}" for v in vs]), parse_mode="Markdown")
    elif action == "clone":
        c=db.clone_model(model_id); await q.message.reply_text(f"📋 {c['name']} cloned successfully. Tap to edit the copy.", parse_mode="Markdown")
    elif action == "rules":
        rp=db.get_rule_performance(model_id); await q.message.reply_text("\n".join(["📊 *Rule Analysis*"]+[f"• {r['name']} | Pass {r['pass_rate']}% | Win {r['win_rate']}%" for r in rp]), parse_mode="Markdown")

async def handle_scan_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer(); pair=q.data.split(":")[1]
    await q.message.reply_text(f"🔍 Scanning `{pair}`...", parse_mode="Markdown")
    from handlers.alerts import _evaluate_and_send
    for m in [x for x in db.get_active_models() if x['pair']==pair]:
        await _evaluate_and_send(q.get_bot(), m, force=True)

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    await update.message.reply_text("Use Stats/Models screens.", parse_mode="Markdown")

async def handle_backtest_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer(); await update.callback_query.message.reply_text("Backtest unchanged.", parse_mode="Markdown")

async def backtest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    await update.message.reply_text("Use `/backtest <model_id> [days]`", parse_mode="Markdown")

async def goal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    if not context.args: return await update.message.reply_text("Usage: /goal <monthly_target_r>", parse_mode="Markdown")
    db.upsert_monthly_goal(float(context.args[0]))
    await update.message.reply_text("🎯 Monthly goal saved.", parse_mode="Markdown")

async def budget_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    if len(context.args)<2: return await update.message.reply_text("Usage: /budget <target_r> <loss_limit_r>", parse_mode="Markdown")
    db.upsert_weekly_goal(float(context.args[0]), float(context.args[1]))
    await update.message.reply_text("💰 Weekly budget saved.", parse_mode="Markdown")

async def journal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    await journal_cmd_like(update.message.reply_text)

async def journal_cmd_like(reply_fn):
    entries = db.get_journal_entries(10)
    lines=["📓 *Journal*", "━━━━━━━━━━━━━━━━━━━━━━━━"]+[f"[{e.get('pair','?')}] [{e.get('result','?')}] {e.get('entry_text','')}" for e in entries]
    await reply_fn("\n".join(lines), parse_mode="Markdown")
