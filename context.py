def get_daily_bias(pair, candles):
    if len(candles) < 2:
        return "Ranging"
    y = candles[-2]
    t = candles[-1]
    high = float(y.get("high", 0))
    low = float(y.get("low", 0))
    cur = float(t.get("close", t.get("price", 0)))
    if cur > high:
        return "Bullish (Above PDH)"
    if cur < low:
        return "Bearish (Below PDL)"
    rng = high - low
    if rng <= 0:
        return "Ranging"
    pos = (cur - low) / rng
    if pos >= 0.75:
        return "Upper Range"
    if pos <= 0.25:
        return "Lower Range"
    return "Ranging"
