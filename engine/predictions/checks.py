from __future__ import annotations

from datetime import datetime, timezone


def _safe(fn, market: dict, model: dict) -> bool:
    try:
        return bool(fn(market, model))
    except Exception:
        return False


def _days_to_resolve(market: dict) -> float:
    ts = market.get("resolve_at") or market.get("end_date")
    if not ts:
        return 999
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return max(0.0, (ts - datetime.now(timezone.utc)).total_seconds() / 86400)


CHECKS = {
    "check_min_volume": lambda m, o: float(m.get("volume_24h", 0) or 0) >= float(o.get("min_volume_24h", 0) or 0),
    "check_min_liquidity": lambda m, o: float(m.get("liquidity", 0) or 0) >= float(o.get("min_liquidity", 0) or 0),
    "check_not_resolved": lambda m, o: bool(m.get("resolved", False)) is False,
    "check_resolves_in_range": lambda m, o: float(o.get("min_days_to_resolve", 0) or 0) <= _days_to_resolve(m) <= float(o.get("max_days_to_resolve", 999) or 999),
    "check_active_market": lambda m, o: bool(m.get("active", True)) is True,
    "check_has_counterparty": lambda m, o: float(m.get("yes_liquidity", 0) or 0) > 0 and float(m.get("no_liquidity", 0) or 0) > 0,
    "check_yes_in_range": lambda m, o: float(o.get("min_yes_pct", 0) or 0) <= float(m.get("yes_pct", 0) or 0) <= float(o.get("max_yes_pct", 100) or 100),
    "check_uncertain_market": lambda m, o: 40 <= float(m.get("yes_pct", 0) or 0) <= 60,
    "check_mispriced_yes": lambda m, o: float(m.get("yes_pct", 100) or 100) < 30 and str(m.get("sentiment", "")).lower() == "bullish",
    "check_mispriced_no": lambda m, o: float(m.get("yes_pct", 0) or 0) > 70 and str(m.get("sentiment", "")).lower() == "bearish",
    "check_probability_trending_up": lambda m, o: float(m.get("yes_pct", 0) or 0) > float(m.get("yes_pct_24h_ago", 0) or 0),
    "check_probability_trending_down": lambda m, o: float(m.get("yes_pct", 0) or 0) < float(m.get("yes_pct_24h_ago", 0) or 0),
    "check_crypto_category": lambda m, o: "crypto" in str(m.get("category", "")).lower(),
    "check_macro_category": lambda m, o: "macro" in str(m.get("category", "")).lower(),
    "check_sentiment_aligned": lambda m, o: str(o.get("sentiment_filter", "any")).lower() in {"any", str(m.get("sentiment", "")).lower()},
    "check_correlated_with_perps": lambda m, o: bool(m.get("perps_aligned", False)),
    "check_high_volume_spike": lambda m, o: float(m.get("volume_24h", 0) or 0) > 3 * max(float(m.get("volume_7d_avg", 1) or 1), 1),
}


async def evaluate_market_against_model(market: dict, model: dict) -> dict:
    passed_checks, failed_checks, mandatory_fails = [], [], []
    weighted_score, total_weight = 0.0, 0.0

    for name in model.get("mandatory_checks", []):
        fn = CHECKS.get(name)
        if not fn:
            continue
        if _safe(fn, market, model):
            passed_checks.append(name)
        else:
            mandatory_fails.append(name)

    if mandatory_fails:
        return {"passed": False, "score": 0.0, "grade": "F", "passed_checks": passed_checks, "failed_checks": mandatory_fails, "mandatory_fails": mandatory_fails}

    for wc in model.get("weighted_checks", []):
        name = wc.get("check", "")
        weight = float(wc.get("weight", 1) or 1)
        fn = CHECKS.get(name)
        if not fn:
            continue
        total_weight += weight
        if _safe(fn, market, model):
            weighted_score += weight
            passed_checks.append(name)
        else:
            failed_checks.append(name)

    score = weighted_score / total_weight * 100 if total_weight else 0
    grade = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 55 else "D" if score >= 40 else "F"
    return {
        "passed": score >= float(model.get("min_passing_score", 60) or 60),
        "score": round(score, 1),
        "grade": grade,
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "mandatory_fails": [],
    }
