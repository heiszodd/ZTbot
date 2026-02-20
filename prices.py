"""Market data utilities powered by CryptoCompare for historical and live-ready feeds."""
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

try:
    import pandas as pd
except Exception:  # optional dependency for backtest dataframe export
    pd = None

from config import (
    CRYPTO_PAIRS,
    CRYPTOCOMPARE_API_KEY,
    CRYPTOCOMPARE_BASE_URL,
    CRYPTOCOMPARE_EXTRA_PARAMS,
)

log = logging.getLogger(__name__)

CRYPTOCOMPARE_HISTO_MINUTE_PATH = "/data/v2/histominute"
CRYPTOCOMPARE_HISTO_HOUR_PATH = "/data/v2/histohour"
CRYPTOCOMPARE_HISTO_DAY_PATH = "/data/v2/histoday"
CRYPTOCOMPARE_PRICE_MULTI_PATH = "/data/pricemulti"
CRYPTOCOMPARE_STREAM_URL = "wss://streamer.cryptocompare.com/v2"
CRYPTOCOMPARE_MAX_LIMIT = 2000

KLINE_INTERVAL_SEC = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}

CACHE_DIR = Path(".cache/cryptocompare")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

FALLBACK_PRICES = {
    "BTCUSDT": 50000.0,
    "ETHUSDT": 3000.0,
    "SOLUSDT": 120.0,
    "BNBUSDT": 450.0,
    "XRPUSDT": 0.6,
    "DOGEUSDT": 0.11,
}

_SESSION = requests.Session()


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


def _split_pair(symbol: str) -> tuple[str, str]:
    symbol = symbol.upper().strip()
    if "/" in symbol:
        base, quote = symbol.split("/", 1)
        return base, quote

    known_quotes = ["USDT", "USDC", "BUSD", "TUSD", "FDUSD", "USD", "EUR", "BTC", "ETH"]
    for quote in known_quotes:
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return symbol[: -len(quote)], quote

    if len(symbol) >= 6:
        return symbol[:-3], symbol[-3:]
    raise ValueError(f"Unable to parse symbol '{symbol}'. Use format like BTCUSDT or BTC/USD")


def _cache_key(prefix: str, payload: dict) -> Path:
    raw_key = f"{prefix}:{json.dumps(payload, sort_keys=True)}"
    digest = hashlib.sha1(raw_key.encode("utf-8")).hexdigest()[:20]
    return CACHE_DIR / f"{prefix}_{digest}.json"


