import asyncio
import logging
from datetime import datetime, timedelta

import db
from config import CHAT_ID
from engine.rules import calc_atr, evaluate_rule, get_candles

log = logging.getLogger(__name__)

PHASE_EXPIRY = {1: 4 * 3600, 2: 1 * 3600, 3: 0, 4: 3 * 900}
PHASE_THRESHOLDS = {1: 60, 2: 55, 3: 70, 4: 50}


DEFAULT_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XAUUSD"]


def get_pairs_for_model(model: dict) -> list[str]:
    pair = str(model.get("pair", "BTCUSDT") or "").strip()
    if not pair or pair.upper() in {"ALL", "ANY"}:
        return list(DEFAULT_PAIRS)
    if "," in pair:
        return [p.strip().upper() for p in pair.split(",") if p.strip()]
    return [pair.upper()]


def get_directions_for_model(model: dict) -> list[str]:
    bias = str(model.get("bias", "Both") or "").strip().lower()
    if not bias or bias in {"both", "all", "any"}:
        return ["bullish", "bearish"]
    if bias in {"bullish", "bull", "long"}:
        return ["bullish"]
    if bias in {"bearish", "bear", "short"}:
        return ["bearish"]
    return ["bullish", "bearish"]


async def passes_volatility_gate(pair: str, timeframe: str, cache: dict) -> bool:
    candles = await get_candles(pair, timeframe, 20, cache)
    if not candles or len(candles) < 2:
        return True
    last, prev = candles[-1], candles[-2]
    if not prev["close"]:
        return True
    change_pct = abs(last["close"] - prev["close"]) / prev["close"] * 100
    atr = calc_atr(candles)
    atr_pct = atr / last["close"] * 100 if last["close"] else 0
    passed = change_pct >= 0.2 or atr_pct >= 0.3
    if not passed:
        log.debug("Volatility gate skipped %s (%s): change %.3f%% atr %.3f%%", pair, timeframe, change_pct, atr_pct)
    return passed


async def evaluate_phase(phase_num: int, rules: list, pair: str, timeframe: str, candle_cache: dict, direction: str) -> dict:
    phase_rules = [r for r in rules if (int(r.get("phase") or 1) if str(r.get("phase") or "").strip() else 1) == phase_num]
    log.info("Phase %s | %s | %s | %s | %s rules", phase_num, pair, direction.capitalize(), timeframe, len(phase_rules))
    if not phase_rules:
        log.info("Phase %s: no rules assigned — auto-passing", phase_num)
        return {
            "phase": phase_num,
            "passed": True,
            "score": 0,
            "max_score": 0,
            "score_pct": 100,
            "passed_rules": [],
            "failed_rules": [],
            "mandatory_failed": [],
            "invalidated": False,
            "phase_data": {},
        }

    passed_rules, failed_rules, mandatory_failed = [], [], []
    score = 0.0
    max_score = sum(float(r.get("weight", 1)) for r in phase_rules)
    phase_data = {"pair": pair, "timeframe": timeframe, "direction": direction}
    for rule in phase_rules:
        ok = await evaluate_rule(rule, pair, timeframe, direction, candle_cache)
        rule_display = rule.get("tag") or rule.get("name") or rule.get("id") or "unknown"
        if ok:
            passed_rules.append(rule_display)
            score += float(rule.get("weight", 1))
            log.debug("  ✅ %s", rule_display)
        else:
            failed_rules.append(rule_display)
            log.debug("  ❌ %s", rule_display)
            if rule.get("mandatory"):
                mandatory_failed.append(rule_display)
    score_pct = (score / max_score * 100) if max_score > 0 else 0
    invalidated = bool(mandatory_failed)
    threshold = PHASE_THRESHOLDS.get(phase_num, 60)
    passed = (not invalidated) and score_pct >= threshold
    log.info(
        "Phase %s result: %.1f/%.1f (%.0f%% vs %s%% threshold) → %s%s",
        phase_num,
        score,
        max_score,
        score_pct,
        threshold,
        "PASS" if passed else "FAIL",
        f" [mandatory failed: {mandatory_failed}]" if mandatory_failed else "",
    )
    return {"phase": phase_num, "passed": passed, "score": score, "max_score": max_score, "score_pct": score_pct, "passed_rules": passed_rules, "failed_rules": failed_rules, "mandatory_failed": mandatory_failed, "invalidated": invalidated, "phase_data": phase_data}


