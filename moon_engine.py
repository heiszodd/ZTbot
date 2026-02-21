from __future__ import annotations


def score_moonshot_potential(token: dict) -> dict:
    liq = float(token.get("liquidity_usd") or 0)
    mcap = float(token.get("mcap") or 0)
    score = 40
    bulls = []
    if mcap and mcap < 20_000_000:
        score += 20
        bulls.append("Early market cap stage")
    if liq > 50_000:
        score += 20
        bulls.append("Tradable liquidity")
    if liq > 200_000:
        score += 10
        bulls.append("Strong liquidity depth")
    score = max(1, min(100, score))
    label = "HIGH" if score >= 75 else "MEDIUM" if score >= 50 else "LOW"
    return {"moon_score": score, "label": label, "bull_factors": bulls[:2]}
