import asyncio
import logging

import db
from engine.solana.wallet_reader import get_token_price_usd

log = logging.getLogger(__name__)


async def _run_once(context):
    from engine.solana.jupiter_quotes import get_swap_quote, USDC_MINT
    from engine.solana.executor import execute_sol_sell
    from engine.execution_pipeline import run_execution_pipeline
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

        token = cfg.get("token_address")
        symbol = cfg.get("token_symbol") or token[:6]
        pos = db.get_sol_position(token)
        tokens_to_sell = float((pos or {}).get("tokens_held") or 0) * sell_pct / 100
        amount_usd = tokens_to_sell * price
        quote = await get_swap_quote(input_mint=token, output_mint=USDC_MINT, amount_usd=amount_usd, input_price=price)
        if "error" in quote:
            continue
        plan = {"coin": symbol, "symbol": symbol, "side": "Sell", "token_address": token, "input_mint": token, "output_mint": USDC_MINT, "size_usd": amount_usd, "entry_price": price, "stop_loss": 0, "sell_pct": sell_pct, "tokens_out": quote["tokens_out"], "slippage_bps": quote["slippage_bps"], "raw_quote": quote["raw_quote"]}
        result = await run_execution_pipeline("solana", plan, execute_sol_sell, 0, context, skip_confirm=True)
        db.log_audit(action="auto_sell_triggered", details={"token": token, "amount_sold": sell_pct, "trigger_reason": reason, "execution_result": result, "tx_id": result.get("tx_id", "")}, success=bool(result.get("success")))
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
