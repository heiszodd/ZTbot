import asyncio
import logging
from datetime import datetime, timedelta, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import db, engine, formatters, prices as px
from degen.scanner import degen_scan_job
from config import CHAT_ID, TIER_RISK, CORRELATED_PAIRS

log = logging.getLogger(__name__)
_recent, _pending, _watching = {}, {}, {}
_skipped_zones = []
_aging_jobs, _last_proximity = {}, {}
_circuit_warned_at = None
_DEDUP_SEC = 900


def _dedup_key(pair, model_id, tier): return f"{pair}_{model_id}_{tier}"
def _is_dup(pair, model_id, tier): return (datetime.now(timezone.utc).timestamp() - _recent.get(_dedup_key(pair, model_id, tier), 0)) < _DEDUP_SEC
def _mark(pair, model_id, tier): _recent[_dedup_key(pair, model_id, tier)] = datetime.now(timezone.utc).timestamp()


def _correlation_warning(pair: str):
    open_pairs = set(db.get_open_trades_pairs())
    corr = set(CORRELATED_PAIRS.get(pair, [])) & open_pairs
    if corr:
        cp = sorted(corr)[0]
        return f"⚠️ Correlation Warning — you have an open {cp} position. Entering this increases correlated exposure."
    return None


async def _setup_aging_follow_up(context: ContextTypes.DEFAULT_TYPE):
    d = context.job.data
    pair, entry = d["pair"], float(d["entry"])
    cur = px.get_price(pair)
    if not cur:
        return
    diff = ((cur - entry) / entry) * 100 if entry else 0
    if abs(diff) > 0.5:
        msg = f"⏰ Setup Update — [{pair}] price has moved [{diff:+.2f}]% from your entry level. Review before entering."
    else:
        msg = f"⏰ Still valid — [{pair}] is near entry. Setup remains active."
    msg += f"\nOriginal entry: `{px.fmt_price(entry)}`\nCurrent price: `{px.fmt_price(cur)}`\nDifference: `{diff:+.2f}%`"
    await context.application.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")


def check_proximity_alerts(bot, model, price):
    levels = model.get("key_levels") or []
    for lv in levels:
        try:
            lv = float(lv)
        except Exception:
            continue
        if lv and abs((price - lv) / lv) * 100 <= 0.3:
            key = f"{model['pair']}:{lv}"
            now = datetime.now(timezone.utc)
            if key not in _last_proximity or (now - _last_proximity[key]).total_seconds() > 1800:
                _last_proximity[key] = now
                asyncio.create_task(bot.send_message(chat_id=CHAT_ID, text=f"📍 Price approaching key level [{lv}] on [{model['pair']}] — [{model['name']}] — prepare your checklist", parse_mode="Markdown"))


async def _evaluate_and_send(bot, model: dict, force=False):
    global _circuit_warned_at
    prefs = db.get_user_preferences(CHAT_ID)
    if prefs.get("risk_off_mode"):
        return False
    pair = model["pair"]
    price = px.get_price(pair)
    if not price:
        return False
    check_proximity_alerts(bot, model, price)

    weekly = db.get_weekly_goal() if hasattr(db, "get_weekly_goal") else None
    if weekly and db.update_weekly_achieved() <= float(weekly.get("loss_limit", -3)):
        if not weekly.get("alerts_paused_notified"):
            await bot.send_message(chat_id=CHAT_ID, text=f"🛑 Weekly loss limit reached ({weekly.get('loss_limit')}R). Alerts paused until Monday.", parse_mode="Markdown")
        return False

    series = px.get_recent_series(pair, days=2)
    setup = engine.build_live_setup(model, series)
    if not setup.get("passed_rule_ids"):
        return False

    scored = engine.score_setup(setup, model)
    if not scored.get("tier"):
        return False
    if not force and _is_dup(pair, model["id"], scored["tier"]):
        return False

    atr = px.estimate_atr(series[-30:]) if series else None
    sl, tp, rr = px.calc_sl_tp(price, setup["direction"], atr=atr)
    setup.update({"entry": price, "sl": sl, "tp": tp, "rr": rr})

    db.log_alert(pair, model["id"], model["name"], scored["final_score"], scored["tier"], setup["direction"], price, sl, tp, rr, True)
    _mark(pair, model["id"], scored["tier"])
    key = f"{pair}_{model['id']}_{datetime.now(timezone.utc).strftime('%H%M%S')}"
    _pending[key] = (setup, model, scored)

    text = formatters.fmt_alert(setup, model, scored, risk_pct=float(TIER_RISK.get(scored["tier"], 0)), risk_usd=0.0, correlation_warning=_correlation_warning(pair))
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Entered", callback_data=f"alert:entered:{key}"), InlineKeyboardButton("🎮 Demo Entry", callback_data=f"alert:demo:{key}")],[InlineKeyboardButton("❌ Skipped", callback_data=f"alert:skipped:{key}"), InlineKeyboardButton("👀 Watching", callback_data=f"alert:watching:{key}")]])
    await bot.send_message(chat_id=CHAT_ID, text=text, reply_markup=kb, parse_mode="Markdown")
    job = bot._application.job_queue.run_once(_setup_aging_follow_up, when=900, data={"pair": pair, "entry": price}, name=f"aging:{key}")
    _aging_jobs[key] = job
    return True


