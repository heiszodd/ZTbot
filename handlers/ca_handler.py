from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import db
from config import CHAT_ID
from degen.dev_checker import check_dev_network
from degen.moon_engine import analyze_bonding_curve, score_moonshot_potential
from degen.risk_engine import (
    analyze_token_description,
    check_volume_authenticity,
    score_token_risk,
)
from formatters import fmt_ca_report
from prices import fmt_price

log = logging.getLogger(__name__)

SOL_RE = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")
EVM_RE = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
BASE58 = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
COMMON_NON_CA = {"hello", "gm", "moon", "telegram", "pump", "address", "contract", "whitelist"}
_monitor_alerts_sent: dict[str, dict[str, float]] = {}


def _now_ts() -> float:
    return time.time()


def _short(a: str) -> str:
    return f"{a[:8]}...{a[-4:]}" if a else "N/A"


def _is_base58(s: str) -> bool:
    return bool(s) and all(c in BASE58 for c in s)


def _is_known_wallet(address: str) -> bool:
    try:
        wallets = db.get_tracked_wallets(active_only=False)
        return any((w.get("address") or "").lower() == address.lower() for w in wallets)
    except Exception:
        return False


def detect_ca_in_text(text: str) -> dict | None:
    if not text:
        return None
    if "@" in text:
        return None
    for m in EVM_RE.finditer(text):
        a = m.group(0)
        return {"address": a, "chain_guess": "evm", "confidence": "high"}

    for m in SOL_RE.finditer(text):
        a = m.group(0)
        if len(a) >= 64:
            continue
        if a.lower() in COMMON_NON_CA:
            continue
        if not _is_base58(a):
            continue
        if _is_known_wallet(a):
            continue
        conf = "high" if len(a) >= 43 else "medium"
        return {"address": a, "chain_guess": "solana", "confidence": conf}
    return None


async def _http_get_json(url: str, headers: dict | None = None, timeout: float = 8.0) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url, headers=headers)
            if r.status_code >= 400:
                return None
            return r.json()
    except Exception:
        return None


SOLANA_BURN_ADDRESSES = {
    "1nc1nerator11111111111111111111111111111111",
    "So11111111111111111111111111111111111111112",
    "11111111111111111111111111111111",
}


async def fetch_dexscreener_data(address: str) -> dict:
    payload = await _http_get_json(f"https://api.dexscreener.com/latest/dex/tokens/{address}")
    pairs = (payload or {}).get("pairs") or []
    if not pairs:
        payload = await _http_get_json(f"https://api.dexscreener.com/latest/dex/search?q={address}")
        pairs = (payload or {}).get("pairs") or []
    if not pairs:
        return {"not_found": True}
    best = max(pairs, key=lambda p: float(((p or {}).get("liquidity") or {}).get("usd") or 0))
    created_ms = int(best.get("pairCreatedAt") or 0)
    age_min = 0
    if created_ms:
        age_min = max(0, int((time.time() - created_ms / 1000) / 60))
    socials = ((best.get("info") or {}).get("socials") or [])
    social_map = {s.get("type"): s.get("url") for s in socials if s.get("type") and s.get("url")}
    websites = ((best.get("info") or {}).get("websites") or [])
    return {
        "name": ((best.get("baseToken") or {}).get("name")),
        "symbol": ((best.get("baseToken") or {}).get("symbol")),
        "address": ((best.get("baseToken") or {}).get("address")) or address,
        "chain": best.get("chainId") or "unknown",
        "dex": best.get("dexId"),
        "url": best.get("url"),
        "pairAddress": best.get("pairAddress"),
        "price_usd": float(best.get("priceUsd") or 0),
        "price_change_1h": float(((best.get("priceChange") or {}).get("h1") or 0)),
        "price_change_6h": float(((best.get("priceChange") or {}).get("h6") or 0)),
        "price_change_24h": float(((best.get("priceChange") or {}).get("h24") or 0)),
        "volume_1h": float(((best.get("volume") or {}).get("h1") or 0)),
        "volume_6h": float(((best.get("volume") or {}).get("h6") or 0)),
        "volume_24h": float(((best.get("volume") or {}).get("h24") or 0)),
        "liquidity_usd": float(((best.get("liquidity") or {}).get("usd") or 0)),
        "mcap": float(best.get("marketCap") or 0),
        "fdv": float(best.get("fdv") or 0),
        "token_age_minutes": age_min,
        "buys_1h": int((((best.get("txns") or {}).get("h1") or {}).get("buys") or 0)),
        "sells_1h": int((((best.get("txns") or {}).get("h1") or {}).get("sells") or 0)),
        "twitter": social_map.get("twitter"),
        "telegram": social_map.get("telegram"),
        "website": (websites[0].get("url") if websites else None),
    }


