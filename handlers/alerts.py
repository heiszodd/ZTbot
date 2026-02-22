import asyncio
import logging
from datetime import datetime, timedelta, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import db, engine, formatters, prices as px
from degen.scanner import degen_scan_job
from config import CHAT_ID, TIER_RISK, CORRELATED_PAIRS, SUPPORTED_PAIRS

log = logging.getLogger(__name__)
_recent, _pending, _watching = {}, {}, {}
_skipped_zones = []
_aging_jobs, _last_proximity = {}, {}
_circuit_warned_at = None
_DEDUP_SEC = 900


def _dedup_key(pair, model_id, tier, direction): return f"{pair}_{model_id}_{tier}_{direction}"
def _is_dup(pair, model_id, tier, direction): return (datetime.now(timezone.utc).timestamp() - _recent.get(_dedup_key(pair, model_id, tier, direction), 0)) < _DEDUP_SEC
def _mark(pair, model_id, tier, direction): _recent[_dedup_key(pair, model_id, tier, direction)] = datetime.now(timezone.utc).timestamp()


def format_duration(start_time: datetime) -> str:
    if not start_time:
        return "0m"
    delta = datetime.now(timezone.utc).replace(tzinfo=None) - (start_time.replace(tzinfo=None) if getattr(start_time, "tzinfo", None) else start_time)
    minutes = int(delta.total_seconds() / 60)
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    mins = minutes % 60
    if hours < 24:
        return f"{hours}h {mins}m"
    days = hours // 24
    return f"{days}d {hours % 24}h"


def make_score_bar(score_pct: float, width: int = 10) -> str:
    filled = round(min(score_pct, 100) / 100 * width)
    return "█" * filled + "░" * (width - filled)


def get_score_trend(current: float, previous: float) -> str:
    delta = current - previous
    if delta > 2:
        return f"📈 Improving (+{delta:.1f} pts)"
    elif delta < -2:
        return f"📉 Worsening ({delta:.1f} pts)"
    return "➡️ Stable"


def pending_keyboard(setup_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👀 Watch", callback_data=f"pending:watch:{setup_id}"),
            InlineKeyboardButton("🔕 Dismiss", callback_data=f"pending:dismiss:{setup_id}")
        ],
        [
            InlineKeyboardButton("⚙️ View Model", callback_data=f"pending:model:{setup_id}"),
            InlineKeyboardButton("🏠 Home", callback_data="nav:perps_home")
        ]
    ])


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


async def _evaluate_and_send(bot, model: dict, force=False, pair_override: str | None = None, pending_duration=None, pending_checks=None):
    global _circuit_warned_at
    prefs = db.get_user_preferences(CHAT_ID)
    if prefs.get("risk_off_mode"):
        return False
    pair = pair_override or model["pair"]
    scan_model = {**model, "pair": pair}
    price = px.get_price(pair)
    if not price:
        return False
    check_proximity_alerts(bot, scan_model, price)

    weekly = db.get_weekly_goal() if hasattr(db, "get_weekly_goal") else None
    if weekly and db.update_weekly_achieved() <= float(weekly.get("loss_limit", -3)):
        if not weekly.get("alerts_paused_notified"):
            await bot.send_message(chat_id=CHAT_ID, text=f"🛑 Weekly loss limit reached ({weekly.get('loss_limit')}R). Alerts paused until Monday.", parse_mode="Markdown")
        return False

    series = px.get_recent_series(pair, days=2)
    setup = engine.build_live_setup(scan_model, series)
    if not setup.get("passed_rule_ids"):
        return False

    scored = engine.score_setup(setup, scan_model)
    if not scored.get("tier"):
        return False
    dedup_direction = "Bullish" if setup.get("direction") == "BUY" else "Bearish"
    if not force and _is_dup(pair, model["id"], scored["tier"], dedup_direction):
        return False

    atr = px.estimate_atr(series[-30:]) if series else None
    sl, tp, rr = px.calc_sl_tp(price, setup["direction"], atr=atr)
    setup.update({"entry": price, "sl": sl, "tp": tp, "rr": rr})

    db.log_alert(pair, model["id"], model["name"], scored["final_score"], scored["tier"], setup["direction"], price, sl, tp, rr, True)
    _mark(pair, model["id"], scored["tier"], dedup_direction)
    key = f"{pair}_{model['id']}_{datetime.now(timezone.utc).strftime('%H%M%S')}"
    _pending[key] = (setup, scan_model, scored)

    text = formatters.fmt_alert(setup, scan_model, scored, risk_pct=float(TIER_RISK.get(scored["tier"], 0)), risk_usd=0.0, correlation_warning=_correlation_warning(pair), pending_duration=pending_duration, pending_checks=pending_checks)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Entered", callback_data=f"alert:entered:{key}"), InlineKeyboardButton("🎮 Demo Entry", callback_data=f"alert:demo:{key}")],[InlineKeyboardButton("❌ Skipped", callback_data=f"alert:skipped:{key}"), InlineKeyboardButton("👀 Watching", callback_data=f"alert:watching:{key}")]])
    await bot.send_message(chat_id=CHAT_ID, text=text, reply_markup=kb, parse_mode="Markdown")
    job = bot._application.job_queue.run_once(_setup_aging_follow_up, when=900, data={"pair": pair, "entry": price}, name=f"aging:{key}")
    _aging_jobs[key] = job
    return True


