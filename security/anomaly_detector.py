import logging
log = logging.getLogger(__name__)
MAX_PRICE_DRIFT_PCT = 3.0
MAX_SIZE_MULTIPLE = 5.0

async def check_price_staleness(coin: str, signal_price: float, section: str) -> tuple[bool, str]:
    try:
        current_price = 0.0
        if section == "hyperliquid":
            from engine.hyperliquid.market_data import get_market_price
            current_price = await get_market_price(coin)
        elif section == "solana":
            from engine.solana.wallet_reader import get_token_price_usd
            current_price = await get_token_price_usd(coin)
        if current_price <= 0 or signal_price <= 0:
            return True, ""
        drift = abs(current_price - signal_price) / signal_price * 100
        if drift > MAX_PRICE_DRIFT_PCT:
            return False, f"Price drifted {drift:.1f}% since signal (max {MAX_PRICE_DRIFT_PCT}%). Signal: ${signal_price:.4f}  Now: ${current_price:.4f}. Re-generate trade plan."
        return True, ""
    except Exception as e:
        log.warning(f"Price staleness check: {e}")
        return True, ""

def check_size_anomaly(section: str, amount_usd: float) -> tuple[bool, str]:
    try:
        import db
        recent = db.get_recent_trade_sizes(section, limit=10)
        if not recent or len(recent) < 3:
            return True, ""
        avg_size = sum(recent) / len(recent)
        multiple = amount_usd / avg_size if avg_size > 0 else 0
        if multiple > MAX_SIZE_MULTIPLE:
            return False, f"Trade size ${amount_usd:.2f} is {multiple:.1f}x your recent average (${avg_size:.2f}). Unusual size blocked for safety."
        return True, ""
    except Exception as e:
        log.warning(f"Size anomaly check: {e}")
        return True, ""

def check_signal_duplicate(signal_id: str) -> tuple[bool, str]:
    if not signal_id:
        return True, ""
    try:
        import db
        if db.signal_already_executed(signal_id):
            return False, f"Signal {signal_id} was already executed. Duplicate blocked."
        return True, ""
    except Exception as e:
        log.warning(f"Duplicate signal check: {e}")
        return True, ""

async def run_all_anomaly_checks(section: str, plan: dict, signal_id: str = "") -> tuple[bool, list]:
    issues = []
    coin = plan.get("coin", "")
    signal_price = plan.get("entry_price", 0)
    amount_usd = plan.get("size_usd", 0)
    ok, msg = await check_price_staleness(coin, signal_price, section)
    if not ok:
        issues.append(msg)
    ok, msg = check_size_anomaly(section, amount_usd)
    if not ok:
        issues.append(msg)
    ok, msg = check_signal_duplicate(signal_id)
    if not ok:
        issues.append(msg)
    return len(issues) == 0, issues