def _save_cache(path: Path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _load_cache(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _request(path: str, params: dict, retries: int = 5, timeout: float = 10.0):
    if CRYPTOCOMPARE_API_KEY:
        params["api_key"] = CRYPTOCOMPARE_API_KEY
    if CRYPTOCOMPARE_EXTRA_PARAMS:
        params["extraParams"] = CRYPTOCOMPARE_EXTRA_PARAMS

    backoff = 1.0
    for attempt in range(1, retries + 1):
        try:
            resp = _SESSION.get(f"{CRYPTOCOMPARE_BASE_URL}{path}", params=params, timeout=timeout)
            if resp.status_code == 429:
                raise requests.HTTPError("429 Too Many Requests", response=resp)
            resp.raise_for_status()
            payload = resp.json()
            if isinstance(payload, dict) and payload.get("Response") == "Error":
                raise RuntimeError(payload.get("Message", "CryptoCompare API error"))
            return payload
        except Exception as exc:
            if attempt == retries:
                raise
            sleep_for = min(backoff * (2 ** (attempt - 1)), 10.0)
            log.warning("CryptoCompare request failed (%s). attempt=%s/%s sleep=%.1fs", exc, attempt, retries, sleep_for)
            time.sleep(sleep_for)


def _parse_histodata_rows(rows: list[dict], interval_sec: int) -> list[Candle]:
    candles: list[Candle] = []
    for row in rows:
        open_time_sec = int(row.get("time", 0))
        if open_time_sec <= 0:
            continue
        candles.append(
            Candle(
                open_time_ms=open_time_sec * 1000,
                open=Decimal(str(row.get("open", 0.0))),
                high=Decimal(str(row.get("high", 0.0))),
                low=Decimal(str(row.get("low", 0.0))),
                close=Decimal(str(row.get("close", 0.0))),
                volume=Decimal(str(row.get("volumefrom", 0.0))),
                close_time_ms=(open_time_sec + interval_sec) * 1000 - 1,
                trades_count=0,
            )
        )
    return candles


def fetch_cryptocompare_ohlcv(
    symbol: str,
    interval: str,
    start_time_ms: int,
    end_time_ms: int | None = None,
    use_cache: bool = True,
) -> list[Candle]:
    """Fetch OHLCV candles with backwards pagination (up to 2000 per call)."""
    normalized_interval = interval.lower()
    if normalized_interval == "1h":
        normalized_interval = "1h"
    if normalized_interval not in KLINE_INTERVAL_SEC:
        raise ValueError(f"Unsupported interval: {interval}")

    interval_sec = KLINE_INTERVAL_SEC[normalized_interval]
    if end_time_ms is None:
        end_time_ms = int(time.time() * 1000)

    cache_payload = {
        "symbol": symbol,
        "interval": normalized_interval,
        "start_time_ms": start_time_ms,
        "end_time_ms": end_time_ms,
    }
    cache_file = _cache_key("hist", cache_payload)
    if use_cache:
        cached = _load_cache(cache_file)
        if cached is not None:
            return _parse_histodata_rows(cached, interval_sec)

    base, quote = _split_pair(symbol)
    endpoint = CRYPTOCOMPARE_HISTO_MINUTE_PATH
    aggregate = max(1, interval_sec // 60)
    if interval_sec >= 3600 and interval_sec < 86400:
        endpoint = CRYPTOCOMPARE_HISTO_HOUR_PATH
        aggregate = max(1, interval_sec // 3600)
    elif interval_sec >= 86400:
        endpoint = CRYPTOCOMPARE_HISTO_DAY_PATH
        aggregate = max(1, interval_sec // 86400)

    start_sec = int(start_time_ms // 1000)
    end_sec = int(end_time_ms // 1000)

    rows_all: list[dict] = []
    seen_times: set[int] = set()
    cursor_to_ts: int | None = end_sec

    while True:
        params = {
            "fsym": base,
            "tsym": quote,
            "limit": CRYPTOCOMPARE_MAX_LIMIT,
            "aggregate": aggregate,
        }
        if cursor_to_ts is not None:
            params["toTs"] = cursor_to_ts

        payload = _request(endpoint, params=params)
        data_block = payload.get("Data", {}) if isinstance(payload, dict) else {}
        batch_rows = data_block.get("Data", []) if isinstance(data_block, dict) else []
        if not batch_rows:
            break

        batch_rows.sort(key=lambda row: row.get("time", 0))
        earliest = int(batch_rows[0].get("time", 0))

        for row in batch_rows:
            ts = int(row.get("time", 0))
            if ts < start_sec or ts > end_sec:
                continue
            if ts in seen_times:
                continue
            seen_times.add(ts)
            rows_all.append(row)

        if earliest <= start_sec:
            break

        next_to_ts = earliest - 1
        if cursor_to_ts is not None and next_to_ts >= cursor_to_ts:
            break
        cursor_to_ts = next_to_ts
        time.sleep(0.08)

    rows_all.sort(key=lambda row: row.get("time", 0))
    if use_cache:
        _save_cache(cache_file, rows_all)
    return _parse_histodata_rows(rows_all, interval_sec)


def fetch_historical_1m(
    fsym: str = "BTC",
    tsym: str = "USD",
    start_unix_sec: int | None = None,
    end_unix_sec: int | None = None,
) -> "pd.DataFrame":
    """Full-pagination 1m OHLCV fetch for backtesting and ICT/SMC pattern scans."""
    now_sec = int(time.time())
    if end_unix_sec is None:
        end_unix_sec = now_sec
    if start_unix_sec is None:
        start_unix_sec = end_unix_sec - (24 * 60 * 60)

    symbol = f"{fsym.upper()}/{tsym.upper()}"
    candles = fetch_cryptocompare_ohlcv(
        symbol=symbol,
        interval="1m",
        start_time_ms=start_unix_sec * 1000,
        end_time_ms=end_unix_sec * 1000,
        use_cache=True,
    )

    if pd is None:
        raise RuntimeError("pandas is required for fetch_historical_1m(). Install pandas to get DataFrame output.")

    frame = pd.DataFrame(
        {
            "timestamp_ms": [c.open_time_ms for c in candles],
            "open": [float(c.open) for c in candles],
            "high": [float(c.high) for c in candles],
            "low": [float(c.low) for c in candles],
            "close": [float(c.close) for c in candles],
            "volume_from": [float(c.volume) for c in candles],
        }
    )
    if frame.empty:
        return frame

    frame = frame.drop_duplicates(subset=["timestamp_ms"]).sort_values("timestamp_ms").reset_index(drop=True)
    return frame


def cryptocompare_ws_details(fsym: str, tsym: str) -> dict[str, str | list[str]]:
    fsym = fsym.upper()
    tsym = tsym.upper()
    ws_url = f"{CRYPTOCOMPARE_STREAM_URL}?api_key={CRYPTOCOMPARE_API_KEY}" if CRYPTOCOMPARE_API_KEY else CRYPTOCOMPARE_STREAM_URL
    return {
        "url": ws_url,
        "subscribe": [f"5~CCCAGG~{fsym}~{tsym}", f"0~CCCAGG~{fsym}~{tsym}~m"],
    }


def _fallback_series(pair: str, days: int) -> list[float]:
    base = FALLBACK_PRICES.get(pair)
    if not base:
        return []
    return [base * (1 + ((i % 10) - 5) * 0.0012) for i in range(days * 24)]


def validate_kline_consistency(candles: list[Candle], interval: str) -> list[int]:
    normalized_interval = interval.lower()
    if normalized_interval not in KLINE_INTERVAL_SEC or len(candles) < 2:
        return []
    step = KLINE_INTERVAL_SEC[normalized_interval] * 1000
    gaps: list[int] = []
    for idx in range(1, len(candles)):
        expected = candles[idx - 1].open_time_ms + step
        if candles[idx].open_time_ms != expected:
            gaps.append(expected)
    return gaps


def detect_fvg(candles: list[Candle]) -> list[dict]:
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
    start_ms = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    return fetch_cryptocompare_ohlcv("BTCUSDT", "1m", start_ms)


def get_crypto_prices(pairs: list[str]) -> dict[str, float]:
    if not pairs:
        return {}

    parsed: list[tuple[str, str, str]] = []
    for pair in sorted(set(pairs)):
        try:
            fsym, tsym = _split_pair(pair)
            parsed.append((pair, fsym, tsym))
        except ValueError:
            continue

    if not parsed:
        return {}

    quotes = sorted(set(tsym for _, _, tsym in parsed))
    if len(quotes) > 1:
        return {pair: FALLBACK_PRICES[pair] for pair in pairs if pair in FALLBACK_PRICES}

    fsyms = ",".join(fsym for _, fsym, _ in parsed)
    tsym = quotes[0]
    try:
        payload = _request(CRYPTOCOMPARE_PRICE_MULTI_PATH, {"fsyms": fsyms, "tsyms": tsym}, timeout=8.0)
        out: dict[str, float] = {}
        for pair, fsym, _ in parsed:
            price = payload.get(fsym, {}).get(tsym)
            if price is not None:
                out[pair] = float(price)
        return {pair: out[pair] for pair in pairs if pair in out}
    except Exception as exc:
        log.error("CryptoCompare live price error: %s", exc)
        return {pair: FALLBACK_PRICES[pair] for pair in pairs if pair in FALLBACK_PRICES}


def fetch_prices(pairs: list[str]) -> dict[str, float]:
    return get_crypto_prices(pairs)


def get_price(pair: str) -> float | None:
    return fetch_prices([pair]).get(pair)


def get_recent_series(pair: str, days: int = 7, interval: str = "1m") -> list[float]:
    days = max(1, min(days, 90))
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (days * 24 * 60 * 60 * 1000)

    try:
        candles = fetch_cryptocompare_ohlcv(pair, interval.lower(), start_ms, end_time_ms=end_ms)
        closes = [float(c.close) for c in candles]
        if closes:
            return closes
    except Exception as exc:
        log.error("CryptoCompare klines error for %s: %s", pair, exc)
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