async def run_scanner(context: ContextTypes.DEFAULT_TYPE):
    bot = context.application.bot
    models = [m for m in db.get_all_models() if m.get("status") == "active"]
    prefs = db.get_user_preferences(CHAT_ID) or {}
    preferred = [p for p in (prefs.get("preferred_pairs") or []) if p in SUPPORTED_PAIRS]
    scan_pairs = preferred or list(dict.fromkeys(SUPPORTED_PAIRS or []))
    processing = context.bot_data.setdefault("processing_setups", set())

    for model in models:
        for pair in scan_pairs:
            timeframe = model.get("timeframe")
            existing = db.get_pending_setup(model.get("id"), pair, timeframe)
            if existing and existing.get("id") in processing:
                continue
            try:
                if existing:
                    processing.add(existing.get("id"))
                score_results = engine.score_pair(pair, timeframe, model)
                if not score_results:
                    continue
                for score_result in score_results:
                    classification = engine.classify_score_result(score_result, model)
                    detected_direction = score_result.get("detected_direction", "Bullish")

                    if classification["classification"] == "FULL_ALERT":
                        if existing and existing.get("status") == "pending":
                            await promote_to_full_alert(context, existing, score_result)
                        else:
                            tier = "A" if score_result.get("score", 0) >= model.get("tier_a", 9.5) else "B" if score_result.get("score", 0) >= model.get("tier_b", 7.5) else "C"
                            if _is_dup(pair, model["id"], tier, detected_direction):
                                continue
                            await _evaluate_and_send(bot, {**model, "bias": detected_direction}, pair_override=pair)

                    elif classification["classification"] == "PENDING":
                        if existing and existing.get("status") == "pending":
                            await update_pending_message(context, existing, classification, score_result)
                            continue
                        if existing and existing.get("status") == "promoted" and existing.get("promoted_at"):
                            if (datetime.now(timezone.utc).replace(tzinfo=None) - existing["promoted_at"]).total_seconds() < 900:
                                continue
                        if existing and existing.get("status") == "expired":
                            db.delete_pending_setup(existing["id"])

                        now = datetime.now(timezone.utc)
                        setup_payload = {
                            "model_id": model["id"], "model_name": model.get("name"), "pair": pair, "timeframe": timeframe,
                            "direction": score_result.get("direction"), "entry_price": score_result.get("entry"), "sl": score_result.get("sl"),
                            "tp1": score_result.get("tp1"), "tp2": score_result.get("tp2"), "tp3": score_result.get("tp3"),
                            "current_score": score_result.get("score"), "max_possible_score": sum(float(r.get("weight",0) or 0) for r in model.get("rules",[])),
                            "score_pct": classification.get("score_pct"), "min_score_threshold": float(model.get("min_score") or model.get("tier_c") or 0),
                            "passed_rules": classification.get("passed_rules"), "failed_rules": classification.get("failed_rules"),
                            "mandatory_passed": classification.get("mandatory_passed"), "mandatory_failed": classification.get("mandatory_failed"),
                            "rule_snapshots": {"score": score_result.get("score"), "passed_rule_ids": [r.get("id") for r in classification.get("passed_rules",[])], "failed_rule_ids": [r.get("id") for r in classification.get("failed_rules",[])]},
                            "telegram_chat_id": CHAT_ID, "status": "pending", "first_detected_at": now, "check_count": 1, "peak_score_pct": classification.get("score_pct",0),
                        }
                        setup_id = db.save_pending_setup(setup_payload)
                        record = db.get_pending_setup(model["id"], pair, timeframe)
                        record["first_seen_label"] = now.strftime("%H:%M WAT")
                        record["last_check_label"] = now.strftime("%H:%M WAT")
                        record["trend"] = "➡️ Score unchanged"
                        text = formatters.fmt_pending_setup(record, classification, score_result)
                        msg = await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown", reply_markup=pending_keyboard(setup_id))
                        db.update_pending_setup(setup_id, {"telegram_message_id": msg.message_id})

                    else:
                        if existing and existing.get("status") == "pending":
                            await expire_pending_message(context, existing, classification)
            except Exception as e:
                log.error(f"scanner error {e}")
            finally:
                if existing and existing.get("id") in processing:
                    processing.discard(existing.get("id"))
    try:
        await degen_scan_job(context)
    except Exception as e:
        log.error(f"degen scanner error {e}")


