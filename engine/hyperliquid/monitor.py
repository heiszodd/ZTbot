import asyncio
import logging
from datetime import datetime, timedelta, timezone

import db
from config import CHAT_ID, HL_ADDRESS
from engine.hyperliquid.account_reader import (
    fetch_account_summary,
    fetch_open_orders_parsed,
    fetch_positions_with_prices,
)
from engine.hyperliquid.client import get_user_fills
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

log = logging.getLogger(__name__)


async def _run_monitor_inner(context) -> None:
    if not HL_ADDRESS:
        return

    summary = await fetch_account_summary(HL_ADDRESS)
    positions = await fetch_positions_with_prices(HL_ADDRESS)
    orders = await fetch_open_orders_parsed(HL_ADDRESS)
    if not summary:
        return

    db.upsert_hl_account(summary)
    for pos in positions:
        db.upsert_hl_position(HL_ADDRESS, pos)

    alerts = []
    account_value = float(summary.get("account_value", 0) or 0)
    saved_positions = {p.get("coin"): p for p in db.get_hl_positions(HL_ADDRESS)}

    for pos in positions:
        coin = pos["coin"]
        mark = float(pos.get("mark_price", 0) or 0)
        liq = pos.get("liq_price")
        live_upnl = float(pos.get("live_upnl", 0) or 0)

        if liq and mark > 0:
            dist_to_liq = abs(mark - liq) / mark * 100
            if dist_to_liq < 15:
                allow = True
                last_sent = (saved_positions.get(coin) or {}).get("last_liq_alert")
                if last_sent and datetime.now(timezone.utc).replace(tzinfo=None) - last_sent < timedelta(hours=1):
                    allow = False
                if allow:
                    alerts.append(
                        f"🚨 *{coin} NEAR LIQUIDATION*\n"
                        f"Mark: ${mark:,.2f}  Liq: ${liq:,.2f}\n"
                        f"Distance: {dist_to_liq:.1f}%\n"
                        "Reduce position or add margin!"
                    )
                    db.update_hl_position_alert_time(HL_ADDRESS, coin)

        if account_value > 0 and live_upnl < 0:
            loss_pct = abs(live_upnl) / account_value * 100
            if loss_pct > 5:
                alerts.append(
                    f"⚠️ *{coin} Large Loss*\n"
                    f"P&L: ${live_upnl:+,.2f} ({loss_pct:.1f}% of account)\n"
                    "Consider reviewing position."
                )

    for alert_text in alerts:
        try:
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text=alert_text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("📊 View Positions", callback_data="hl:positions"),
                            InlineKeyboardButton("🏠 HL Dashboard", callback_data="hl:home"),
                        ]
                    ]
                ),
            )
        except Exception as e:
            log.error("HL alert send: %s", e)

    if orders:
        log.debug("HL monitor open orders: %s", len(orders))

    try:
        fills = await get_user_fills(HL_ADDRESS)
        for fill in fills[:20]:
            oid = str(fill.get("oid") or "")
            if not oid:
                continue
            order = db.get_hl_order(oid)
            if order and order.get("status") == "open":
                db.update_hl_order_status(oid, "filled")
                await context.bot.send_message(
                    chat_id=CHAT_ID,
                    text=(
                        f"✅ Order Filled — {fill.get('side','')} {fill.get('coin','')}\n"
                        f"Filled @ ${float(fill.get('px') or 0):,.2f}\n"
                        f"Size: ${float(fill.get('sz') or 0):,.2f}"
                    ),
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📊 Position", callback_data="hl:positions")]]),
                )
    except Exception as e:
        log.debug("HL fill monitor skipped: %s", e)


async def run_hl_monitor(context) -> None:
    try:
        await asyncio.wait_for(_run_monitor_inner(context), timeout=60)
    except asyncio.TimeoutError:
        log.warning("HL monitor timed out after 60 seconds")
    except Exception as e:
        log.error("HL monitor fetch error: %s", e)
