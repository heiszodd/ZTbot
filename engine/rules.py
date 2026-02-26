import asyncio
import logging
import time as time_module
from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd

from config import BINANCE_BASE_URL, CRYPTOPANIC_TOKEN

log = logging.getLogger(__name__)

BINANCE_BASE = f"{BINANCE_BASE_URL.rstrip('/')}/api/v3"
_GLOBAL_CACHE = {}
_GLOBAL_CACHE_TTL = 25

HTF_MAP = {
    "1m": "5m",
    "3m": "15m",
    "5m": "15m",
    "15m": "1h",
    "30m": "4h",
    "1h": "4h",
    "2h": "4h",
    "4h": "1d",
    "6h": "1d",
    "12h": "1d",
    "1d": "1w",
}


def _normalize_symbol(pair: str) -> str:
    symbol = (pair or "").upper()
    symbol = symbol.replace("/", "").replace("-", "").replace("_", "")
    return symbol


def _normalize_interval(timeframe: str) -> str:
    mapping = {
        "1M": "1m",
        "3M": "3m",
        "5m": "5m",
        "5M": "5m",
        "15m": "15m",
        "15M": "15m",
        "30m": "30m",
        "30M": "30m",
        "1h": "1h",
        "1H": "1h",
        "2h": "2h",
        "2H": "2h",
        "4h": "4h",
        "4H": "4h",
        "6h": "6h",
        "6H": "6h",
        "12h": "12h",
        "12H": "12h",
        "1d": "1d",
        "1D": "1d",
        "3d": "3d",
        "1w": "1w",
        "1W": "1w",
    }
    return mapping.get(timeframe, (timeframe or "").lower())


def get_htf(timeframe: str) -> str:
    tf = _normalize_interval(timeframe)
    return HTF_MAP.get(tf, "4h")


def _confirmed(candles: list) -> list:
    return candles[:-1] if len(candles) > 1 else candles


async def get_candles(pair: str, timeframe: str, limit: int = 100, cache: dict = None, as_df: bool = False) -> list | pd.DataFrame:
    if cache is None:
        cache = {}

    symbol = _normalize_symbol(pair)
    interval = _normalize_interval(timeframe)
    cache_key = f"{symbol}_{interval}_{limit}"

    if cache_key in cache:
        return cache[cache_key]

    now = time_module.time()
    if cache_key in _GLOBAL_CACHE:
        entry = _GLOBAL_CACHE[cache_key]
        if now - entry["ts"] < _GLOBAL_CACHE_TTL:
            cache[cache_key] = entry["data"]
            return entry["data"]

    url = f"{BINANCE_BASE}/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": min(max(limit + 1, 2), 1000),
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params=params)
            if r.status_code == 400:
                log.warning("Binance 400 for %s %s - invalid symbol or interval", symbol, interval)
                return []
            if r.status_code == 429:
                log.warning("Binance rate limit hit - waiting 5s")
                await asyncio.sleep(5)
                return []
            r.raise_for_status()
            raw = r.json()
    except httpx.TimeoutException:
        log.error("Binance timeout for %s %s", symbol, interval)
        return []
    except Exception as exc:
        log.error("Binance fetch error %s %s: %s: %s", symbol, interval, type(exc).__name__, exc)
        return []

    if not isinstance(raw, list) or not raw:
        return []

    candles = []
    for k in raw:
        try:
            candles.append(
                {
                    "time": k[0] / 1000,
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                }
            )
        except (IndexError, ValueError, TypeError):
            continue

    _GLOBAL_CACHE[cache_key] = {"ts": now, "data": candles}
    cache[cache_key] = candles
    log.debug("Binance %s %s: %s candles fetched", symbol, interval, len(candles))

    if as_df:
        df = pd.DataFrame(candles)
        if not df.empty:
            # ICT engine expects 'timestamp' instead of 'time'
            df = df.rename(columns={"time": "timestamp"})
            # Convert timestamp to ms if necessary or just ensure it's numeric/datetime
            # ICT validate_ohlcv handles conversion if it's already a timestamp or numeric
        return df

    return candles


def find_swing_highs(candles: list, lookback: int = 3) -> list:
    confirmed = _confirmed(candles)
    lookback = max(2, int(lookback or 3))
    highs = []
    n = len(confirmed)
    if n < (lookback * 2 + 1):
        return highs
    for i in range(lookback, n - lookback):
        c = confirmed[i]
        is_high = all(c["high"] > confirmed[i - k]["high"] for k in range(1, lookback + 1)) and all(
            c["high"] > confirmed[i + k]["high"] for k in range(1, lookback + 1)
        )
        if is_high:
            highs.append({"price": c["high"], "time": c["time"], "index": i})
    return highs


