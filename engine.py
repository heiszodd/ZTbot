from datetime import datetime, timezone
from config import ATR_BANDS, SESSIONS, NEWS_BLACKOUT_MIN, TIER_RISK


def classify_volatility(atr_ratio: float) -> dict:
    for lo, hi, label, modifier in ATR_BANDS:
        if lo <= atr_ratio < hi:
            return {"label": label, "modifier": modifier}
    return {"label": "Extreme", "modifier": -1.0}


def calc_htf_modifier(htf_1h: str, htf_4h: str, bias: str) -> dict:
    aligned  = (htf_1h == bias) and (htf_4h == bias)
    conflict = (htf_1h != bias and htf_1h != "Neutral") or \
               (htf_4h != bias and htf_4h != "Neutral")
    if aligned:  return {"modifier":  0.5, "label": "Both 1H+4H aligned ✅"}
    if conflict: return {"modifier": -1.0, "label": "HTF conflict ❌"}
    return               {"modifier":  0.0, "label": "HTF neutral"}


def get_session(utc_hour: int = None) -> str:
    if utc_hour is None:
        utc_hour = datetime.now(timezone.utc).hour
    if 12 <= utc_hour < 16: return "Overlap"
    if  8 <= utc_hour < 16: return "London"
    if 13 <= utc_hour < 21: return "NY"
    if utc_hour >= 23 or utc_hour < 8: return "Asia"
    return "Off-Hours"


def score_setup(setup: dict, model: dict) -> dict:
    result = {
        "valid": True, "invalid_reason": None,
        "mandatory_failed": [], "passed_rules": [], "failed_rules": [],
        "raw_score": 0.0, "modifiers": [], "modifier_total": 0.0,
        "final_score": 0.0, "tier": None, "risk_pct": None,
        "vol_label": "Normal", "htf_label": "Neutral",
        "session": get_session(),
    }
    passed_ids = set(setup.get("passed_rule_ids", []))

    # ① Mandatory gate
    for rule in model.get("rules", []):
        if rule.get("mandatory") and rule["id"] not in passed_ids:
            result["valid"] = False
            result["mandatory_failed"].append(rule["name"])
    if not result["valid"]:
        result["invalid_reason"] = "Mandatory rule failed: " + ", ".join(result["mandatory_failed"])
        return result

    # ② News gate
    news_min = setup.get("news_minutes")
    if news_min is not None and news_min <= NEWS_BLACKOUT_MIN:
        result["valid"] = False
        result["invalid_reason"] = f"High-impact news in {news_min} min"
        return result

    # ③ Raw score
    for rule in model.get("rules", []):
        if rule["id"] in passed_ids:
            result["raw_score"] += rule["weight"]
            result["passed_rules"].append(rule)
        else:
            result["failed_rules"].append(rule)

    # ④ Modifiers
    vol = classify_volatility(setup.get("atr_ratio", 1.0))
    result["vol_label"] = vol["label"]
    if vol["modifier"] != 0:
        result["modifiers"].append({"label": f"Volatility ({vol['label']})", "value": vol["modifier"]})

    htf = calc_htf_modifier(
        setup.get("htf_1h", "Neutral"),
        setup.get("htf_4h", "Neutral"),
        model.get("bias", "Bullish")
    )
    result["htf_label"] = htf["label"]
    if htf["modifier"] != 0:
        result["modifiers"].append({"label": htf["label"], "value": htf["modifier"]})

    result["modifier_total"] = sum(m["value"] for m in result["modifiers"])
    result["final_score"]    = round(result["raw_score"] + result["modifier_total"], 2)

    # ⑤ Tier
    if   result["final_score"] >= model.get("tier_a", 9.5):
        result["tier"] = "A"; result["risk_pct"] = TIER_RISK["A"]
    elif result["final_score"] >= model.get("tier_b", 7.5):
        result["tier"] = "B"; result["risk_pct"] = TIER_RISK["B"]
    elif result["final_score"] >= model.get("tier_c", 5.5):
        result["tier"] = "C"; result["risk_pct"] = TIER_RISK["C"]

    return result


def calc_trade_levels(price: float, direction: str, atr: float) -> dict:
    """
    Calculate entry, SL, TP from live price and ATR.
    SL = 1.5× ATR from entry, TP = 3× ATR (RR 1:2).
    """
    if direction == "BUY":
        entry = price
        sl    = round(price - atr * 1.5, 5)
        tp    = round(price + atr * 3.0, 5)
    else:
        entry = price
        sl    = round(price + atr * 1.5, 5)
        tp    = round(price - atr * 3.0, 5)
    rr = 2.0
    return {"entry": entry, "sl": sl, "tp": tp, "rr": rr}


def build_live_setup(model: dict, prices_series: list[float]) -> dict:
    """Generate a deterministic setup snapshot from recent prices."""
    if len(prices_series) < 20:
        return {"pair": model["pair"], "passed_rule_ids": []}

    recent = prices_series[-1]
    prev = prices_series[-6]
    mom = (recent - prev) / prev if prev else 0
    direction = "BUY" if mom >= 0 else "SELL"
    if model.get("bias") == "Bearish":
        direction = "SELL"
    elif model.get("bias") == "Bullish":
        direction = "BUY"

    passed = []
    for idx, rule in enumerate(model.get("rules", []), start=1):
        # Staggered deterministic pass rates by momentum and rule index
        threshold = 0.0005 * idx
        cond = abs(mom) >= threshold or (idx % 2 == 0)
        if cond:
            passed.append(rule["id"])

    return {
        "pair": model["pair"],
        "passed_rule_ids": passed,
        "atr_ratio": 1.0 + min(abs(mom) * 80, 1.5),
        "htf_1h": model.get("bias", "Neutral"),
        "htf_4h": model.get("bias", "Neutral"),
        "news_minutes": None,
        "direction": direction,
    }


def backtest_model(model: dict, prices_series: list[float]) -> dict:
    """Simple bar-by-bar backtest returning win-rate and sample stats."""
    if len(prices_series) < 40:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "avg_rr": 0.0,
        }

    wins = losses = 0
    rr_values = []

    for i in range(30, len(prices_series) - 8, 3):
        window = prices_series[: i + 1]
        setup = build_live_setup(model, window)
        scored = score_setup(setup, model)
        if not scored["valid"] or not scored["tier"]:
            continue

        entry = prices_series[i]
        if setup["direction"] == "BUY":
            future_max = max(prices_series[i + 1 : i + 7])
            future_min = min(prices_series[i + 1 : i + 7])
            hit_tp = (future_max - entry) / entry >= 0.006
            hit_sl = (entry - future_min) / entry >= 0.003
        else:
            future_max = max(prices_series[i + 1 : i + 7])
            future_min = min(prices_series[i + 1 : i + 7])
            hit_tp = (entry - future_min) / entry >= 0.006
            hit_sl = (future_max - entry) / entry >= 0.003

        if hit_tp and not hit_sl:
            wins += 1
            rr_values.append(2.0)
        elif hit_sl:
            losses += 1
            rr_values.append(-1.0)

    trades = wins + losses
    avg_rr = round(sum(rr_values) / len(rr_values), 2) if rr_values else 0.0
    win_rate = round((wins / trades * 100), 2) if trades else 0.0

    return {
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "avg_rr": avg_rr,
    }
