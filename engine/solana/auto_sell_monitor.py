import asyncio
import logging

import db
from engine.solana.wallet_reader import get_token_price_usd

log = logging.getLogger(__name__)


async def _run_once(context):
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM auto_sell_configs WHERE active=TRUE")
            configs = [dict(r) for r in cur.fetchall()]

    for cfg in configs:
        price = await get_token_price_usd(cfg.get("token_address"))
        entry = float(cfg.get("entry_price") or 0)
        if entry <= 0 or price <= 0:
            continue
        pct_change = (price - entry) / entry * 100
        updates = []
        reason = None
        sell_pct = None

        high = float(cfg.get("trailing_high") or 0)
        if cfg.get("trailing_stop_pct") is not None:
            if price > high:
                updates.append(("trailing_high", price))
                high = price
            if high > 0:
                trigger = high * (1 - float(cfg["trailing_stop_pct"]) / 100)
                if price <= trigger:
                    reason = f"Trailing SL (-{cfg['trailing_stop_pct']}% from peak)"
                    sell_pct = 100

        if reason is None and pct_change <= float(cfg.get("stop_loss_pct") or -20) and not cfg.get("sl_hit"):
            reason, sell_pct = "SL", 100
            updates.append(("sl_hit", True))
        if reason is None and pct_change >= float(cfg.get("tp1_pct") or 50) and not cfg.get("tp1_hit"):
            reason, sell_pct = "TP1", float(cfg.get("tp1_sell_pct") or 25)
            updates.append(("tp1_hit", True))
        if reason is None and pct_change >= float(cfg.get("tp2_pct") or 100) and not cfg.get("tp2_hit"):
            reason, sell_pct = "TP2", float(cfg.get("tp2_sell_pct") or 25)
            updates.append(("tp2_hit", True))
        if reason is None and pct_change >= float(cfg.get("tp3_pct") or 200) and not cfg.get("tp3_hit"):
            reason, sell_pct = "TP3", float(cfg.get("tp3_sell_pct") or 50)
            updates.append(("tp3_hit", True))

        if not reason:
            if updates:
                with db.get_conn() as conn:
                    with conn.cursor() as cur:
                        for col, val in updates:
                            cur.execute(f"UPDATE auto_sell_configs SET {col}=%s WHERE id=%s", (val, cfg["id"]))
                    conn.commit()
            continue

        db.log_audit(action="auto_sell_trigger", details={"config_id": cfg["id"], "reason": reason, "pct": sell_pct, "price": price}, success=True)
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                for col, val in updates:
                    cur.execute(f"UPDATE auto_sell_configs SET {col}=%s WHERE id=%s", (val, cfg["id"]))
                if reason in {"SL", "Trailing SL"} or sell_pct == 100:
                    cur.execute("UPDATE auto_sell_configs SET active=FALSE WHERE id=%s", (cfg["id"],))
            conn.commit()


async def run_auto_sell_monitor(context):
    try:
        await asyncio.wait_for(_run_once(context), timeout=30)
    except asyncio.TimeoutError:
        db.log_audit(action="auto_sell_monitor_timeout", details={}, success=False, error="timeout")
    except Exception as exc:
        log.error("auto sell monitor failed: %s", exc)