def find_swing_lows(candles: list, lookback: int = 3) -> list:
    confirmed = _confirmed(candles)
    lookback = max(2, int(lookback or 3))
    lows = []
    n = len(confirmed)
    if n < (lookback * 2 + 1):
        return lows
    for i in range(lookback, n - lookback):
        c = confirmed[i]
        is_low = all(c["low"] < confirmed[i - k]["low"] for k in range(1, lookback + 1)) and all(
            c["low"] < confirmed[i + k]["low"] for k in range(1, lookback + 1)
        )
        if is_low:
            lows.append({"price": c["low"], "time": c["time"], "index": i})
    return lows


def is_bullish_trend(candles: list) -> bool:
    confirmed = _confirmed(candles)
    if len(confirmed) < 10:
        return False
    recent = confirmed[-20:]
    highs = find_swing_highs(recent, lookback=2)
    lows = find_swing_lows(recent, lookback=2)
    if len(highs) < 2 or len(lows) < 2:
        return False
    return highs[-1]["price"] > highs[-2]["price"] and lows[-1]["price"] > lows[-2]["price"]


def is_bearish_trend(candles: list) -> bool:
    confirmed = _confirmed(candles)
    if len(confirmed) < 10:
        return False
    recent = confirmed[-20:]
    highs = find_swing_highs(recent, lookback=2)
    lows = find_swing_lows(recent, lookback=2)
    if len(highs) < 2 or len(lows) < 2:
        return False
    return highs[-1]["price"] < highs[-2]["price"] and lows[-1]["price"] < lows[-2]["price"]


def find_order_blocks(candles: list, direction: str = "bullish", lookback: int = 50) -> list:
    confirmed = _confirmed(candles)
    confirmed = confirmed[-int(lookback or 50) :]
    if len(confirmed) < 10:
        return []

    obs = []
    for i in range(len(confirmed) - 2):
        c = confirmed[i]
        next1 = confirmed[i + 1]
        next2 = confirmed[i + 2]
        if direction == "bullish":
            if c["close"] >= c["open"]:
                continue
            if not (next1["close"] > c["high"] or next2["close"] > c["high"]):
                continue
            obs.append({"top": c["open"], "bottom": c["low"], "time": c["time"], "index": i, "type": "bullish", "valid": True})
        else:
            if c["close"] <= c["open"]:
                continue
            if not (next1["close"] < c["low"] or next2["close"] < c["low"]):
                continue
            obs.append({"top": c["high"], "bottom": c["open"], "time": c["time"], "index": i, "type": "bearish", "valid": True})

    for ob in obs:
        for j in range(ob["index"] + 3, len(confirmed)):
            c = confirmed[j]
            if direction == "bullish":
                if c["close"] < ob["bottom"]:
                    ob["valid"] = False
                    break
            else:
                if c["close"] > ob["top"]:
                    ob["valid"] = False
                    break
    return [ob for ob in obs if ob["valid"]]


def find_fvg(candles: list, direction: str = "bullish", lookback: int = 50) -> list:
    confirmed = _confirmed(candles)
    confirmed = confirmed[-int(lookback or 50) :]
    if len(confirmed) < 10:
        return []

    fvgs = []
    for i in range(len(confirmed) - 2):
        prev = confirmed[i]
        mid = confirmed[i + 1]
        nxt = confirmed[i + 2]
        if direction == "bullish":
            if nxt["low"] > prev["high"]:
                fvgs.append({"top": nxt["low"], "bottom": prev["high"], "time": mid["time"], "index": i, "type": "bullish", "filled": False})
        else:
            if nxt["high"] < prev["low"]:
                fvgs.append({"top": prev["low"], "bottom": nxt["high"], "time": mid["time"], "index": i, "type": "bearish", "filled": False})

    for fvg in fvgs:
        for j in range(fvg["index"] + 3, len(confirmed)):
            c = confirmed[j]
            if direction == "bullish":
                if c["low"] <= fvg["bottom"]:
                    fvg["filled"] = True
                    break
            else:
                if c["high"] >= fvg["top"]:
                    fvg["filled"] = True
                    break
    return [f for f in fvgs if not f["filled"]]


