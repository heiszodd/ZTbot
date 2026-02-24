from __future__ import annotations

from typing import Callable, Awaitable


async def _safe(fn, token_data: dict, model: dict) -> bool:
    try:
        return bool(fn(token_data, model))
    except Exception:
        return False


def _dev_sold_pct(token_data: dict) -> float:
    return float((token_data.get("dev_activity") or {}).get("sold_pct_30m", 100) or 100)


def _top10_pct(token_data: dict) -> float:
    return float((token_data.get("holder_distribution") or {}).get("top10_pct", 100) or 100)


CHECKS: dict[str, Callable[[dict, dict], bool]] = {
    "check_not_honeypot": lambda t, m: t.get("honeypot") is False,
    "check_not_blacklisted": lambda t, m: not bool(t.get("blacklisted", False)),
    "check_contract_verified": lambda t, m: bool(t.get("verified")) is True,
    "check_mint_disabled": lambda t, m: bool(t.get("mint_disabled")) is True,
    "check_freeze_disabled": lambda t, m: bool(t.get("freeze_disabled")) is True,
    "check_rug_score_low": lambda t, m: float(t.get("rug_score", 101) or 101) <= float(m.get("max_rug_score", 40) or 40),
    "check_dev_not_dumping": lambda t, m: _dev_sold_pct(t) < 10,
    "check_top10_not_concentrated": lambda t, m: _top10_pct(t) < 50,
    "check_min_liquidity": lambda t, m: float(t.get("liquidity_usd", 0) or 0) >= float(m.get("min_liquidity_usd", 0) or 0),
    "check_liquidity_locked": lambda t, m: bool(t.get("lp_locked")) is True,
    "check_mcap_in_range": lambda t, m: float(m.get("min_mcap_usd", 0) or 0) <= float(t.get("market_cap_usd", 0) or 0) <= float(m.get("max_mcap_usd", 10**12) or 10**12),
    "check_volume_to_mcap": lambda t, m: (float(t.get("volume_24h", 0) or 0) / max(float(t.get("market_cap_usd", 1) or 1), 1)) > 0.1,
    "check_buy_sell_ratio": lambda t, m: float(t.get("buys_1h", 0) or 0) > float(t.get("sells_1h", 0) or 0),
    "check_narrative_match": lambda t, m: not (m.get("narrative_filter") or []) or str(t.get("narrative", "")).lower() in {str(x).lower() for x in (m.get("narrative_filter") or [])},
    "check_social_velocity": lambda t, m: str((t.get("social") or {}).get("trend", "")).lower() in {"rising", "up", "surging"},
    "check_holder_growth": lambda t, m: float(t.get("holder_growth_1h_pct", 0) or 0) > 0,
    "check_age_in_range": lambda t, m: float(m.get("min_age_minutes", 0) or 0) <= float(t.get("token_age_minutes", 10**9) or 10**9) <= float(m.get("max_age_minutes", 10**9) or 10**9),
    "check_early_entry_score": lambda t, m: float(t.get("early_score", 0) or 0) >= 60,
    "check_price_momentum": lambda t, m: float(t.get("price_change_1h_pct", 0) or 0) > 5,
    "check_min_holders": lambda t, m: int(t.get("holder_count", 0) or 0) >= int(m.get("min_holder_count", 0) or 0),
    "check_no_recent_dump": lambda t, m: float(t.get("price_change_1h_pct", 0) or 0) > -20,
    "check_dev_wallet_small": lambda t, m: float(t.get("dev_supply_pct", 100) or 100) < 5,
    "check_not_copy_token": lambda t, m: not bool(t.get("known_scam_symbol", False)),
}


def get_check_function(name: str):
    fn = CHECKS.get(name)
    if fn is None:
        return None

    async def wrapped(token_data: dict, model: dict) -> bool:
        return await _safe(fn, token_data, model)

    return wrapped
