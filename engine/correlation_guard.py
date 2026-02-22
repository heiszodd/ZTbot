CORRELATION_GROUPS = {
    "crypto_majors": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "AVAXUSDT", "ADAUSDT"],
    "btc_correlated": ["BTCUSDT", "ETHUSDT"],
    "gold": ["XAUUSD", "XAGUSD"],
}


def get_correlated_pairs(pair: str) -> list:
    correlated = []
    for _, pairs in CORRELATION_GROUPS.items():
        if pair in pairs:
            for p in pairs:
                if p != pair and p not in correlated:
                    correlated.append(p)
    return correlated


def check_correlation(new_pair: str, new_direction: str, open_trades: list) -> dict:
    correlated = get_correlated_pairs(new_pair)
    if not correlated:
        return {"conflict": False, "severity": "none", "reason": "", "conflicts": []}
    conflicts = []
    for trade in open_trades:
        trade_pair = trade.get("pair", "")
        trade_dir = str(trade.get("direction", "")).lower()
        if trade_pair not in correlated:
            continue
        if trade_dir == str(new_direction).lower():
            conflicts.append({"pair": trade_pair, "direction": trade_dir, "entry": trade.get("entry_price", 0)})
    if not conflicts:
        return {"conflict": False, "severity": "none", "reason": "", "conflicts": []}
    btc_group = CORRELATION_GROUPS["btc_correlated"]
    high_corr = new_pair in btc_group and any(c["pair"] in btc_group for c in conflicts)
    severity = "high" if high_corr else "medium"
    pair_list = ", ".join(c["pair"] for c in conflicts)
    reason = f"Already {new_direction.lower()} on {pair_list} — adding {new_pair} would create {'heavily ' if high_corr else ''}correlated exposure"
    return {"conflict": True, "severity": severity, "reason": reason, "conflicts": conflicts}
