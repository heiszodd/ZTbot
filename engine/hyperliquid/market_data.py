import logging

from engine.hyperliquid.client import get_all_mids, get_l2_book, get_meta

log = logging.getLogger(__name__)


async def fetch_all_markets() -> list:
    meta = await get_meta()
    mids = await get_all_mids()
    if not meta:
        return []
    universe = meta.get("universe", [])
    asset_ctxs = meta.get("assetCtxs", [])
    markets = []
    for i, m in enumerate(universe):
        coin = m.get("name", "")
        ctx = asset_ctxs[i] if i < len(asset_ctxs) else {}
        markets.append(
            {
                "coin": coin,
                "price": float(mids.get(coin, 0) or 0),
                "sz_decimals": m.get("szDecimals", 5),
                "max_leverage": m.get("maxLeverage", 50),
                "only_isolated": m.get("onlyIsolated", False),
                "funding_rate": float(ctx.get("funding", 0) or 0),
                "day_volume": float(ctx.get("dayNtlVlm", 0) or 0),
                "open_interest": float(ctx.get("openInterest", 0) or 0),
            }
        )
    return sorted(markets, key=lambda x: x["coin"])


async def get_market_price(coin: str) -> float:
    mids = await get_all_mids()
    return float(mids.get(coin, 0) or 0)


async def get_order_book_summary(coin: str) -> dict:
    book = await get_l2_book(coin)
    if not book:
        return {}
    levels = book.get("levels", [[], []])
    bids = levels[0] if len(levels) > 0 else []
    asks = levels[1] if len(levels) > 1 else []
    if not bids or not asks:
        return {}
    try:
        best_bid = float(bids[0].get("px", 0))
        best_ask = float(asks[0].get("px", 0))
        spread = best_ask - best_bid
        spread_pct = (spread / best_bid * 100) if best_bid > 0 else 0
        bid_depth = sum(float(b.get("sz", 0)) for b in bids[:5])
        ask_depth = sum(float(a.get("sz", 0)) for a in asks[:5])
        return {
            "coin": coin,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid": (best_bid + best_ask) / 2,
            "spread": round(spread, 4),
            "spread_pct": round(spread_pct, 4),
            "bid_depth": round(bid_depth, 4),
            "ask_depth": round(ask_depth, 4),
            "imbalance": round((bid_depth / (bid_depth + ask_depth) * 100) if (bid_depth + ask_depth) > 0 else 50, 1),
        }
    except Exception as e:
        log.error("Order book parse %s: %s", coin, e)
        return {}


async def get_funding_rates() -> dict:
    meta = await get_meta()
    if not meta:
        return {}
    universe = meta.get("universe", [])
    asset_ctxs = meta.get("assetCtxs", [])
    rates = {}
    for i, ctx in enumerate(asset_ctxs):
        if i >= len(universe):
            break
        rates[universe[i].get("name", "")] = float(ctx.get("funding", 0) or 0)
    return rates
