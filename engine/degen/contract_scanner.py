import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx

import db
from config import DEXSCREENER_BASE, GOPLUSLABS_BASE, HONEYPOT_BASE

log = logging.getLogger(__name__)

CHAIN_ID_MAP = {
    "eth": "1",
    "ethereum": "1",
    "bsc": "56",
    "bnb": "56",
    "polygon": "137",
    "matic": "137",
    "base": "8453",
    "solana": "solana",
    "sol": "solana",
}


def detect_chain(address: str) -> str:
    if address.startswith("0x") and len(address) == 42:
        return "eth"
    if len(address) in range(32, 45) and not address.startswith("0x"):
        return "solana"
    return "eth"


async def fetch_goplus_data(address: str, chain: str) -> dict:
    chain_id = CHAIN_ID_MAP.get((chain or "eth").lower(), "1")
    url = f"{GOPLUSLABS_BASE}/token_security/{chain_id}"
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(url, params={"contract_addresses": address})
            response.raise_for_status()
            data = response.json()

        result = data.get("result", {}) or {}
        token_data = result.get(address.lower(), {}) or result.get(address, {})
        if not token_data:
            log.warning("GoPlus returned no token data for %s on %s", address, chain)
        return token_data or {}
    except Exception as exc:
        log.error("GoPlus error %s/%s: %s", chain, address, exc)
        return {}


async def fetch_dexscreener_data(address: str) -> dict:
    url = f"{DEXSCREENER_BASE}/dex/tokens/{address}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        pairs = data.get("pairs") or []
        if not pairs:
            return {"liquidity_usd": 0, "volume_24h": 0, "price_usd": 0, "market_cap": 0}

        pairs.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0, reverse=True)
        best = pairs[0]

        pair_created = None
        if best.get("pairCreatedAt"):
            try:
                pair_created = datetime.fromtimestamp(best["pairCreatedAt"] / 1000, tz=timezone.utc).isoformat()
            except Exception:
                pair_created = None

        return {
            "price_usd": float(best.get("priceUsd") or 0),
            "liquidity_usd": float((best.get("liquidity") or {}).get("usd") or 0),
            "volume_24h": float((best.get("volume") or {}).get("h24") or 0),
            "market_cap": float(best.get("marketCap") or 0),
            "fdv": float(best.get("fdv") or 0),
            "dex_name": best.get("dexId") or "",
            "pair_address": best.get("pairAddress") or "",
            "pair_created_at": pair_created,
            "price_change_24h": float((best.get("priceChange") or {}).get("h24") or 0),
        }
    except Exception as exc:
        log.error("DexScreener error %s: %s", address, exc)
        return {"liquidity_usd": 0, "volume_24h": 0, "price_usd": 0, "market_cap": 0}


async def fetch_honeypot_data(address: str, chain: str = "eth") -> dict:
    chain_ids = {"eth": "1", "bsc": "56", "polygon": "137", "base": "8453"}
    chain_key = (chain or "eth").lower()
    if chain_key in ("solana", "sol"):
        return {"is_honeypot": False, "honeypot_reason": "Solana — honeypot check skipped"}

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(
                f"{HONEYPOT_BASE}/IsHoneypot",
                params={"address": address, "chainID": chain_ids.get(chain_key, "1")},
            )
            response.raise_for_status()
            data = response.json()

        honeypot_result = data.get("honeypotResult") or {}
        sim = data.get("simulationResult") or {}
        return {
            "is_honeypot": bool(honeypot_result.get("isHoneypot", False)),
            "honeypot_reason": honeypot_result.get("honeypotReason") or "",
            "buy_tax": float(sim.get("buyTax") or 0),
            "sell_tax": float(sim.get("sellTax") or 0),
            "buy_gas": float(sim.get("buyGas") or 0),
            "sell_gas": float(sim.get("sellGas") or 0),
        }
    except Exception as exc:
        log.error("Honeypot check error %s/%s: %s", chain, address, exc)
        return {"is_honeypot": False, "honeypot_reason": f"Honeypot check failed: {exc}"}


