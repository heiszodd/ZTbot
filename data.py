"""
data.py — live candle fetching and ATR calculation via ccxt.
Plug this into handlers/alerts.py _evaluate_model() to get real atr_ratio.
"""
import logging
import ccxt

log = logging.getLogger(__name__)

# Binance for crypto, swap out for your broker for forex
exchange = ccxt.binance({"enableRateLimit": True})


def fetch_candles(pair: str, timeframe: str = "15m", limit: int = 60) -> list:
    """
    Returns list of [timestamp, open, high, low, close, volume].
    Pair format for crypto: BTC/USDT
    """
    # Normalise pair format  BTCUSDT → BTC/USDT
    if "/" not in pair and len(pair) > 5:
        base  = pair[:-4]
        quote = pair[-4:]
        pair  = f"{base}/{quote}"
    try:
        return exchange.fetch_ohlcv(pair, timeframe, limit=limit)
    except Exception as e:
        log.error(f"fetch_candles error {pair} {timeframe}: {e}")
        return []


def calc_atr(candles: list, period: int = 14) -> float:
    """Average True Range over the last `period` candles."""
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        high  = candles[i][2]
        low   = candles[i][3]
        prev_close = candles[i-1][4]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs[-period:]) / period


def get_atr_ratio(pair: str, timeframe: str = "15m") -> float:
    """
    Returns current ATR(14) divided by its own 14-period rolling average.
    < 0.7   → Low
    0.7-1.3 → Normal
    1.3-2.0 → High    (+0.5)
    > 2.0   → Extreme (-1.0)
    """
    candles = fetch_candles(pair, timeframe, limit=60)
    if len(candles) < 30:
        return 1.0  # default to Normal

    # Recent ATR (last 14 candles)
    current_atr = calc_atr(candles[-15:], period=14)

    # Rolling average ATR (over all fetched candles)
    avg_atr = calc_atr(candles, period=14)

    if avg_atr == 0:
        return 1.0
    return round(current_atr / avg_atr, 3)


def get_htf_bias(pair: str, bias: str) -> tuple[str, str]:
    """
    Returns (htf_1h, htf_4h) as 'Bullish', 'Bearish', or 'Neutral'
    based on EMA slope on 1H and 4H charts.

    Simple method: compare current close to EMA(50).
    Replace with your own structure logic if preferred.
    """
    def _ema(values: list, period: int) -> float:
        k = 2 / (period + 1)
        ema = values[0]
        for v in values[1:]:
            ema = v * k + ema * (1 - k)
        return ema

    def _bias_for_tf(tf: str) -> str:
        candles = fetch_candles(pair, tf, limit=60)
        if len(candles) < 55:
            return "Neutral"
        closes = [c[4] for c in candles]
        ema50  = _ema(closes, 50)
        last   = closes[-1]
        if last > ema50 * 1.001:   return "Bullish"
        if last < ema50 * 0.999:   return "Bearish"
        return "Neutral"

    htf_1h = _bias_for_tf("1h")
    htf_4h = _bias_for_tf("4h")
    return htf_1h, htf_4h