async def run_scanner(context: ContextTypes.DEFAULT_TYPE):
    bot = context.application.bot
    models = db.get_active_models()
    sem = asyncio.Semaphore(4)

    async def _scan_model(m):
        async with sem:
            try:
                return await _evaluate_and_send(bot, m)
            except Exception as e:
                log.error(f"scanner error {e}")
                return False

    if models:
        await asyncio.gather(*[_scan_model(m) for m in models])
    try:
        await degen_scan_job(context)
    except Exception as e:
        log.error(f"degen scanner error {e}")


async def _render_checklist(message, context):
    st = context.user_data.get("checklist")
    if not st:
        return
    icon = lambda x: "✅" if x else "❌"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{icon(st['alert_fired'])} Alert fired", callback_data="alert:chk:alert_fired")],
        [InlineKeyboardButton(f"{icon(st['size_correct'])} Size correct", callback_data="alert:chk:size_correct")],
        [InlineKeyboardButton(f"{icon(st['sl_placed'])} SL placed", callback_data="alert:chk:sl_placed")],
        [InlineKeyboardButton("📈 Trending", callback_data="alert:mc:trending"), InlineKeyboardButton("↔️ Ranging", callback_data="alert:mc:ranging")],
        [InlineKeyboardButton("Confirm Entry", callback_data="alert:confirm_entry"), InlineKeyboardButton("Confirm anyway", callback_data="alert:confirm_anyway")],
    ])
    await message.reply_text("Before logging this trade, confirm:\n✅ An alert fired for this setup\n✅ Position size matches the tier risk %\n✅ Stop loss is placed at the correct level", parse_mode="Markdown", reply_markup=kb)


async def handle_alert_response(update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    parts = q.data.split(":")
    action = parts[1]

    if action in ("chk", "mc", "confirm_entry", "confirm_anyway", "revenge_yes", "revenge_no"):
        return await handle_alert_extras(update, context)

    key = parts[2]
    pending = _pending.get(key)
    await q.edit_message_reply_markup(reply_markup=None)

    if action == "entered":
        if key in _aging_jobs:
            _aging_jobs.pop(key).schedule_removal()
        last = db.get_last_closed_loss()
        if last and last.get("closed_at"):
            mins = int((datetime.now(timezone.utc) - last["closed_at"]).total_seconds() / 60)
            if mins <= 10:
                context.user_data["revenge_pending"] = {"key": key, "mins": mins}
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("Yes, proceed", callback_data="alert:revenge_yes"), InlineKeyboardButton("No, skip this one", callback_data="alert:revenge_no")]])
                await q.message.reply_text(f"⚠️ Revenge Trade Warning\nYour last trade was a loss [{mins}] minutes ago.\nAre you sure you want to enter now?", parse_mode="Markdown", reply_markup=kb)
                return
        context.user_data["checklist"] = {"key": key, "alert_fired": False, "size_correct": False, "sl_placed": False, "market_condition": None, "revenge": False}
        await _render_checklist(q.message, context)

    elif action == "skipped":
        if key in _aging_jobs:
            _aging_jobs.pop(key).schedule_removal()
        _pending.pop(key, None)
        await q.message.reply_text("❌ *Skipped* — setup dismissed.", parse_mode="Markdown")

    elif action == "watching":
        if pending:
            setup, model, _ = pending
            _watching[key] = {"pair": setup["pair"], "model_id": model["id"]}
        await q.message.reply_text("👀 *Watching* — you will get invalidation updates.", parse_mode="Markdown")

    elif action == "demo":
        if not pending:
            return
        setup, model, scored = pending
        acct = db.get_demo_account("perps")
        if not acct:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎮 Setup Demo", callback_data="demo:perps:home")]])
            await q.message.reply_text("You don't have a demo account yet. Set one up first.", reply_markup=kb)
            return
        context.user_data["demo_alert_trade"] = {
            "pair": setup.get("pair"),
            "direction": setup.get("direction"),
            "entry_price": setup.get("entry"),
            "sl": setup.get("sl"),
            "tp": setup.get("tp"),
            "model_id": model.get("id"),
            "model_name": model.get("name"),
            "tier": scored.get("tier"),
            "score": scored.get("final_score"),
            "balance": float(acct.get("balance") or 0),
        }
        await q.message.reply_text(
            "🎮 Demo Entry\n"
            f"Pair: {setup.get('pair')}\n"
            f"Entry: {px.fmt_price(setup.get('entry'))}\n"
            f"SL: {px.fmt_price(setup.get('sl'))}\n"
            f"TP: {px.fmt_price(setup.get('tp'))}\n\n"
            "Reply with risk amount in USD (e.g. 50)."
        )


