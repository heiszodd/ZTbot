import logging
from datetime import datetime, timedelta, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import db, engine, formatters, prices as px
from config import CHAT_ID, TIER_RISK

log = logging.getLogger(__name__)

_recent: dict = {}
_pending: dict = {}
_watching: dict = {}
_skipped_zones: list[dict] = []
_circuit_warned_at: datetime | None = None
_DEDUP_SEC = 900


CORRELATED = {
    "BTCUSDT": {"ETHUSDT"},
    "ETHUSDT": {"BTCUSDT"},
}


def _dedup_key(pair, model_id, tier):
    return f"{pair}_{model_id}_{tier}"


def _is_dup(pair, model_id, tier) -> bool:
    key = _dedup_key(pair, model_id, tier)
    last = _recent.get(key, 0)
    return (datetime.utcnow().timestamp() - last) < _DEDUP_SEC


def _mark(pair, model_id, tier):
    _recent[_dedup_key(pair, model_id, tier)] = datetime.utcnow().timestamp()


def _calc_tp_levels(entry: float, sl: float, direction: str) -> tuple[float, float, float]:
    risk = abs(entry - sl)
    if direction == "BUY":
        return entry + risk, entry + risk * 2, entry + risk * 3
    return entry - risk, entry - risk * 2, entry - risk * 3


def _correlation_warning(pair: str) -> str | None:
    open_trades = db.get_open_trades()
    open_pairs = {t["pair"] for t in open_trades if t.get("pair")}
    correlated_open = CORRELATED.get(pair, set()) & open_pairs
    if correlated_open:
        cp = ", ".join(sorted(correlated_open))
        return f"⚠️ Correlation risk: open trade detected in {cp}."
    return None


async def _evaluate_and_send(bot, model: dict, force: bool = False) -> bool:
    global _circuit_warned_at

    prefs = db.get_user_preferences(CHAT_ID)
    now_utc = datetime.now(timezone.utc)

    if prefs.get("risk_off_mode"):
        return False

    lock_until = prefs.get("alert_lock_until")
    if lock_until and lock_until > now_utc.replace(tzinfo=None):
        return False

    daily_loss_pct = db.get_daily_realized_loss_pct()
    loss_limit = float(prefs.get("daily_loss_limit_pct") or 3.0)
    if daily_loss_pct >= loss_limit:
        if _circuit_warned_at is None or (now_utc - _circuit_warned_at) > timedelta(hours=1):
            await bot.send_message(
                chat_id=CHAT_ID,
                text=(
                    f"⚠️ *Circuit Breaker Active*\n"
                    f"Daily realized loss: *{daily_loss_pct:.2f}%* (limit {loss_limit:.2f}%).\n"
                    "New alerts are suppressed for the rest of the day."
                ),
                parse_mode="Markdown",
            )
            _circuit_warned_at = now_utc
        return False

    open_trades = db.get_open_trades()
    max_concurrent = int(prefs.get("max_concurrent_trades") or 3)
    at_capacity = len(open_trades) >= max_concurrent

    pair = model["pair"]
    price = px.get_price(pair)
    if not price:
        log.warning(f"No price for {pair}")
        return False

    series = px.get_recent_series(pair, days=2)
    setup = engine.build_live_setup(model, series)
    if not setup.get("passed_rule_ids"):
        return False

    scored = engine.score_setup(setup, model)
    if not scored["valid"] or not scored["tier"]:
        return False

    if not force and _is_dup(pair, model["id"], scored["tier"]):
        return False

    atr = px.estimate_atr(series[-30:]) if series else None
    sl, tp, rr = px.calc_sl_tp(price, setup["direction"], atr=atr)
    setup["entry"] = price
    setup["sl"] = sl
    setup["tp"] = tp
    setup["rr"] = rr
    tp1, tp2, tp3 = _calc_tp_levels(price, sl, setup["direction"])
    setup["tp1"], setup["tp2"], setup["tp3"] = tp1, tp2, tp3

    confluence_count = len(scored.get("passed_rules") or [])
    setup["confluence_count"] = confluence_count

    risk_pct = float(TIER_RISK.get(scored["tier"], scored.get("risk_pct") or 0.0))
    risk_usd = (float(prefs.get("account_balance") or 0.0) * risk_pct) / 100.0
    setup["risk_usd"] = risk_usd

    correlation_warning = _correlation_warning(pair)
    reentry = False
    tolerance = max(price * 0.0015, 0.01)
    for z in list(_skipped_zones):
        if z["pair"] == pair and z["model_id"] == model["id"] and abs(price - z["entry"]) <= tolerance:
            reentry = True
            _skipped_zones.remove(z)
            break

    db.log_alert(
        pair,
        model["id"],
        model["name"],
        scored["final_score"],
        scored["tier"],
        setup["direction"],
        price,
        sl,
        tp,
        rr,
        True,
    )
    _mark(pair, model["id"], scored["tier"])

    ts = datetime.utcnow().strftime("%H%M%S")
    key = f"{pair}_{model['id']}_{ts}"
    _pending[key] = (setup, model, scored)

    text = formatters.fmt_alert(
        setup,
        model,
        scored,
        risk_pct=risk_pct,
        risk_usd=risk_usd,
        at_capacity=at_capacity,
        max_concurrent=max_concurrent,
        correlation_warning=correlation_warning,
        reentry=reentry,
    )

    if db.get_losing_streak() >= 3:
        text += "\n\n⚠️ Losing streak detected (3+). Follow your rules."

    kb = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ Entered", callback_data=f"alert:entered:{key}"),
            InlineKeyboardButton("❌ Skipped", callback_data=f"alert:skipped:{key}"),
            InlineKeyboardButton("👀 Watching", callback_data=f"alert:watching:{key}"),
        ]]
    )
    await bot.send_message(chat_id=CHAT_ID, text=text, reply_markup=kb, parse_mode="Markdown")

    if at_capacity:
        await bot.send_message(
            chat_id=CHAT_ID,
            text=f"⚠️ Max concurrent trades reached ({len(open_trades)}/{max_concurrent}).",
            parse_mode="Markdown",
        )
    log.info(f"Alert sent: {pair} Tier {scored['tier']} score={scored['final_score']}")
    return True


