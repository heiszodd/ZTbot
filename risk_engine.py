from __future__ import annotations


def score_token_risk(token: dict) -> dict:
    liq = float(token.get("liquidity_usd") or 0)
    mcap = float(token.get("mcap") or 0)
    score = 50
    flags = []
    if liq < 10000:
        score += 20
        flags.append("Low liquidity")
    if mcap and mcap < 1000000:
        score += 15
        flags.append("Very low market cap")
    if liq and mcap and liq / max(mcap, 1) < 0.02:
        score += 10
        flags.append("Thin liquidity ratio")
    score = max(1, min(100, score))
    level = "LOW" if score < 35 else "MEDIUM" if score < 70 else "HIGH"
    return {"risk_score": score, "risk_level": level, "risk_flags": flags[:3]}