def detect_mss(candles: list, direction: str = "bullish") -> bool:
    confirmed = _confirmed(candles)
    if len(confirmed) < 10:
        return False
    last = confirmed[-1]
    if direction == "bullish":
        highs = find_swing_highs(confirmed[:-1], lookback=3)
        if not highs:
            return False
        return last["close"] > highs[-1]["price"]
    lows = find_swing_lows(confirmed[:-1], lookback=3)
    if not lows:
        return False
    return last["close"] < lows[-1]["price"]


def detect_liquidity_sweep(candles: list, direction: str = "bullish") -> bool:
    confirmed = _confirmed(candles)
    if len(confirmed) < 10:
        return False
    sweep_candle = confirmed[-2]
    last_candle = confirmed[-1]
    prior = confirmed[-22:-2]
    if not prior:
        return False
    if direction == "bullish":
        lowest_prior = min(c["low"] for c in prior)
        return (
            sweep_candle["low"] < lowest_prior
            and sweep_candle["close"] > lowest_prior
            and last_candle["close"] > last_candle["open"]
        )
    highest_prior = max(c["high"] for c in prior)
    return (
        sweep_candle["high"] > highest_prior
        and sweep_candle["close"] < highest_prior
        and last_candle["close"] < last_candle["open"]
    )


def calc_atr(candles: list, period: int = 14) -> float:
    confirmed = _confirmed(candles)
    if len(confirmed) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(confirmed)):
        c = confirmed[i]
        p = confirmed[i - 1]
        trs.append(max(c["high"] - c["low"], abs(c["high"] - p["close"]), abs(c["low"] - p["close"])))
    return sum(trs[-period:]) / period


def is_in_session(name: str) -> bool:
    hour = datetime.now(timezone.utc).hour
    sessions = {"Asia": (0, 8), "London": (7, 16), "NY": (13, 22), "Overlap": (13, 16)}
    start, end = sessions.get(name, (0, 24))
    return start <= hour < end


async def _bool_guard(fn, *args):
    try:
        return bool(await fn(*args))
    except Exception:
        return False



# ── Rule Registry ───────────────────────────────────────

async def wrapper_htf_bull(candles, **kwargs):
    cache = kwargs.get("cache")
    pair = kwargs.get("pair")
    tf = kwargs.get("tf")
    htf = get_htf(tf)
    htf_candles = await get_candles(pair, htf, 80, cache)
    return is_bullish_trend(htf_candles)

async def wrapper_htf_bear(candles, **kwargs):
    cache = kwargs.get("cache")
    pair = kwargs.get("pair")
    tf = kwargs.get("tf")
    htf = get_htf(tf)
    htf_candles = await get_candles(pair, htf, 80, cache)
    return is_bearish_trend(htf_candles)

def rule_htf_bullish(candles: list, **kwargs) -> bool:
    try: return is_bullish_trend(candles) # This is called with HTF candles if model tf is htf
    except Exception: return False

def rule_htf_bearish(candles: list, **kwargs) -> bool:
    try: return is_bearish_trend(candles)
    except Exception: return False

def rule_ltf_bullish_structure(candles: list, **kwargs) -> bool:
    try: return is_bullish_trend(candles)
    except Exception: return False

def rule_ltf_bearish_structure(candles: list, **kwargs) -> bool:
    try: return is_bearish_trend(candles)
    except Exception: return False

def rule_bullish_ob_present(candles: list, **kwargs) -> bool:
    try:
        if len(candles) < 10: return False
        obs = find_order_blocks(candles, "bullish", lookback=80)
        if not obs: return False
        current = candles[-1]["close"]
        for ob in reversed(obs[-3:]):
            if ob["bottom"] <= current <= ob["top"]: return True
            tolerance = ob["top"] * 0.003
            if ob["top"] <= current <= ob["top"] + tolerance: return True
        return False
    except Exception: return False

def rule_bearish_ob_present(candles: list, **kwargs) -> bool:
    try:
        if len(candles) < 10: return False
        obs = find_order_blocks(candles, "bearish", lookback=80)
        if not obs: return False
        current = candles[-1]["close"]
        for ob in reversed(obs[-3:]):
            if ob["bottom"] <= current <= ob["top"]: return True
            tolerance = ob["bottom"] * 0.003
            if ob["bottom"] - tolerance <= current <= ob["bottom"]: return True
        return False
    except Exception: return False

