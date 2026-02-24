async def calculate_hl_performance(address: str) -> dict:
    from engine.hyperliquid.account_reader import fetch_funding_summary, fetch_trade_history

    trades = await fetch_trade_history(address, limit=200)
    funding = await fetch_funding_summary(address)
    if not trades:
        return {"total_trades": 0, "funding": funding}

    closes = [t for t in trades if t["is_close"]]
    if not closes:
        return {"total_trades": len(trades), "closes": 0, "funding": funding}

    wins = [t for t in closes if t["net_pnl"] > 0]
    losses = [t for t in closes if t["net_pnl"] < 0]
    total_pnl = sum(t["net_pnl"] for t in closes)
    total_fees = sum(t["fee"] for t in trades)
    win_rate = len(wins) / len(closes) * 100 if closes else 0
    avg_win = sum(t["net_pnl"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["net_pnl"] for t in losses) / len(losses) if losses else 0
    expectancy = win_rate / 100 * avg_win + (1 - win_rate / 100) * avg_loss
    gross_profit = sum(t["net_pnl"] for t in wins)
    gross_loss = abs(sum(t["net_pnl"] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
    best = max(closes, key=lambda x: x["net_pnl"])
    worst = min(closes, key=lambda x: x["net_pnl"])

    by_coin = {}
    for t in closes:
        coin = t["coin"]
        by_coin.setdefault(coin, {"trades": 0, "pnl": 0, "wins": 0})
        by_coin[coin]["trades"] += 1
        by_coin[coin]["pnl"] += t["net_pnl"]
        if t["net_pnl"] > 0:
            by_coin[coin]["wins"] += 1
    for coin, data in by_coin.items():
        data["win_rate"] = round(data["wins"] / data["trades"] * 100, 1)
        data["pnl"] = round(data["pnl"], 2)

    return {
        "total_trades": len(trades),
        "closes": len(closes),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "total_fees": round(total_fees, 4),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "expectancy": round(expectancy, 2),
        "profit_factor": round(profit_factor, 2),
        "best_trade": best,
        "worst_trade": worst,
        "by_coin": by_coin,
        "funding": funding,
        "net_with_funding": round(total_pnl + funding["total"], 2),
    }


def format_performance(perf: dict) -> str:
    if perf.get("total_trades", 0) == 0:
        return "📊 *Hyperliquid Performance*\nNo trade history found.\nConnect your address first."

    pnl_emoji = "🟢" if perf.get("total_pnl", 0) > 0 else "🔴"
    pf = perf.get("profit_factor", 0)
    pf_emoji = "✅" if pf > 1.5 else "⚠️" if pf > 1 else "🔴"
    best = perf.get("best_trade", {})
    worst = perf.get("worst_trade", {})

    text = (
        "📊 *Hyperliquid Performance*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Trades:   {perf.get('closes', 0)} closed\n"
        f"Win rate: {perf.get('win_rate', 0):.1f}%  ({perf.get('wins', 0)}W / {perf.get('losses', 0)}L)\n\n"
        "💰 *P&L*\n"
        f"{pnl_emoji} Total:    ${perf.get('total_pnl', 0):+,.2f}\n"
        f"  Fees:     -${perf.get('total_fees', 0):.4f}\n"
        f"  Funding:  ${perf.get('funding', {}).get('total', 0):+.4f}\n"
        f"  Net:      ${perf.get('net_with_funding', 0):+,.2f}\n\n"
        "📈 *Quality*\n"
        f"Avg win:   ${perf.get('avg_win', 0):+.2f}\n"
        f"Avg loss:  ${perf.get('avg_loss', 0):+.2f}\n"
        f"Expectancy:${perf.get('expectancy', 0):+.2f}\n"
        f"{pf_emoji} Prof.factor: {pf:.2f}\n\n"
    )
    if best:
        text += f"🏆 Best: {best.get('coin', '')} +${best.get('net_pnl', 0):.2f}\n"
    if worst:
        text += f"💀 Worst: {worst.get('coin', '')} ${worst.get('net_pnl', 0):.2f}\n"

    by_coin = perf.get("by_coin", {})
    if by_coin:
        text += "\n*Top Markets*\n"
        for coin, data in sorted(by_coin.items(), key=lambda x: abs(x[1]["pnl"]), reverse=True)[:3]:
            sign = "+" if data["pnl"] > 0 else ""
            text += f"  {coin}: ${sign}{data['pnl']:.2f} ({data['win_rate']:.0f}% WR)\n"
    return text
