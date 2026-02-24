import logging
log = logging.getLogger(__name__)

def is_halted() -> bool:
    try:
        import db
        return db.is_trading_halted()
    except Exception as e:
        log.error(f"Emergency stop check failed: {e}")
        return True

def halt_trading(reason: str = "") -> None:
    import db
    db.set_trading_halted(True, reason=reason or "Manual stop")
    from security.key_manager import _clear_key_cache
    _clear_key_cache()
    log.critical(f"TRADING HALTED: {reason or 'Manual'}")

def resume_trading(reason: str = "") -> None:
    import db
    db.set_trading_halted(False, reason=reason or "Manual resume")
    log.warning(f"Trading resumed: {reason or 'Manual'}")

def require_not_halted(func):
    import functools
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        if is_halted():
            raise RuntimeError("Trading is halted. Run /resume to restart.")
        return await func(*args, **kwargs)
    return wrapper
