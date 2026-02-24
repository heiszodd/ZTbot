import asyncio
import logging

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs

log = logging.getLogger(__name__)
POLY_HOST = "https://clob.polymarket.com"
POLY_CHAIN_ID = 137


async def get_poly_client() -> ClobClient:
    from security.key_manager import get_private_key
    from security.key_utils import eth_account_from_privkey

    try:
        wallet = get_private_key("poly_hot_wallet")
        api_key = get_private_key("poly_api_key")
        api_secret = get_private_key("poly_api_secret")
        api_passphrase = get_private_key("poly_api_passphrase")
    except ValueError as e:
        raise RuntimeError(f"Polymarket keys not configured: {e}")

    account = eth_account_from_privkey(wallet)
    return ClobClient(
        host=POLY_HOST,
        chain_id=POLY_CHAIN_ID,
        key=(account.key.hex() if str(account.key.hex()).startswith("0x") else f"0x{account.key.hex()}"),
        creds={"apiKey": api_key, "apiSecret": api_secret, "apiPassphrase": api_passphrase},
    )


async def execute_poly_trade(plan: dict) -> dict:
    try:
        client = await asyncio.wait_for(get_poly_client(), timeout=10)
    except Exception as e:
        return {"success": False, "error": str(e)}

    market_id = plan["market_id"]
    token_id = plan.get("token_id", "")
    size_usd = plan["size_usd"]
    price = float(plan.get("price", 0.5) or 0.5)
    position = plan.get("position", "YES")

    if not token_id:
        token_id = await _get_token_id(client, market_id, position)
        if not token_id:
            return {"success": False, "error": f"Could not find {position} token for market {market_id}"}

    shares = round(size_usd / price, 2) if price > 0 else 0
    if shares <= 0:
        return {"success": False, "error": "Invalid share calculation"}

    try:
        response = client.create_market_order(MarketOrderArgs(token_id=token_id, amount=size_usd))
        order_id = response.get("orderID", response.get("id", "")) if response else ""
        if not order_id:
            return {"success": False, "error": "No response from Polymarket"}
        return {"success": True, "tx_id": str(order_id), "order_id": order_id, "shares": shares, "price": price, "position": position, "result": response}
    except Exception as e:
        return {"success": False, "error": f"Trade failed: {type(e).__name__}: {str(e)[:200]}"}


async def _get_token_id(client, market_id: str, position: str) -> str:
    try:
        market = client.get_market(market_id)
        for token in market.get("tokens", []):
            if token.get("outcome", "").upper() == position.upper():
                return token.get("token_id", "")
    except Exception:
        return ""
    return ""


async def close_poly_position(market_id: str, token_id: str, shares: float, position: str) -> dict:
    try:
        client = await get_poly_client()
        response = client.create_market_sell(MarketOrderArgs(token_id=token_id, amount=shares))
        return {"success": True, "tx_id": str(response.get("orderID", "")), "result": response}
    except Exception as e:
        return {"success": False, "error": str(e)}