async def update_pending_message(context, setup: dict, classification: dict, score_result: dict):
    now = datetime.now(timezone.utc)
    prev = float(setup.get("current_score") or 0)
    setup["first_seen_label"] = (setup.get("first_detected_at") or now).strftime("%H:%M WAT")
    setup["last_check_label"] = now.strftime("%H:%M WAT")
    setup["trend"] = get_score_trend(float(score_result.get("score") or 0), prev)
    new_text = formatters.fmt_pending_setup(setup, classification, score_result)
    old_snapshot = setup.get("rule_snapshots", {}) or {}
    new_snapshot = {
        "score": score_result["score"],
        "passed_rule_ids": [r.get("id") for r in classification["passed_rules"]],
        "failed_rule_ids": [r.get("id") for r in classification["failed_rules"]],
    }
    if old_snapshot == new_snapshot:
        db.update_pending_setup(setup["id"], {"last_updated_at": now})
        return
    try:
        await context.bot.edit_message_text(
            chat_id=setup["telegram_chat_id"],
            message_id=setup["telegram_message_id"],
            text=new_text,
            reply_markup=pending_keyboard(setup["id"]),
            parse_mode="Markdown",
        )
    except Exception as e:
        if "message is not modified" in str(e):
            pass
        elif "message to edit not found" in str(e):
            msg = await context.bot.send_message(chat_id=setup["telegram_chat_id"], text=new_text, parse_mode="Markdown", reply_markup=pending_keyboard(setup["id"]))
            db.update_pending_setup(setup["id"], {"telegram_message_id": msg.message_id})
        else:
            log.error(f"Failed to edit pending message: {e}")

    db.update_pending_setup(setup["id"], {
        "current_score": score_result["score"],
        "score_pct": classification["score_pct"],
        "passed_rules": classification["passed_rules"],
        "failed_rules": classification["failed_rules"],
        "mandatory_passed": classification["mandatory_passed"],
        "mandatory_failed": classification["mandatory_failed"],
        "rule_snapshots": new_snapshot,
        "last_updated_at": now,
        "check_count": int(setup.get("check_count", 0)) + 1,
        "peak_score_pct": max(float(setup.get("peak_score_pct") or 0), classification["score_pct"]),
        "entry_price": score_result.get("entry"), "sl": score_result.get("sl"), "tp1": score_result.get("tp1"), "tp2": score_result.get("tp2"), "tp3": score_result.get("tp3"),
    })


async def promote_to_full_alert(context, setup: dict, score_result: dict):
    try:
        promoted_text = (
            f"✅ *SETUP CONFIRMED — FULL ALERT SENT*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ {setup['model_name']}\n"
            f"🪙 {setup['pair']}   {setup['timeframe']}\n"
            f"⏱ Pending for: {format_duration(setup['first_detected_at'])}\n"
            f"📊 Peak score: {float(setup.get('peak_score_pct') or 0):.0f}%\n"
            f"✅ All criteria now met — see alert below"
        )
        await context.bot.edit_message_text(chat_id=setup["telegram_chat_id"], message_id=setup["telegram_message_id"], text=promoted_text, parse_mode="Markdown")
    except Exception as e:
        log.error(f"Failed to edit promoted message: {e}")

    db.promote_pending_setup(setup["id"])
    model = db.get_model(setup["model_id"])
    if model:
        tier = "A" if score_result.get("score", 0) >= model.get("tier_a", 9.5) else "B" if score_result.get("score", 0) >= model.get("tier_b", 7.5) else "C"
        if not _is_dup(setup["pair"], model["id"], tier):
            await _evaluate_and_send(context.bot, model, pair_override=setup["pair"], pending_duration=format_duration(setup["first_detected_at"]), pending_checks=setup.get("check_count", 0))


