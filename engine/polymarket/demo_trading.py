import logging
import db

log = logging.getLogger(__name__)


async def open_poly_demo_trade(market_id: str, question: str, position: str, yes_pct: float, size_usd: float = 10.0) -> int:
    entry_price = yes_pct / 100
    return db.create_poly_demo_trade(
        {
            "market_id": market_id,
            "question": question,
            "position": position.upper(),
            "entry_price": entry_price,
            "entry_yes_prob": yes_pct,
            "size_usd": size_usd,
            "current_price": entry_price,
            "status": "open",
        }
    )


async def update_poly_demo_trades(context) -> None:
    from datetime import datetime
    from config import CHAT_ID
    from engine.polymarket.market_reader import fetch_market_by_id

    open_trades = db.get_open_poly_demo_trades()
    for trade in open_trades:
        try:
            market = await fetch_market_by_id(trade["market_id"])
            if not market:
                continue

            tokens = market.get("tokens", [])
            yes_price = 0.0
            for t in tokens:
                if str(t.get("outcome", "")).lower() == "yes":
                    yes_price = float(t.get("price", 0) or 0)

            entry = float(trade.get("entry_price") or 0)
            pos = trade.get("position")
            size = float(trade.get("size_usd") or 0)
            if pos == "YES":
                pnl = (yes_price - entry) * size
            else:
                pnl = ((1 - yes_price) - (1 - entry)) * size

            resolved = market.get("closed", False)
            outcome = None
            if resolved:
                for t in tokens:
                    if float(t.get("price", 0) or 0) > 0.99:
                        outcome = t.get("outcome", "?").upper()
                        break

            db.update_poly_demo_trade(
                trade["id"],
                {
                    "current_price": yes_price,
                    "pnl_usd": round(pnl, 2),
                    "status": "resolved" if resolved else "open",
                    "outcome": outcome,
                    "resolution_price": yes_price if resolved else None,
                    "closed_at": datetime.utcnow().isoformat() if resolved else None,
                },
            )

            if resolved and outcome:
                won = (pos == "YES" and outcome == "YES") or (pos == "NO" and outcome == "NO")
                await context.bot.send_message(
                    chat_id=CHAT_ID,
                    text=(
                        f"{'🎉' if won else '❌'} *Poly Demo Resolved*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"{trade['question'][:60]}\n\n"
                        f"Your position: {pos}\n"
                        f"Outcome: {outcome}\n"
                        f"Result: {'WIN' if won else 'LOSS'}\n"
                        f"P&L: ${pnl:+.2f}\n"
                    ),
                    parse_mode="Markdown",
                )
        except Exception as e:
            log.error(f"Poly demo update error: {e}")
