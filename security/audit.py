import logging
from datetime import datetime, timezone
log = logging.getLogger(__name__)

def log_event(action: str, details: dict, user_id: int = 0, success: bool = True, error: str = "") -> None:
    try:
        import db
        db.log_audit({"action": action, "details": details, "user_id": user_id, "success": success, "error": error, "timestamp": datetime.now(timezone.utc).isoformat()})
    except Exception as e:
        log.error(f"AUDIT LOG WRITE FAILED: {action} — {e}\nDetails: {details}")

def log_trade_attempt(section: str, plan: dict, user_id: int, blocked_by: str = "") -> None:
    log_event("trade_attempted", {"section": section, "coin": plan.get("coin", plan.get("symbol", "?")), "side": plan.get("side", "?"), "size_usd": plan.get("size_usd", 0), "entry": plan.get("entry_price", 0), "blocked_by": blocked_by}, user_id=user_id, success=not bool(blocked_by), error=blocked_by)

def log_trade_executed(section: str, plan: dict, tx_id: str, user_id: int) -> None:
    log_event("trade_executed", {"section": section, "coin": plan.get("coin", "?"), "side": plan.get("side", "?"), "size_usd": plan.get("size_usd", 0), "entry": plan.get("entry_price", 0), "tx_id": tx_id}, user_id=user_id, success=True)

def log_security_event(event_type: str, details: dict, user_id: int = 0) -> None:
    log.warning(f"SECURITY EVENT: {event_type} — user={user_id} details={details}")
    log_event(action=f"security_{event_type}", details=details, user_id=user_id, success=False, error=event_type)
