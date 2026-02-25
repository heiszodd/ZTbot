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

    # Trailing stop automation
    for pos in positions:
        coin = pos["coin"]
        side = pos["side"]
        size = pos["size"]
        upnl_p = float(pos.get("live_upnl_pct", 0) or 0)

        row = db.get_hl_position_by_coin(coin)
        if not row:
            continue
        trail_pct = row.get("trailing_stop_pct")
        if not trail_pct:
            continue

        if upnl_p >= float(trail_pct):
            old_oid = row.get("trailing_stop_order_id")
            entry_px = float(pos.get("entry_price", 0) or 0)
            if entry_px <= 0:
                continue

            if side == "Long":
                new_stop = entry_px * 1.001
            else:
                new_stop = entry_px * 0.999

            if old_oid:
                try:
                    from engine.hyperliquid.executor import cancel_order

                    await cancel_order(coin, int(old_oid))
                except Exception:
                    pass

            try:
                from engine.hyperliquid.executor import get_hl_exchange

                exchange = await get_hl_exchange()
                raw = exchange.order(
                    name=coin,
                    is_buy=side != "Long",
                    sz=size,
                    limit_px=new_stop,
                    order_type={"trigger": {"triggerPx": new_stop, "isMarket": True, "tpsl": "sl"}},
                    reduce_only=True,
                )
                oid = ""
                try:
                    status = raw.get("response", {}).get("data", {}).get("statuses", [])[0]
                    oid = status.get("resting", {}).get("oid", "") or status.get("filled", {}).get("oid", "")
                except Exception:
                    oid = ""
                result = {"success": raw.get("status") != "err", "order_id": oid}
            except Exception:
                continue

            if result.get("success"):
                try:
                    db.save_hl_trailing_stop_order_id(coin, str(result.get("order_id", "")))
                except Exception:
                    pass

                msg = (
                    f"🔒 *Trailing Stop Moved*\n"
                    f"{coin} {side}\n"
                    f"Stop moved to breakeven at ${new_stop:,.4f}\n"
                    f"PnL locked: ≥ 0%"
                )
                try:
                    from security.auth import ALLOWED_USER_IDS
                except Exception:
                    ALLOWED_USER_IDS = [CHAT_ID]
                for uid in ALLOWED_USER_IDS:
                    try:
                        await context.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
                    except Exception:
                        pass

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
