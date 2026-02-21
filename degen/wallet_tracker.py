from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import db
import moon_engine
import risk_engine
from config import CHAT_ID, HELIUS_API_KEY, ETHERSCAN_KEY, BSCSCAN_KEY, WAT

log = logging.getLogger(__name__)

SOLSCAN_TX_URL = "https://api.solscan.io/account/transactions?account={address}&limit={limit}"
SOLSCAN_TOKEN_URL = "https://api.solscan.io/account/tokens?account={address}"
SOLSCAN_ACCOUNT_URL = "https://api.solscan.io/account?account={address}"
HELIUS_TX_URL = "https://api.helius.xyz/v0/addresses/{address}/transactions?api-key={api_key}&limit={limit}"
DEXSCREENER_URL = "https://api.dexscreener.com/latest/dex/tokens/{token}"
ETHERSCAN_TX_URL = "https://api.etherscan.io/api?module=account&action=tokentx&address={address}&sort=desc&apikey={api_key}"
BSCSCAN_TX_URL = "https://api.bscscan.com/api?module=account&action=tokentx&address={address}&sort=desc&apikey={api_key}"


def _safe_get(url: str) -> dict[str, Any]:
    try:
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, dict) else {"data": data}
    except Exception as exc:
        log.warning("wallet api failed url=%s err=%s", url, exc)
        return {}


