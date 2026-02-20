"""data.py — live candle fetching and ATR calculation via CryptoCompare."""
import logging
import time

import prices as px

log = logging.getLogger(__name__)


def fetch_candles(pair: str, timeframe: str = "15m", limit: int = 60) -> list:
    """Returns list of [timestamp, open, high, low, close, volume]."""
    try:
        interval = timeframe.lower()
        end_ms = int(time.time() * 1000)
        step_ms = px.KLINE_INTERVAL_SEC.get(interval, 60) * 1000
        start_ms = end_ms - (limit + 5) * step_ms
        candles = px.fetch_cryptocompare_ohlcv(pair, interval, start_ms, end_time_ms=end_ms)
        return [[c.open_time_ms, float(c.open), float(c.high), float(c.low), float(c.close), float(c.volume)] for c in candles[-limit:]]
    except Exception as e:
        log.error(f"fetch_candles error {pair} {timeframe}: {e}")
        return []


def calc_atr(candles: list, period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        high = candles[i][2]
        low = candles[i][3]
        prev_close = candles[i - 1][4]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs[-period:]) / period


def get_atr_ratio(pair: str, timeframe: str = "15m") -> float:
    candles = fetch_candles(pair, timeframe, limit=60)
    if len(candles) < 30:
        return 1.0

    current_atr = calc_atr(candles[-15:], period=14)
    avg_atr = calc_atr(candles, period=14)

    if avg_atr == 0:
        return 1.0
    return round(current_atr / avg_atr, 3)


def get_htf_bias(pair: str, bias: str) -> tuple[str, str]:
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
        ema50 = _ema(closes, 50)
        last = closes[-1]
        if last > ema50 * 1.001:
            return "Bullish"
        if last < ema50 * 0.999:
            return "Bearish"
        return "Neutral"

    return _bias_for_tf("1h"), _bias_for_tf("4h")
