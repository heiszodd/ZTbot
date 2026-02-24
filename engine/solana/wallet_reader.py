import httpx
import logging
from config import SOLANA_RPC_URL

log = logging.getLogger(__name__)

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
WSOL_MINT = "So11111111111111111111111111111111111111112"


async def get_sol_balance(public_key: str) -> float:
    """Get SOL balance for a wallet address."""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                SOLANA_RPC_URL,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getBalance",
                    "params": [public_key],
                },
            )
            data = r.json()
            lamports = data.get("result", {}).get("value", 0)
            return lamports / 1e9
    except Exception as e:
        log.error(f"SOL balance error: {e}")
        return 0.0


async def get_token_accounts(public_key: str) -> list:
    """Get all SPL token balances for a wallet."""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                SOLANA_RPC_URL,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTokenAccountsByOwner",
                    "params": [
                        public_key,
                        {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                        {"encoding": "jsonParsed"},
                    ],
                },
            )
            data = r.json()
            accts = data.get("result", {}).get("value", [])
    except Exception as e:
        log.error(f"Token accounts error: {e}")
        return []

    tokens = []
    for acct in accts:
        try:
            info = acct["account"]["data"]["parsed"]["info"]
            mint = info["mint"]
            amount = float(info["tokenAmount"].get("uiAmount") or 0)
            if amount <= 0:
                continue
            tokens.append(
                {
                    "mint": mint,
                    "amount": amount,
                    "decimals": info["tokenAmount"].get("decimals", 0),
                }
            )
        except Exception:
            continue
    return tokens


async def get_token_price_usd(mint: str) -> float:
    """Get token price in USD from Jupiter."""
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get("https://price.jup.ag/v4/price", params={"ids": mint})
            data = r.json()
            return float(data.get("data", {}).get(mint, {}).get("price", 0) or 0)
    except Exception:
        return 0.0


async def get_wallet_summary(public_key: str) -> dict:
    """Get full wallet summary including SOL, USDC, and top token holdings."""
    sol_balance = await get_sol_balance(public_key)
    token_accts = await get_token_accounts(public_key)

    sol_price = await get_token_price_usd(WSOL_MINT)
    sol_usd = sol_balance * sol_price

    usdc_balance = 0.0
    other_tokens = []

    for t in token_accts:
        if t["mint"] == USDC_MINT:
            usdc_balance = t["amount"]
        else:
            price = await get_token_price_usd(t["mint"])
            usd_val = t["amount"] * price
            if usd_val >= 0.5:
                other_tokens.append(
                    {
                        "mint": t["mint"],
                        "amount": t["amount"],
                        "price": price,
                        "usd_val": usd_val,
                    }
                )

    other_tokens.sort(key=lambda x: x["usd_val"], reverse=True)
    total_usd = sol_usd + usdc_balance + sum(t["usd_val"] for t in other_tokens)

    return {
        "public_key": public_key,
        "sol_balance": round(sol_balance, 4),
        "sol_price": round(sol_price, 2),
        "sol_usd": round(sol_usd, 2),
        "usdc_balance": round(usdc_balance, 2),
        "other_tokens": other_tokens[:10],
        "total_usd": round(total_usd, 2),
    }