def rule_ob_respected(candles: list, **kwargs) -> bool:
    try:
        direction = kwargs.get("direction", "bullish")
        if len(candles) < 12: return False
        obs = find_order_blocks(candles, direction, lookback=80)
        if not obs: return False
        confirmed = _confirmed(candles)
        current = candles[-1]["close"]
        for ob in reversed(obs[-3:]):
            tapped = any(c["low"] <= ob["top"] and c["high"] >= ob["bottom"] for c in confirmed[-4:-1])
            moving = current > ob["top"] if direction == "bullish" else current < ob["bottom"]
            if tapped and moving: return True
        return False
    except Exception: return False

def rule_breaker_block(candles: list, **kwargs) -> bool:
    try:
        direction = kwargs.get("direction", "bullish")
        if len(candles) < 12: return False
        opp = "bearish" if direction == "bullish" else "bullish"
        obs = find_order_blocks(candles, opp, lookback=100)
        if not obs: return False
        current = candles[-1]["close"]
        for ob in reversed(obs[-5:]):
            if direction == "bullish" and ob["top"] * 0.997 <= current <= ob["top"] * 1.003: return True
            if direction == "bearish" and ob["bottom"] * 0.997 <= current <= ob["bottom"] * 1.003: return True
        return False
    except Exception: return False

def rule_bullish_fvg(candles: list, **kwargs) -> bool:
    try:
        if len(candles) < 10: return False
        fvgs = find_fvg(candles, "bullish", lookback=80)
        if not fvgs: return False
        current = candles[-1]["close"]
        return any(f["bottom"] <= current <= f["top"] for f in reversed(fvgs[-3:]))
    except Exception: return False

def rule_bearish_fvg(candles: list, **kwargs) -> bool:
    try:
        if len(candles) < 10: return False
        fvgs = find_fvg(candles, "bearish", lookback=80)
        if not fvgs: return False
        current = candles[-1]["close"]
        return any(f["bottom"] <= current <= f["top"] for f in reversed(fvgs[-3:]))
    except Exception: return False

def rule_fvg_within_ob(candles: list, **kwargs) -> bool:
    try:
        direction = kwargs.get("direction", "bullish")
        if len(candles) < 12: return False
        obs = find_order_blocks(candles, direction, lookback=100)
        fvgs = find_fvg(candles, direction, lookback=100)
        if not obs or not fvgs: return False
        latest_ob = obs[-1]
        return any(f["bottom"] >= latest_ob["bottom"] and f["top"] <= latest_ob["top"] for f in fvgs)
    except Exception: return False

def rule_liquidity_swept_bull(candles: list, **kwargs) -> bool:
    try: return detect_liquidity_sweep(candles, "bullish")
    except Exception: return False

def rule_liquidity_swept_bear(candles: list, **kwargs) -> bool:
    try: return detect_liquidity_sweep(candles, "bearish")
    except Exception: return False

def rule_mss_bullish(candles: list, **kwargs) -> bool:
    try: return detect_mss(candles, "bullish")
    except Exception: return False

def rule_mss_bearish(candles: list, **kwargs) -> bool:
    try: return detect_mss(candles, "bearish")
    except Exception: return False

def rule_bos_bullish(candles: list, **kwargs) -> bool:
    try:
        conf = _confirmed(candles)
        if len(conf) < 20: return False
        split = len(conf) // 2
        older, recent = conf[:split], conf[split:]
        return recent[-1]["close"] > max(c["high"] for c in older)
    except Exception: return False

def rule_bos_bearish(candles: list, **kwargs) -> bool:
    try:
        conf = _confirmed(candles)
        if len(conf) < 20: return False
        split = len(conf) // 2
        older, recent = conf[:split], conf[split:]
        return recent[-1]["close"] < min(c["low"] for c in older)
    except Exception: return False

def rule_pin_bar_bull(candles: list, **kwargs) -> bool:
    try:
        if len(candles) < 2: return False
        c = candles[-1]
        body = abs(c["close"] - c["open"])
        rng = c["high"] - c["low"]
        if rng <= 0: return False
        upper_wick = c["high"] - max(c["open"], c["close"])
        lower_wick = min(c["open"], c["close"]) - c["low"]
        return lower_wick > body * 2.5 and lower_wick > upper_wick * 2
    except Exception: return False

