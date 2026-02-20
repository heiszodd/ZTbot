"""Market data, Binance integrations, and utility pricing functions."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from statistics import mean

import requests

from config import BINANCE_BASE_URLS, CRYPTO_PAIRS

log = logging.getLogger(__name__)

BINANCE_KLINES_PATH = "/api/v3/klines"
BINANCE_TIME_PATH = "/api/v3/time"
BINANCE_EXCHANGE_INFO_PATH = "/api/v3/exchangeInfo"
BINANCE_MAX_LIMIT = 1000
KLINE_INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}
CACHE_DIR = Path(".cache/binance")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

FALLBACK_PRICES = {
    "BTCUSDT": 50000.0,
    "ETHUSDT": 3000.0,
    "SOLUSDT": 120.0,
    "BNBUSDT": 450.0,
    "XRPUSDT": 0.6,
    "DOGEUSDT": 0.11,
    "EURUSD": 1.08,
    "GBPUSD": 1.27,
    "XAUUSD": 2030.0,
    "USDJPY": 150.0,
    "AUDUSD": 0.65,
    "GBPJPY": 191.0,
}

_SESSION = requests.Session()
_SELECTED_BASE_URL: str | None = None


@dataclass(slots=True)
class Candle:
    open_time_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    close_time_ms: int
    trades_count: int


def _fallback_series(pair: str, days: int) -> list[float]:
    base = FALLBACK_PRICES.get(pair)
    if not base:
        return []
    return [base * (1 + ((i % 10) - 5) * 0.0012) for i in range(days * 24)]


def _cache_key(symbol: str, interval: str, start_ms: int, end_ms: int) -> Path:
    raw_key = f"{symbol}:{interval}:{start_ms}:{end_ms}"
    digest = hashlib.sha1(raw_key.encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"{symbol}_{interval}_{digest}.json"


def _save_cache(path: Path, payload: list[list]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _load_cache(path: Path) -> list[list] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _select_fastest_binance_base_url(timeout: float = 2.0) -> str:
    global _SELECTED_BASE_URL
    if _SELECTED_BASE_URL:
        return _SELECTED_BASE_URL

    timings: list[tuple[float, str]] = []
    for base_url in BINANCE_BASE_URLS:
        started = time.perf_counter()
        try:
            response = _SESSION.get(f"{base_url}{BINANCE_TIME_PATH}", timeout=timeout)
            response.raise_for_status()
            timings.append((time.perf_counter() - started, base_url))
        except Exception as exc:
            log.warning("Binance base URL check failed for %s: %s", base_url, exc)

    _SELECTED_BASE_URL = min(timings, key=lambda item: item[0])[1] if timings else BINANCE_BASE_URLS[0]
    log.info("Using Binance base URL: %s", _SELECTED_BASE_URL)
    return _SELECTED_BASE_URL


def _binance_get(path: str, params: dict, retries: int = 5, timeout: float = 10.0):
    base_url = _select_fastest_binance_base_url()
    backoff = 0.6
    for attempt in range(1, retries + 1):
        try:
            response = _SESSION.get(f"{base_url}{path}", params=params, timeout=timeout)
            if response.status_code == 429:
                raise requests.HTTPError("429 Too Many Requests", response=response)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and data.get("code") == -1003:
                raise requests.HTTPError("-1003 Too much request weight", response=response)
            return data
        except Exception as exc:
            if attempt == retries:
                raise
            sleep_for = min(backoff * (2 ** (attempt - 1)), 8.0)
            log.warning("Binance request failed (%s). attempt=%s/%s sleep=%.2fs", exc, attempt, retries, sleep_for)
            time.sleep(sleep_for)


def _parse_klines(raw_klines: list[list]) -> list[Candle]:
    candles: list[Candle] = []
    for row in raw_klines:
        candles.append(
            Candle(
                open_time_ms=int(row[0]),
                open=Decimal(row[1]),
                high=Decimal(row[2]),
                low=Decimal(row[3]),
                close=Decimal(row[4]),
                volume=Decimal(row[5]),
                close_time_ms=int(row[6]),
                trades_count=int(row[8]),
            )
        )
    return candles


def fetch_binance_klines(
    symbol: str,
    interval: str,
    start_time_ms: int,
    end_time_ms: int | None = None,
    limit: int = BINANCE_MAX_LIMIT,
    use_cache: bool = True,
    sleep_between_calls: float = 0.12,
) -> list[Candle]:
    """Fetch Binance klines with pagination and optional disk cache."""
    if interval not in KLINE_INTERVAL_MS:
        raise ValueError(f"Unsupported interval: {interval}")
    limit = max(1, min(limit, BINANCE_MAX_LIMIT))
    if end_time_ms is None:
        end_time_ms = int(time.time() * 1000)

    cache_file = _cache_key(symbol, interval, start_time_ms, end_time_ms)
    if use_cache:
        cached = _load_cache(cache_file)
        if cached is not None:
            return _parse_klines(cached)

    raw_all: list[list] = []
    cursor = start_time_ms

    while cursor < end_time_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": cursor,
            "endTime": end_time_ms,
            "limit": limit,
        }
        batch = _binance_get(BINANCE_KLINES_PATH, params=params)
        if not batch:
            break

        raw_all.extend(batch)
        last_close_ms = int(batch[-1][6])
        cursor = last_close_ms + 1

        if len(batch) < limit:
            break
        time.sleep(sleep_between_calls)

    if use_cache:
        _save_cache(cache_file, raw_all)
    return _parse_klines(raw_all)


def validate_kline_consistency(candles: list[Candle], interval: str) -> list[int]:
    """Return list of missing open_time_ms values if gaps are found."""
    if interval not in KLINE_INTERVAL_MS or len(candles) < 2:
        return []
    step = KLINE_INTERVAL_MS[interval]
    gaps: list[int] = []
    for idx in range(1, len(candles)):
        expected = candles[idx - 1].open_time_ms + step
        if candles[idx].open_time_ms != expected:
            gaps.append(expected)
    return gaps


def detect_fvg(candles: list[Candle]) -> list[dict]:
    """Detect simple ICT fair value gaps."""
    fvgs = []
    for idx in range(1, len(candles) - 1):
        left = candles[idx - 1]
        right = candles[idx + 1]
        if left.high < right.low:
            fvgs.append({"index": idx, "type": "bullish", "from": float(left.high), "to": float(right.low)})
        elif left.low > right.high:
            fvgs.append({"index": idx, "type": "bearish", "from": float(right.high), "to": float(left.low)})
    return fvgs


def detect_liquidity_sweeps(candles: list[Candle], lookback: int = 20, volume_spike: float = 1.8) -> list[dict]:
    sweeps = []
    for idx in range(lookback, len(candles)):
        current = candles[idx]
        window = candles[idx - lookback : idx]
        recent_high = max(c.high for c in window)
        recent_low = min(c.low for c in window)
        avg_vol = sum(c.volume for c in window) / Decimal(len(window))
        vol_spike = current.volume >= avg_vol * Decimal(str(volume_spike))

        upper_wick = current.high - max(current.open, current.close)
        lower_wick = min(current.open, current.close) - current.low

        if current.high > recent_high and upper_wick > (current.high - current.low) * Decimal("0.35") and vol_spike:
            sweeps.append({"index": idx, "side": "buy_side_liquidity", "level": float(recent_high)})
        if current.low < recent_low and lower_wick > (current.high - current.low) * Decimal("0.35") and vol_spike:
            sweeps.append({"index": idx, "side": "sell_side_liquidity", "level": float(recent_low)})
    return sweeps


def detect_order_blocks(candles: list[Candle], lookback: int = 30) -> list[dict]:
    order_blocks = []
    for idx in range(lookback, len(candles) - 2):
        pivot = candles[idx]
        window = candles[idx - lookback : idx]
        avg_vol = sum(c.volume for c in window) / Decimal(len(window))

        is_bear_reversal = pivot.close > pivot.open and candles[idx + 1].close < candles[idx + 1].open
        is_bull_reversal = pivot.close < pivot.open and candles[idx + 1].close > candles[idx + 1].open
        high_volume = pivot.volume >= avg_vol * Decimal("1.5")

        if is_bear_reversal and high_volume:
            order_blocks.append(
                {"index": idx, "type": "supply", "high": float(pivot.high), "low": float(pivot.low), "mitigated": False}
            )
        elif is_bull_reversal and high_volume:
            order_blocks.append(
                {"index": idx, "type": "demand", "high": float(pivot.high), "low": float(pivot.low), "mitigated": False}
            )
    return order_blocks


def fetch_historical_1m_btcusdt_2023_to_now() -> list[Candle]:
    """Example helper requested by users: 1m BTCUSDT from 2023-01-01 UTC to now."""
    start_ms = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    return fetch_binance_klines("BTCUSDT", "1m", start_ms)


def get_crypto_prices(pairs: list[str]) -> dict[str, float]:
    crypto_pairs = [pair for pair in pairs if pair in CRYPTO_PAIRS]
    if not crypto_pairs:
        return {p: FALLBACK_PRICES[p] for p in pairs if p in FALLBACK_PRICES}

    symbols = list(sorted(set(crypto_pairs)))
    try:
        tickers = _binance_get("/api/v3/ticker/price", params={"symbols": json.dumps(symbols)}, timeout=8.0)
        data = {t["symbol"]: float(t["price"]) for t in tickers}
        result = {}
        for pair in pairs:
            if pair in data:
                result[pair] = data[pair]
            elif pair in FALLBACK_PRICES:
                result[pair] = FALLBACK_PRICES[pair]
        return result
    except Exception as exc:
        log.error("Binance price error: %s", exc)
        return {p: FALLBACK_PRICES[p] for p in pairs if p in FALLBACK_PRICES}


def fetch_prices(pairs: list[str]) -> dict[str, float]:
    return get_crypto_prices(pairs)


def get_price(pair: str) -> float | None:
    return fetch_prices([pair]).get(pair)


def get_recent_series(pair: str, days: int = 7, interval: str = "1m") -> list[float]:
    days = max(1, min(days, 90))
    if pair not in CRYPTO_PAIRS:
        return _fallback_series(pair, days)

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (days * 24 * 60 * 60 * 1000)

    try:
        candles = fetch_binance_klines(pair, interval, start_ms, end_ms=end_ms)
        return [float(c.close) for c in candles]
    except Exception as exc:
        log.error("Binance klines error for %s: %s", pair, exc)
        return _fallback_series(pair, days)


def estimate_atr(prices: list[float], window: int = 14) -> float:
    if len(prices) < 3:
        return 0.0
    diffs = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
    sample = diffs[-window:] if len(diffs) >= window else diffs
    return mean(sample) if sample else 0.0


def calc_sl_tp(price: float, direction: str, atr: float | None = None):
    atr = atr if atr is not None and atr > 0 else max(price * 0.003, 0.0001)
    if direction == "BUY":
        sl = round(price - atr * 1.5, 6)
        tp = round(price + atr * 3.0, 6)
    else:
        sl = round(price + atr * 1.5, 6)
        tp = round(price - atr * 3.0, 6)
    return sl, tp, 2.0


def fmt_price(price: float | None) -> str:
    if price is None:
        return "N/A"
    if price >= 1000:
        return f"${price:,.2f}"
    if price >= 1:
        return f"${price:.4f}"
    return f"${price:.6f}"


def get_all_prices() -> dict[str, float]:
    return fetch_prices(CRYPTO_PAIRS)
