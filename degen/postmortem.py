from __future__ import annotations

import db


def create_postmortem(token_id: int) -> int | None:
    token = db.get_degen_token_by_id(token_id)
    if not token:
        return None
    factors = token.get("risk_flags") or []
    risk0 = int(token.get("initial_risk_score") or token.get("risk_score") or 0)
    risk1 = int(token.get("latest_risk_score") or token.get("risk_score") or risk0)
    moon0 = int(token.get("moon_score") or 0)
    price_alert = float(token.get("price_usd") or 0)
    rug_price = float(token.get("current_price") or token.get("price_usd") or 0)
    drop = ((price_alert - rug_price) / price_alert * 100) if price_alert else 0
    mins = int(token.get("time_to_rug_minutes") or 0)
    missed = token.get("missed_signals") or ["holder clustering", "insider funding", "LP concentration"]
    payload = {
        "token_id": token_id,
        "token_address": token.get("address"),
        "token_symbol": token.get("symbol"),
        "initial_risk_score": risk0,
        "final_risk_score": risk1,
        "initial_moon_score": moon0,
        "price_at_alert": price_alert,
        "price_at_rug": rug_price,
        "drop_pct": drop,
        "time_to_rug_minutes": mins,
        "was_alerted": bool(token.get("was_alerted", True)),
        "was_in_watchlist": bool(token.get("in_watchlist", True)),
        "triggered_risk_factors": factors,
        "missed_signals": missed,
        "detected_at": token.get("created_at"),
    }
    return db.insert_rug_postmortem(payload)