def calculate_rug_score(scan: dict) -> dict:
    score = 0
    flags = []
    passed = []

    if scan.get("is_honeypot"):
        flags.append("🚨 HONEYPOT — cannot sell")
    else:
        score += 25
        passed.append("No honeypot detected")

    buy_tax = float(scan.get("buy_tax", 0) or 0)
    sell_tax = float(scan.get("sell_tax", 0) or 0)
    if sell_tax > 10:
        flags.append(f"🚨 Sell tax {sell_tax:.1f}% — likely rug or trap")
    elif sell_tax > 5:
        score += 5
        flags.append(f"⚠️ High sell tax: {sell_tax:.1f}%")
    else:
        score += 15
        passed.append(f"Tax OK: buy {buy_tax:.1f}% / sell {sell_tax:.1f}%")

    danger_powers = 0
    if scan.get("mint_enabled"):
        danger_powers += 1
        flags.append("⚠️ Mint enabled — devs can print")
    if scan.get("owner_can_blacklist"):
        danger_powers += 1
        flags.append("⚠️ Owner can blacklist wallets")
    if scan.get("transfer_pausable"):
        danger_powers += 1
        flags.append("⚠️ Transfers can be paused")

    if danger_powers == 0:
        score += 15
        passed.append("No dangerous owner powers")
    elif danger_powers == 1:
        score += 8

    top10 = float(scan.get("top10_holder_pct", 100) or 100)
    dev_pct = float(scan.get("dev_holding_pct", 0) or 0)
    holders = int(scan.get("holder_count", 0) or 0)

    if dev_pct > 20:
        flags.append(f"🚨 Dev holds {dev_pct:.1f}% of supply")
    elif dev_pct > 10:
        flags.append(f"⚠️ Dev holds {dev_pct:.1f}% of supply")

    if top10 > 80:
        flags.append(f"🚨 Top 10 holders own {top10:.1f}%")
    elif top10 > 60:
        score += 8
        flags.append(f"⚠️ Top 10 holders own {top10:.1f}%")
    else:
        score += 20
        passed.append(f"Good distribution: top 10 = {top10:.1f}%")

    if holders > 500:
        passed.append(f"{holders:,} holders")
    elif holders > 100:
        flags.append(f"⚠️ Only {holders} holders")
    else:
        flags.append(f"🚨 Very few holders: {holders}")

    lp_locked = float(scan.get("lp_locked_pct", 0) or 0)
    if lp_locked >= 80:
        score += 15
        passed.append(f"LP locked: {lp_locked:.0f}%")
    elif lp_locked >= 50:
        score += 8
        flags.append(f"⚠️ LP partially locked: {lp_locked:.0f}%")
    else:
        flags.append(f"🚨 LP NOT locked ({lp_locked:.0f}%) — can rug anytime")

    liq = float(scan.get("liquidity_usd", 0) or 0)
    if liq >= 100000:
        score += 10
        passed.append(f"Liquidity: ${liq:,.0f}")
    elif liq >= 50000:
        score += 6
        flags.append(f"⚠️ Low liquidity: ${liq:,.0f}")
    elif liq >= 10000:
        score += 3
        flags.append(f"⚠️ Very low liquidity: ${liq:,.0f}")
    else:
        flags.append(f"🚨 Dangerously low liquidity: ${liq:,.0f}")

    score = round(min(max(score, 0), 100), 1)

    if scan.get("is_honeypot"):
        grade = "F"
    elif score >= 85:
        grade = "A"
    elif score >= 70:
        grade = "B"
    elif score >= 55:
        grade = "C"
    elif score >= 40:
        grade = "D"
    else:
        grade = "F"

    grade_emoji = {"A": "✅", "B": "👍", "C": "⚠️", "D": "🔴", "F": "💀"}.get(grade, "⚠️")
    return {"score": score, "grade": grade, "grade_emoji": grade_emoji, "flags": flags, "passed": passed}