async def expire_pending_message(context, setup: dict, classification: dict):
    reason = ""
    if classification["classification"] == "INVALIDATED":
        reason = f"❌ Invalidated: {classification.get('reason', 'mandatory gate failed')}"
    elif classification["classification"] == "INSUFFICIENT":
        reason = "📉 Setup weakened below 50% threshold"

    try:
        expired_text = (
            f"❌ *PENDING SETUP EXPIRED*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ {setup['model_name']}\n"
            f"🪙 {setup['pair']}   {setup['timeframe']}\n"
            f"⏱ Was pending for: {format_duration(setup['first_detected_at'])}\n"
            f"📊 Peak score reached: {float(setup.get('peak_score_pct', 0) or 0):.0f}%\n"
            f"🔄 Total checks: {setup['check_count']}\n\n{reason}\n\n_Setup did not complete. Market moved away._"
        )
        await context.bot.edit_message_text(chat_id=setup["telegram_chat_id"], message_id=setup["telegram_message_id"], text=expired_text, parse_mode="Markdown")
    except Exception as e:
        log.error(f"Failed to edit expired message: {e}")

    db.expire_pending_setup(setup["id"])


async def run_pending_checker(context):
    tick_count = context.bot_data.get("pending_tick", 0) + 1
    context.bot_data["pending_tick"] = tick_count
    processing = context.bot_data.setdefault("processing_setups", set())
    watched = context.bot_data.get("watched_setups", set())
    pending = db.get_all_pending_setups(status="pending")
    if len(pending) > 20:
        pending = sorted(pending, key=lambda x: float(x.get("score_pct") or 0), reverse=True)[:20]

    last_cleanup = context.bot_data.get("pending_last_cleanup")
    if not last_cleanup or (datetime.now(timezone.utc) - last_cleanup).total_seconds() >= 3600:
        db.delete_old_expired_setups(hours=24)
        context.bot_data["pending_last_cleanup"] = datetime.now(timezone.utc)

    for setup in pending:
        if setup["id"] in processing:
            continue
        is_watched = setup["id"] in watched
        if not is_watched and tick_count % 2 != 0:
            continue
        processing.add(setup["id"])
        try:
            model = db.get_model(setup["model_id"])
            if not model or model.get("status") != "active":
                db.expire_pending_setup(setup["id"])
                continue

            score_results = engine.score_pair(setup["pair"], setup["timeframe"], model)
            if not score_results:
                stale_minutes = (datetime.now(timezone.utc).replace(tzinfo=None) - setup["last_updated_at"]).total_seconds() / 60
                if stale_minutes >= 10:
                    try:
                        await context.bot.edit_message_text(chat_id=setup["telegram_chat_id"], message_id=setup["telegram_message_id"], text="⚠️ _Price data unavailable — retrying..._", parse_mode="Markdown", reply_markup=pending_keyboard(setup["id"]))
                    except Exception:
                        pass
                    db.update_pending_setup(setup["id"], {"status": "stale"})
                continue

            for score_result in score_results:
                classification = engine.classify_score_result(score_result, model)
                if classification["classification"] == "FULL_ALERT":
                    await promote_to_full_alert(context, setup, score_result)
                elif classification["classification"] == "PENDING":
                    await update_pending_message(context, setup, classification, score_result)
                else:
                    await expire_pending_message(context, setup, classification)
        except Exception as e:
            log.error(f"Pending checker error for setup {setup['id']}: {e}")
        finally:
            processing.discard(setup["id"])


async def handle_pending_cb(update, context):
    q = update.callback_query
    await q.answer()
    parts = q.data.split(":")
    action = parts[1]
    setup_id = int(parts[2])

    if action == "watch":
        watched = context.bot_data.setdefault("watched_setups", set())
        watched.add(setup_id)
        await q.answer("👀 Now watching this setup closely", show_alert=False)
        try:
            await q.message.reply_text("👀 Watching — checking every 15s", parse_mode="Markdown")
        except Exception:
            pass
    elif action == "dismiss":
        db.expire_pending_setup(setup_id)
        db.delete_pending_setup(setup_id)
        try:
            await q.edit_message_text("🔕 Dismissed by user")
        except Exception:
            pass
        await q.answer("Setup dismissed", show_alert=False)
    elif action == "model":
        recs = [x for x in db.get_all_pending_setups(status="pending") if x["id"] == setup_id]
        if not recs:
            await q.answer("Setup not found", show_alert=True)
            return
        setup = recs[0]
        from handlers import commands
        m = db.get_model(setup["model_id"])
        if not m:
            await q.answer("Model not found", show_alert=True)
            return
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="nav:perps_home")]])
        await q.message.reply_text(formatters.fmt_model_detail(m, px.get_price(m['pair'])), parse_mode="Markdown", reply_markup=kb)


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
