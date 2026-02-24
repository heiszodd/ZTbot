import logging
from datetime import datetime, timezone

from engine.hyperliquid.client import (
    get_account_state,
    get_all_mids,
    get_funding_history,
    get_open_orders,
    get_user_fills,
)

log = logging.getLogger(__name__)


async def fetch_account_summary(address: str) -> dict:
    state = await get_account_state(address)
    if not state:
        return {}

    margin = state.get("marginSummary", {})
    account_value = float(margin.get("accountValue", 0) or 0)
    total_margin = float(margin.get("totalMarginUsed", 0) or 0)
    total_ntl = float(margin.get("totalNtlPos", 0) or 0)
    available_margin = float(state.get("withdrawable", 0) or 0)

    positions = []
    total_upnl = 0.0
    for ap in state.get("assetPositions", []):
        pos = ap.get("position", {})
        if not pos:
            continue
        szi = float(pos.get("szi", 0) or 0)
        if szi == 0:
            continue

        margin_used = float(pos.get("marginUsed", 0) or 0)
        upnl = float(pos.get("unrealizedPnl", 0) or 0)
        roe = float(pos.get("returnOnEquity", 0) or 0)
        total_upnl += upnl

        lev = pos.get("leverage", {})
        liq_px = pos.get("liquidationPx")
        positions.append(
            {
                "coin": pos.get("coin", ""),
                "side": "Long" if szi > 0 else "Short",
                "size": abs(szi),
                "size_usd": float(pos.get("positionValue", 0) or 0),
                "entry_price": float(pos.get("entryPx", 0) or 0),
                "margin_used": margin_used,
                "leverage": float(lev.get("value", 1) or 1),
                "lev_type": lev.get("type", "cross"),
                "upnl": round(upnl, 2),
                "upnl_pct": round((upnl / margin_used * 100) if margin_used > 0 else 0, 2),
                "roe_pct": round(roe * 100, 2),
                "liq_price": float(liq_px) if liq_px else None,
                "pos_value": float(pos.get("positionValue", 0) or 0),
            }
        )

    positions.sort(key=lambda x: abs(x["size_usd"]), reverse=True)
    total_pnl_pct = (total_upnl / account_value * 100) if account_value > 0 else 0

    return {
        "address": address,
        "account_value": round(account_value, 2),
        "total_margin": round(total_margin, 2),
        "available": round(available_margin, 2),
        "total_ntl": round(total_ntl, 2),
        "total_upnl": round(total_upnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "positions": positions,
        "position_count": len(positions),
        "margin_ratio": round(total_margin / account_value * 100 if account_value > 0 else 0, 1),
    }


async def fetch_positions_with_prices(address: str) -> list:
    summary = await fetch_account_summary(address)
    if not summary:
        return []

    mids = await get_all_mids()
    positions = summary.get("positions", [])
    for pos in positions:
        mark_price = float(mids.get(pos["coin"], 0) or 0)
        if mark_price > 0:
            entry = float(pos.get("entry_price", 0) or 0)
            size = float(pos.get("size", 0) or 0)
            margin = float(pos.get("margin_used", 0) or 0)
            live_upnl = (mark_price - entry) * size if pos["side"] == "Long" else (entry - mark_price) * size
            pos["mark_price"] = mark_price
            pos["live_upnl"] = round(live_upnl, 2)
            pos["live_upnl_pct"] = round((live_upnl / margin * 100) if margin > 0 else 0, 2)
        else:
            pos["mark_price"] = pos.get("entry_price", 0)
            pos["live_upnl"] = pos.get("upnl", 0)
            pos["live_upnl_pct"] = pos.get("upnl_pct", 0)
    return positions


async def fetch_trade_history(address: str, limit: int = 50) -> list:
    fills = await get_user_fills(address)
    if not fills:
        return []

    trades = []
    for f in fills[:limit]:
        try:
            ts_ms = int(f.get("time", 0) or 0)
            ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc) if ts_ms else None
            cpnl = float(f.get("closedPnl", 0) or 0)
            fee = float(f.get("fee", 0) or 0)
            trades.append(
                {
                    "coin": f.get("coin", ""),
                    "side": "Long" if f.get("side") == "B" else "Short",
                    "size": float(f.get("sz", 0) or 0),
                    "price": float(f.get("px", 0) or 0),
                    "size_usd": round(float(f.get("sz", 0) or 0) * float(f.get("px", 0) or 0), 2),
                    "fee": round(fee, 4),
                    "closed_pnl": round(cpnl, 2),
                    "net_pnl": round(cpnl - fee, 2),
                    "timestamp": ts,
                    "order_id": str(f.get("oid", "")),
                    "is_close": cpnl != 0,
                }
            )
        except Exception as e:
            log.debug("Fill parse error: %s", e)
    return trades


async def fetch_open_orders_parsed(address: str) -> list:
    orders = await get_open_orders(address)
    parsed = []
    for o in orders:
        try:
            price = float(o.get("limitPx", 0) or 0)
            size = float(o.get("sz", 0) or 0)
            parsed.append(
                {
                    "coin": o.get("coin", ""),
                    "side": "Buy" if o.get("side") == "B" else "Sell",
                    "price": price,
                    "size": size,
                    "size_usd": round(price * size, 2),
                    "order_id": str(o.get("oid", "")),
                    "order_type": o.get("orderType", "Limit"),
                    "reduce_only": o.get("reduceOnly", False),
                    "tif": o.get("tif", "Gtc"),
                }
            )
        except Exception as e:
            log.debug("Order parse error: %s", e)
    return parsed


async def fetch_funding_summary(address: str) -> dict:
    history = await get_funding_history(address)
    if not history:
        return {"total": 0, "by_coin": {}}

    total = 0.0
    by_coin = {}
    entries = []
    for entry in history:
        try:
            payment = float(entry.get("usdc", 0) or 0)
            coin = entry.get("coin", "")
            rate = float(entry.get("fundingRate", 0) or 0)
            ts = int(entry.get("time", 0) or 0)
            total += payment
            by_coin[coin] = by_coin.get(coin, 0) + payment
            entries.append({"coin": coin, "payment": payment, "rate": rate, "time": ts})
        except Exception:
            continue

    by_coin_sorted = dict(sorted(by_coin.items(), key=lambda x: abs(x[1]), reverse=True))
    entries.sort(key=lambda x: x["time"], reverse=True)
    return {"total": round(total, 4), "by_coin": by_coin_sorted, "history": entries}