async def handle_alert_extras(update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    d = q.data
    st = context.user_data.get("checklist")
    if d == "alert:revenge_no":
        rv = context.user_data.get("revenge_pending")
        if rv:
            _pending.pop(rv["key"], None)
        await q.message.reply_text("❌ *Skipped* — noted.", parse_mode="Markdown")
        return
    if d == "alert:revenge_yes":
        rv = context.user_data.get("revenge_pending")
        if rv:
            context.user_data["checklist"] = {"key": rv["key"], "alert_fired": False, "size_correct": False, "sl_placed": False, "market_condition": None, "revenge": True}
            await _render_checklist(q.message, context)
        return
    if not st:
        return
    if d.startswith("alert:chk:"):
        k = d.split(":")[-1]
        st[k] = not st[k]
        await _render_checklist(q.message, context)
        return
    if d.startswith("alert:mc:"):
        st["market_condition"] = d.split(":")[-1]
        await _render_checklist(q.message, context)
        return
    if d in ("alert:confirm_entry", "alert:confirm_anyway"):
        all_ok = st["alert_fired"] and st["size_correct"] and st["sl_placed"]
        if d == "alert:confirm_entry" and not all_ok:
            await q.answer("Complete all checklist items", show_alert=True)
            return
        setup, model, scored = _pending.get(st["key"])
        prefs = db.get_user_preferences(CHAT_ID)
        risk_pct = float(TIER_RISK.get(scored["tier"], 0))
        risk_usd = (float(prefs.get("account_balance") or 0) * risk_pct) / 100
        tid = db.log_trade({"pair": setup["pair"], "model_id": model["id"], "tier": scored["tier"], "direction": setup.get("direction", "BUY"), "entry_price": setup.get("entry", 0), "sl": setup.get("sl", 0), "tp": setup.get("tp", 0), "rr": setup.get("rr", 0), "session": scored["session"], "score": scored["final_score"], "risk_pct": risk_pct, "result": None, "violation": None})
        db.log_checklist(tid, st["alert_fired"], st["size_correct"], st["sl_placed"], all_ok)
        db.update_trade_flags(tid, entry_confirmed=all_ok, revenge_flagged=bool(st.get("revenge")), market_condition=st.get("market_condition"))
        await q.message.reply_text(f"✅ *Trade Logged*\n🆔 ID: `{tid}`\n⚖️ Risk: `{risk_pct}%` (${risk_usd:.2f})", parse_mode="Markdown")
        if not all_ok:
            await q.message.reply_text("⚠️ Trade logged with incomplete checklist. Review your process.", parse_mode="Markdown")
        if st.get("revenge"):
            db.update_trade_flags(tid, revenge_flagged=True)
        _pending.pop(st["key"], None)

        async def reminder():
            await asyncio.sleep(5)
            await q.message.reply_text(f"📸 Screenshot reminder — capture your entry on the chart now.\n Pair: [{setup['pair']}] | Entry: [{setup['entry']}] | TF: [{model['timeframe']}]", parse_mode="Markdown")
            db.update_trade_flags(tid, screenshot_reminded=True)

        asyncio.create_task(reminder())