def _parse_ts(value: Any) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    try:
        iv = int(value)
        if iv > 10_000_000_000:
            iv = iv // 1000
        return datetime.fromtimestamp(iv, tz=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def classify_transaction_type(tx: dict) -> str:
    tx_type = str(tx.get("txType") or tx.get("type") or "").lower()
    if tx_type in {"swap", "buy"}:
        return "buy"
    if tx_type == "sell":
        return "sell"
    direction = str(tx.get("direction") or "").lower()
    if direction in {"in", "receive", "received"}:
        return "buy"
    if direction in {"out", "send", "sent"}:
        return "sell"
    if tx_type in {"transfer", "spl-transfer", "token transfer"}:
        return "transfer"
    return "unknown"


def _normalize_tx(raw: dict, chain: str, wallet_address: str) -> dict:
    token = raw.get("tokenAddress") or raw.get("mint") or raw.get("contractAddress") or ""
    amount_token = float(raw.get("tokenAmount") or raw.get("amount") or raw.get("tokenDecimal") or 0)
    amount_usd = float(raw.get("valueUsd") or raw.get("amountUsd") or raw.get("value") or 0)
    if raw.get("tokenDecimal") and raw.get("value"):
        try:
            amount_token = float(raw.get("value", 0)) / (10 ** int(raw.get("tokenDecimal", 0)))
        except Exception:
            pass
    price = amount_usd / amount_token if amount_token else float(raw.get("price") or 0)
    return {
        "tx_hash": raw.get("txHash") or raw.get("signature") or raw.get("hash") or "",
        "timestamp": _parse_ts(raw.get("blockTime") or raw.get("timestamp") or raw.get("timeStamp")),
        "type": classify_transaction_type(raw),
        "token_address": token,
        "token_name": raw.get("tokenName") or raw.get("token_name") or raw.get("symbol") or "Unknown",
        "token_symbol": raw.get("tokenSymbol") or raw.get("symbol") or "UNK",
        "amount_token": amount_token,
        "amount_usd": amount_usd,
        "price_per_token": price,
        "chain": chain,
        "wallet_address": wallet_address,
    }


def get_recent_transactions(wallet_address: str, chain: str, limit: int = 10) -> list[dict]:
    chain_key = chain.upper()
    txs: list[dict] = []
    if chain_key == "SOL":
        primary = _safe_get(SOLSCAN_TX_URL.format(address=wallet_address, limit=limit))
        rows = primary.get("data") or []
        if not rows and HELIUS_API_KEY:
            helius = _safe_get(HELIUS_TX_URL.format(address=wallet_address, api_key=HELIUS_API_KEY, limit=limit))
            rows = helius if isinstance(helius, list) else helius.get("data") or []
        txs = [_normalize_tx(x, "SOL", wallet_address) for x in rows[:limit]]
    elif chain_key in {"ETH", "BASE"} and ETHERSCAN_KEY:
        rows = (_safe_get(ETHERSCAN_TX_URL.format(address=wallet_address, api_key=ETHERSCAN_KEY)).get("result") or [])[:limit]
        txs = [_normalize_tx(x, chain_key, wallet_address) for x in rows]
    elif chain_key == "BSC" and BSCSCAN_KEY:
        rows = (_safe_get(BSCSCAN_TX_URL.format(address=wallet_address, api_key=BSCSCAN_KEY)).get("result") or [])[:limit]
        txs = [_normalize_tx(x, "BSC", wallet_address) for x in rows]
    txs.sort(key=lambda x: x["timestamp"], reverse=True)
    return txs


def detect_new_transactions(wallet: dict, last_seen_tx: str) -> list[dict]:
    rows = get_recent_transactions(wallet["address"], wallet["chain"], limit=10)
    if not last_seen_tx:
        return rows[:1]
    out = []
    for tx in rows:
        if tx["tx_hash"] == last_seen_tx:
            break
        out.append(tx)
    return out


def get_wallet_portfolio(wallet_address: str, chain: str) -> list[dict]:
    chain_key = chain.upper()
    if chain_key != "SOL":
        return []
    payload = _safe_get(SOLSCAN_TOKEN_URL.format(address=wallet_address))
    rows = payload.get("data") or []
    out = []
    for row in rows:
        bal = float(row.get("tokenAmount", {}).get("uiAmount") or row.get("amount") or 0)
        price = float(row.get("tokenAmount", {}).get("priceUsdt") or 0)
        out.append({
            "symbol": row.get("tokenSymbol") or "UNK",
            "address": row.get("tokenAddress") or row.get("token_address") or "",
            "balance": bal,
            "value_usd": bal * price,
        })
    return sorted(out, key=lambda x: x["value_usd"], reverse=True)


def get_wallet_pnl_estimate(wallet_address: str, chain: str) -> dict:
    txs = get_recent_transactions(wallet_address, chain, limit=100)
    buys = sum(x["amount_usd"] for x in txs if x["type"] == "buy")
    sells = sum(x["amount_usd"] for x in txs if x["type"] == "sell")
    wins = sum(1 for x in txs if x["type"] == "sell" and x["amount_usd"] > 0)
    total_sells = max(sum(1 for x in txs if x["type"] == "sell"), 1)
    return {
        "total_buys_usd": round(buys, 2),
        "total_sells_usd": round(sells, 2),
        "estimated_pnl": round(sells - buys, 2),
        "win_rate_estimate": round((wins / total_sells) * 100, 2),
    }


def score_whale_reputation(wallet_address: str, chain: str) -> dict:
    txs = get_recent_transactions(wallet_address, chain, limit=100)
    portfolio = get_wallet_portfolio(wallet_address, chain)
    pnl = get_wallet_pnl_estimate(wallet_address, chain)
    total_value = sum(x.get("value_usd", 0) for x in portfolio)
    tx_count = len(txs)
    now = datetime.now(timezone.utc)
    oldest = min((t["timestamp"] for t in txs), default=now)
    age_days = max((now - oldest).days, 0)

    if age_days < 7:
        credibility, age_label = "LOW", "🆕 Very new wallet"
    elif age_days < 30:
        credibility, age_label = "MEDIUM", "📅 Less than 1 month old"
    elif age_days >= 90:
        credibility, age_label = "HIGH", "🏛️ Established wallet"
    else:
        credibility, age_label = "MEDIUM", "📅 Growing wallet"

    if total_value > 1_000_000:
        size_label = "🐋 Whale"
    elif total_value > 100_000:
        size_label = "🦈 Shark"
    elif total_value > 10_000:
        size_label = "🐬 Dolphin"
    else:
        size_label = "🐟 Small fish"

    wr = pnl["win_rate_estimate"]
    tier, tier_label = "UNKNOWN", "🔍 Unclassified"
    if size_label == "🐋 Whale" and credibility == "HIGH" and wr > 65:
        tier, tier_label = "ALPHA", "🔥 Alpha Whale"
    elif size_label in {"🐋 Whale", "🦈 Shark"}:
        tier, tier_label = "WHALE", "🐋 Whale"
    elif size_label == "🐬 Dolphin" and wr > 60:
        tier, tier_label = "SMART", "🧠 Smart Money"
    elif wr > 75:
        tier, tier_label = "DEGEN_GOD", "👑 Degen God"

    summary = f"{tier_label} | {age_label} | {size_label} | WR ~{wr:.1f}%"
    return {
        "address": wallet_address,
        "chain": chain,
        "age_days": age_days,
        "tx_count": tx_count,
        "tier": tier,
        "tier_label": tier_label,
        "credibility": credibility,
        "estimated_win_rate": wr,
        "portfolio_size_label": size_label,
        "total_value_usd": round(total_value, 2),
        "top_holdings": portfolio[:5],
        "summary": summary,
    }


def get_token_market_data(token_address: str) -> dict:
    payload = _safe_get(DEXSCREENER_URL.format(token=token_address))
    pairs = payload.get("pairs") or []
    if not pairs:
        return {}
    p = pairs[0]
    return {
        "price_usd": float(p.get("priceUsd") or 0),
        "mcap": float((p.get("fdv") or p.get("marketCap") or 0)),
        "liquidity": float((p.get("liquidity") or {}).get("usd") or 0),
        "age_minutes": int((p.get("pairCreatedAt") or 0) / 60000) if p.get("pairCreatedAt") else 0,
        "url": p.get("url") or "",
    }


def _fmt_short_address(address: str) -> str:
    return f"{address[:6]}...{address[-4:]}" if address and len(address) > 12 else address


async def _send_buy_alert(bot, wallet: dict, tx: dict, intel: dict, risk: dict, moon: dict):
    wt = tx["timestamp"].astimezone(WAT).strftime("%H:%M")
    msg = (
        "🐋 WHALE ACTIVITY DETECTED\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{wallet.get('tier_label','🔍 Unclassified')} {wallet.get('label') or _fmt_short_address(wallet['address'])}\n"
        f"📋 {_fmt_short_address(wallet['address'])}\n"
        f"🔗 {wallet['chain']}   ⏰ {wt} WAT\n\n"
        "💰 BOUGHT\n"
        f"   Token:    {tx['token_name']} ({tx['token_symbol']})\n"
        f"   Amount:   {tx['amount_token']:.4f} tokens\n"
        f"   Value:    ${tx['amount_usd']:,.2f}\n"
        f"   Price:    ${tx['price_per_token']:.8f}\n\n"
        "📊 Token Intel\n"
        f"   Market Cap:  ${intel.get('mcap',0):,.0f}\n"
        f"   Liquidity:   ${intel.get('liquidity',0):,.0f}\n"
        f"   Age:         {intel.get('age_minutes',0)} min\n"
        f"   Risk Score:  {risk.get('risk_score',0)}/100   {risk.get('risk_level','N/A')}\n"
        f"   Moon Score:  {moon.get('moon_score',0)}/100   {moon.get('label','N/A')}\n\n"
        f"🔗 {intel.get('url') or 'https://dexscreener.com'}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Copy this trade?"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Copy Trade", callback_data=f"wallet:copy:{tx['tx_hash']}"), InlineKeyboardButton("🎮 Demo Copy", callback_data=f"wallet:demo_copy:{tx['tx_hash']}")],[InlineKeyboardButton("👀 Watch Token", callback_data=f"wallet:watch:{tx['token_address']}"), InlineKeyboardButton("❌ Ignore", callback_data="wallet:dismiss")],
        [InlineKeyboardButton("🔍 Full Token Report", callback_data=f"wallet:token:{tx['token_address']}"), InlineKeyboardButton("👤 Wallet History", callback_data=f"wallet:history:{wallet['id']}")],
    ])
    await bot.send_message(chat_id=CHAT_ID, text=msg, reply_markup=kb)