async def fetch_rugcheck_data(address: str) -> dict | None:
    payload = await _http_get_json(
        f"https://api.rugcheck.xyz/v1/tokens/{address}/report",
        headers={"accept": "application/json", "User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    if not payload:
        return None
    th = payload.get("topHolders") or []
    markets = payload.get("markets") or [{}]
    lp = (markets[0].get("lp") if markets else {}) or {}
    risks = payload.get("risks") or []

    def _to_pct(raw: float) -> float:
        return raw * 100 if 0 <= raw < 1 else raw

    top5 = sum(_to_pct(float((x or {}).get("pct") or 0)) for x in th[:5])
    top1 = _to_pct(float((th[0] or {}).get("pct") or 0)) if th else 0.0

    raw_score = payload.get("score")
    if raw_score is None:
        norm = payload.get("score_normalised")
        raw_score = int(float(norm) * 1000) if isinstance(norm, (int, float)) else 0

    lp_holders = lp.get("holders") or []
    lp_burned = bool(lp.get("lpBurned"))
    if not lp_burned and lp_holders:
        for holder in lp_holders:
            holder_addr = (holder.get("address") or holder.get("owner") or "").strip()
            if holder_addr in SOLANA_BURN_ADDRESSES:
                lp_burned = True
                break

            pct = _to_pct(float(holder.get("pct") or 0))
            holder_low = holder_addr.lower()
            if pct >= 90 and (
                holder_addr.endswith("pump")
                or "burn" in holder_low
                or "dead" in holder_low
            ):
                lp_burned = True
                break

    log.info(
        "RugCheck parsed %s: score=%s risk_count=%s top1=%s lp_locked=%s",
        _short(address),
        int(raw_score or 0),
        len(risks),
        round(top1, 4),
        float(lp.get("lpLockedPct") or 0),
    )

    return {
        "rugcheck_score": int(raw_score or 0),
        "rugcheck_risks": risks,
        "name": ((payload.get("tokenMeta") or {}).get("name")),
        "symbol": ((payload.get("tokenMeta") or {}).get("symbol")),
        "top_holders": th,
        "top1_holder_pct": float(top1),
        "top5_holders_pct": float(top5),
        "lp_locked_pct": float(lp.get("lpLockedPct") or 0),
        "lp_burned": lp_burned,
        "mint_revoked": payload.get("mintAuthority") is None,
        "freeze_revoked": payload.get("freezeAuthority") is None,
        "dev_wallet": payload.get("creator"),
        "verified": bool(payload.get("verification") or payload.get("verified")),
        "is_honeypot": bool(payload.get("honeypot") or False),
    }


async def fetch_wallet_age_days(wallet_address: str) -> float:
    if not wallet_address:
        return 0.0
    headers = {"accept": "application/json", "User-Agent": "Mozilla/5.0"}
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(
                "https://public-api.solscan.io/account/info",
                params={"account": wallet_address},
                headers=headers,
            )
            if resp.status_code == 429:
                log.warning("Solscan account/info rate limited for %s", wallet_address)
            elif resp.status_code != 200:
                log.warning("Solscan account/info %s for %s", resp.status_code, wallet_address)
            else:
                data = resp.json() or {}
                first_ts = data.get("first_tx_time") or data.get("firstTxTime") or data.get("created_at")
                if isinstance(first_ts, (int, float)) and first_ts > 0:
                    return float(max(0, int((time.time() - float(first_ts)) / 86400)))

            tx_resp = await client.get(
                "https://public-api.solscan.io/account/transactions",
                params={"account": wallet_address, "limit": 50, "offset": 0},
                headers=headers,
            )
            if tx_resp.status_code == 429:
                log.warning("Solscan account/transactions rate limited for %s", wallet_address)
                return 0.0
            if tx_resp.status_code != 200:
                log.warning("Solscan account/transactions %s for %s", tx_resp.status_code, wallet_address)
                return 0.0

            txs = tx_resp.json() or []
            if not isinstance(txs, list) or not txs:
                return 0.0

            oldest_ts = None
            for tx in txs:
                block_time = tx.get("blockTime") or tx.get("block_time") or tx.get("timestamp")
                if isinstance(block_time, (int, float)) and block_time > 0:
                    oldest_ts = block_time if oldest_ts is None else min(oldest_ts, block_time)

            if not oldest_ts:
                return 0.0
            return float(max(0, int((time.time() - float(oldest_ts)) / 86400)))
    except Exception as exc:
        log.warning("fetch_wallet_age_days failed for %s: %s", wallet_address, exc)
        return 0.0


async def fetch_holder_data(address: str) -> dict | None:
    headers = {"accept": "application/json", "User-Agent": "Mozilla/5.0"}
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(
                "https://public-api.solscan.io/token/holders",
                params={"tokenAddress": address, "limit": 1, "offset": 0},
                headers=headers,
            )
            if r.status_code == 429:
                log.warning("Solscan holders rate limited for %s", address)
            elif r.status_code != 200:
                log.warning("Solscan holders %s for %s", r.status_code, address)
            else:
                data = r.json() or {}
                total = data.get("total")
                if total is not None:
                    return {"holder_count": int(total)}
                items = data.get("data") or []
                if items:
                    log.warning("Solscan holders missing total for %s; using item count fallback", address)
                    return {"holder_count": len(items)}

            r2 = await client.get(
                f"https://api-v2.solscan.io/v2/token/holders/total?address={address}",
                headers={
                    "accept": "application/json",
                    "User-Agent": "Mozilla/5.0",
                    "origin": "https://solscan.io",
                    "referer": "https://solscan.io/",
                },
            )
            if r2.status_code != 200:
                log.warning("Solscan v2 holders %s for %s", r2.status_code, address)
                return {"holder_count": 0}
            data2 = r2.json() or {}
            return {"holder_count": int(((data2.get("data") or {}).get("total") or 0))}
    except Exception as exc:
        log.warning("fetch_holder_data failed for %s: %s", address, exc)
        return {"holder_count": 0}


async def fetch_pumpfun_data(address: str) -> dict | None:
    payload = await _http_get_json(f"https://frontend-api.pump.fun/coins/{address}")
    if not payload:
        return None
    vs = float(payload.get("virtual_sol_reserves") or 0)
    vt = float(payload.get("virtual_token_reserves") or 0)
    curve_pct = min(100.0, (vs / max(vs + vt, 1)) * 100)
    return {
        "is_pumpfun": True,
        "name": payload.get("name"),
        "symbol": payload.get("symbol"),
        "description": payload.get("description"),
        "created_timestamp": payload.get("created_timestamp"),
        "twitter": payload.get("twitter"),
        "telegram": payload.get("telegram"),
        "website": payload.get("website"),
        "virtual_sol_reserves": payload.get("virtual_sol_reserves"),
        "virtual_token_reserves": payload.get("virtual_token_reserves"),
        "graduated": bool(payload.get("complete")),
        "reply_count": int(payload.get("reply_count") or 0),
        "market_cap": float(payload.get("market_cap") or 0),
        "curve_pct": curve_pct,
        "pump_url": f"https://pump.fun/{address}",
    }


def _check_dev_reputation(token_data: dict, chain_guess: str) -> dict:
    age = int(token_data.get("dev_wallet_age_days") or 0)
    rugs = int(token_data.get("dev_rug_count") or 0)
    supply = float(token_data.get("top1_holder_pct") or 0)
    label = "UNKNOWN"
    if rugs > 0 or age < 3:
        label = "RISKY"
    elif age > 30 and rugs == 0:
        label = "GOOD"
    return {"reputation_label": label, "past_rugs": rugs, "supply_held_pct": supply}


async def process_ca(update: Update, context: ContextTypes.DEFAULT_TYPE, ca: dict):
    addr = ca["address"]
    await update.message.reply_text(
        f"🔍 Analysing `{addr[:8]}...{addr[-4:]}`\n⏳ Fetching on-chain data — this takes a few seconds...",
        parse_mode="Markdown",
    )

    async def _run(coro):
        try:
            return await asyncio.wait_for(coro, timeout=8)
        except Exception:
            return None

    dex, rug, holders, pump = await asyncio.gather(
        _run(fetch_dexscreener_data(addr)),
        _run(fetch_rugcheck_data(addr)),
        _run(fetch_holder_data(addr)),
        _run(fetch_pumpfun_data(addr)),
        return_exceptions=False,
    )

    token_data = {"address": addr, "chain": ca.get("chain_guess", "unknown")}
    for part in (dex, rug, holders, pump):
        if isinstance(part, dict):
            token_data.update(part)

    dev_wallet = token_data.get("dev_wallet") or ""
    dev_age = 0.0
    if dev_wallet:
        dev_age = await fetch_wallet_age_days(dev_wallet)
        token_data["dev_wallet_age_days"] = dev_age

    if token_data.get("holder_count", 0) == 0 and token_data.get("top_holders"):
        token_data["holder_count"] = len(token_data.get("top_holders") or [])

    log.info(
        "SCAN DEBUG %s holder_count=%s dev_age_days=%s rugcheck_score=%s top_holder_pct=%s liquidity=%s",
        _short(addr),
        int(token_data.get("holder_count") or 0),
        token_data.get("dev_wallet_age_days", 0),
        int(token_data.get("rugcheck_score") or 0),
        float(token_data.get("top1_holder_pct") or 0),
        float(token_data.get("liquidity_usd") or 0),
    )

    if token_data.get("not_found"):
        token_data["dex_note"] = "not found on DEX — may be too new or invalid CA"

    risk = score_token_risk(token_data)
    moon = score_moonshot_potential(token_data, risk.get("profile"))
    dev = _check_dev_reputation(token_data, ca["chain_guess"])
    curve = analyze_bonding_curve(token_data)
    auth = check_volume_authenticity(token_data, token_data.get("recent_txs", []))
    nlp = analyze_token_description(token_data.get("name", ""), token_data.get("description", ""))
    net = check_dev_network(token_data.get("dev_wallet", ""), ca["chain_guess"])

    token_data.update(risk)
    token_data.update(moon)
    token_data["chain_guess"] = ca.get("chain_guess")

    try:
        db.upsert_degen_token_snapshot(token_data)
    except Exception as e:
        log.warning("Failed to save token snapshot: %s", e)

    cache = context.user_data.setdefault("last_ca_report", {})
    cache[addr] = {
        "ts": _now_ts(),
        "token_data": token_data,
        "risk": risk,
        "moon": moon,
        "dev": dev,
        "curve": curve,
        "auth": auth,
        "nlp": nlp,
        "net": net,
    }

    report = fmt_ca_report(token_data, risk, moon, dev, curve, auth, nlp, net)
    kb = _build_ca_actions(token_data, risk)
    await update.message.reply_text(report, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=kb)


async def handle_ca_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("in_conversation"):
        return
    if not update.message or not update.message.text:
        return
    if update.message.text.startswith("/"):
        return
    ca = detect_ca_in_text(update.message.text)
    if not ca:
        return
    await process_ca(update, context, ca)


def _build_ca_actions(token_data: dict, risk: dict) -> InlineKeyboardMarkup:
    addr = token_data.get("address")
    honeypot = bool(token_data.get("is_honeypot"))
    risk_level = str(risk.get("risk_level") or "").upper()
    if honeypot:
        rows = [
            [InlineKeyboardButton("💀 HONEYPOT — DO NOT ENTER", callback_data="ca:noop")],
            [InlineKeyboardButton("🔄 Refresh Data", callback_data=f"ca:refresh:{addr}"), InlineKeyboardButton("🎰 Degen Home", callback_data="nav:degen_home")],
        ]
    elif risk_level in {"CONFIRMED", "EXTREME", "HIGH"}:
        rows = [
            [InlineKeyboardButton("⚠️ High Risk — Whitelist Anyway", callback_data=f"ca:whitelist:{addr}"), InlineKeyboardButton("🎮 Demo Ape In", callback_data=f"ca:demo:{addr}")],
            [InlineKeyboardButton("🔄 Refresh Data", callback_data=f"ca:refresh:{addr}"), InlineKeyboardButton("🎰 Degen Home", callback_data="nav:degen_home")],
        ]
    else:
        rows = [
            [InlineKeyboardButton("⭐ Whitelist — Monitor Live", callback_data=f"ca:whitelist:{addr}"), InlineKeyboardButton("🎮 Demo Ape In", callback_data=f"ca:demo:{addr}")],
            [InlineKeyboardButton("🔄 Refresh Data", callback_data=f"ca:refresh:{addr}"), InlineKeyboardButton("📋 Copy Address", callback_data=f"ca:copy:{addr}")],
            [InlineKeyboardButton("🎰 Degen Home", callback_data="nav:degen_home")],
        ]
    return InlineKeyboardMarkup(rows)


async def _load_report(context: ContextTypes.DEFAULT_TYPE, address: str) -> dict | None:
    cached = (context.user_data.get("last_ca_report") or {}).get(address)
    if cached and (_now_ts() - float(cached.get("ts") or 0) < 300):
        return cached
    return None


async def handle_ca_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "ca:noop":
        return
    parts = data.split(":")
    action = parts[1]
    target = parts[2] if len(parts) > 2 else ""
    if action == "copy":
        await q.message.reply_text(f"📋 `{target}`", parse_mode="Markdown")
    elif action == "whitelist":
        payload = await _load_report(context, target)
        if not payload:
            return await q.message.reply_text("Report cache expired. Tap Refresh Data first.")
        td = payload["token_data"]
        db.add_ca_monitor(td)
        db.add_degen_watchlist(td)
        await q.message.reply_text(
            "⭐ *Whitelisted — Now Monitoring*\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 {td.get('name') or td.get('symbol') or 'Token'} ({td.get('symbol') or '?'})\n"
            f"📋 `{td.get('address')}`\n\n"
            f"📈 Price moves ±5% from current ({fmt_price(td.get('price_usd') or 0)})\n"
            "👥 Holder count changes significantly\n⚠️ Risk score worsens\n💀 Rug signals detected\n📊 Volume spikes or dies",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔕 Stop Monitoring", callback_data=f"ca:stop:{target}"), InlineKeyboardButton("🎮 Demo Ape In", callback_data=f"ca:demo:{target}")], [InlineKeyboardButton("🎰 Degen Home", callback_data="nav:degen_home")]]),
        )
    elif action == "stop":
        db.remove_ca_monitor(target)
        await q.message.reply_text("🔕 Monitoring stopped for this contract.")
    elif action in {"refresh", "report"}:
        ca = {"address": target, "chain_guess": "unknown", "confidence": "high"}
        fake = type("_U", (), {"message": q.message})
        await process_ca(fake, context, ca)
    elif action == "demo":
        payload = await _load_report(context, target)
        if not payload:
            return await q.message.reply_text("Report cache expired. Refresh and try again.")
        acct = db.get_demo_account("degen")
        if not acct:
            return await q.message.reply_text("No DEGEN demo account found. Run /demo_degen first.")
        bal = float(acct.get("balance") or 0)
        risk_label = payload["risk"].get("risk_level")
        moon = payload["moon"].get("moon_score")
        t = payload["token_data"]
        context.user_data["ca_demo"] = {"address": target, "balance": bal, "payload": payload}
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("0.1%", callback_data="ca:alloc:0.1"), InlineKeyboardButton("0.25%", callback_data="ca:alloc:0.25"), InlineKeyboardButton("0.5%", callback_data="ca:alloc:0.5")],
            [InlineKeyboardButton("1%", callback_data="ca:alloc:1"), InlineKeyboardButton("2%", callback_data="ca:alloc:2"), InlineKeyboardButton("✏️ Custom", callback_data="ca:alloc:custom")],
            [InlineKeyboardButton("❌ Cancel", callback_data="ca:noop")],
        ])
        await q.message.reply_text(
            f"🎮 *Demo Ape In*\n━━━━━━━━━━━━━━━━━━━━━━━━\n🪙 {t.get('name') or '?'} ({t.get('symbol') or '?'})\n"
            f"💰 Demo Balance:   ${bal:,.2f}\n📊 Risk Level:     {risk_label}\n🚀 Moon Score:     {moon}/100\n\nChoose your allocation:",
            parse_mode="Markdown",
            reply_markup=kb,
        )
    elif action == "alloc":
        if target == "custom":
            return await q.message.reply_text("Custom not supported in callbacks yet. Use preset allocation.")
        state = context.user_data.get("ca_demo") or {}
        payload = (state or {}).get("payload")
        if not payload:
            return await q.message.reply_text("Session expired.")
        pct = float(target)
        bal = float(state.get("balance") or 0)
        amount = bal * pct / 100
        td = payload["token_data"]
        exits = payload["moon"].get("smart_exits") or {}
        tokens = amount / max(float(td.get("price_usd") or 0.0000001), 0.0000001)
        context.user_data["ca_demo_confirm"] = {"amount": amount, "tokens": tokens, "payload": payload}
        await q.message.reply_text(
            f"🎮 *Confirm Demo Entry*\n━━━━━━━━━━━━━━━━━━━━━━━━\n🪙 {td.get('name')} ({td.get('symbol')})\n"
            f"💰 Allocation:   ${amount:,.2f} ({pct}% of demo)\n"
            f"📈 Entry:        {fmt_price(td.get('price_usd') or 0)}\n"
            f"🛑 SL:           {fmt_price(exits.get('sl') or 0)}\n"
            f"🎯 TP1:          {fmt_price(exits.get('tp1') or 0)}\n"
            f"🎯 TP2:          {fmt_price(exits.get('tp2') or 0)}\n"
            f"🎯 TP3:          {fmt_price(exits.get('tp3') or 0)}\n"
            f"Tokens you'll receive: {tokens:,.2f} {td.get('symbol')}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm Ape In", callback_data="ca:ape:confirm"), InlineKeyboardButton("❌ Cancel", callback_data="ca:noop")]]),
        )
    elif action == "ape":
        state = context.user_data.get("ca_demo_confirm") or {}
        payload = state.get("payload")
        if not payload:
            return await q.message.reply_text("Session expired.")
        td = payload["token_data"]
        exits = payload["moon"].get("smart_exits") or {}
        amount = float(state.get("amount") or 0)
        tid = db.open_demo_trade({
            "section": "degen", "pair": td.get("address")[:20], "token_symbol": td.get("symbol"), "direction": "BUY",
            "entry_price": float(td.get("price_usd") or 0), "sl": float(exits.get("sl") or 0), "tp1": float(exits.get("tp1") or 0), "tp2": float(exits.get("tp2") or 0), "tp3": float(exits.get("tp3") or 0),
            "position_size_usd": amount, "risk_amount_usd": amount, "risk_pct": 0.0, "model_id": "ca", "model_name": "CA Report", "tier": "A", "score": payload["moon"].get("moon_score"), "source": "ca_report", "notes": json.dumps({"address": td.get("address")}),
        })
        db.link_ca_monitor_trade(td.get("address"), tid)
        await q.message.reply_text(
            f"🎮 *Demo Position Opened*\n━━━━━━━━━━━━━━━━━━━━━━━━\n🪙 {td.get('name')} ({td.get('symbol')})\n"
            f"📈 Entry:   {fmt_price(td.get('price_usd') or 0)}\n💰 Size:    ${amount:,.2f}\n🆔 Trade:   #{tid}\n\nMonitoring your position live.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📊 View Position", callback_data=f"ca:position:{tid}"), InlineKeyboardButton("💸 Sell Now", callback_data=f"ca:sell:{tid}")], [InlineKeyboardButton("🎰 Degen Home", callback_data="nav:degen_home")]]),
        )
    elif action == "position":
        await _send_position_card(q.message.reply_text, int(target))
    elif action == "sell":
        await _send_sell_confirm(q.message.reply_text, int(target))
    elif action == "sell_confirm":
        tr = db.get_demo_trade_by_id(int(target))
        if not tr:
            return
        current = await fetch_dexscreener_data(json.loads(tr.get("notes") or "{}").get("address", ""))
        price = float((current or {}).get("price_usd") or tr.get("current_price") or tr.get("entry_price") or 0)
        closed = db.close_demo_trade(int(target), price, "MANUAL")
        await q.message.reply_text(f"✅ *Position Closed*\n━━━━━━━━━━━━━━━━━━━━━━━━\n🪙 {tr.get('token_symbol')}\n💹 Exit: {fmt_price(price)}\n💰 PnL: {closed.get('final_pnl_usd',0):+.2f}", parse_mode="Markdown")
    elif action == "sell50":
        db.partial_close_demo_trade(int(target), 0.5)
        await q.message.reply_text("✅ 50% sold. Remaining position SL moved to breakeven.")
    elif action == "ride":
        await q.message.reply_text("🚀 Keep riding acknowledged.")
    elif action == "time_extend":
        db.extend_demo_trade_time_stop(int(target), 30)
        await q.message.reply_text("⏳ Time stop extended by 30 minutes.")


