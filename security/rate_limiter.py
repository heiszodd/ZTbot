import time
from collections import defaultdict

_call_log: dict = defaultdict(list)
COMMANDS_PER_MINUTE = 20
TRADES_PER_HOUR = 10
TRADES_PER_DAY = 50
_trade_log: dict = defaultdict(list)


def check_command_rate(user_id: int) -> tuple[bool, str]:
    now = time.time()
    calls = [t for t in _call_log[user_id] if now - t < 60]
    _call_log[user_id] = calls
    if len(calls) >= COMMANDS_PER_MINUTE:
        wait = int(60 - (now - calls[0]))
        return False, f"Rate limit: {COMMANDS_PER_MINUTE} commands/minute. Wait {wait}s."
    calls.append(now)
    _call_log[user_id] = calls
    return True, ""


def check_trade_rate(user_id: int) -> tuple[bool, str]:
    now = time.time()
    trades = _trade_log[user_id]
    hour_trades = [t for t in trades if now - t < 3600]
    if len(hour_trades) >= TRADES_PER_HOUR:
        wait = int(3600 - (now - hour_trades[0]))
        return False, f"Trade rate limit: {TRADES_PER_HOUR}/hour. Wait {wait//60}min."
    day_trades = [t for t in trades if now - t < 86400]
    if len(day_trades) >= TRADES_PER_DAY:
        return False, f"Daily trade limit reached: {TRADES_PER_DAY}/day."
    trades.append(now)
    _trade_log[user_id] = [t for t in trades if now - t < 86400]
    return True, ""


def record_trade(user_id: int) -> None:
    _trade_log[user_id].append(time.time())


def get_rate_status(user_id: int) -> dict:
    now = time.time()
    calls = _call_log.get(user_id, [])
    trades = _trade_log.get(user_id, [])
    return {
        "commands_last_minute": len([t for t in calls if now - t < 60]),
        "commands_limit": COMMANDS_PER_MINUTE,
        "trades_last_hour": len([t for t in trades if now - t < 3600]),
        "trades_hour_limit": TRADES_PER_HOUR,
        "trades_today": len([t for t in trades if now - t < 86400]),
        "trades_day_limit": TRADES_PER_DAY,
    }
