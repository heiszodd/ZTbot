import logging
from datetime import datetime, timezone

import httpx

import db

log = logging.getLogger(__name__)
SEEN_MINTS = set()


async def run_trenches_scanner(context):
    settings = db.get_user_settings(int(__import__('config').CHAT_ID))
    found = []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://frontend-api.pump.fun/coins",
                params={"limit": 20, "offset": 0, "sort": "created_timestamp", "order": "DESC", "includeNsfw": "false"},
            )
        if r.status_code != 200:
            return []
        items = r.json() if isinstance(r.json(), list) else []
        now = datetime.now(timezone.utc).timestamp()
        for token in items:
            mint = token.get("mint")
            if not mint or mint in SEEN_MINTS:
                continue
            SEEN_MINTS.add(mint)
            age = int(now - (float(token.get("created_timestamp") or now) / 1000))
            mc = float(token.get("usd_market_cap") or token.get("market_cap") or 0)
            if not (10000 <= mc <= 500000 and 60 <= age <= 3600):
                continue
            
            found.append({
                "address": mint,
                "symbol": token.get("symbol"),
                "mcap": mc,
                "age": age
            })

            if settings.get("trenches_alerts"):
                db.log_audit(action="trenches_token", details={"mint": mint, "symbol": token.get("symbol"), "mcap": mc}, success=True)
        return found
    except Exception as exc:
        log.error("trenches scanner failed: %s", exc)
        return []
