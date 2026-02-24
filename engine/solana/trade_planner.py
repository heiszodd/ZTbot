async def generate_trade_plan(token_address: str, token_symbol: str, action: str, amount_usd: float, scan_data: dict = None) -> dict:
    from engine.solana.jupiter_quotes import get_swap_quote, get_priority_fee_estimate, USDC_MINT
    from engine.solana.wallet_reader import get_token_price_usd

    token_price = await get_token_price_usd(token_address)
    liq = (scan_data or {}).get("liquidity_usd", 0) or 0
    if liq >= 500000:
        slippage_bps = 50
    elif liq >= 100000:
        slippage_bps = 100
    elif liq >= 50000:
        slippage_bps = 200
    else:
        slippage_bps = 300

    if action == "buy":
        quote = await get_swap_quote(USDC_MINT, token_address, amount_usd, 1.0, slippage_bps)
    else:
        quote = await get_swap_quote(token_address, USDC_MINT, amount_usd, token_price, slippage_bps)

    fees = await get_priority_fee_estimate()
    if "error" in quote:
        return {"success": False, "error": quote["error"]}

    steps = _build_execution_steps(action, token_symbol, token_address, amount_usd, quote, fees, slippage_bps)
    return {
        "success": True,
        "action": action,
        "token_symbol": token_symbol,
        "token_address": token_address,
        "amount_usd": amount_usd,
        "quote": quote,
        "fees": fees,
        "slippage_bps": slippage_bps,
        "steps": steps,
        "token_price": token_price,
    }


def _build_execution_steps(action, token_symbol, token_address, amount_usd, quote, fees, slippage_bps) -> list:
    slippage_pct = slippage_bps / 100
    med_fee_sol = fees["medium"] / 1e9
    impact = quote.get("price_impact_pct", 0)
    if action == "buy":
        return [
            "Open Jupiter (jup.ag) or Phantom swap",
            "Set input token: USDC",
            f"Set output token: {token_symbol}\n   Address: `{token_address}`",
            f"Set amount: ${amount_usd:.2f} USDC",
            f"Set slippage: {slippage_pct}%\n   (low liq — don't go tighter)",
            f"Set priority fee: Medium\n   (~{fees['medium']:,} microlamports\n   ≈ ${med_fee_sol * 150:.4f} at\n   SOL=$150)",
            f"Review: you should receive ~{quote['tokens_out']:.4f} {token_symbol}",
            f"Price impact: {impact:.2f}% {'⚠️ high' if impact > 2 else '✅ ok'}",
            "Confirm and sign the transaction",
        ]
    return [
        "Open Jupiter (jup.ag) or Phantom swap",
        f"Set input token: {token_symbol}\n   Address: `{token_address}`",
        "Set output token: USDC",
        f"Set amount in {token_symbol} tokens\n   (≈${amount_usd:.2f} worth)",
        f"Set slippage: {slippage_pct}%",
        "Set priority fee: Medium",
        f"Review: you should receive ~${quote['tokens_out']:.2f} USDC",
        "Confirm and sign the transaction",
    ]


def format_trade_plan(plan: dict) -> str:
    if not plan.get("success"):
        return f"❌ *Trade Plan Failed*\n{plan.get('error','Unknown error')}"

    action = plan["action"].upper()
    symbol = plan["token_symbol"]
    quote = plan["quote"]
    steps = plan["steps"]
    fees = plan["fees"]
    impact = quote.get("price_impact_pct", 0)
    slippage = plan["slippage_bps"] / 100
    impact_emoji = "🚨" if impact > 5 else "⚠️" if impact > 2 else "✅"

    text = (
        f"📋 *Live Trade Plan — {action} {symbol}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Amount:        ${plan['amount_usd']:.2f}\n"
        f"Expected out:  {quote['tokens_out']:.6f} {symbol}\n"
        f"Eff. price:    ${quote['effective_price']:.8f}\n"
        f"Route:         {quote['route']}\n"
        f"{impact_emoji} Impact:     {impact:.2f}%\n"
        f"Slippage:      {slippage}%\n"
        f"Priority fee:  {fees['medium']:,} microlamports\n\n"
        f"*Execute in Phantom/Jupiter:*\n"
    )
    for i, step in enumerate(steps, 1):
        text += f"{i}. {step}\n"
    text += "\n⚠️ _Phase 1: manual execution._\n_Auto-execution coming in Phase 2._"
    return text
