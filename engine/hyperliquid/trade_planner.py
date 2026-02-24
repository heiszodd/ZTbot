import logging

from engine.hyperliquid.market_data import fetch_all_markets, get_market_price, get_order_book_summary

log = logging.getLogger(__name__)


async def coin_from_pair(pair: str) -> str:
    coin = (pair or "").upper()
    for suffix in ["/USDT", "/USD", "-USDT", "-USD", "USDT", "USDC", "BUSD", "USD"]:
        coin = coin.replace(suffix, "")
    return coin.strip()


async def get_hl_market_for_pair(pair: str) -> dict:
    coin = await coin_from_pair(pair)
    markets = await fetch_all_markets()
    for market in markets:
        if market["coin"].upper() == coin.upper():
            return market
    return {}


async def generate_hl_trade_plan(signal: dict, account_value: float = 0) -> dict:
    pair = signal.get("pair", "")
    direction = signal.get("direction", "Bullish")
    side = "Long" if "bull" in str(direction).lower() else "Short"

    coin = await coin_from_pair(pair)
    market = await get_hl_market_for_pair(pair)
    if not market:
        return {"success": False, "error": f"{coin} not available on Hyperliquid. Check pair name."}

    mark_price = await get_market_price(coin)
    if mark_price <= 0:
        return {"success": False, "error": "Could not fetch mark price"}

    entry_price = float(signal.get("entry_price", 0) or 0)
    if entry_price <= 0:
        entry_price = mark_price * (0.9995 if side == "Long" else 1.0005)

    stop_loss = float(signal.get("stop_loss", 0) or signal.get("sl", 0) or 0)
    take_profit = float(signal.get("take_profit", 0) or signal.get("tp1", 0) or 0)
    if stop_loss <= 0:
        return {"success": False, "error": "Missing stop_loss from signal"}

    if side == "Long" and stop_loss >= entry_price:
        return {"success": False, "error": f"SL ({stop_loss}) must be below entry ({entry_price:.4f}) for Long"}
    if side == "Short" and stop_loss <= entry_price:
        return {"success": False, "error": f"SL ({stop_loss}) must be above entry ({entry_price:.4f}) for Short"}

    max_lev = int(market.get("max_leverage", 50) or 50)
    leverage = min(float(signal.get("leverage", 5) or 5), max_lev)
    risk_amount = float(signal.get("risk_amount", 0) or 0)
    rr_ratio = float(signal.get("rr_ratio", 0) or 0)

    stop_dist = abs(entry_price - stop_loss)
    stop_pct = stop_dist / entry_price if entry_price > 0 else 0
    if risk_amount > 0 and stop_pct > 0:
        size_usd = risk_amount / stop_pct
    else:
        size_usd = float(signal.get("position_size", 0) or 0) or (account_value * 0.05 if account_value > 0 else 100)

    sz_dec = int(market.get("sz_decimals", 5) or 5)
    size_coins = round(size_usd / entry_price, sz_dec)
    size_usd_actual = size_coins * entry_price
    margin_required = size_usd_actual / leverage if leverage > 0 else size_usd_actual

    range_to_sl = abs(entry_price - stop_loss)
    if take_profit > 0:
        tp1 = take_profit
    else:
        tp1 = entry_price + range_to_sl * 1.5 if side == "Long" else entry_price - range_to_sl * 1.5
    tp2 = entry_price + range_to_sl * 3 if side == "Long" else entry_price - range_to_sl * 3
    tp3 = entry_price + range_to_sl * 5 if side == "Long" else entry_price - range_to_sl * 5

    rr1 = abs(tp1 - entry_price) / range_to_sl if range_to_sl > 0 else 0
    rr2 = abs(tp2 - entry_price) / range_to_sl if range_to_sl > 0 else 0
    rr3 = abs(tp3 - entry_price) / range_to_sl if range_to_sl > 0 else 0

    maker_fee = size_usd_actual * 0.0002
    liq_est = entry_price * (1 - 1 / leverage * 0.9) if side == "Long" else entry_price * (1 + 1 / leverage * 0.9)
    book = await get_order_book_summary(coin)
    dist_to_entry_pct = abs(mark_price - entry_price) / mark_price * 100 if mark_price > 0 else 0

    return {
        "success": True,
        "coin": coin,
        "pair": pair,
        "side": side,
        "order_type": "Limit",
        "entry_price": round(entry_price, 4),
        "mark_price": round(mark_price, 4),
        "dist_entry_pct": round(dist_to_entry_pct, 2),
        "stop_loss": round(stop_loss, 4),
        "tp1": round(tp1, 4),
        "tp2": round(tp2, 4),
        "tp3": round(tp3, 4),
        "rr1": round(rr1, 2),
        "rr2": round(rr2, 2),
        "rr3": round(rr3, 2),
        "size_coins": size_coins,
        "size_usd": round(size_usd_actual, 2),
        "margin_required": round(margin_required, 2),
        "leverage": leverage,
        "max_leverage": max_lev,
        "risk_amount": round(risk_amount, 2),
        "est_maker_fee": round(maker_fee, 4),
        "liq_estimate": round(liq_est, 2),
        "quality_grade": signal.get("quality_grade", "C"),
        "quality_score": float(signal.get("quality_score", 0) or 0),
        "rr_ratio": rr_ratio or rr1,
        "book": book,
        "steps": _build_hl_steps(side, coin, entry_price, stop_loss, tp1, tp2, tp3, size_coins, leverage, margin_required),
        "signal": signal,
    }


