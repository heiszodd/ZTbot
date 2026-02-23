import asyncio
import logging

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import db
from config import CHAT_ID, ETHERSCAN_KEY

log = logging.getLogger(__name__)

ETHERSCAN_ENDPOINTS = {
    "eth": "https://api.etherscan.io/api",
    "bsc": "https://api.bscscan.com/api",
    "polygon": "https://api.polygonscan.com/api",
    "base": "https://api.basescan.org/api",
}


async def fetch_evm_transactions(wallet: str, chain: str, contract: str, limit: int = 20) -> list:
    base_url = ETHERSCAN_ENDPOINTS.get(chain.lower(), ETHERSCAN_ENDPOINTS["eth"])
    params = {
        "module": "account",
        "action": "tokentx",
        "address": wallet,
        "contractaddress": contract,
        "sort": "desc",
        "offset": limit,
        "page": 1,
    }
    if ETHERSCAN_KEY:
        params["apikey"] = ETHERSCAN_KEY

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(base_url, params=params)
            response.raise_for_status()
            data = response.json()

        if data.get("status") != "1":
            return []
        return data.get("result") or []
    except Exception as exc:
        log.error("Etherscan fetch error %s/%s: %s", wallet, chain, exc)
        return []


async def fetch_solana_transactions(wallet: str, token_address: str, limit: int = 20) -> list:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://public-api.solscan.io/account/token/txs",
                params={"account": wallet, "token": token_address, "limit": limit, "offset": 0},
            )
            response.raise_for_status()
            data = response.json()
        return data.get("data") or []
    except Exception as exc:
        log.error("Solscan fetch error %s: %s", wallet, exc)
        return []


def classify_evm_tx(tx: dict, wallet: str, contract: str) -> dict | None:
    from_addr = (tx.get("from") or "").lower()
    to_addr = (tx.get("to") or "").lower()
    wallet_l = wallet.lower()

    try:
        value = int(tx.get("value") or "0")
    except Exception:
        value = 0

    try:
        decimals = int(tx.get("tokenDecimal") or "18")
        token_amount = value / (10 ** decimals)
    except Exception:
        token_amount = 0

    if from_addr == wallet_l:
        event_type = "sell"
    elif to_addr == wallet_l:
        event_type = "buy"
    else:
        return None

    return {
        "event_type": event_type,
        "token_amount": token_amount,
        "tx_hash": tx.get("hash") or "",
        "timestamp": int(tx.get("timeStamp") or 0),
    }


async def check_dev_wallet(wallet_record: dict, context) -> list:
    from datetime import datetime, timezone

    wallet = wallet_record["wallet_address"]
    contract = wallet_record["contract_address"]
    chain = wallet_record.get("chain", "eth")

    if chain.lower() in ("solana", "sol"):
        txs = await fetch_solana_transactions(wallet, contract)
        events = _parse_solana_txs(txs, wallet, contract)
    else:
        txs = await fetch_evm_transactions(wallet, chain, contract)
        events = [e for tx in txs for e in [classify_evm_tx(tx, wallet, contract)] if e is not None]

    if not events:
        return []

    last_activity = wallet_record.get("last_activity")
    if isinstance(last_activity, str):
        try:
            last_activity = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
        except Exception:
            last_activity = None
    if isinstance(last_activity, datetime) and last_activity.tzinfo is None:
        last_activity = last_activity.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    new_events = []
    for event in events:
        ts = int(event.get("timestamp") or 0)
        event_dt = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else now
        tx_hash = event.get("tx_hash")
        if tx_hash and db.dev_wallet_event_exists(tx_hash):
            continue
        if last_activity and event_dt <= last_activity:
            continue
        new_events.append({**event, "wallet_address": wallet, "contract_address": contract, "chain": chain, "detected_at": now.isoformat()})

    return new_events


def _parse_solana_txs(txs: list, wallet: str, token: str) -> list:
    events = []
    for tx in txs:
        change = tx.get("changeAmount", 0)
        if change is None:
            continue
        event_type = "buy" if float(change) > 0 else "sell"
        events.append(
            {
                "event_type": event_type,
                "token_amount": abs(float(change)),
                "tx_hash": tx.get("txHash") or "",
                "timestamp": int(tx.get("blockTime") or 0),
            }
        )
    return events


async def send_dev_wallet_alert(context, event: dict, scan: dict) -> None:
    event_type = event["event_type"]
    wallet = event["wallet_address"]
    contract = event["contract_address"]
    amount = float(event.get("token_amount") or 0)
    tx = event.get("tx_hash") or ""
    symbol = (scan or {}).get("token_symbol", "?")

    short_wallet = wallet[:6] + "..." + wallet[-4:]
    short_tx = tx[:10] + "..." if tx else "?"

    if event_type == "sell":
        emoji = "🚨"
        action = "SELLING"
        note = "Dev is selling tokens. This may precede a rug or dump. Consider exiting position."
    else:
        emoji = "👀"
        action = "BUYING"
        note = "Dev is accumulating. Could be bullish — watch price action."

    text = (
        f"{emoji} *Dev Wallet Alert — {symbol}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Action:  {action}\n"
        f"Amount:  {amount:,.2f} {symbol}\n"
        f"Wallet:  `{short_wallet}`\n"
        f"TX:      `{short_tx}`\n\n"
        f"_{note}_"
    )

    await context.bot.send_message(
        chat_id=CHAT_ID,
        text=text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🔍 Re-Scan Contract", callback_data=f"degen:scan:{contract}"),
                    InlineKeyboardButton("🛑 Stop Watching", callback_data=f"degen:unwatch:{wallet}:{contract}"),
                ]
            ]
        ),
    )


async def run_dev_wallet_monitor(context) -> None:
    try:
        await asyncio.wait_for(_run_dev_wallet_monitor_inner(context), timeout=60)
    except asyncio.TimeoutError:
        log.warning("dev_wallet_monitor timed out after 60 seconds")
    except Exception as e:
        log.error(f"dev_wallet_monitor error: {e}")


async def _run_dev_wallet_monitor_inner(context) -> None:
    from datetime import datetime, timezone

    wallets = db.get_watched_dev_wallets()
    if not wallets:
        return

    for wallet_record in wallets:
        try:
            new_events = await check_dev_wallet(wallet_record, context)
            if not new_events:
                continue

            contract = wallet_record["contract_address"]
            chain = wallet_record.get("chain", "eth")
            scan = db.get_contract_scan(contract, chain)

            for event in new_events:
                event_type = event["event_type"]
                if event_type == "sell" and not wallet_record.get("alert_on_sell", True):
                    continue
                if event_type == "buy" and not wallet_record.get("alert_on_buy", True):
                    continue
                await send_dev_wallet_alert(context, event, scan)
                db.save_dev_wallet_event(event)

            db.update_dev_wallet(
                wallet_record["wallet_address"],
                wallet_record["contract_address"],
                {"last_activity": datetime.now(timezone.utc).isoformat()},
            )
        except Exception as exc:
            log.error("Dev wallet monitor error %s: %s", wallet_record.get("wallet_address"), exc)
