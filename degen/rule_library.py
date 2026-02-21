from __future__ import annotations

from typing import Callable


def _safe_eval(fn: Callable[[dict], bool]) -> Callable[[dict], bool]:
    def wrapped(token_data: dict) -> bool:
        try:
            return bool(fn(token_data or {}))
        except Exception:
            return False

    return wrapped


def _rule(rule_id: str, name: str, category: str, description: str, weight_default: float, mandatory_default: bool, evaluate_fn: Callable[[dict], bool]) -> dict:
    return {
        "id": rule_id,
        "name": name,
        "category": category,
        "description": description,
        "weight_default": weight_default,
        "mandatory_default": mandatory_default,
        "evaluate": _safe_eval(evaluate_fn),
    }


RULES = [
    _rule("dev_no_rugs", "Dev has zero rug history", "DEV REPUTATION", "Dev wallet has never been linked to a rug pull", 3.0, False, lambda t: t.get("dev_rug_count", 99) == 0),
    _rule("dev_clean_reputation", "Dev reputation is CLEAN", "DEV REPUTATION", "", 2.5, False, lambda t: t.get("dev_reputation") == "CLEAN"),
    _rule("dev_wallet_age_7d", "Dev wallet older than 7 days", "DEV REPUTATION", "", 1.5, False, lambda t: t.get("dev_wallet_age_days", 0) >= 7),
    _rule("dev_wallet_age_30d", "Dev wallet older than 30 days", "DEV REPUTATION", "", 2.0, False, lambda t: t.get("dev_wallet_age_days", 0) >= 30),
    _rule("dev_low_supply", "Dev holds less than 5% of supply", "DEV REPUTATION", "", 2.0, False, lambda t: t.get("dev_pct", 100) < 5),
    _rule("dev_very_low_supply", "Dev holds less than 2% of supply", "DEV REPUTATION", "", 2.5, False, lambda t: t.get("dev_pct", 100) < 2),
    _rule("dev_not_serial_rugger", "Dev is not a serial rugger", "DEV REPUTATION", "", 3.0, True, lambda t: t.get("dev_reputation") != "SERIAL_RUGGER"),
    _rule("mint_revoked", "Mint authority revoked", "CONTRACT SAFETY", "Devs cannot print more tokens", 3.0, False, lambda t: t.get("mint_authority_revoked") is True),
    _rule("freeze_revoked", "Freeze authority revoked", "CONTRACT SAFETY", "Devs cannot freeze your wallet", 3.0, False, lambda t: t.get("freeze_authority_revoked") is True),
    _rule("contract_verified", "Contract is verified", "CONTRACT SAFETY", "", 1.5, False, lambda t: t.get("contract_verified") is True),
    _rule("no_honeypot", "Not a honeypot", "CONTRACT SAFETY", "", 5.0, True, lambda t: t.get("honeypot") is not True),
    _rule("rugcheck_safe", "RugCheck score below 300", "CONTRACT SAFETY", "", 2.0, False, lambda t: t.get("rugcheck_score", 999) < 300),
    _rule("rugcheck_very_safe", "RugCheck score below 150", "CONTRACT SAFETY", "", 3.0, False, lambda t: t.get("rugcheck_score", 999) < 150),
    _rule("lp_locked", "LP is locked", "LIQUIDITY", "", 2.5, False, lambda t: t.get("lp_locked_pct", 0) > 0),
    _rule("lp_locked_50", "LP locked at least 50%", "LIQUIDITY", "", 2.0, False, lambda t: t.get("lp_locked_pct", 0) >= 50),
    _rule("lp_locked_80", "LP locked at least 80%", "LIQUIDITY", "", 3.0, False, lambda t: t.get("lp_locked_pct", 0) >= 80),
    _rule("lp_burned", "LP burned", "LIQUIDITY", "", 3.5, False, lambda t: t.get("lp_burned") is True),
    _rule("liquidity_10k", "Liquidity over $10,000", "LIQUIDITY", "", 1.5, False, lambda t: t.get("liquidity_usd", 0) >= 10000),
    _rule("liquidity_50k", "Liquidity over $50,000", "LIQUIDITY", "", 2.0, False, lambda t: t.get("liquidity_usd", 0) >= 50000),
    _rule("liquidity_100k", "Liquidity over $100,000", "LIQUIDITY", "", 2.5, False, lambda t: t.get("liquidity_usd", 0) >= 100000),
    _rule("top1_under_10", "Top holder under 10%", "HOLDER DISTRIBUTION", "", 2.0, False, lambda t: t.get("top1_holder_pct", 100) < 10),
    _rule("top1_under_5", "Top holder under 5%", "HOLDER DISTRIBUTION", "", 2.5, False, lambda t: t.get("top1_holder_pct", 100) < 5),
    _rule("top5_under_30", "Top 5 holders under 30%", "HOLDER DISTRIBUTION", "", 2.0, False, lambda t: t.get("top5_holders_pct", 100) < 30),
    _rule("holder_count_100", "At least 100 holders", "HOLDER DISTRIBUTION", "", 1.5, False, lambda t: t.get("holder_count", 0) >= 100),
    _rule("holder_count_500", "At least 500 holders", "HOLDER DISTRIBUTION", "", 2.0, False, lambda t: t.get("holder_count", 0) >= 500),
    _rule("holder_count_1000", "At least 1000 holders", "HOLDER DISTRIBUTION", "", 2.5, False, lambda t: t.get("holder_count", 0) >= 1000),
    _rule("positive_1h", "Positive price action last 1 hour", "MOMENTUM", "", 1.0, False, lambda t: t.get("price_change_1h", 0) > 0),
    _rule("strong_pump_1h", "Over 50% gain in last hour", "MOMENTUM", "", 1.5, False, lambda t: t.get("price_change_1h", 0) > 50),
    _rule("buyers_dominating", "Buy/Sell ratio above 1.5", "MOMENTUM", "", 1.5, False, lambda t: t.get("buy_count_1h", 0) / max(t.get("sell_count_1h", 1), 1) >= 1.5),
    _rule("strong_buyers", "Buy/Sell ratio above 2.0", "MOMENTUM", "", 2.0, False, lambda t: t.get("buy_count_1h", 0) / max(t.get("sell_count_1h", 1), 1) >= 2.0),
    _rule("volume_active", "1h volume over $5,000", "MOMENTUM", "", 1.0, False, lambda t: t.get("volume_1h", 0) >= 5000),
    _rule("volume_strong", "1h volume over $25,000", "MOMENTUM", "", 1.5, False, lambda t: t.get("volume_1h", 0) >= 25000),
    _rule("under_30min", "Token launched under 30 minutes ago", "TOKEN AGE", "", 2.0, False, lambda t: t.get("token_age_minutes", 999) <= 30),
    _rule("under_1h", "Token launched under 1 hour ago", "TOKEN AGE", "", 1.5, False, lambda t: t.get("token_age_minutes", 999) <= 60),
    _rule("over_1h", "Token survived at least 1 hour", "TOKEN AGE", "", 1.5, False, lambda t: t.get("token_age_minutes", 0) >= 60),
    _rule("over_6h", "Token survived at least 6 hours", "TOKEN AGE", "", 2.0, False, lambda t: t.get("token_age_minutes", 0) >= 360),
    _rule("graduated_pumpfun", "Graduated from Pump.fun to Raydium", "TOKEN AGE", "", 2.5, False, lambda t: t.get("pump_graduated") is True),
    _rule("has_twitter", "Has Twitter/X account", "NARRATIVE AND SOCIALS", "", 1.0, False, lambda t: t.get("has_twitter") is True),
    _rule("has_telegram", "Has Telegram community", "NARRATIVE AND SOCIALS", "", 1.0, False, lambda t: t.get("has_telegram") is True),
    _rule("has_website", "Has website", "NARRATIVE AND SOCIALS", "", 0.5, False, lambda t: t.get("has_website") is True),
    _rule("full_socials", "Has Twitter, Telegram AND website", "NARRATIVE AND SOCIALS", "", 2.0, False, lambda t: all([t.get("has_twitter"), t.get("has_telegram"), t.get("has_website")])),
    _rule("meme_narrative", "Strong meme narrative in name/description", "NARRATIVE AND SOCIALS", "", 1.5, False, lambda t: any(k in ((t.get("name", "") + " " + t.get("description", "")).lower()) for k in ["dog", "cat", "pepe", "frog", "elon", "trump", "inu", "shib", "moon", "rocket", "doge", "baby", "chad", "wojak", "based", "ape", "hamster", "penguin", "panda"])),
    _rule("high_engagement", "Over 100 replies on Pump.fun", "NARRATIVE AND SOCIALS", "", 1.5, False, lambda t: t.get("reply_count", 0) >= 100),
    _rule("micro_cap", "Market cap under $50,000", "MARKET CAP", "", 2.0, False, lambda t: 0 < t.get("market_cap", 999999999) <= 50000),
    _rule("small_cap", "Market cap under $500,000", "MARKET CAP", "", 1.5, False, lambda t: 0 < t.get("market_cap", 999999999) <= 500000),
    _rule("sub_1m", "Market cap under $1,000,000", "MARKET CAP", "", 1.0, False, lambda t: 0 < t.get("market_cap", 999999999) <= 1000000),
    _rule("low_fdv_ratio", "FDV less than 3x market cap", "MARKET CAP", "", 1.5, False, lambda t: t.get("market_cap", 0) > 0 and t.get("fdv", 999999) / t.get("market_cap", 1) < 3),
    _rule("risk_under_30", "Risk score below 30 (Low risk)", "RISK SCORE", "", 2.5, False, lambda t: t.get("risk_score", 100) < 30),
    _rule("risk_under_50", "Risk score below 50 (Medium risk)", "RISK SCORE", "", 1.5, False, lambda t: t.get("risk_score", 100) < 50),
    _rule("moon_over_50", "Moon score above 50", "RISK SCORE", "", 2.0, False, lambda t: t.get("moon_score", 0) > 50),
    _rule("moon_over_70", "Moon score above 70 (High potential)", "RISK SCORE", "", 2.5, False, lambda t: t.get("moon_score", 0) > 70),
]

RULES_BY_ID = {r["id"]: r for r in RULES}
CATEGORIES = sorted({r["category"] for r in RULES})


def get_rule(rule_id: str) -> dict | None:
    return RULES_BY_ID.get(rule_id)


def get_rules_by_category(category: str) -> list[dict]:
    return [r for r in RULES if r["category"] == category]
