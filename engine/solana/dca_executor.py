import asyncio
import logging
from datetime import datetime, timedelta, timezone

import db
from engine.solana.wallet_reader import get_token_price_usd

log = logging.getLogger(__name__)


async def _run_once(context):
    now = datetime.now(timezone.utc)
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM dca_orders WHERE status='active' AND next_order_at<=NOW() AND orders_placed < num_orders")
            orders = [dict(r) for r in cur.fetchall()]

    for order in orders:
        price = await get_token_price_usd(order.get("token_address"))
        if float(order.get("min_price") or 0) and price < float(order["min_price"]):
            continue
        if float(order.get("max_price") or 0) and price > float(order["max_price"]):
            continue

        placed = int(order.get("orders_placed") or 0) + 1
        status = "completed" if placed >= int(order.get("num_orders") or 1) else "active"
        next_at = now + timedelta(seconds=int(order.get("interval_secs") or 60))
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE dca_orders SET orders_placed=%s,next_order_at=%s,status=%s WHERE id=%s",
                    (placed, next_at, status, order["id"]),
                )
            conn.commit()
        db.log_audit(action="dca_fill", details={"order_id": order["id"], "order": placed, "total": order.get("num_orders")}, success=True)


async def run_dca_executor(context):
    try:
        await asyncio.wait_for(_run_once(context), timeout=30)
    except asyncio.TimeoutError:
        db.log_audit(action="dca_executor_timeout", details={}, success=False, error="timeout")
    except Exception as exc:
        log.error("dca executor failed: %s", exc)
