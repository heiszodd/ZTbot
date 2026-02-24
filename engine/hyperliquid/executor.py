import asyncio
import logging
import time

from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

log = logging.getLogger(__name__)


async def get_hl_exchange() -> Exchange:
    from security.key_manager import get_private_key

    try:
        private_key = get_private_key("hl_api_wallet")
    except ValueError as e:
        raise RuntimeError(f"Hyperliquid API wallet not configured: {e}\nUse /addkey to store hl_api_wallet")

    account = Account.from_key(private_key)
    return Exchange(account, constants.MAINNET_API_URL, account_address=account.address)


async def place_limit_order(plan: dict) -> dict:
    try:
        exchange = await asyncio.wait_for(get_hl_exchange(), timeout=10)
    except asyncio.TimeoutError:
        return {"success": False, "error": "Timeout getting HL exchange"}
    except RuntimeError as e:
        return {"success": False, "error": str(e)}

    coin = plan["coin"]
    is_buy = plan["side"] == "Long"
    price = plan["entry_price"]
    size = plan["size_coins"]
    leverage = int(plan.get("leverage", 5))

    try:
        exchange.update_leverage(leverage=leverage, name=coin, is_cross=True)
    except Exception as e:
        log.warning("HL leverage set failed %s: %s", coin, e)

    try:
        order_type = {"limit": {"tif": "Alo" if plan.get("post_only", True) else "Gtc"}}
        result = exchange.order(
            name=coin,
            is_buy=is_buy,
            sz=size,
            limit_px=price,
            order_type=order_type,
            reduce_only=plan.get("reduce_only", False),
        )
    except Exception as e:
        return {"success": False, "error": f"Order failed: {type(e).__name__}: {str(e)[:200]}"}

    if result.get("status") == "err":
        return {"success": False, "error": str(result.get("response", "Unknown HL error"))}

    try:
        status = result["response"]["data"]["statuses"][0]
        order_id = status.get("resting", {}).get("oid", "") or status.get("filled", {}).get("oid", "")
    except Exception:
        order_id = ""

    tx_id = str(order_id) or str(int(time.time()))

    sl_result = await _place_sl_order(exchange, coin, is_buy, float(plan.get("stop_loss", 0) or 0), size)
    for tp_key, sell_pct in [("tp1", 0.40), ("tp2", 0.40), ("tp3", 0.20)]:
        tp_price = float(plan.get(tp_key, 0) or 0)
        if tp_price:
            await _place_tp_order(exchange, coin, is_buy, tp_price, round(size * sell_pct, 5))

    return {"success": True, "tx_id": tx_id, "order_id": order_id, "result": result, "sl_placed": sl_result.get("success", False)}


async def _place_sl_order(exchange, coin: str, entry_is_buy: bool, sl_price: float, size: float) -> dict:
    if sl_price <= 0:
        return {"success": False}
    try:
        result = exchange.order(
            name=coin,
            is_buy=not entry_is_buy,
            sz=size,
            limit_px=sl_price,
            order_type={"trigger": {"triggerPx": sl_price, "isMarket": True, "tpsl": "sl"}},
            reduce_only=True,
        )
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _place_tp_order(exchange, coin: str, entry_is_buy: bool, tp_price: float, size: float) -> dict:
    if tp_price <= 0 or size <= 0:
        return {"success": False}
    try:
        result = exchange.order(
            name=coin,
            is_buy=not entry_is_buy,
            sz=size,
            limit_px=tp_price,
            order_type={"trigger": {"triggerPx": tp_price, "isMarket": False, "tpsl": "tp"}},
            reduce_only=True,
        )
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def cancel_order(coin: str, order_id: int) -> dict:
    try:
        exchange = await get_hl_exchange()
        return {"success": True, "result": exchange.cancel(coin, order_id)}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def close_position(coin: str, size: float, is_long: bool, pct: float = 100.0) -> dict:
    try:
        exchange = await get_hl_exchange()
        close_size = round(size * pct / 100, 5)
        result = exchange.market_close(name=coin, sz=close_size if pct < 100 else None)
        return {"success": True, "result": result, "tx_id": str(int(time.time()))}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def update_leverage(coin: str, leverage: int, is_cross: bool = True) -> dict:
    try:
        exchange = await get_hl_exchange()
        return {"success": True, "result": exchange.update_leverage(leverage=leverage, name=coin, is_cross=is_cross)}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def set_trailing_stop(coin: str, size: float, is_long: bool, trail_pct: float) -> dict:
    try:
        exchange = await get_hl_exchange()
        result = exchange.order(
            name=coin,
            is_buy=not is_long,
            sz=size,
            limit_px=0,
            order_type={"trigger": {"isMarket": True, "tpsl": "sl", "triggerPx": 0, "trailingPct": trail_pct}},
            reduce_only=True,
        )
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}
