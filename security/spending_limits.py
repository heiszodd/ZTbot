import logging
import time
from collections import defaultdict

log = logging.getLogger(__name__)
MAX_SINGLE_TRADE_USD = {"hyperliquid": 1000.0, "solana": 500.0, "polymarket": 200.0}
MAX_DAILY_SPEND_USD = {"hyperliquid": 3000.0, "solana": 1500.0, "polymarket": 500.0}
MAX_OPEN_POSITIONS = {"hyperliquid": 5, "solana": 10, "polymarket": 10}
MAX_LEVERAGE = {"hyperliquid": 10}
MIN_TRADE_INTERVAL_SECONDS = 30
_daily_spend: dict = defaultdict(list)
_last_trade: dict = {}

def check_trade_size(section: str, amount_usd: float) -> tuple[bool, str]:
    limit = MAX_SINGLE_TRADE_USD.get(section, 500.0)
    if amount_usd > limit:
        return False, f"Trade size ${amount_usd:.2f} exceeds maximum ${limit:.2f} for {section}"
    return True, ""

def check_daily_spend(section: str, amount_usd: float) -> tuple[bool, str]:
    limit = MAX_DAILY_SPEND_USD.get(section, 1000.0)
    now = time.time()
    today = time.strftime("%Y-%m-%d")
    _daily_spend[section] = [e for e in _daily_spend[section] if time.strftime("%Y-%m-%d", time.gmtime(e["ts"])) == today]
    spent = sum(e["amount"] for e in _daily_spend[section])
    if spent + amount_usd > limit:
        remaining = max(0, limit - spent)
        return False, f"Daily limit ${limit:.2f} for {section}. Spent: ${spent:.2f}. Remaining: ${remaining:.2f}."
    return True, ""

def record_spend(section: str, amount_usd: float) -> None:
    _daily_spend[section].append({"amount": amount_usd, "ts": time.time()})
    log.info(f"Spend recorded: ${amount_usd:.2f} on {section}")

def check_position_count(section: str, current_count: int) -> tuple[bool, str]:
    limit = MAX_OPEN_POSITIONS.get(section, 5)
    if current_count >= limit:
        return False, f"Maximum open positions ({limit}) reached for {section}"
    return True, ""

def check_leverage(section: str, leverage: float) -> tuple[bool, str]:
    limit = MAX_LEVERAGE.get(section, 10)
    if leverage > limit:
        return False, f"Leverage {leverage}x exceeds bot maximum {limit}x for {section}"
    return True, ""

def check_duplicate_trade(market_key: str) -> tuple[bool, str]:
    last = _last_trade.get(market_key)
    if last:
        elapsed = time.time() - last
        if elapsed < MIN_TRADE_INTERVAL_SECONDS:
            wait = int(MIN_TRADE_INTERVAL_SECONDS - elapsed)
            return False, f"Trade on {market_key} placed {int(elapsed)}s ago. Wait {wait}s to prevent double-execution."
    return True, ""

def record_trade_time(market_key: str) -> None:
    _last_trade[market_key] = time.time()

def run_all_checks(section: str, amount_usd: float, market_key: str, leverage: float = 1.0, current_positions: int = 0) -> tuple[bool, list]:
    failures = []
    for allowed, reason in [
        check_trade_size(section, amount_usd),
        check_daily_spend(section, amount_usd),
        check_position_count(section, current_positions),
        check_leverage(section, leverage),
        check_duplicate_trade(market_key),
    ]:
        if not allowed:
            failures.append(reason)
    return len(failures) == 0, failures

def get_daily_summary() -> dict:
    today = time.strftime("%Y-%m-%d")
    summary = {}
    for section in ["hyperliquid", "solana", "polymarket"]:
        entries = [e for e in _daily_spend.get(section, []) if time.strftime("%Y-%m-%d", time.gmtime(e["ts"])) == today]
        spent = sum(e["amount"] for e in entries)
        limit = MAX_DAILY_SPEND_USD.get(section, 1000.0)
        summary[section] = {"spent": round(spent, 2), "limit": limit, "remaining": round(max(0, limit - spent), 2), "trades": len(entries)}
    return summary