async def run_phase_engine(context):
    try:
        await asyncio.wait_for(_run_phase_engine_inner(context), timeout=240)
    except asyncio.TimeoutError:
        log.warning("phase_engine timed out after 4 minutes")
    except Exception as e:
        log.error(f"phase_engine error: {e}")


async def _run_phase_engine_inner(context):
    models = db.get_active_models()
    if not models:
        log.info("Phase engine: no active models")
        return

    candle_cache = {}
    log.info("Phase engine: evaluating %s models", len(models))
    for model in models:
        rules = model.get("rules", [])
        if not rules:
            log.warning("Model '%s' has no rules — skipping", model.get("name"))
            continue
        pairs = get_pairs_for_model(model)
        directions = get_directions_for_model(model)
        phase_tfs = model.get("phase_timeframes", {"1": "4h", "2": "1h", "3": "15m", "4": "5m"})
        log.debug(
            "Model '%s': pairs=%s directions=%s rules=%s",
            model.get("name"),
            pairs,
            directions,
            len(rules),
        )
        for pair in pairs:
            for direction in directions:
                try:
                    await evaluate_model_phases(context, model, pair, direction, rules, phase_tfs, candle_cache)
                except Exception as exc:
                    log.error(
                        "Phase engine error — model='%s' pair=%s direction=%s: %s: %s",
                        model.get("name"),
                        pair,
                        direction,
                        type(exc).__name__,
                        exc,
                    )


async def evaluate_model_phases(context, model, pair, direction, rules, phase_tfs, candle_cache):
    existing = db.get_setup_phase(model["id"], pair, direction)
    if existing is None:
        sid = db.save_setup_phase({"model_id": model["id"], "model_name": model["name"], "pair": pair, "direction": direction, "overall_status": "phase1", "check_count": 0})
        existing = db.get_setup_phase(model["id"], pair, direction) or {"id": sid, "overall_status": "phase1"}
    if not await passes_volatility_gate(pair, phase_tfs.get("3", "15m"), candle_cache):
        return
    status = existing.get("overall_status", "phase1")
    if status == "phase1":
        result = await evaluate_phase(1, rules, pair, phase_tfs.get("1", "4h"), candle_cache, direction)
        if result["passed"]:
            await _complete_phase(context, existing, 1, result, model, pair, direction)
        elif result["invalidated"]:
            await _invalidate_setup(existing, result)
    elif status == "phase2":
        if _is_expired(existing, 1):
            await _reset_to_phase1(existing)
            return
        result = await evaluate_phase(2, rules, pair, phase_tfs.get("2", "1h"), candle_cache, direction)
        if result["passed"]:
            await _complete_phase(context, existing, 2, result, model, pair, direction)
        elif result["invalidated"]:
            await _invalidate_setup(existing, result)
    elif status == "phase3":
        if _is_expired(existing, 2):
            await _reset_to_phase1(existing)
            return
        result = await evaluate_phase(3, rules, pair, phase_tfs.get("3", "15m"), candle_cache, direction)
        if result["passed"]:
            await _fire_alert(context, existing, result, model, pair)
    elif status == "phase4":
        result = await evaluate_phase(4, rules, pair, phase_tfs.get("4", "5m"), candle_cache, direction)
        await _send_phase4_result(context, existing, result, model, pair)


