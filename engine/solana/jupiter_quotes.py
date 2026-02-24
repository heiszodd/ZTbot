import httpx
import logging

log = logging.getLogger(__name__)

JUPITER_QUOTE_URL = "https://quote-api.jup.ag/v6/quote"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
WSOL_MINT = "So11111111111111111111111111111111111111112"


async def get_swap_quote(input_mint: str, output_mint: str, amount_usd: float, input_price: float, slippage_bps: int = 100) -> dict:
    if input_mint == USDC_MINT:
        amount_in = int(amount_usd * 1e6)
    else:
        if input_price <= 0:
            return {"error": "Invalid input price"}
        token_amount = amount_usd / input_price
        amount_in = int(token_amount * 1e9)

    params = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": amount_in,
        "slippageBps": slippage_bps,
        "onlyDirectRoutes": False,
        "asLegacyTransaction": False,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(JUPITER_QUOTE_URL, params=params)
            if r.status_code == 400:
                err = r.json().get("error", "")
                return {"error": f"Jupiter: {err}"}
            r.raise_for_status()
            quote = r.json()
    except Exception as e:
        log.error(f"Jupiter quote error: {e}")
        return {"error": str(e)}

    if not quote:
        return {"error": "Empty Jupiter response"}

    out_amount = int(quote.get("outAmount", 0))
    in_amount = int(quote.get("inAmount", 0))
    price_impact = float(quote.get("priceImpactPct", 0) or 0)

    route_plan = quote.get("routePlan", [])
    route_hops = []
    for hop in route_plan:
        swap_info = hop.get("swapInfo", {})
        route_hops.append(swap_info.get("label", "?"))
    route_str = " → ".join(route_hops) if route_hops else "Direct"

    out_decimals = 6 if output_mint == USDC_MINT else 9
    in_decimals = 6 if input_mint == USDC_MINT else 9

    tokens_out = out_amount / (10**out_decimals)
    usd_in = in_amount / (10**in_decimals) if input_mint == USDC_MINT else (in_amount / 1e9) * input_price
    effective_price = usd_in / tokens_out if tokens_out > 0 else 0

    min_out = out_amount * (1 - slippage_bps / 10000)
    min_tokens = min_out / (10**out_decimals)

    return {
        "input_mint": input_mint,
        "output_mint": output_mint,
        "amount_usd": amount_usd,
        "tokens_out": round(tokens_out, 6),
        "min_tokens_out": round(min_tokens, 6),
        "effective_price": round(effective_price, 8),
        "price_impact_pct": round(price_impact, 3),
        "slippage_bps": slippage_bps,
        "slippage_pct": slippage_bps / 100,
        "route": route_str,
        "raw_quote": quote,
        "warning": "⚠️ High price impact — consider smaller size" if price_impact > 3 else "",
    }


def format_quote(quote: dict, token_symbol: str, action: str = "BUY") -> str:
    if "error" in quote:
        return f"❌ Quote failed: {quote['error']}"

    impact = quote["price_impact_pct"]
    impact_emoji = "🚨" if impact > 5 else "⚠️" if impact > 2 else "✅"
    slippage = quote["slippage_pct"]

    text = (
        f"📋 *Trade Quote — {action} {token_symbol}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Spending:      ${quote['amount_usd']:.2f} USDC\n"
        f"Receiving:     {quote['tokens_out']:.6f} {token_symbol}\n"
        f"Min received:  {quote['min_tokens_out']:.6f} (after {slippage}% slippage)\n"
        f"Eff. price:    ${quote['effective_price']:.8f}\n"
        f"Route:         {quote['route']}\n"
        f"{impact_emoji} Price impact: {impact:.2f}%\n"
    )
    if quote.get("warning"):
        text += f"\n{quote['warning']}\n"
    text += (
        f"\n_To execute: open Phantom or Solflare,_\n"
        f"_swap USDC → {token_symbol} with_\n"
        f"_{slippage}% slippage on Jupiter._"
    )
    return text


async def get_priority_fee_estimate() -> dict:
    from config import HELIUS_API_KEY

    if not HELIUS_API_KEY:
        return {"low": 1000, "medium": 5000, "high": 50000, "unit": "microlamports"}

    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.post(
                f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}",
                json={
                    "jsonrpc": "2.0",
                    "id": "priority-fee",
                    "method": "getPriorityFeeEstimate",
                    "params": [{"accountKeys": ["JUP6LkbZbjS1jKKwapdHNy584ocKhkB1UMTDnzVL7"], "options": {"includeAllPriorityFeeLevels": True}}],
                },
            )
            data = r.json()
            fees = data.get("result", {}).get("priorityFeeLevels", {})
            return {
                "low": int(fees.get("low", 1000)),
                "medium": int(fees.get("medium", 5000)),
                "high": int(fees.get("high", 50000)),
                "unit": "microlamports",
            }
    except Exception as e:
        log.warning(f"Priority fee fetch: {e}")
        return {"low": 1000, "medium": 5000, "high": 50000, "unit": "microlamports"}
