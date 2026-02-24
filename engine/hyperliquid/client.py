import logging

import httpx

from config import HL_INFO_URL

log = logging.getLogger(__name__)


async def hl_info(payload: dict, timeout: float = 10.0) -> dict | list | None:
    """Core Hyperliquid info API call. Returns JSON or None."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(
                HL_INFO_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            if r.status_code == 429:
                log.warning("Hyperliquid rate limited")
                return None
            if r.status_code == 422:
                log.warning(
                    "Hyperliquid invalid request: %s — %s",
                    payload.get("type"),
                    r.text[:200],
                )
                return None
            r.raise_for_status()
            return r.json()
    except httpx.TimeoutException:
        log.error("Hyperliquid timeout: %s", payload.get("type"))
        return None
    except Exception as e:
        log.error(
            "Hyperliquid API error %s: %s: %s",
            payload.get("type"),
            type(e).__name__,
            e,
        )
        return None


async def get_all_mids() -> dict:
    result = await hl_info({"type": "allMids"})
    if not result or not isinstance(result, dict):
        return {}
    return result


async def get_meta() -> dict:
    result = await hl_info({"type": "meta"})
    if not result or not isinstance(result, dict):
        return {}
    return result


async def get_account_state(address: str) -> dict:
    if not address:
        return {}
    result = await hl_info({"type": "clearinghouseState", "user": address})
    return result if isinstance(result, dict) else {}


async def get_open_orders(address: str) -> list:
    if not address:
        return []
    result = await hl_info({"type": "openOrders", "user": address})
    return result if isinstance(result, list) else []


async def get_user_fills(address: str) -> list:
    if not address:
        return []
    result = await hl_info({"type": "userFills", "user": address})
    return result if isinstance(result, list) else []


async def get_funding_history(address: str, start_time: int = None) -> list:
    if not address:
        return []
    import time

    payload = {
        "type": "userFundingHistory",
        "user": address,
        "startTime": start_time or int((time.time() - 7 * 86400) * 1000),
    }
    result = await hl_info(payload)
    return result if isinstance(result, list) else []


async def get_order_status(address: str, oid: int | str) -> dict:
    if not address or oid in (None, ""):
        return {}
    result = await hl_info({"type": "orderStatus", "user": address, "oid": int(oid)})
    return result if isinstance(result, dict) else {}


async def get_l2_book(coin: str) -> dict:
    result = await hl_info({"type": "l2Book", "coin": coin})
    return result if isinstance(result, dict) else {}


async def get_candles(coin: str, interval: str, start_time: int, end_time: int = None) -> list:
    import time as time_mod

    payload = {
        "type": "candles",
        "req": {
            "coin": coin,
            "interval": interval,
            "startTime": start_time,
            "endTime": end_time or int(time_mod.time() * 1000),
        },
    }
    result = await hl_info(payload)
    return result if isinstance(result, list) else []
