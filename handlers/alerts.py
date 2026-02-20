import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import db, engine, formatters
from config import CHAT_ID

log = logging.getLogger(__name__)

# In-memory store for pending alert context (pair, model, scored)
# keyed by alert_key so button callbacks can look them up
_pending: dict = {}


def _alert_key(pair: str, model_id: str, ts: str) -> str:
    return f"{pair}_{model_id}_{ts}"


async def send_alert(app, setup: dict, model: dict, scored: dict):
    """Format and send a tiered alert with Yes/No/Watching buttons."""
    from datetime import datetime
    ts  = datetime.utcnow().strftime("%H%M%S")
    key = _alert_key(setup["pair"], model["id"], ts)
    _pending[key] = (setup, model, scored)

    text = formatters.fmt_alert(setup, model, scored)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Entered",  callback_data=f"entered:{key}"),
        InlineKeyboardButton("❌ Skipped",  callback_data=f"skipped:{key}"),
        InlineKeyboardButton("👀 Watching", callback_data=f"watching:{key}"),
    ]])
    await app.bot.send_message(chat_id=CHAT_ID, text=text, reply_markup=keyboard)
    db.log_alert(setup["pair"], model["id"], scored["final_score"],
                 scored["tier"], True)


async def send_invalidation(app, reason: str, pair: str, model_name: str):
    """Send a plain invalidation notice — no buttons needed."""
    text = formatters.fmt_invalidation(reason, pair, model_name)
    await app.bot.send_message(chat_id=CHAT_ID, text=text)
    db.log_alert(pair, None, 0, None, False, reason)


# ── Button response handler ───────────────────────────
async def handle_alert_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, key = query.data.split(":", 1)
    pending = _pending.get(key)

    # Remove inline buttons so they can't be pressed twice
    await query.edit_message_reply_markup(reply_markup=None)

    if action == "entered":
        if pending:
            setup, model, scored = pending
            trade_id = db.log_trade({
                "pair":        setup["pair"],
                "model_id":    model["id"],
                "tier":        scored["tier"],
                "direction":   setup.get("direction", ""),
                "entry_price": 0.0,   # user can confirm later
                "sl":          float(setup.get("sl", 0) or 0),
                "tp":          float(setup.get("tp", 0) or 0),
                "rr":          float(setup.get("rr", 0) or 0),
                "session":     scored["session"],
                "score":       scored["final_score"],
                "risk_pct":    scored["risk_pct"],
                "result":      None,
                "violation":   None,
            })
            _pending.pop(key, None)
            await query.message.reply_text(
                f"✅ Trade logged  (ID: {trade_id})\n"
                f"Pair:  {setup['pair']}  Tier {scored['tier']}\n"
                f"Risk:  {scored['risk_pct']}%\n\n"
                f"Use /result {trade_id} TP  or  /result {trade_id} SL  when closed."
            )
        else:
            await query.message.reply_text("✅ Entered — noted (context expired).")

    elif action == "skipped":
        _pending.pop(key, None)
        await query.message.reply_text("❌ Skipped — noted.")

    elif action == "watching":
        await query.message.reply_text("👀 Watching — I'll keep it on screen.")


# ── Scanner job (runs every 15 min via APScheduler) ───
async def run_scanner(context: ContextTypes.DEFAULT_TYPE):
    """
    Iterates every active model, evaluates the setup,
    and fires an alert or invalidation notice.

    Plug real rule evaluation into _evaluate_model().
    """
    log.info("Scanner tick")
    app = context.application

    try:
        active_models = db.get_active_models()
    except Exception as e:
        log.error(f"Scanner DB error: {e}")
        return

    for m in active_models:
        m["rules"] = m["rules"] if isinstance(m["rules"], list) else []
        try:
            setup  = _evaluate_model(m)
            scored = engine.score_setup(setup, m)

            if not scored["valid"]:
                # Only notify invalidation if the setup was otherwise close
                # (prevents spam on every candle when no setup exists)
                if scored["mandatory_failed"] or scored["invalid_reason"]:
                    await send_invalidation(
                        app,
                        scored["invalid_reason"],
                        setup["pair"],
                        m["name"]
                    )
            elif scored["tier"]:
                await send_alert(app, setup, m, scored)

        except Exception as e:
            log.error(f"Scanner error on model {m['id']}: {e}")


def _evaluate_model(model: dict) -> dict:
    """
    Stub for real rule evaluation.
    Replace the placeholder values with live candle data.

    Example wiring:
        from data import get_atr_ratio, get_htf_bias
        from rules import check_sweep, check_ob, check_fvg, check_smt

        pair = model["pair"]
        tf   = model["timeframe"]
        candles = fetch_candles(pair, tf)

        passed = []
        if check_sweep(candles): passed.append("r1")
        if check_ob(candles):    passed.append("r2")
        ...
    """
    pair = model["pair"]
    return {
        "pair":            pair,
        "passed_rule_ids": [],      # ← real rule checks go here
        "atr_ratio":       1.0,     # ← data.get_atr_ratio(pair, tf)
        "htf_1h":          "Neutral",
        "htf_4h":          "Neutral",
        "news_minutes":    None,    # ← news.minutes_to_next_event(pair)
        "sl":              "0.0000",
        "tp":              "0.0000",
        "rr":              "0.0",
        "direction":       "BUY",
    }
