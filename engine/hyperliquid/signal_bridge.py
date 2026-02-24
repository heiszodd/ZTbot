import logging

from config import HL_ADDRESS

log = logging.getLogger(__name__)


async def enrich_signal_with_hl_plan(signal: dict) -> dict:
    from engine.hyperliquid.trade_planner import generate_hl_trade_plan, get_hl_market_for_pair

    try:
        pair = signal.get("pair", "")
        market = await get_hl_market_for_pair(pair)
        if not market:
            signal["hl_available"] = False
            return signal

        signal["hl_available"] = True
        signal["hl_market"] = market

        account_value = 0.0
        if HL_ADDRESS:
            from engine.hyperliquid.account_reader import fetch_account_summary

            summary = await fetch_account_summary(HL_ADDRESS)
            account_value = summary.get("account_value", 0)

        signal["hl_plan"] = await generate_hl_trade_plan(signal, account_value)
    except Exception as e:
        log.error("HL signal bridge error %s: %s", signal.get("pair", ""), e)
        signal["hl_available"] = False
    return signal