async def run_scanner(context: ContextTypes.DEFAULT_TYPE):
    log.info("Scanner tick")
    bot = context.application.bot
    try:
        active = db.get_active_models()
    except Exception as e:
        log.error(f"Scanner DB error: {e}")
        return

    for watch_key, state in list(_watching.items()):
        m = db.get_model(state["model_id"])
        if not m:
            _watching.pop(watch_key, None)
            continue
        series = px.get_recent_series(state["pair"], days=1)
        setup = engine.build_live_setup(m, series)
        scored = engine.score_setup(setup, m)
        if (not scored["valid"]) or (len(scored.get("passed_rules") or []) < 3):
            await bot.send_message(
                chat_id=CHAT_ID,
                text=formatters.fmt_invalidation("Structure broke or key confluence lost", state["pair"], m["name"]),
                parse_mode="Markdown",
            )
            _watching.pop(watch_key, None)

    for m in active:
        try:
            await _evaluate_and_send(bot, m)
        except Exception as e:
            log.error(f"Scanner error {m['id']}: {e}")


async def handle_alert_response(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    action = parts[1]
    key = parts[2]
    pending = _pending.get(key)
    await query.edit_message_reply_markup(reply_markup=None)

    if action == "entered":
        if pending:
            setup, model, scored = pending
            try:
                prefs = db.get_user_preferences(CHAT_ID)
                risk_pct = float(TIER_RISK.get(scored["tier"], scored.get("risk_pct") or 0.0))
                risk_usd = (float(prefs.get("account_balance") or 0.0) * risk_pct) / 100.0
                trade_id = db.log_trade(
                    {
                        "pair": setup["pair"],
                        "model_id": model["id"],
                        "tier": scored["tier"],
                        "direction": setup.get("direction", "BUY"),
                        "entry_price": setup.get("entry", 0),
                        "sl": setup.get("sl", 0),
                        "tp": setup.get("tp", 0),
                        "rr": setup.get("rr", 0),
                        "session": scored["session"],
                        "score": scored["final_score"],
                        "risk_pct": risk_pct,
                        "result": None,
                        "violation": None,
                    }
                )
                db.update_user_preferences(CHAT_ID, discipline_score=min(100, int(prefs.get("discipline_score", 100)) + 2))
                _pending.pop(key, None)
                await query.message.reply_text(
                    f"✅ *Trade Logged*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🪙 {setup['pair']}   {formatters._tier_badge(scored['tier'])}\n"
                    f"💹 Entry  `{px.fmt_price(setup.get('entry'))}`\n"
                    f"🛑 SL     `{px.fmt_price(setup.get('sl'))}`\n"
                    f"🎯 TP     `{px.fmt_price(setup.get('tp'))}`\n"
                    f"⚖️ Risk    `{risk_pct}%` (${risk_usd:.2f})\n"
                    f"🆔 ID: `{trade_id}`\n\n"
                    f"_Mark result when closed:_\n"
                    f"`/result {trade_id} TP`  or  `/result {trade_id} SL`",
                    parse_mode="Markdown",
                )
            except Exception as e:
                await query.message.reply_text(f"❌ Error logging trade: {e}")
        else:
            await query.message.reply_text("✅ *Entered* — noted _(context expired)_", parse_mode="Markdown")

    elif action == "skipped":
        if pending:
            setup, model, scored = pending
            _skipped_zones.append({"pair": setup["pair"], "model_id": model["id"], "entry": setup.get("entry", 0), "tier": scored["tier"]})
        _pending.pop(key, None)
        await query.message.reply_text("❌ *Skipped* — setup dismissed.", parse_mode="Markdown")

    elif action == "watching":
        if pending:
            setup, model, _ = pending
            _watching[key] = {"pair": setup["pair"], "model_id": model["id"]}
        await query.message.reply_text("👀 *Watching* — you will get invalidation updates.", parse_mode="Markdown")