def format_scan_result(scan: dict) -> str:
    grade = scan.get("rug_grade", "?")
    score = scan.get("rug_score", 0)
    grade_emoji = {"A": "✅", "B": "👍", "C": "⚠️", "D": "🔴", "F": "💀"}.get(grade, "⚠️")
    symbol = scan.get("token_symbol", "?")
    name = scan.get("token_name", "Unknown")
    chain = scan.get("chain", "?").upper()

    text = (
        f"🔍 *Contract Scan — {symbol}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Token:  {name} ({symbol})\n"
        f"Chain:  {chain}\n\n"
        f"{grade_emoji} *Safety Grade: {grade}*  ({score}/100)\n\n"
    )

    flags = scan.get("safety_flags", [])
    if flags:
        text += "*⚠️ Flags*\n"
        for flag in flags:
            text += f"{flag}\n"
        text += "\n"

    passed = scan.get("passed_checks", [])
    if passed:
        text += "*✅ Passed*\n"
        for item in passed:
            text += f"✅ {item}\n"
        text += "\n"

    liq = float(scan.get("liquidity_usd", 0) or 0)
    vol = float(scan.get("volume_24h", 0) or 0)
    mcap = float(scan.get("market_cap", 0) or 0)
    buy_t = float(scan.get("buy_tax", 0) or 0)
    sell_t = float(scan.get("sell_tax", 0) or 0)
    top10 = float(scan.get("top10_holder_pct", 0) or 0)
    dev_pct = float(scan.get("dev_holding_pct", 0) or 0)

    text += (
        f"*Market Data*\n"
        f"Liquidity: ${liq:>12,.0f}\n"
        f"Volume 24h:${vol:>12,.0f}\n"
        f"Market cap:${mcap:>12,.0f}\n"
        f"Tax:        buy {buy_t:.1f}% / sell {sell_t:.1f}%\n"
        f"Top 10:     {top10:.1f}% of supply\n"
        f"Dev holds:  {dev_pct:.1f}% of supply\n"
        f"LP locked:  {float(scan.get('lp_locked_pct',0) or 0):.0f}%\n"
        f"Holders:    {int(scan.get('holder_count',0) or 0):,}\n"
    )

    dev = scan.get("dev_wallet") or ""
    if dev:
        text += f"Dev wallet: `{dev[:6]}...{dev[-4:]}`\n"

    return text


def calculate_degen_position(
    account_size: float,
    max_position_pct: float,
    rug_score: float,
    early_score: float,
    social_velocity: float = 0,
) -> dict:
    base = float(account_size or 0) * float(max_position_pct or 0) / 100

    if rug_score >= 85:
        grade = "A"
    elif rug_score >= 70:
        grade = "B"
    elif rug_score >= 55:
        grade = "C"
    elif rug_score >= 40:
        grade = "D"
    else:
        grade = "F"

    rug_mult = {"A": 1.0, "B": 1.0, "C": 0.5, "D": 0.25, "F": 0.0}.get(grade, 0)
    early_mult = 1.1 if early_score >= 75 else 1.0 if early_score >= 35 else 0.75
    social_mult = 1.05 if social_velocity >= 50 else 1.0
    final_size = round(base * rug_mult * early_mult * social_mult, 2)

    return {
        "base_size": round(base, 2),
        "final_size": final_size,
        "rug_grade": grade,
        "rug_mult": rug_mult,
        "early_mult": early_mult,
        "blocked": grade == "F" or final_size <= 0,
        "note": "Full size" if rug_mult == 1.0 else f"Reduced ({int(rug_mult * 100)}%) due to {grade} safety grade",
    }