def _build_hl_steps(side, coin, entry, sl, tp1, tp2, tp3, size_coins, leverage, margin) -> list:
    action = "BUY / Long" if side == "Long" else "SELL / Short"
    return [
        "Go to app.hyperliquid.xyz",
        f"Select market: *{coin}-USDC*",
        "Set order type: *Limit*",
        f"Set side: *{action}*",
        f"Set price: *{entry:.4f}*",
        f"Set size: *{size_coins} {coin}* (≈${size_coins * entry:.2f} notional)",
        f"Set leverage: *{leverage}x* (margin needed: ≈${margin:.2f})",
        f"After fill — set Stop Loss: *{sl:.4f}*",
        f"Set TP1: *{tp1:.4f}* (close 40%)",
        f"Set TP2: *{tp2:.4f}* (close 40%)",
        f"Set TP3: *{tp3:.4f}* (close 20%)",
        "⚠️ Phase 1: manual execution\n   Auto-orders coming in Phase 2",
    ]


def format_hl_trade_plan(plan: dict) -> str:
    if not plan.get("success"):
        return f"❌ *Trade Plan Failed*\n{plan.get('error', 'Unknown')}"

    side_emoji = "🟢" if plan["side"] == "Long" else "🔴"
    grade = plan["quality_grade"]
    grade_emoji = {"A": "✅", "B": "👍", "C": "⚠️", "D": "🔴", "F": "💀"}.get(grade, "⚠️")
    book = plan.get("book", {})
    imbalance = book.get("imbalance", 50)
    book_bias = "📈 Bid heavy" if imbalance > 60 else "📉 Ask heavy" if imbalance < 40 else "⚖️ Balanced"

    text = (
        f"{side_emoji} *Hyperliquid Trade Plan*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Market:  {plan['coin']}-USDC\n"
        f"Side:    {plan['side']}  {grade_emoji} Grade {grade}\n\n"
        f"💰 *Prices*\n"
        f"Mark:    ${plan['mark_price']:,.4f}\n"
        f"Entry:   ${plan['entry_price']:,.4f} ({plan['dist_entry_pct']:.2f}% away)\n"
        f"SL:      ${plan['stop_loss']:,.4f}\n"
        f"TP1:     ${plan['tp1']:,.4f} ({plan['rr1']:.1f}R)\n"
        f"TP2:     ${plan['tp2']:,.4f} ({plan['rr2']:.1f}R)\n"
        f"TP3:     ${plan['tp3']:,.4f} ({plan['rr3']:.1f}R)\n\n"
        f"📊 *Position*\n"
        f"Size:    {plan['size_coins']} {plan['coin']} (${plan['size_usd']:,.2f})\n"
        f"Margin:  ${plan['margin_required']:,.2f}\n"
        f"Leverage:{plan['leverage']}x (max {plan['max_leverage']}x)\n"
        f"Risk:    ${plan['risk_amount']:,.2f}\n"
        f"Fee est: ${plan['est_maker_fee']:.4f} (maker 0.02%)\n"
        f"Liq est: ${plan['liq_estimate']:,.2f}\n\n"
        f"📖 *Order Book*\n"
        f"{book_bias}  Spread: {book.get('spread_pct',0):.3f}%\n\n"
        "*Execute on Hyperliquid:*\n"
    )
    for i, step in enumerate(plan["steps"], 1):
        text += f"{i}. {step}\n"
    return text
