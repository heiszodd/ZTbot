from datetime import datetime, timezone
from config import ATR_BANDS, SESSIONS, NEWS_BLACKOUT_MIN, TIER_RISK


def classify_volatility(atr_ratio: float) -> dict:
    for lo, hi, label, modifier in ATR_BANDS:
        if lo <= atr_ratio < hi:
            return {"label": label, "modifier": modifier}
    return {"label": "Extreme", "modifier": -1.0}


def calc_htf_modifier(htf_1h: str, htf_4h: str, bias: str) -> dict:
    """Both 1H and 4H must agree for +0.5. Either conflicting = -1.0."""
    aligned  = (htf_1h == bias) and (htf_4h == bias)
    conflict = (htf_1h != bias and htf_1h != "Neutral") or \
               (htf_4h != bias and htf_4h != "Neutral")
    if aligned:  return {"modifier":  0.5, "label": "Both 1H+4H aligned"}
    if conflict: return {"modifier": -1.0, "label": "HTF conflict"}
    return               {"modifier":  0.0, "label": "HTF neutral"}


def get_session(utc_hour: int = None) -> str:
    if utc_hour is None:
        utc_hour = datetime.now(timezone.utc).hour
    # Overlap must be checked before London/NY (it's a subset of both)
    if 12 <= utc_hour < 16: return "Overlap"
    if  8 <= utc_hour < 16: return "London"
    if 13 <= utc_hour < 21: return "NY"
    if utc_hour >= 23 or utc_hour < 8: return "Asia"
    return "Off-Hours"


def score_setup(setup: dict, model: dict) -> dict:
    """
    Full scoring pipeline:
      ① Mandatory gate  — fail = invalidate immediately
      ② News gate       — high-impact news within 30 min = invalidate
      ③ Raw score       — sum weights of all passing rules
      ④ Flat modifiers  — ATR volatility + HTF alignment
      ⑤ Tier assignment — A / B / C or None
    """
    result = {
        "valid":            True,
        "invalid_reason":   None,
        "mandatory_failed": [],
        "passed_rules":     [],
        "failed_rules":     [],
        "raw_score":        0.0,
        "modifiers":        [],
        "modifier_total":   0.0,
        "final_score":      0.0,
        "tier":             None,
        "risk_pct":         None,
        "vol_label":        "Normal",
        "htf_label":        "Neutral",
        "session":          get_session(),
    }

    passed_ids = set(setup.get("passed_rule_ids", []))

    # ① Mandatory gate
    for rule in model.get("rules", []):
        if rule.get("mandatory") and rule["id"] not in passed_ids:
            result["valid"] = False
            result["mandatory_failed"].append(rule["name"])

    if not result["valid"]:
        failed = ", ".join(result["mandatory_failed"])
        result["invalid_reason"] = f"Mandatory rule failed: {failed}"
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
        result["modifiers"].append({
            "label": f"Volatility ({vol['label']})",
            "value": vol["modifier"]
        })

    htf = calc_htf_modifier(
        setup.get("htf_1h", "Neutral"),
        setup.get("htf_4h", "Neutral"),
        model.get("bias", "Bullish")
    )
    result["htf_label"] = htf["label"]
    if htf["modifier"] != 0:
        result["modifiers"].append({
            "label": htf["label"],
            "value": htf["modifier"]
        })

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