def rule_pin_bar_bear(candles: list, **kwargs) -> bool:
    try:
        if len(candles) < 2: return False
        c = candles[-1]
        body = abs(c["close"] - c["open"])
        rng = c["high"] - c["low"]
        if rng <= 0: return False
        upper_wick = c["high"] - max(c["open"], c["close"])
        lower_wick = min(c["open"], c["close"]) - c["low"]
        return upper_wick > body * 2.5 and upper_wick > lower_wick * 2
    except Exception: return False

def rule_bearish_engulfing(candles: list, **kwargs) -> bool:
    try:
        if len(candles) < 2: return False
        prev, curr = candles[-2], candles[-1]
        return prev["close"] > prev["open"] and curr["close"] < curr["open"] and curr["close"] < prev["open"] and curr["open"] > prev["close"]
    except Exception: return False

def rule_bullish_engulfing(candles: list, **kwargs) -> bool:
    try:
        if len(candles) < 2: return False
        prev, curr = candles[-2], candles[-1]
        return prev["close"] < prev["open"] and curr["close"] > curr["open"] and curr["close"] > prev["open"] and curr["open"] < prev["close"]
    except Exception: return False

def rule_volume_spike(candles: list, **kwargs) -> bool:
    try:
        if len(candles) < 21: return False
        avg = sum(x["volume"] for x in candles[-21:-1]) / 20
        return candles[-1]["volume"] > avg * 2
    except Exception: return False


async def rule_htf_ltf_aligned_bull(pair, tf, direction, cache):
    h = await get_candles(pair, get_htf(tf), 80, cache)
    l = await get_candles(pair, tf, 80, cache)
    return is_bullish_trend(h) and is_bullish_trend(l)


async def rule_htf_ltf_aligned_bear(pair, tf, direction, cache):
    h = await get_candles(pair, get_htf(tf), 80, cache)
    l = await get_candles(pair, tf, 80, cache)
    return is_bearish_trend(h) and is_bearish_trend(l)


async def rule_ob_on_htf(pair, tf, direction, cache):
    return len(find_order_blocks(await get_candles(pair, get_htf(tf), 120, cache), direction, lookback=100)) > 0


async def rule_nested_fvg(pair, tf, direction, cache):
    h = await get_candles(pair, get_htf(tf), 120, cache)
    l = await get_candles(pair, tf, 120, cache)
    hf = find_fvg(h, direction, lookback=100)
    lf = find_fvg(l, direction, lookback=100)
    if not hf or not lf:
        return False
    h_last = hf[-1]
    return any(x["bottom"] >= h_last["bottom"] and x["top"] <= h_last["top"] for x in lf)


async def rule_asian_range_swept(pair, tf, direction, cache):
    candles = await get_candles(pair, "1h", 36, cache)
    confirmed = _confirmed(candles)
    if len(confirmed) < 10:
        return False
    asian = [x for x in confirmed if datetime.fromtimestamp(x["time"], tz=timezone.utc).hour < 8]
    if not asian:
        return False
    ah = max(x["high"] for x in asian)
    al = min(x["low"] for x in asian)
    last = confirmed[-1]
    if direction == "bullish":
        return last["low"] < al and last["close"] > al
    return last["high"] > ah and last["close"] < ah


async def rule_stop_hunt(pair, tf, direction, cache):
    candles = await get_candles(pair, tf, 30, cache)
    confirmed = _confirmed(candles)
    if len(confirmed) < 3:
        return False
    c = confirmed[-2]
    nxt = confirmed[-1]
    body = abs(c["close"] - c["open"])
    total = c["high"] - c["low"]
    if total <= 0:
        return False
    upper_wick = c["high"] - max(c["open"], c["close"])
    lower_wick = min(c["open"], c["close"]) - c["low"]
    if direction == "bullish":
        return lower_wick > body * 2.5 and lower_wick > upper_wick * 2 and nxt["close"] > nxt["open"]
    return upper_wick > body * 2.5 and upper_wick > lower_wick * 2 and nxt["close"] < nxt["open"]


async def rule_choch_bullish(candles: list, **kwargs) -> bool:
    confirmed = _confirmed(candles)
    if len(confirmed) < 30:
        return False
    early = confirmed[:20]
    middle = confirmed[20:45]
    recent = confirmed[45:]
    if len(recent) < 2 or len(middle) < 4:
        return False

    bear_count = sum(1 for c in early if c["close"] < c["open"])
    prior_bearish = bear_count > len(early) * 0.55
    mid_lows = [c["low"] for c in middle]
    split = len(mid_lows) // 2
    if split == 0 or split == len(mid_lows):
        return False
    first_half_avg = sum(mid_lows[:split]) / split
    second_half_avg = sum(mid_lows[split:]) / (len(mid_lows) - split)
    higher_lows = second_half_avg > first_half_avg
    structure_break = max(c["close"] for c in recent) > max(c["high"] for c in early)
    return prior_bearish and higher_lows and structure_break