def _is_expired(existing: dict, phase_num: int) -> bool:
    expiry = existing.get(f"phase{phase_num}_expires_at")
    return bool(expiry and datetime.utcnow() > expiry)


async def _reset_to_phase1(existing: dict):
    db.update_phase_status(existing["id"], 1, "pending", {"reset": True})


async def _invalidate_setup(existing: dict, result: dict):
    db.update_phase_status(existing["id"], 1, "pending", {"invalidated": True, "reason": result.get("mandatory_failed", [])})


async def _complete_phase(context, existing, phase_num, result, model, pair, direction):
    db.update_phase_status(existing["id"], phase_num, "completed", result)
    if phase_num == 1:
        msg = await context.bot.send_message(chat_id=CHAT_ID, text=f"🔭 *Phase 1 Complete — Context Set*\n⚙️ {model['name']} | 🪙 {pair}\n📊 Direction: {direction.upper()}\n✅ {len(result['passed_rules'])} HTF rules passed\n⏳ Watching for Phase 2 (MTF Setup)...", parse_mode="Markdown")
        db.save_setup_phase({"id": existing["id"], "overall_status": "phase2", "alert_message_id": msg.message_id})
    elif phase_num == 2:
        msg = await context.bot.send_message(chat_id=CHAT_ID, text=f"🔬 *Phase 2 Complete — Setup Building*\n⚙️ {model['name']} | 🪙 {pair}\n📊 Direction: {direction.upper()}\n✅ Phase 1: HTF Context ✓\n✅ Phase 2: MTF Setup ✓\n⚡ Watching for Phase 3 (LTF Trigger)...", parse_mode="Markdown")
        db.save_setup_phase({"id": existing["id"], "overall_status": "phase3", "alert_message_id": msg.message_id})


