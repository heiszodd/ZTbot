import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import db

log = logging.getLogger(__name__)


async def run_polymarket_monitor(context) -> None:
    from config import CHAT_ID
    from engine.polymarket.market_reader import fetch_market_by_id

    watchlist = db.get_poly_watchlist()
    if not watchlist:
        return

    for item in watchlist:
        market_id = item["market_id"]
        try:
            market = await fetch_market_by_id(market_id)
            if not market:
                continue

            tokens = market.get("tokens", [])
            yes_price = 0.0
            for t in tokens:
                if str(t.get("outcome", "")).lower() == "yes":
                    yes_price = float(t.get("price", 0) or 0)
                    break
            yes_pct = round(yes_price * 100, 1)

            alert_above = item.get("alert_yes_above")
            alert_below = item.get("alert_yes_below")
            question = item.get("question", "?")

            triggered, alert_msg = False, ""
            if alert_above and yes_pct >= alert_above:
                if not db.poly_alert_recently_sent(market_id, f"above_{alert_above}"):
                    triggered = True
                    alert_msg = f"📈 YES crossed {alert_above}%"
            elif alert_below and yes_pct <= alert_below:
                if not db.poly_alert_recently_sent(market_id, f"below_{alert_below}"):
                    triggered = True
                    alert_msg = f"📉 YES dropped to {yes_pct}%"

            if triggered:
                short_q = question[:60] + "..." if len(question) > 60 else question
                await context.bot.send_message(
                    chat_id=CHAT_ID,
                    text=(
                        f"🎯 *Polymarket Alert*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"{short_q}\n\n"
                        f"{alert_msg}\n"
                        f"YES: *{yes_pct:.1f}%*  NO: {100-yes_pct:.1f}%\n"
                    ),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton("📲 Live Trade", callback_data=f"poly:live:{market_id}"),
                                InlineKeyboardButton("🎮 Demo Trade", callback_data=f"poly:demo:{market_id}"),
                            ],
                            [
                                InlineKeyboardButton("📊 Market Details", callback_data=f"poly:detail:{market_id}"),
                                InlineKeyboardButton("🗑 Remove Alert", callback_data=f"poly:remove:{market_id}"),
                            ],
                        ]
                    ),
                )
                db.save_poly_alert_sent({"market_id": market_id, "alert_type": alert_msg, "yes_price": yes_pct / 100})
        except Exception as e:
            log.error(f"Poly monitor error {market_id}: {e}")

    live = db.get_open_poly_live_trades()
    for trade in live:
        try:
            market = await fetch_market_by_id(trade["market_id"])
            if not market:
                continue
            yes_price = 0.0
            for t in market.get("tokens", []):
                if str(t.get("outcome", "")).upper() == "YES":
                    yes_price = float(t.get("price", 0) or 0)
                    break
            now_price = yes_price if trade.get("position") == "YES" else (1 - yes_price)
            entry = float(trade.get("entry_price") or 0)
            if entry <= 0:
                continue
            pnl_pct = (now_price - entry) / entry * 100
            pnl_usd = float(trade.get("size_usd") or 0) * pnl_pct / 100
            db.update_poly_live_trade(int(trade["id"]), {"current_price": now_price, "pnl_usd": pnl_usd})
            if pnl_pct >= 50 or pnl_pct <= -30:
                short_q = trade.get("question", "")[:50]
                await context.bot.send_message(
                    chat_id=CHAT_ID,
                    text=(f"📈 Poly Position Alert\n{short_q}\nEntry: {entry*100:.1f}%  Now: {now_price*100:.1f}%\nP&L: {pnl_usd:+.2f} ({pnl_pct:+.1f}%)"),
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💸 Close", callback_data=f"poly:close:{trade['market_id']}"), InlineKeyboardButton("📊 Detail", callback_data=f"poly:position:{trade['market_id']}")]]),
                )
        except Exception as e:
            log.error("Poly live monitor error %s: %s", trade.get("market_id"), e)
