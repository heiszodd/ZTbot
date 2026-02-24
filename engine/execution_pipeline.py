import logging
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)


async def run_execution_pipeline(
    section: str,
    plan: dict,
    executor: Callable[[dict], Awaitable[dict]],
    user_id: int,
    context,
    signal_id: str = "",
    skip_confirm: bool = False,
) -> dict:
    """Universal execution pipeline for all live trades."""
    from security.emergency_stop import is_halted
    from security.rate_limiter import check_trade_rate, record_trade
    from security.spending_limits import run_all_checks, record_spend, record_trade_time
    from security.anomaly_detector import run_all_anomaly_checks
    from security.audit import log_trade_attempt, log_trade_executed, log_event
    import db

    coin = plan.get("coin", plan.get("symbol", "?"))
    size_usd = float(plan.get("size_usd", 0) or 0)
    leverage = float(plan.get("leverage", 1.0) or 1.0)
    market_key = f"{section}:{coin}"

    if is_halted():
        log_event("trade_blocked_halt", {"section": section, "coin": coin}, user_id=user_id, success=False, error="Trading halted")
        return {"success": False, "error": "🛑 Trading is halted.\nRun /resume to restart."}

    allowed, reason = check_trade_rate(user_id)
    if not allowed:
        log_event("trade_blocked_rate", {"section": section, "reason": reason}, user_id=user_id, success=False, error=reason)
        return {"success": False, "error": reason}

    current_positions = db.count_open_positions(section)
    all_ok, failures = run_all_checks(
        section=section,
        amount_usd=size_usd,
        market_key=market_key,
        leverage=leverage,
        current_positions=current_positions,
    )
    if not all_ok:
        log_trade_attempt(section, plan, user_id, blocked_by="; ".join(failures))
        return {"success": False, "error": "⛔ Limit check failed:\n" + "\n".join([f"• {f}" for f in failures])}

    anomaly_ok, issues = await run_all_anomaly_checks(section=section, plan=plan, signal_id=signal_id)
    if not anomaly_ok:
        plan["anomaly_warnings"] = issues

    if not skip_confirm:
        from security.confirmation import create_confirmation, build_confirmation_message, build_confirmation_keyboard

        async def confirmed_executor(p: dict) -> dict:
            return await run_execution_pipeline(
                section=section,
                plan=p,
                executor=executor,
                user_id=user_id,
                context=context,
                signal_id=signal_id,
                skip_confirm=True,
            )

        confirm_id = create_confirmation(plan=plan, callback=confirmed_executor)
        return {
            "success": None,
            "pending": True,
            "confirm_id": confirm_id,
            "message": build_confirmation_message(plan, section, confirm_id),
            "keyboard": build_confirmation_keyboard(confirm_id, section),
        }

    log_trade_attempt(section, plan, user_id)
    try:
        result = await executor(plan)
    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)[:200]}"
        log_event("trade_execution_error", {"section": section, "coin": coin, "error": error_msg}, user_id=user_id, success=False, error=error_msg)
        return {"success": False, "error": f"Execution failed: {error_msg}"}

    if not result.get("success"):
        err = result.get("error", "")
        log_event("trade_failed", {"section": section, "coin": coin, "error": err}, user_id=user_id, success=False, error=err)
        return result

    tx_id = result.get("tx_id", "")
    record_spend(section, size_usd)
    record_trade_time(market_key)
    record_trade(user_id)

    if signal_id:
        db.mark_signal_executed(signal_id, section, coin)

    log_trade_executed(section, plan, tx_id, user_id)
    db.save_trade_to_history(section, plan, result)

    return {"success": True, "tx_id": tx_id, "result": result}