async def rule_choch_bearish(candles: list, **kwargs) -> bool:
    confirmed = _confirmed(candles)
    if len(confirmed) < 30:
        return False
    early = confirmed[:20]
    middle = confirmed[20:45]
    recent = confirmed[45:]
    if len(recent) < 2 or len(middle) < 4:
        return False

    bull_count = sum(1 for c in early if c["close"] > c["open"])
    prior_bullish = bull_count > len(early) * 0.55
    mid_highs = [c["high"] for c in middle]
    split = len(mid_highs) // 2
    if split == 0 or split == len(mid_highs):
        return False
    first_half_avg = sum(mid_highs[:split]) / split
    second_half_avg = sum(mid_highs[split:]) / (len(mid_highs) - split)
    higher_highs = second_half_avg < first_half_avg
    structure_break = min(c["close"] for c in recent) < min(c["low"] for c in early)
    return prior_bullish and higher_highs and structure_break


async def rule_session_london(pair, tf, direction, cache):
    return is_in_session("London")


async def rule_session_ny(pair, tf, direction, cache):
    return is_in_session("NY")


async def rule_session_overlap(pair, tf, direction, cache):
    return is_in_session("Overlap")


async def rule_london_open_sweep(pair, tf, direction, cache):
    return is_in_session("London") and await rule_asian_range_swept(pair, tf, direction, cache)


async def rule_ny_open_reversal(pair, tf, direction, cache):
    if not is_in_session("NY"):
        return False
    candles = await get_candles(pair, "1h", 12, cache)
    confirmed = _confirmed(candles)
    if len(confirmed) < 4:
        return False
    london = confirmed[-4:-1]
    cur = confirmed[-1]
    london_dir = "bullish" if london[-1]["close"] > london[0]["open"] else "bearish"
    if direction == "bearish":
        return london_dir == "bullish" and cur["close"] < london[-1]["close"]
    return london_dir == "bearish" and cur["close"] > london[-1]["close"]


async def rule_premium_zone(pair, tf, direction, cache):
    candles = await get_candles(pair, tf, 80, cache)
    confirmed = _confirmed(candles)
    if len(confirmed) < 10:
        return False
    hi = max(x["high"] for x in confirmed)
    lo = min(x["low"] for x in confirmed)
    return candles[-1]["close"] > (hi + lo) / 2


async def rule_discount_zone(pair, tf, direction, cache):
    candles = await get_candles(pair, tf, 80, cache)
    confirmed = _confirmed(candles)
    if len(confirmed) < 10:
        return False
    hi = max(x["high"] for x in confirmed)
    lo = min(x["low"] for x in confirmed)
    return candles[-1]["close"] < (hi + lo) / 2


async def rule_equilibrium(pair, tf, direction, cache):
    candles = await get_candles(pair, tf, 80, cache)
    confirmed = _confirmed(candles)
    if len(confirmed) < 10:
        return False
    hi = max(x["high"] for x in confirmed)
    lo = min(x["low"] for x in confirmed)
    mid = (hi + lo) / 2
    band = (hi - lo) * 0.05
    return abs(candles[-1]["close"] - mid) <= band


async def rule_near_htf_level(pair, tf, direction, cache):
    candles = await get_candles(pair, get_htf(tf), 120, cache)
    confirmed = _confirmed(candles)
    if len(confirmed) < 12:
        return False
    levels = [x["price"] for x in find_swing_highs(confirmed, 3)] + [x["price"] for x in find_swing_lows(confirmed, 3)]
    if not levels:
        return False
    current = candles[-1]["close"]
    return any(abs(current - lvl) / lvl < 0.005 for lvl in levels if lvl)


async def rule_doji_rejection(pair, tf, direction, cache):
    candles = await get_candles(pair, tf, 12, cache)
    confirmed = _confirmed(candles)
    if len(confirmed) < 2:
        return False
    c = confirmed[-2]
    rng = c["high"] - c["low"]
    if rng <= 0:
        return False
    return abs(c["close"] - c["open"]) / rng < 0.15