async def _fire_alert(context, existing, result, model, pair):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from engine import get_session
    from engine.correlation_guard import check_correlation
    from engine.notification_filter import should_suppress_alert, record_alert_fired
    from engine.quality_scorer import score_setup_quality, format_quality_badge
    from engine.risk_engine import run_risk_checks

    candles = await get_candles(pair, "15m", 20, {})
    price = candles[-1]["close"] if candles else 0
    direction = existing.get("direction", "bullish")
    sl = price * (0.995 if direction == "bullish" else 1.005)
    rr = abs(price - sl)
    tp1 = price + rr if direction == "bullish" else price - rr
    tp2 = price + rr * 2 if direction == "bullish" else price - rr * 2
    tp3 = price + rr * 3 if direction == "bullish" else price - rr * 3

    try:
        quality = score_setup_quality(
            phase1_result={"score_pct": existing.get("phase1_score", 0) / max(existing.get("phase1_max_score", 1), 1) * 100, "passed": True, "passed_rules": existing.get("phase1_passed_rules", []), "mandatory_failed": [], "completed_at": existing.get("phase1_completed_at")},
            phase2_result={"score_pct": existing.get("phase2_score", 0) / max(existing.get("phase2_max_score", 1), 1) * 100, "passed": True, "passed_rules": existing.get("phase2_passed_rules", []), "mandatory_failed": [], "completed_at": existing.get("phase2_completed_at")},
            phase3_result=result, pair=pair, direction=direction, model=model,
        )
    except Exception as exc:
        log.error("Quality scorer failed: %s", exc)
        quality = {"grade": "C", "score": 50, "grade_emoji": "⚠️", "phase_pcts": {"p1": 0, "p2": 0, "p3": 0}, "session": "Unknown"}

    settings = db.get_risk_settings()
    min_grade = settings.get("min_quality_grade", "C")
    order = ["D", "C", "B", "A", "A+"]
    if order.index(quality["grade"]) < order.index(min_grade):
        await context.bot.send_message(chat_id=CHAT_ID, text=f"⚠️ *Alert Filtered — Low Quality*\n━━━━━━━━━━━━━━━━━━━━━━━━\n⚙️ {model['name']} | {pair}\nGrade: {quality['grade_emoji']} {quality['grade']} ({quality['score']}/100)\nMinimum grade set to: {min_grade}", parse_mode="Markdown")
        return

    suppress = should_suppress_alert({"session": get_session(), "pair": pair, "model_id": model["id"], "direction": direction, "quality_grade": quality["grade"]})
    if suppress["suppress"]:
        await context.bot.send_message(chat_id=CHAT_ID, text=f"🔕 *Alert Filtered*\n{pair} | {direction}\n_{suppress['reason']}_", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👁 Show This Alert", callback_data=f"filter:override:{model['id']}:{pair}")]]))
        return

    try:
        risk = await run_risk_checks(pair, direction, price, sl, tp1)
    except Exception as exc:
        log.error("Risk checks failed: %s", exc)
        risk = {"approved": True, "risk_level": "yellow", "summary": "⚠️ Risk check unavailable", "position": {"risk_amount": 0, "position_size": 0, "leverage_needed": 0, "rr_ratio": 0}}

    if not risk.get("approved") and risk.get("risk_level") == "red":
        await context.bot.send_message(chat_id=CHAT_ID, text=f"🚫 *Alert Suppressed — Risk Check Failed*\n⚙️ {model['name']} | 🪙 {pair}\n{risk['summary']}", parse_mode="Markdown")
        return

    quality_badge = format_quality_badge(quality)
    alert_text = f"🚨 *PHASE ALERT — ALL 3 PHASES COMPLETE*\n✅ P1: HTF Context\n✅ P2: MTF Setup\n✅ P3: LTF Trigger ({len(result['passed_rules'])} rules)\n⏳ P4: Awaiting confirmation...\n\n{model['name']} {pair}\nEntry: {price:.4f}\nSL: {sl:.4f}\nTP1: {tp1:.4f}\nTP2: {tp2:.4f}\nTP3: {tp3:.4f}"
    alert_text += f"\n━━━━━━━━━━━━━━━━━━━━━━━━\n{quality_badge}\n━━━━━━━━━━━━━━━━━━━━━━━━\n💰 *Risk Analysis*\n{risk['summary']}"

    corr = check_correlation(pair, direction, db.get_open_demo_trades_all())
    if corr["conflict"]:
        if corr["severity"] == "high":
            alert_text += f"\n\n🔗 *Correlation Warning*\n⚠️ {corr['reason']}"
        else:
            alert_text += f"\n\n🔗 _{corr['reason']}_"

    msg = await context.bot.send_message(chat_id=CHAT_ID, text=alert_text, parse_mode="Markdown")
    record_alert_fired({"session": get_session(), "pair": pair, "model_id": model["id"], "direction": direction, "quality_grade": quality["grade"]})
    db.save_setup_phase({"id": existing["id"], "overall_status": "phase4", "alert_message_id": msg.message_id, "entry_price": price, "stop_loss": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3})
    lc_id = db.save_alert_lifecycle({"setup_phase_id": existing["id"], "model_id": model["id"], "pair": pair, "direction": direction, "entry_price": price, "risk_level": risk.get("risk_level"), "risk_amount": risk.get("position", {}).get("risk_amount"), "position_size": risk.get("position", {}).get("position_size"), "leverage": risk.get("position", {}).get("leverage_needed"), "rr_ratio": risk.get("position", {}).get("rr_ratio"), "quality_grade": quality["grade"], "quality_score": quality["score"]})
    context.job_queue.run_once(phase4_check_job, when=900, data={"setup_phase_id": existing["id"], "lifecycle_id": lc_id})


async def phase4_check_job(context):
    setup_phase_id = context.job.data.get("setup_phase_id")
    setup = next((x for x in db.get_phases_awaiting_phase4() if x["id"] == setup_phase_id), None)
    if not setup:
        return
    model = db.get_model(setup["model_id"])
    await _send_phase4_result(context, setup, {"passed": True, "passed_rules": [], "failed_rules": []}, model or {"name": setup["model_id"]}, setup["pair"])


async def _send_phase4_result(context, existing, result, model, pair):
    passed = result.get("passed", False)
    text = "✅ *Phase 4 Confirmed*\nSetup is following through as expected.\nEntry is valid — manage your position." if passed else "❌ *Phase 4 Failed*\nSetup did not follow through.\nConsider reducing position or exiting."
    await context.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")
    lc = db.get_alert_lifecycle(existing["id"])
    if lc:
        db.update_alert_lifecycle(lc["id"], {"phase4_result": "confirmed" if passed else "failed", "phase4_message": text, "phase4_sent_at": datetime.utcnow(), "outcome": "active" if passed else "failed"})
    db.update_model_performance(existing["model_id"])
    current_regime = db.get_latest_regime()
    if current_regime:
        db.update_model_regime_performance(model.get("id", existing["model_id"]), current_regime["regime"], confirmed=passed)
    db.save_setup_phase({"id": existing["id"], "overall_status": "phase1", "phase1_status": "pending", "phase2_status": "waiting", "phase3_status": "waiting", "phase4_status": "waiting"})


async def alert_lifecycle_job(context):
    lifecycles = db.get_active_lifecycles()
    cache = {}
    for lc in lifecycles:
        candles = await get_candles(lc["pair"], "15m", 5, cache)
        if not candles:
            continue
        current, entry = candles[-1]["close"], lc["entry_price"]
        if not lc.get("entry_touched"):
            band = entry * 0.001
            if abs(current - entry) <= band:
                db.update_alert_lifecycle(lc["id"], {"entry_touched": True, "entry_touched_at": datetime.utcnow()})
                from engine.notification_filter import record_entry_touched
                record_entry_touched({"session": lc.get("session", "Unknown"), "pair": lc["pair"], "model_id": lc.get("model_id", ""), "direction": lc.get("direction", ""), "quality_grade": lc.get("quality_grade", "C")})
        elapsed = (datetime.utcnow() - lc["alert_sent_at"]).seconds
        if elapsed > 1800 and not lc.get("entry_touched"):
            await context.bot.send_message(chat_id=CHAT_ID, text=f"⏰ *Entry Missed — {lc['pair']}*\nPrice never reached entry zone.\nAlert is now stale.", parse_mode="Markdown")
            db.update_alert_lifecycle(lc["id"], {"outcome": "missed", "closed_at": datetime.utcnow()})


def calculate_model_grade(perf: dict) -> str:
    total = perf.get("total_alerts", 0)
    if total < 10:
        return "N/A"
    p4_rate = perf.get("phase4_confirms", 0) / max(total, 1)
    win_rate = perf.get("demo_win_rate", 0)
    avg_r = perf.get("avg_r", 0)
    score = (p4_rate * 40) + (win_rate * 40) + (min(avg_r, 3) / 3 * 20)
    if score >= 80:
        return "A+"
    if score >= 70:
        return "A"
    if score >= 60:
        return "B"
    if score >= 50:
        return "C"
    if score >= 40:
        return "D"
    return "F"


async def model_grading_job(context):
    for model in db.get_active_models():
        db.update_model_performance(model["id"])
        perf = db.get_model_performance(model["id"])
        grade = calculate_model_grade(perf)
        if grade in ["D", "F"]:
            await context.bot.send_message(chat_id=CHAT_ID, text=f"⚠️ *Model Grade: {grade}*\n⚙️ {model['name']}\nAlerts: {perf['total_alerts']}\nWin rate: {perf['demo_win_rate']:.0%}\nAvg R: {perf['avg_r']:.1f}\n\nConsider reviewing this model's rules.", parse_mode="Markdown")


async def expire_old_phases_job(context):
    db.expire_old_phases()
