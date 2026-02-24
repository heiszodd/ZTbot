import asyncio
import logging
import os

import httpx

import db

log = logging.getLogger(__name__)


async def _run_once(context):
    api_key = os.getenv("HELIUS_API_KEY", "").strip()
    if not api_key:
        log.warning("HELIUS_API_KEY not set; wallet tracker skipped")
        return

    wallets = db.get_tracked_wallets(active_only=True)[:10]
    async with httpx.AsyncClient(timeout=10) as client:
        for wallet in wallets:
            addr = wallet.get("address")
            if not addr:
                continue
            url = f"https://api.helius.xyz/v0/addresses/{addr}/transactions"
            r = await client.get(url, params={"api-key": api_key, "limit": 10})
            if r.status_code != 200:
                continue
            txs = r.json() if isinstance(r.json(), list) else []
            if not txs:
                continue
            latest = txs[0].get("signature")
            if latest and latest != wallet.get("last_tx_hash"):
                db.update_tracked_wallet_tx(wallet["id"], latest)
                db.log_audit(action="wallet_tracker_new_tx", details={"wallet": addr, "tx": latest}, success=True)


async def run_wallet_tracker(context):
    try:
        await asyncio.wait_for(_run_once(context), timeout=30)
    except asyncio.TimeoutError:
        db.log_audit(action="wallet_tracker_timeout", details={}, success=False, error="timeout")
    except Exception as exc:
        log.error("wallet tracker failed: %s", exc)
