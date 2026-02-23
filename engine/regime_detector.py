import logging
from datetime import date

import db

log = logging.getLogger(__name__)

REGIMES = {
    "trending_bull": "📈 Trending Bullish",
    "trending_bear": "📉 Trending Bearish",
    "ranging": "↔️ Ranging",
    "high_volatility": "⚡ High Volatility",
    "low_volatility": "😴 Low Volatility",
}


async def detect_market_regime() -> dict:
    from engine.rules import get_candles, calc_atr, is_bullish_trend, is_bearish_trend, find_swing_highs, find_swing_lows

    cache = {}
    pair = "BTCUSDT"
    d1_c = await get_candles(pair, "1d", 30, cache)
    h4_c = await get_candles(pair, "4h", 50, cache)
    if not d1_c or not h4_c:
        return {"regime": "ranging", "label": REGIMES["ranging"], "confidence": 0, "details": {"error": "No data"}, "atr_pct": 0, "range_pct": 0}
    details = {}
    atr_d1 = calc_atr(d1_c, period=14)
    price = d1_c[-1]["close"]
    atr_pct = atr_d1 / price * 100 if price > 0 else 0
    details["atr_pct_daily"] = round(atr_pct, 3)
    recent_20 = d1_c[-20:]
    range_high = max(c["high"] for c in recent_20)
    range_low = min(c["low"] for c in recent_20)
    range_pct = (range_high - range_low) / range_low * 100 if range_low > 0 else 0
    d1_bull = is_bullish_trend(d1_c)
    d1_bear = is_bearish_trend(d1_c)
    h4_bull = is_bullish_trend(h4_c)
    h4_bear = is_bearish_trend(h4_c)
    highs = find_swing_highs(h4_c[-30:], lookback=3)
    lows = find_swing_lows(h4_c[-30:], lookback=3)
    structure_range = ((highs[-1]["price"] - lows[-1]["price"]) / lows[-1]["price"] * 100) if highs and lows and lows[-1]["price"] > 0 else range_pct
    if atr_pct > 3.0:
        regime, confidence = "high_volatility", min(atr_pct / 5.0, 1.0)
    elif atr_pct < 0.8:
        regime, confidence = "low_volatility", min((0.8 - atr_pct) / 0.8, 1.0)
    elif d1_bull and h4_bull:
        regime, confidence = "trending_bull", 0.7 + (atr_pct / 10)
    elif d1_bear and h4_bear:
        regime, confidence = "trending_bear", 0.7 + (atr_pct / 10)
    else:
        regime, confidence = "ranging", max(0, 1.0 - (structure_range / 10))
    confidence = round(min(confidence, 1.0), 2)
    return {"regime": regime, "label": REGIMES.get(regime, regime), "confidence": confidence, "atr_pct": atr_pct, "range_pct": range_pct, "details": details}


async def apply_regime_to_models(regime: str, context) -> dict:
    models = db.get_all_models()
    changed = {"activated": [], "deactivated": []}
    hints = {
        "trending_bull": ["htf_bullish", "bos_bullish", "mss_bullish", "htf_ltf_aligned_bull"],
        "trending_bear": ["htf_bearish", "bos_bearish", "mss_bearish", "htf_ltf_aligned_bear"],
        "ranging": ["bullish_ob_present", "bearish_ob_present", "discount_zone", "premium_zone", "ote_zone"],
        "high_volatility": ["volume_spike", "liquidity_swept_bull", "liquidity_swept_bear", "stop_hunt"],
        "low_volatility": [],
    }
    preferred = hints.get(regime, [])
    for model in models:
        perf = db.get_model_regime_performance(model["id"], regime)
        rules = model.get("rules", [])
        tags = [r.get("tag", "") or r.get("id", "") for r in rules]
        if perf and perf.get("total_alerts", 0) >= 20:
            should_be_active = perf.get("confirm_rate", 0) >= 0.35
        elif regime == "low_volatility":
            should_be_active = False
        else:
            overlap = sum(1 for t in tags if t in preferred)
            should_be_active = overlap >= 1 or not preferred
        currently_active = str(model.get("status", "inactive")) == "active"
        regime_managed = bool(model.get("regime_managed"))
        if should_be_active and not currently_active and regime_managed:
            db.set_model_active(model["id"], True, regime_managed=False)
            changed["activated"].append(model["name"])
        elif not should_be_active and currently_active:
            db.set_model_active(model["id"], False, regime_managed=True)
            changed["deactivated"].append(model["name"])
    return changed


async def run_regime_detection(context):
    from config import CHAT_ID

    try:
        regime_data = await detect_market_regime()
        regime = regime_data["regime"]
        db.save_market_regime({"regime_date": date.today().isoformat(), "regime": regime, "confidence": regime_data["confidence"], "btc_atr_pct": regime_data["atr_pct"], "range_size": regime_data["range_pct"], "details": regime_data["details"]})
        changes = await apply_regime_to_models(regime, context)
        text = f"🌐 *Market Regime Detected*\n━━━━━━━━━━━━━━━━━━━━━━━━\nRegime:     {regime_data['label']}\nConfidence: {regime_data['confidence']:.0%}\nATR (daily): {regime_data['atr_pct']:.2f}%\n\n"
        if changes["activated"]:
            text += "*Activated models:*\n" + "\n".join([f"  ✅ {m}" for m in changes["activated"]]) + "\n\n"
        if changes["deactivated"]:
            text += "*Deactivated models:*\n" + "\n".join([f"  ⏸ {m}" for m in changes["deactivated"]]) + "\n\n"
        if not changes["activated"] and not changes["deactivated"]:
            text += "_No model changes needed._\n"
        await context.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")
    except Exception as e:
        log.error(f"Regime detection failed: {e}")