async def _send_sell_alert(bot, wallet: dict, tx: dict):
    wt = tx["timestamp"].astimezone(WAT).strftime("%H:%M")
    msg = (
        "🔴 WHALE SELLING\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{wallet.get('tier_label','🔍 Unclassified')} {wallet.get('label') or _fmt_short_address(wallet['address'])}\n"
        f"📋 {_fmt_short_address(wallet['address'])}\n\n"
        f"📤 SOLD {tx['token_name']} ({tx['token_symbol']})\n"
        f"   Amount: {tx['amount_token']:.4f} tokens\n"
        f"   Value:  ${tx['amount_usd']:,.2f}\n"
        f"   Chain:  {wallet['chain']}   ⏰ {wt} WAT\n\n"
        "⚠️ If you hold this token, consider reviewing your position."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Check Token", callback_data=f"wallet:token:{tx['token_address']}"), InlineKeyboardButton("👤 Wallet History", callback_data=f"wallet:history:{wallet['id']}")],
        [InlineKeyboardButton("❌ Dismiss", callback_data="wallet:dismiss")],
    ])
    await bot.send_message(chat_id=CHAT_ID, text=msg, reply_markup=kb)


async def wallet_monitor_job(context):
    wallets = db.get_tracked_wallets(active_only=True)
    if not wallets:
        return
    cursor = int(context.application.bot_data.get("wallet_monitor_cursor", 0))
    selected = wallets[cursor:cursor + 20]
    if len(selected) < 20:
        selected += wallets[: max(0, 20 - len(selected))]
    context.application.bot_data["wallet_monitor_cursor"] = (cursor + 20) % max(len(wallets), 1)

    for wallet in selected:
        try:
            new_txs = detect_new_transactions(wallet, wallet.get("last_tx_hash") or "")
            for tx in reversed(new_txs):
                if tx["type"] == "buy" and wallet.get("alert_on_buy", True) and tx["amount_usd"] >= float(wallet.get("alert_min_usd") or 0):
                    intel = get_token_market_data(tx["token_address"])
                    token_payload = {"address": tx["token_address"], "symbol": tx["token_symbol"], "price_usd": intel.get("price_usd", tx["price_per_token"]), "liquidity_usd": intel.get("liquidity", 0), "mcap": intel.get("mcap", 0)}
                    risk = risk_engine.score_token_risk(token_payload)
                    moon = moon_engine.score_moonshot_potential(token_payload)
                    wallet_tx_id = db.log_wallet_transaction({
                        "wallet_id": wallet["id"], "wallet_address": wallet["address"], "tx_hash": tx["tx_hash"], "chain": wallet["chain"], "tx_type": tx["type"],
                        "token_address": tx["token_address"], "token_name": tx["token_name"], "token_symbol": tx["token_symbol"], "amount_token": tx["amount_token"],
                        "amount_usd": tx["amount_usd"], "price_per_token": tx["price_per_token"], "token_risk_score": risk.get("risk_score", 0), "token_moon_score": moon.get("moon_score", 0),
                        "token_risk_level": risk.get("risk_level", "UNKNOWN"), "tx_timestamp": tx["timestamp"], "alert_sent": True,
                    })
                    context.application.bot_data[f"wallet_tx:{tx['tx_hash']}"] = {"wallet_tx_id": wallet_tx_id, "wallet_id": wallet["id"], "tx": tx}
                    await _send_buy_alert(context.application.bot, wallet, tx, intel, risk, moon)
                elif tx["type"] == "sell" and wallet.get("alert_on_sell", True):
                    await _send_sell_alert(context.application.bot, wallet, tx)
                db.update_wallet_last_tx(wallet["id"], tx["tx_hash"])
        except Exception as exc:
            log.exception("wallet monitor failed wallet=%s err=%s", wallet.get("address"), exc)
            continue