async def rule_volume_declining_pullback(pair, tf, direction, cache):
    candles = await get_candles(pair, tf, 12, cache)
    confirmed = _confirmed(candles)
    if len(confirmed) < 5:
        return False
    v = [x["volume"] for x in confirmed[-5:]]
    return v[-1] < v[-3] and v[-2] < v[-4]


async def rule_volume_expanding_breakout(pair, tf, direction, cache):
    candles = await get_candles(pair, tf, 30, cache)
    confirmed = _confirmed(candles)
    if len(confirmed) < 21:
        return False
    avg = sum(x["volume"] for x in confirmed[-21:-1]) / 20
    cur = confirmed[-1]
    if direction == "bullish":
        breakout = cur["close"] > max(x["high"] for x in confirmed[-10:-1])
    else:
        breakout = cur["close"] < min(x["low"] for x in confirmed[-10:-1])
    return breakout and cur["volume"] > avg * 1.5


async def rule_ote_zone(pair, timeframe, direction, cache) -> bool:
    candles = await get_candles(pair, timeframe, 100, cache)
    confirmed = _confirmed(candles)
    if len(confirmed) < 20:
        return False
    highs = find_swing_highs(confirmed, lookback=3)
    lows = find_swing_lows(confirmed, lookback=3)
    if not highs or not lows:
        return False
    current = candles[-1]["close"]
    swing_high = highs[-1]["price"]
    swing_low = lows[-1]["price"]
    swing_range = swing_high - swing_low
    if swing_range <= 0:
        return False
    if direction == "bullish":
        ote_top = swing_high - swing_range * 0.618
        ote_bottom = swing_high - swing_range * 0.79
        return ote_bottom <= current <= ote_top
    ote_bottom = swing_low + swing_range * 0.618
    ote_top = swing_low + swing_range * 0.79
    return ote_bottom <= current <= ote_top


async def rule_power_of_three(pair, tf, direction, cache):
    candles = await get_candles(pair, "1d", 5, cache)
    confirmed = _confirmed(candles)
    if len(confirmed) < 1:
        return False
    c = confirmed[-1]
    body = abs(c["close"] - c["open"])
    total = c["high"] - c["low"]
    if total <= 0:
        return False
    if direction == "bullish":
        return body / total > 0.5 and c["close"] > c["open"]
    return body / total > 0.5 and c["close"] < c["open"]


async def rule_judas_swing(pair, tf, direction, cache):
    if not is_in_session("London"):
        return False
    candles = await get_candles(pair, tf, 12, cache)
    confirmed = _confirmed(candles)
    if len(confirmed) < 4:
        return False
    first = confirmed[-4]
    recent = confirmed[-1]
    anchor = confirmed[-3]
    if direction == "bullish":
        return first["close"] < first["open"] and recent["close"] > anchor["open"]
    return first["close"] > first["open"] and recent["close"] < anchor["open"]


async def rule_silver_bullet_window(pair, tf, direction, cache):
    now = datetime.now(timezone.utc)
    if now.hour not in {15, 19}:
        return False
    candles = await get_candles(pair, "5m", 30, cache)
    if len(candles) < 10:
        return False
    return len(find_fvg(candles[-12:], direction, lookback=12)) > 0


async def rule_midnight_open(pair, tf, direction, cache):
    candles = await get_candles(pair, "1h", 30, cache)
    confirmed = _confirmed(candles)
    if len(confirmed) < 5:
        return False
    midnight = None
    for x in reversed(confirmed):
        if datetime.fromtimestamp(x["time"], tz=timezone.utc).hour == 0:
            midnight = x
            break
    if not midnight:
        return False
    return abs(candles[-1]["close"] - midnight["open"]) <= midnight["open"] * 0.001


async def rule_three_confluences(pair, tf, direction, cache):
    checks = [
        await (rule_htf_bullish if direction == "bullish" else rule_htf_bearish)(pair, tf, direction, cache),
        await (rule_mss_bullish if direction == "bullish" else rule_mss_bearish)(pair, tf, direction, cache),
        await (rule_bullish_fvg if direction == "bullish" else rule_bearish_fvg)(pair, tf, direction, cache),
        await rule_volume_spike(pair, tf, direction, cache),
    ]
    return sum(bool(x) for x in checks) >= 3