async def _send_sell_confirm(sender, trade_id: int):
    tr = db.get_demo_trade_by_id(trade_id)
    if not tr:
        return
    current = float(tr.get("current_price") or tr.get("entry_price") or 0)
    await sender(
        f"💸 *Sell Demo Position*\n━━━━━━━━━━━━━━━━━━━━━━━━\n🪙 {tr.get('token_symbol')}\n📈 Entry: {fmt_price(tr.get('entry_price') or 0)}\n💹 Current: {fmt_price(current)}\n"
        f"💰 PnL: {float(tr.get('current_pnl_usd') or 0):+.2f} ({float(tr.get('current_pnl_pct') or 0):+.2f}%)\n\nConfirm sell at {fmt_price(current)}?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes — Sell All", callback_data=f"ca:sell_confirm:{trade_id}"), InlineKeyboardButton("💸 Sell 50%", callback_data=f"ca:sell50:{trade_id}")], [InlineKeyboardButton("❌ Cancel", callback_data="ca:noop")]]),
    )


async def _send_position_card(sender, trade_id: int):
    tr = db.get_demo_trade_by_id(trade_id)
    if not tr:
        return
    await sender(
        f"📊 *Live Position*\n━━━━━━━━━━━━━━━━━━━━━━━━\n🎮 Demo Trade #{trade_id}\n🪙 {tr.get('token_symbol')}\n"
        f"💹 Entry: {fmt_price(tr.get('entry_price') or 0)}\nCurrent: {fmt_price(tr.get('current_price') or 0)}\nChange: {float(tr.get('current_pnl_pct') or 0):+.2f}%\n"
        f"💰 PnL: {float(tr.get('current_pnl_usd') or 0):+.2f}\n",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💸 Sell All", callback_data=f"ca:sell:{trade_id}"), InlineKeyboardButton("💸 Sell 50%", callback_data=f"ca:sell50:{trade_id}")],
            [InlineKeyboardButton("🔄 Refresh", callback_data=f"ca:position:{trade_id}"), InlineKeyboardButton("📋 Full Report", callback_data=f"ca:report:{json.loads(tr.get('notes') or '{}').get('address','')}")],
            [InlineKeyboardButton("🎰 Degen Home", callback_data="nav:degen_home")],
        ])
    )


