import logging
from datetime import datetime, timezone

import httpx

import db

log = logging.getLogger(__name__)


def _score_market(m: dict) -> float:
    """
    Score a Polymarket market 0-100.
    Higher = better trading opportunity.
    """
    score = 0.0

    vol = float(m.get("volume24hr") or m.get("volume") or 0)
    liq = float(m.get("liquidity") or 0)
    yes = float(m.get("bestAsk") or m.get("yes_bid") or 0.5)

    if vol >= 500000:
        score += 30
    elif vol >= 100000:
        score += 20
    elif vol >= 50000:
        score += 12
    elif vol >= 10000:
        score += 5

    if liq >= 100000:
        score += 20
    elif liq >= 50000:
        score += 13
    elif liq >= 10000:
        score += 6

    distance_from_50 = abs(yes - 0.5)
    if distance_from_50 <= 0.10:
        score += 30
    elif distance_from_50 <= 0.20:
        score += 20
    elif distance_from_50 <= 0.35:
        score += 10

    end_date = m.get("endDate") or m.get("end_date_iso", "")
    if end_date:
        try:
            end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            days = (end - now).days
            if 1 <= days <= 7:
                score += 20
            elif 7 < days <= 14:
                score += 15
            elif 14 < days <= 30:
                score += 10
            elif days > 30:
                score += 3
        except Exception:
            score += 5

    return min(100, score)


async def run_market_scanner() -> list:
    """
    Fetch markets from Polymarket.
    Returns empty list on timeout or error.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://gamma-api.polymarket.com/markets",
                params={
                    "limit": 25,
                    "active": "true",
                    "closed": "false",
                    "order": "volume24hr",
                    "ascending": "false",
                    "tag_slug": "",
                    "liquidity_min": "5000",
                    "volume_num_min": "10000",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            markets = data if isinstance(data, list) else data.get("markets", [])

            active_models = db.get_active_prediction_models()
            if active_models:
                for m in markets:
                    yes = float(m.get("bestAsk") or m.get("yes_bid") or 0.5)
                    vol = float(m.get("volume24hr") or 0)
                    liq = float(m.get("liquidity") or 0)
                    market_score = _score_market(m)
                    for model in active_models:
                        yes_pct = yes * 100
                        mn = model.get("min_yes_pct", 0)
                        mx = model.get("max_yes_pct", 100)
                        min_vol = model.get("min_volume_24h", 0)
                        min_liq = model.get("min_liquidity", 0)
                        if mn <= yes_pct <= mx and vol >= min_vol and liq >= min_liq:
                            try:
                                db.save_pending_signal(
                                    {
                                        "section": "predictions",
                                        "pair": (m.get("question", "?"))[:80],
                                        "direction": "YES" if yes_pct >= 50 else "NO",
                                        "phase": 4,
                                        "quality_score": market_score,
                                        "quality_grade": "A" if market_score >= 70 else "B",
                                        "signal_data": m,
                                        "status": "pending",
                                    }
                                )
                            except Exception:
                                pass
                            break
            return markets
    except httpx.TimeoutException:
        return []
    except Exception as e:
        log.error("Market scanner: %s", e)
        return []


def format_scanner_results(markets: list) -> str:
    if not markets:
        return (
            "🔍 *Prediction Scanner*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "No markets found.\n"
            "Polymarket API may be unavailable.\n"
            "Try again in a moment."
        )

    scored = []
    for m in markets:
        s = _score_market(m)
        scored.append((s, m))
    scored.sort(key=lambda x: x[0], reverse=True)

    text = (
        "🔍 *Prediction Scanner*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Top {min(8, len(scored))} markets by opportunity score:\n\n"
    )

    for score, m in scored[:8]:
        q = (m.get("question") or "?")[:55]
        yes = float(m.get("bestAsk") or m.get("yes_bid") or 0.5)
        no = 1 - yes
        vol = float(m.get("volume24hr") or m.get("volume") or 0)
        vol_s = (
            f"${vol/1000000:.1f}M"
            if vol >= 1000000
            else f"${vol/1000:.0f}K"
            if vol >= 1000
            else f"${vol:.0f}"
        )
        grade = "A" if score >= 70 else "B" if score >= 50 else "C"
        if yes <= 0.35:
            e = "🔴"
        elif yes >= 0.65:
            e = "🟢"
        else:
            e = "🟡"

        text += (
            f"{e} [{grade}] *{q}*\n"
            f"   YES {yes*100:.0f}%  NO {no*100:.0f}%  Vol {vol_s}\n\n"
        )

    return text