async def scan_contract(address: str, chain: str | None = None, force_refresh: bool = False) -> dict:
    if not chain:
        chain = detect_chain(address)

    if not force_refresh:
        cached = db.get_contract_scan(address, chain)
        if cached:
            scanned_at = cached.get("scanned_at")
            if isinstance(scanned_at, str):
                try:
                    scanned_at = datetime.fromisoformat(scanned_at.replace("Z", "+00:00"))
                except Exception:
                    scanned_at = None
            if isinstance(scanned_at, datetime):
                if scanned_at.tzinfo is None:
                    scanned_at = scanned_at.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - scanned_at < timedelta(hours=1):
                    return cached

    goplus_task = fetch_goplus_data(address, chain)
    dex_task = fetch_dexscreener_data(address)
    honeypot_task = fetch_honeypot_data(address, chain)
    goplus, dex, honeypot = await asyncio.gather(goplus_task, dex_task, honeypot_task, return_exceptions=True)

    goplus = {} if isinstance(goplus, Exception) else (goplus or {})
    dex = {} if isinstance(dex, Exception) else (dex or {})
    honeypot = {} if isinstance(honeypot, Exception) else (honeypot or {})

    def gp_bool(key: str) -> bool:
        return str(goplus.get(key, "0")) == "1"

    def gp_float(key: str, default: float = 0.0) -> float:
        try:
            return float(goplus.get(key, default) or 0)
        except Exception:
            return default

    holders = goplus.get("holders") or []
    top10_pct = sum(float(h.get("percent", 0) or 0) for h in holders[:10]) * 100 if holders else 0

    lp_holders = goplus.get("lp_holders") or []
    lp_locked = (
        sum(float(h.get("percent", 0) or 0) for h in lp_holders if h.get("is_locked") in (1, "1", True)) * 100
        if lp_holders
        else 0
    )

    dev_wallet = goplus.get("creator_address") or goplus.get("owner_address") or ""
    dev_holding = 0.0
    if dev_wallet and holders:
        dev_holding = (
            sum(float(h.get("percent", 0) or 0) for h in holders if (h.get("address") or "").lower() == dev_wallet.lower())
            * 100
        )

    buy_tax = float(honeypot.get("buy_tax") or gp_float("buy_tax"))
    sell_tax = float(honeypot.get("sell_tax") or gp_float("sell_tax"))
    is_honeypot = bool(honeypot.get("is_honeypot") or gp_bool("is_honeypot"))

    scan = {
        "contract_address": address,
        "chain": chain,
        "token_name": goplus.get("token_name") or "Unknown",
        "token_symbol": goplus.get("token_symbol") or "?",
        "is_honeypot": is_honeypot,
        "honeypot_reason": honeypot.get("honeypot_reason") or "",
        "mint_enabled": gp_bool("is_mintable"),
        "owner_can_blacklist": gp_bool("is_blacklisted"),
        "owner_can_whitelist": gp_bool("is_whitelisted"),
        "is_proxy": gp_bool("is_proxy"),
        "is_open_source": gp_bool("is_open_source"),
        "trading_cooldown": gp_bool("trading_cooldown"),
        "transfer_pausable": gp_bool("transfer_pausable"),
        "buy_tax": round(buy_tax, 2),
        "sell_tax": round(sell_tax, 2),
        "holder_count": int(goplus.get("holder_count", 0) or 0),
        "top10_holder_pct": round(top10_pct, 2),
        "dev_wallet": dev_wallet,
        "dev_holding_pct": round(dev_holding, 2),
        "lp_holder_count": len(lp_holders),
        "lp_locked_pct": round(lp_locked, 2),
        "liquidity_usd": float(dex.get("liquidity_usd", 0) or 0),
        "volume_24h": float(dex.get("volume_24h", 0) or 0),
        "price_usd": float(dex.get("price_usd", 0) or 0),
        "market_cap": float(dex.get("market_cap", 0) or 0),
        "pair_created_at": dex.get("pair_created_at"),
        "dex_name": dex.get("dex_name") or "",
        "raw_goplus": goplus,
    }

    rug_result = calculate_rug_score(scan)
    scan["rug_score"] = rug_result["score"]
    scan["rug_grade"] = rug_result["grade"]
    scan["safety_flags"] = rug_result["flags"]
    scan["passed_checks"] = rug_result["passed"]

    db.save_contract_scan(scan)

    if dev_wallet:
        db.save_dev_wallet(
            {
                "contract_address": address,
                "chain": chain,
                "wallet_address": dev_wallet,
                "label": "deployer",
                "watching": True,
            }
        )

    return scan
