import httpx
import logging
from config import POLYMARKET_CLOB, POLYMARKET_GAMMA

log = logging.getLogger(__name__)


async def fetch_markets(limit: int = 50, active: bool = True, category: str = None) -> list:
    try:
        params = {"limit": limit, "active": str(active).lower(), "closed": "false", "archived": "false"}
        if category:
            params["category"] = category
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.get(f"{POLYMARKET_GAMMA}/markets", params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.error(f"Polymarket markets fetch: {e}")
        return []

    markets = []
    items = data if isinstance(data, list) else data.get("markets", [])
    for m in items:
        try:
            tokens = m.get("tokens", [])
            yes_price = 0.0
            no_price = 0.0
            for t in tokens:
                outcome = str(t.get("outcome", "")).lower()
                price = float(t.get("price", 0) or 0)
                if outcome == "yes":
                    yes_price = price
                elif outcome == "no":
                    no_price = price
            if yes_price == 0:
                yes_price = float(m.get("outcomePrices", ["0", "0"])[0] if m.get("outcomePrices") else 0)
            if no_price == 0:
                no_price = float(m.get("outcomePrices", ["0", "0"])[1] if m.get("outcomePrices") and len(m.get("outcomePrices", [])) > 1 else 0)
            markets.append(
                {
                    "market_id": m.get("conditionId", m.get("id", "")),
                    "question": m.get("question", ""),
                    "category": m.get("category", ""),
                    "yes_price": round(yes_price, 4),
                    "no_price": round(no_price, 4),
                    "yes_pct": round(yes_price * 100, 1),
                    "volume_24h": float(m.get("volume24hr", 0) or 0),
                    "total_volume": float(m.get("volume", 0) or 0),
                    "liquidity": float(m.get("liquidity", 0) or 0),
                    "end_date": m.get("endDate", ""),
                    "active": m.get("active", True),
                    "closed": m.get("closed", False),
                }
            )
        except Exception as e:
            log.debug(f"Market parse error: {e}")
    return markets


async def fetch_market_by_id(market_id: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{POLYMARKET_GAMMA}/markets/{market_id}")
            if r.status_code == 404:
                return {}
            r.raise_for_status()
            return r.json()
    except Exception as e:
        log.error(f"Polymarket market fetch {market_id}: {e}")
        return {}


async def fetch_price_history(market_id: str, resolution: str = "1h", limit: int = 48) -> list:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                f"{POLYMARKET_CLOB}/prices-history",
                params={"market": market_id, "resolution": resolution, "limit": limit, "fidelity": resolution},
            )
            r.raise_for_status()
            data = r.json()
        return data.get("history", [])
    except Exception as e:
        log.debug(f"Price history {market_id}: {e}")
        return []