async def rule_news_clear(pair, tf, direction, cache):
    if not CRYPTOPANIC_TOKEN:
        return True
    try:
        symbol = _normalize_symbol(pair).replace("USDT", "")
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                "https://cryptopanic.com/api/v1/posts/",
                params={"auth_token": CRYPTOPANIC_TOKEN, "currencies": symbol, "filter": "important", "public": "true"},
            )
            r.raise_for_status()
            data = r.json()
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
        recent = [p for p in data.get("results", []) if datetime.fromisoformat(p["created_at"].replace("Z", "+00:00")) > cutoff]
        return len(recent) == 0
    except Exception:
        return True


async def rule_higher_high_confirmation(pair, tf, direction, cache):
    return await rule_bos_bullish(pair, tf, direction, cache)


async def rule_lower_low_confirmation(pair, tf, direction, cache):
    return await rule_bos_bearish(pair, tf, direction, cache)


# Rule Registry
RULE_REGISTRY = {
    "htf_bullish": wrapper_htf_bull,
    "htf_bearish": wrapper_htf_bear,
    "ltf_bullish": rule_ltf_bullish_structure,
    "ltf_bearish": rule_ltf_bearish_structure,
    "ob_bullish": rule_bullish_ob_present,
    "ob_bearish": rule_bearish_ob_present,
    "ob_respected": rule_ob_respected,
    "fvg_bullish": rule_bullish_fvg,
    "fvg_bearish": rule_bearish_fvg,
    "mss_bullish": rule_mss_bullish,
    "mss_bearish": rule_mss_bearish,
    "bos_bullish": rule_bos_bullish,
    "bos_bearish": rule_bos_bearish,
    "liquidity_swept_bull": rule_liquidity_swept_bull,
    "liquidity_swept_bear": rule_liquidity_swept_bear,
    "pin_bar_bull": rule_pin_bar_bull,
    "pin_bar_bear": rule_pin_bar_bear,
    "engulfing_bull": rule_bullish_engulfing,
    "engulfing_bear": rule_bearish_engulfing,
    "volume_spike": rule_volume_spike,
    "choch_bullish": rule_choch_bullish,
    "choch_bearish": rule_choch_bearish,
    "breaker_bullish": rule_breaker_block,
    "breaker_bearish": rule_breaker_block,
    
    # Direction-agnostic aliases (resolved in evaluate_rule)
    "bos": "bos",
    "mss": "mss",
    "choch": "choch",
    "fvg": "fvg",
    "ifvg": "fvg",
    "order_block": "ob",
    "ob": "ob",
    "liquidity_sweep": "liquidity_swept",
    "breaker": "breaker",
}

async def evaluate_rule(rule: dict, pair: str, timeframe: str, direction: str, cache: dict) -> bool:
    rule = rule or {}
    raw_id = str(rule.get("rule_id") or rule.get("tag") or rule.get("function") or rule.get("id") or "").lower()
    if not raw_id:
        return False
        
    # Resolve aliases and direction
    is_bull = "bull" in direction.lower() or direction.lower() in {"long", "buy"}
    suffix = "_bullish" if is_bull else "_bearish"
    
    fn_key = raw_id
    if fn_key in RULE_REGISTRY:
        val = RULE_REGISTRY[fn_key]
        if isinstance(val, str): # It's an alias like "bos" -> "bos_bullish"
            fn_key = f"{val}{suffix}"
    
    # Final check if key exists
    if fn_key not in RULE_REGISTRY:
        # One last try: append suffix if not present
        if not fn_key.endswith("_bullish") and not fn_key.endswith("_bearish"):
            if f"{fn_key}{suffix}" in RULE_REGISTRY:
                fn_key = f"{fn_key}{suffix}"
        
    if fn_key not in RULE_REGISTRY:
        log.warning("Rule not found: '%s' (resolved from '%s') - returning False", fn_key, raw_id)
        return False
        
    fn = RULE_REGISTRY[fn_key]
    if isinstance(fn, str): # Nested alias? shouldn't happen but safe-guard
        fn = RULE_REGISTRY.get(f"{fn}{suffix}")
        if not fn: return False

    candles = await get_candles(pair, timeframe, 150, cache)
    if not candles:
        return False

    try:
        kwargs = {"pair": pair, "tf": timeframe, "direction": direction, "cache": cache}
        if asyncio.iscoroutinefunction(fn):
            return await fn(candles, **kwargs)
        return bool(fn(candles, **kwargs))
    except Exception as e:
        log.error("Rule evaluation failed for '%s': %s", fn_key, e)
        return False
