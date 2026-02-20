import logging
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import db, engine, formatters, prices as px
from config import CHAT_ID

log = logging.getLogger(__name__)

_recent:  dict = {}   # dedup: key → unix timestamp
_pending: dict = {}   # button context: key → (setup, model, scored)
_DEDUP_SEC = 900      # 15 min dedup window


def _dedup_key(pair, model_id, tier):
    return f"{pair}_{model_id}_{tier}"


def _is_dup(pair, model_id, tier) -> bool:
    key  = _dedup_key(pair, model_id, tier)
    last = _recent.get(key, 0)
    return (datetime.utcnow().timestamp() - last) < _DEDUP_SEC


def _mark(pair, model_id, tier):
    _recent[_dedup_key(pair, model_id, tier)] = datetime.utcnow().timestamp()


async def _evaluate_and_send(bot, model: dict, force: bool = False) -> bool:
    pair  = model["pair"]
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
    sl, tp, rr     = px.calc_sl_tp(price, setup["direction"], atr=atr)
    setup["entry"] = price
    setup["sl"]    = sl
    setup["tp"]    = tp
    setup["rr"]    = rr

    db.log_alert(
        pair, model["id"], model["name"],
        scored["final_score"], scored["tier"], setup["direction"],
        price, sl, tp, rr, True
    )
    _mark(pair, model["id"], scored["tier"])

    ts  = datetime.utcnow().strftime("%H%M%S")
    key = f"{pair}_{model['id']}_{ts}"
    _pending[key] = (setup, model, scored)

    text = formatters.fmt_alert(setup, model, scored)
    kb   = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Entered",  callback_data=f"alert:entered:{key}"),
        InlineKeyboardButton("❌ Skipped",  callback_data=f"alert:skipped:{key}"),
        InlineKeyboardButton("👀 Watching", callback_data=f"alert:watching:{key}"),
    ]])
    await bot.send_message(
        chat_id=CHAT_ID, text=text,
        reply_markup=kb, parse_mode="Markdown"
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
    for m in active:
        try:
            await _evaluate_and_send(bot, m)
        except Exception as e:
            log.error(f"Scanner error {m['id']}: {e}")


async def handle_alert_response(update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    parts  = query.data.split(":")
    action = parts[1]
    key    = parts[2]
    pending = _pending.get(key)
    await query.edit_message_reply_markup(reply_markup=None)

    if action == "entered":
        if pending:
            setup, model, scored = pending
            try:
                trade_id = db.log_trade({
                    "pair":        setup["pair"],
                    "model_id":    model["id"],
                    "tier":        scored["tier"],
                    "direction":   setup.get("direction", "BUY"),
                    "entry_price": setup.get("entry", 0),
                    "sl":          setup.get("sl", 0),
                    "tp":          setup.get("tp", 0),
                    "rr":          setup.get("rr", 0),
                    "session":     scored["session"],
                    "score":       scored["final_score"],
                    "risk_pct":    scored["risk_pct"],
                    "result":      None,
                    "violation":   None,
                })
                _pending.pop(key, None)
                await query.message.reply_text(
                    f"✅ *Trade Logged*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🪙 {setup['pair']}   {formatters._tier_badge(scored['tier'])}\n"
                    f"💹 Entry  `{px.fmt_price(setup.get('entry'))}`\n"
                    f"🛑 SL     `{px.fmt_price(setup.get('sl'))}`\n"
                    f"🎯 TP     `{px.fmt_price(setup.get('tp'))}`\n"
                    f"⚖️ Risk    `{scored['risk_pct']}%`\n"
                    f"🆔 ID: `{trade_id}`\n\n"
                    f"_Mark result when closed:_\n"
                    f"`/result {trade_id} TP`  or  `/result {trade_id} SL`",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("📊 Stats", callback_data="nav:stats"),
                        InlineKeyboardButton("🏠 Home",  callback_data="nav:home"),
                    ]])
                )
            except Exception as e:
                await query.message.reply_text(f"❌ Error logging trade: {e}")
        else:
            await query.message.reply_text(
                "✅ *Entered* — noted _(context expired)_",
                parse_mode="Markdown"
            )

    elif action == "skipped":
        _pending.pop(key, None)
        await query.message.reply_text(
            "❌ *Skipped* — setup dismissed.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Home", callback_data="nav:home")
            ]])
        )

    elif action == "watching":
        await query.message.reply_text(
            "👀 *Watching* — tap Entered or Skipped when you decide.",
            parse_mode="Markdown"
        )
