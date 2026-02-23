import logging

import db
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

EXIT_PLAN = [
    {"multiplier": 2.0, "action": "Take out initial investment", "pct_to_sell": 50, "note": "You are now playing with house money"},
    {"multiplier": 5.0, "action": "Take 40% profits", "pct_to_sell": 40, "note": "Lock in significant gains"},
    {"multiplier": 10.0, "action": "Take another 25%", "pct_to_sell": 25, "note": "Only moon bag remains"},
    {"multiplier": 20.0, "action": "Consider full exit", "pct_to_sell": 50, "note": "20x is extraordinary — protect it"},
]


def format_exit_plan(entry_price: float, position_size: float) -> str:
    text = "*📤 Exit Plan*\n"
    for step in EXIT_PLAN:
        target = float(entry_price or 0) * step["multiplier"]
        sell_usd = float(position_size or 0) * step["pct_to_sell"] / 100
        text += (
            f"At {step['multiplier']}x (${target:,.6f}): "
            f"sell {step['pct_to_sell']}% (~${sell_usd:.2f})\n"
        )
    return text


async def monitor_exit_triggers(context) -> None:
    import httpx
    from config import CHAT_ID

    open_trades = db.get_open_degen_journal_entries()
    if not open_trades:
        return

    for trade in open_trades:
        try:
            contract = trade.get("contract_address")
            if not contract:
                continue

            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(f"https://api.dexscreener.com/latest/dex/tokens/{contract}")
                response.raise_for_status()
                data = response.json()

            pairs = data.get("pairs") or []
            if not pairs:
                continue

            current_price = float(pairs[0].get("priceUsd") or 0)
            if current_price <= 0:
                continue

            entry_price = float(trade.get("entry_price") or 0)
            if entry_price <= 0:
                continue

            multiplier = current_price / entry_price
            symbol = trade.get("token_symbol", "?")

            peak = float(trade.get("peak_price") or 0)
            if current_price > peak:
                db.update_degen_journal(trade["id"], {"peak_price": current_price, "peak_multiplier": multiplier})

            for step in EXIT_PLAN:
                target_mult = step["multiplier"]
                if multiplier < target_mult:
                    continue
                if db.exit_reminder_sent(trade["id"], target_mult):
                    continue

                pos_size = float(trade.get("position_size_usd") or 0)
                sell_pct = step["pct_to_sell"]
                sell_usd = pos_size * sell_pct / 100
                target_price = entry_price * target_mult

                await context.bot.send_message(
                    chat_id=CHAT_ID,
                    text=(
                        f"🎯 *Exit Reminder — {symbol}*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🪙 {symbol} is up {multiplier:.1f}x\n\n"
                        f"📤 *{step['action']}*\n"
                        f"Sell: {sell_pct}% (~${sell_usd:.2f})\n"
                        f"_{step['note']}_\n\n"
                        f"Current: ${current_price:.8f}\n"
                        f"Entry:   ${entry_price:.8f}\n"
                        f"Target was: ${target_price:.8f}"
                    ),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [InlineKeyboardButton("✅ Sold — Update Journal", callback_data=f"degen:sold:{trade['id']}:{target_mult}")],
                            [InlineKeyboardButton("⏭ Hold On", callback_data=f"degen:hold:{trade['id']}")],
                        ]
                    ),
                )

                db.save_exit_reminder(
                    {
                        "journal_id": trade["id"],
                        "contract_address": contract,
                        "token_symbol": symbol,
                        "entry_price": entry_price,
                        "current_price": current_price,
                        "multiplier": multiplier,
                        "reminder_type": f"{target_mult}x",
                        "sent": True,
                    }
                )
        except Exception as exc:
            logging.getLogger(__name__).error("Exit monitor error %s: %s", trade.get("token_symbol"), exc)