async def ca_monitor_job(context: ContextTypes.DEFAULT_TYPE):
    monitors = db.get_active_ca_monitors()
    for m in monitors:
        try:
            current = await fetch_dexscreener_data(m["address"])
            if not current or current.get("not_found"):
                continue
            current_price = float(current.get("price_usd") or 0)
            current_holders = int(current.get("holder_count") or 0)
            price_change = abs((current_price - float(m.get("price_at_add") or 0)) / max(float(m.get("price_at_add") or 0.000001), 0.000001)) * 100
            alerts = []
            if price_change >= float(m.get("price_alert_pct") or 5):
                direction = "📈 UP" if current_price > float(m.get("price_at_add") or 0) else "📉 DOWN"
                alerts.append(("price", f"💰 *Price Alert — {m.get('symbol') or '?'}*\n{direction} {price_change:.1f}%\nThen: {fmt_price(m.get('price_at_add') or 0)}\nNow: {fmt_price(current_price)}"))
            if m.get("initial_holders") and current_holders:
                hp = (current_holders - int(m.get("initial_holders") or 1)) / max(int(m.get("initial_holders") or 1), 1) * 100
                if hp > 50:
                    alerts.append(("holders_up", f"👥 *Holder Surge — {m.get('symbol')}*\n{m.get('initial_holders')} → {current_holders}"))
                elif hp < -20:
                    alerts.append(("holders_down", f"👥 *Holders Leaving — {m.get('symbol')}*\n{m.get('initial_holders')} → {current_holders}"))
            token_data_fresh = {**m, **current}
            new_risk = score_token_risk(token_data_fresh)
            if int(new_risk.get("risk_score") or 0) > int(m.get("initial_risk") or 0) + 15:
                alerts.append(("risk", f"⚠️ *Risk Increasing — {m.get('symbol')}*\n{m.get('initial_risk')} → {new_risk.get('risk_score')}"))
            if float(current.get("volume_1h") or 0) < float(current.get("volume_24h") or 1) / 24 * 0.1:
                alerts.append(("volume", f"📉 *Volume Dying — {m.get('symbol')}*\n1h volume < 10% daily avg."))

            for typ, text in alerts:
                now = _now_ts()
                sent = _monitor_alerts_sent.setdefault(m["address"], {})
                if now - float(sent.get(typ) or 0) < 1800:
                    continue
                sent[typ] = now
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("📲 Live Trade", callback_data=f"degen:live:{m['address']}"), InlineKeyboardButton("🎮 Demo Trade", callback_data=f"degen:demo:{m['address']}")], [InlineKeyboardButton("📊 View Report", callback_data=f"ca:report:{m['address']}"), InlineKeyboardButton("🔕 Stop Monitoring", callback_data=f"ca:stop:{m['address']}")]])
                await context.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown", reply_markup=kb)
            db.update_ca_monitor_check(m["address"], current_price, current_holders)
        except Exception as e:
            log.error("CA monitor error for %s: %s", m.get("address"), e)
