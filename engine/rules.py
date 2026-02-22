import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

from config import CRYPTOPANIC_TOKEN

log = logging.getLogger(__name__)

_GLOBAL_CACHE: dict = {}
_GLOBAL_CACHE_TTL = 25


def _normalize_symbol(pair: str) -> str:
    symbol = (pair or "").upper().replace("/", "").replace("-", "")
    if not any(symbol.endswith(x) for x in ["USDT", "BTC", "ETH", "BNB", "USD"]):
        symbol += "USDT"
    return symbol


async def get_candles(pair, timeframe, limit=100, cache=None) -> list:
    key = f"{pair}:{timeframe}:{limit}"
    if cache is not None and key in cache:
        return cache[key]
    global_entry = _GLOBAL_CACHE.get(key)
    if global_entry:
        age = time.time() - global_entry["ts"]
        if age < _GLOBAL_CACHE_TTL:
            if cache is not None:
                cache[key] = global_entry["data"]
            return global_entry["data"]

    symbol = _normalize_symbol(pair)
    tf = timeframe.lower()
    tf_map = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "2h": "2h", "4h": "4h", "1d": "1d", "1w": "1w"}
    candles = []
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                "https://api.cryptocompare.com/api/v3/klines",
                params={"symbol": symbol, "interval": tf_map.get(tf, "1h"), "limit": limit},
            )
            r.raise_for_status()
            raw = r.json()
        if isinstance(raw, dict):
            raw = raw.get("Data") or raw.get("data") or []
        for c in raw:
            if isinstance(c, dict):
                candles.append({"time": int(c.get("time", 0)) * (1000 if c.get("time", 0) < 9999999999 else 1), "open": float(c.get("open", 0)), "high": float(c.get("high", 0)), "low": float(c.get("low", 0)), "close": float(c.get("close", 0)), "volume": float(c.get("volumefrom", c.get("volume", 0)))})
            else:
                candles.append({"time": int(c[0]), "open": float(c[1]), "high": float(c[2]), "low": float(c[3]), "close": float(c[4]), "volume": float(c[5])})
    except Exception as exc:
        log.debug("Candle fetch failed for %s %s: %s", pair, timeframe, exc)
        candles = []

    _GLOBAL_CACHE[key] = {"data": candles, "ts": time.time()}
    if cache is not None:
        cache[key] = candles
    if len(_GLOBAL_CACHE) > 200:
        cutoff = time.time() - 60
        for k in [k for k, v in _GLOBAL_CACHE.items() if v["ts"] < cutoff]:
            _GLOBAL_CACHE.pop(k, None)
    return candles


def find_swing_highs(candles, lookback=5) -> list:
    highs = []
    for i in range(lookback, len(candles) - lookback):
        if all(candles[i]["high"] >= candles[j]["high"] for j in range(i - lookback, i + lookback + 1) if j != i):
            highs.append({"index": i, "price": candles[i]["high"], "time": candles[i]["time"]})
    return highs


def find_swing_lows(candles, lookback=5) -> list:
    lows = []
    for i in range(lookback, len(candles) - lookback):
        if all(candles[i]["low"] <= candles[j]["low"] for j in range(i - lookback, i + lookback + 1) if j != i):
            lows.append({"index": i, "price": candles[i]["low"], "time": candles[i]["time"]})
    return lows


def is_bullish_trend(candles) -> bool:
    if len(candles) < 20:
        return False
    recent = candles[-20:]
    highs = [c["high"] for c in recent]
    lows = [c["low"] for c in recent]
    return highs[-1] > max(highs[:-5]) and lows[-1] > min(lows[:-5])


def is_bearish_trend(candles) -> bool:
    if len(candles) < 20:
        return False
    recent = candles[-20:]
    highs = [c["high"] for c in recent]
    lows = [c["low"] for c in recent]
    return highs[-1] < max(highs[:-5]) and lows[-1] < min(lows[:-5])


def find_order_blocks(candles, direction) -> list:
    obs = []
    for i in range(2, len(candles) - 1):
        prev, nxt = candles[i - 1], candles[i + 1]
        if direction == "bullish" and prev["close"] < prev["open"] and nxt["close"] > nxt["open"] and nxt["close"] > prev["open"]:
            obs.append({"index": i - 1, "top": prev["open"], "bottom": prev["close"], "time": prev["time"]})
        elif direction == "bearish" and prev["close"] > prev["open"] and nxt["close"] < nxt["open"] and nxt["close"] < prev["open"]:
            obs.append({"index": i - 1, "top": prev["close"], "bottom": prev["open"], "time": prev["time"]})
    return obs


def find_fvg(candles, direction) -> list:
    fvgs = []
    for i in range(1, len(candles) - 1):
        prev, curr, nxt = candles[i - 1], candles[i], candles[i + 1]
        if direction == "bullish" and nxt["low"] > prev["high"]:
            fvgs.append({"top": nxt["low"], "bottom": prev["high"], "index": i, "time": curr["time"], "filled": False})
        if direction == "bearish" and nxt["high"] < prev["low"]:
            fvgs.append({"top": prev["low"], "bottom": nxt["high"], "index": i, "time": curr["time"], "filled": False})
    for fvg in fvgs:
        for c in candles[fvg["index"] + 1 :]:
            if direction == "bullish" and c["low"] <= fvg["top"] and c["high"] >= fvg["bottom"]:
                fvg["filled"] = True
                break
            if direction == "bearish" and c["high"] >= fvg["bottom"] and c["low"] <= fvg["top"]:
                fvg["filled"] = True
                break
    return fvgs


def detect_mss(candles, direction) -> bool:
    if len(candles) < 20:
        return False
    recent = candles[-30:]
    if direction == "bullish":
        highs = find_swing_highs(recent, 3)
        return bool(highs) and recent[-1]["close"] > highs[-1]["price"]
    lows = find_swing_lows(recent, 3)
    return bool(lows) and recent[-1]["close"] < lows[-1]["price"]


def detect_liquidity_sweep(candles, direction) -> bool:
    if len(candles) < 10:
        return False
    recent = candles[-15:]
    if direction == "bullish":
        lows = find_swing_lows(recent[:-3], 2)
        return bool(lows) and recent[-2]["low"] < min(s["price"] for s in lows) and recent[-2]["close"] > min(s["price"] for s in lows)
    highs = find_swing_highs(recent[:-3], 2)
    return bool(highs) and recent[-2]["high"] > max(s["price"] for s in highs) and recent[-2]["close"] < max(s["price"] for s in highs)


def calc_atr(candles, period=14) -> float:
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        c, p = candles[i], candles[i - 1]
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

# rule implementations
async def rule_htf_bullish(pair, tf, direction, cache):
    return is_bullish_trend(await get_candles(pair, {"1h":"4h","4h":"1d","15m":"4h","30m":"4h","5m":"1h"}.get(tf,"4h"), 50, cache))
async def rule_htf_bearish(pair, tf, direction, cache):
    return is_bearish_trend(await get_candles(pair, {"1h":"4h","4h":"1d","15m":"4h","30m":"4h","5m":"1h"}.get(tf,"4h"), 50, cache))
async def rule_ltf_bullish_structure(pair, tf, direction, cache):
    return is_bullish_trend(await get_candles(pair, tf, 50, cache))
async def rule_ltf_bearish_structure(pair, tf, direction, cache):
    return is_bearish_trend(await get_candles(pair, tf, 50, cache))
async def rule_htf_ltf_aligned_bull(pair, tf, direction, cache):
    htf={"1h":"4h","4h":"1d","15m":"4h"}.get(tf,"4h");h=await get_candles(pair,htf,50,cache);l=await get_candles(pair,tf,50,cache);return is_bullish_trend(h) and is_bullish_trend(l)
async def rule_htf_ltf_aligned_bear(pair, tf, direction, cache):
    htf={"1h":"4h","4h":"1d","15m":"4h"}.get(tf,"4h");h=await get_candles(pair,htf,50,cache);l=await get_candles(pair,tf,50,cache);return is_bearish_trend(h) and is_bearish_trend(l)

async def rule_bullish_ob_present(pair, tf, direction, cache):
    c=await get_candles(pair,tf,100,cache);obs=find_order_blocks(c,"bullish");
    return bool(c and obs and obs[-1]["bottom"]<=c[-1]["close"]<=obs[-1]["top"]*1.005)
async def rule_bearish_ob_present(pair, tf, direction, cache):
    c=await get_candles(pair,tf,100,cache);obs=find_order_blocks(c,"bearish");
    return bool(c and obs and obs[-1]["bottom"]*0.995<=c[-1]["close"]<=obs[-1]["top"])
async def rule_ob_respected(pair, tf, direction, cache):
    c=await get_candles(pair,tf,100,cache);obs=find_order_blocks(c,direction); 
    if not c or not obs: return False
    ob=obs[-1];recent=c[-3:];entered=any(x["low"]<=ob["top"] and x["high"]>=ob["bottom"] for x in recent[:-1]);moving=recent[-1]["close"]>ob["top"] if direction=="bullish" else recent[-1]["close"]<ob["bottom"];return entered and moving
async def rule_breaker_block(pair, tf, direction, cache):
    c=await get_candles(pair,tf,100,cache);opp="bearish" if direction=="bullish" else "bullish";obs=find_order_blocks(c,opp)
    if not c or not obs:return False
    cur=c[-1]["close"]
    for ob in reversed(obs):
        if direction=="bullish" and ob["top"]*0.998<cur<ob["top"]*1.005:return True
        if direction=="bearish" and ob["bottom"]*0.995<cur<ob["bottom"]*1.002:return True
    return False
async def rule_ob_on_htf(pair, tf, direction, cache):
    return len(find_order_blocks(await get_candles(pair,{"1h":"4h","4h":"1d","15m":"4h"}.get(tf,"4h"),100,cache),direction))>0

async def rule_bullish_fvg(pair, tf, direction, cache):
    c=await get_candles(pair,tf,100,cache);o=[f for f in find_fvg(c,"bullish") if not f["filled"]];return bool(c and o and o[-1]["bottom"]<=c[-1]["close"]<=o[-1]["top"]*1.002)
async def rule_bearish_fvg(pair, tf, direction, cache):
    c=await get_candles(pair,tf,100,cache);o=[f for f in find_fvg(c,"bearish") if not f["filled"]];return bool(c and o and o[-1]["bottom"]*0.998<=c[-1]["close"]<=o[-1]["top"])
async def rule_fvg_within_ob(pair, tf, direction, cache):
    c=await get_candles(pair,tf,100,cache);obs=find_order_blocks(c,direction);fv=[f for f in find_fvg(c,direction) if not f["filled"]]
    return bool(obs and any(f["bottom"]>=obs[-1]["bottom"] and f["top"]<=obs[-1]["top"] for f in fv))
async def rule_nested_fvg(pair, tf, direction, cache):
    h=await get_candles(pair,{"15m":"1h","5m":"15m","1h":"4h"}.get(tf,"1h"),100,cache);l=await get_candles(pair,tf,100,cache)
    hf=[f for f in find_fvg(h,direction) if not f["filled"]];lf=[f for f in find_fvg(l,direction) if not f["filled"]]
    return bool(hf and lf and any(x["bottom"]>=hf[-1]["bottom"] and x["top"]<=hf[-1]["top"] for x in lf))

async def rule_liquidity_swept_bull(pair, tf, direction, cache): return detect_liquidity_sweep(await get_candles(pair,tf,50,cache),"bullish")
async def rule_liquidity_swept_bear(pair, tf, direction, cache): return detect_liquidity_sweep(await get_candles(pair,tf,50,cache),"bearish")
async def rule_asian_range_swept(pair, tf, direction, cache):
    c=await get_candles(pair,"1h",24,cache)
    if len(c)<8:return False
    asian=[x for x in c if datetime.fromtimestamp(x["time"]/1000,tz=timezone.utc).hour<8]
    if not asian:return False
    ah=max(x["high"] for x in asian);al=min(x["low"] for x in asian);last=c[-1]
    return (last["low"]<al and last["close"]>al) if direction=="bullish" else (last["high"]>ah and last["close"]<ah)
async def rule_stop_hunt(pair, tf, direction, cache):
    c=await get_candles(pair,tf,30,cache)
    if len(c)<5:return False
    x=c[-2];body=abs(x["close"]-x["open"])
    if direction=="bullish":return (min(x["open"],x["close"])-x["low"])>body*2 and x["close"]>x["open"]
    return (x["high"]-max(x["open"],x["close"]))>body*2 and x["close"]<x["open"]

async def rule_mss_bullish(pair, tf, direction, cache): return detect_mss(await get_candles(pair,tf,50,cache),"bullish")
async def rule_mss_bearish(pair, tf, direction, cache): return detect_mss(await get_candles(pair,tf,50,cache),"bearish")
async def rule_bos_bullish(pair, tf, direction, cache):
    c=await get_candles(pair,tf,30,cache);h=find_swing_highs(c[:-5],3) if c else [];return bool(h and c[-1]["close"]>h[-1]["price"])
async def rule_bos_bearish(pair, tf, direction, cache):
    c=await get_candles(pair,tf,30,cache);l=find_swing_lows(c[:-5],3) if c else [];return bool(l and c[-1]["close"]<l[-1]["price"])
async def rule_choch_bullish(pair, tf, direction, cache):
    c=await get_candles(pair,tf,50,cache)
    if len(c)<20:return False
    mid, recent = c[-20:-5], c[-5:]
    hs=find_swing_highs(mid,2)
    return is_bearish_trend(mid) and bool(hs) and max(x["high"] for x in recent)>hs[-1]["price"]
async def rule_choch_bearish(pair, tf, direction, cache):
    c=await get_candles(pair,tf,50,cache)
    if len(c)<20:return False
    mid, recent = c[-20:-5], c[-5:]
    ls=find_swing_lows(mid,2)
    return is_bullish_trend(mid) and bool(ls) and min(x["low"] for x in recent)<ls[-1]["price"]

async def rule_session_london(pair, tf, direction, cache): return is_in_session("London")
async def rule_session_ny(pair, tf, direction, cache): return is_in_session("NY")
async def rule_session_overlap(pair, tf, direction, cache): return is_in_session("Overlap")
async def rule_london_open_sweep(pair, tf, direction, cache): return is_in_session("London") and await rule_asian_range_swept(pair,tf,direction,cache)
async def rule_ny_open_reversal(pair, tf, direction, cache):
    if not is_in_session("NY"): return False
    c=await get_candles(pair,"1h",8,cache)
    if len(c)<4:return False
    london=c[-4:-1];cur=c[-1];ld="bullish" if london[-1]["close"]>london[0]["open"] else "bearish"
    return (ld=="bullish" and cur["close"]<london[-1]["close"]) if direction=="bearish" else (ld=="bearish" and cur["close"]>london[-1]["close"])

async def rule_premium_zone(pair, tf, direction, cache):
    c=await get_candles(pair,tf,50,cache); 
    return bool(c and c[-1]["close"]>(max(x["high"] for x in c)+min(x["low"] for x in c))/2)
async def rule_discount_zone(pair, tf, direction, cache):
    c=await get_candles(pair,tf,50,cache); 
    return bool(c and c[-1]["close"]<(max(x["high"] for x in c)+min(x["low"] for x in c))/2)
async def rule_equilibrium(pair, tf, direction, cache):
    c=await get_candles(pair,tf,50,cache)
    if not c:return False
    hi,lo=max(x["high"] for x in c),min(x["low"] for x in c);mid=(hi+lo)/2;band=(hi-lo)*0.05
    return abs(c[-1]["close"]-mid)<=band
async def rule_near_htf_level(pair, tf, direction, cache):
    c=await get_candles(pair,{"1h":"4h","4h":"1d","15m":"4h"}.get(tf,"4h"),50,cache)
    lv=[x["price"] for x in find_swing_highs(c,5)]+[x["price"] for x in find_swing_lows(c,5)]
    return bool(c and lv and any(abs(c[-1]["close"]-lvl)/lvl<0.005 for lvl in lv if lvl))

async def rule_bullish_engulfing(pair, tf, direction, cache):
    c=await get_candles(pair,tf,10,cache)
    return len(c)>=2 and c[-2]["close"]<c[-2]["open"] and c[-1]["close"]>c[-1]["open"] and c[-1]["open"]<=c[-2]["close"] and c[-1]["close"]>=c[-2]["open"]
async def rule_bearish_engulfing(pair, tf, direction, cache):
    c=await get_candles(pair,tf,10,cache)
    return len(c)>=2 and c[-2]["close"]>c[-2]["open"] and c[-1]["close"]<c[-1]["open"] and c[-1]["open"]>=c[-2]["close"] and c[-1]["close"]<=c[-2]["open"]
async def rule_pin_bar_bull(pair, tf, direction, cache):
    c=await get_candles(pair,tf,5,cache)
    if len(c)<2:return False
    x=c[-2];body=abs(x["close"]-x["open"]);lw=min(x["open"],x["close"])-x["low"];return body>0 and lw>body*2.5
async def rule_pin_bar_bear(pair, tf, direction, cache):
    c=await get_candles(pair,tf,5,cache)
    if len(c)<2:return False
    x=c[-2];body=abs(x["close"]-x["open"]);uw=x["high"]-max(x["open"],x["close"]);return body>0 and uw>body*2.5
async def rule_doji_rejection(pair, tf, direction, cache):
    c=await get_candles(pair,tf,10,cache)
    if len(c)<2:return False
    x=c[-2];rng=x["high"]-x["low"];return rng>0 and abs(x["close"]-x["open"])/rng<0.15
async def rule_volume_spike(pair, tf, direction, cache):
    c=await get_candles(pair,tf,25,cache); return len(c)>=21 and c[-1]["volume"]>(sum(x["volume"] for x in c[-21:-1])/20)*2
async def rule_volume_declining_pullback(pair, tf, direction, cache):
    c=await get_candles(pair,tf,10,cache);v=[x["volume"] for x in c[-5:]] if len(c)>=5 else [];return bool(v and v[-1]<v[-3] and v[-2]<v[-4])
async def rule_volume_expanding_breakout(pair, tf, direction, cache):
    c=await get_candles(pair,tf,25,cache)
    if len(c)<21:return False
    avg=sum(x["volume"] for x in c[-21:-1])/20;cur=c[-1]
    breakout=detect_mss(c,direction) or (direction=="bullish" and cur["close"]>max(x["high"] for x in c[-10:-1])) or (direction=="bearish" and cur["close"]<min(x["low"] for x in c[-10:-1]))
    return breakout and cur["volume"]>avg*1.5
async def rule_ote_zone(pair, tf, direction, cache):
    c=await get_candles(pair,tf,50,cache);hs=find_swing_highs(c,3);ls=find_swing_lows(c,3)
    if not c or not hs or not ls:return False
    cur=c[-1]["close"]
    if direction=="bullish":
        lo,hi=ls[-1]["price"],hs[-1]["price"]
        if lo>=hi:return False
        r=hi-lo;return hi-r*0.79<=cur<=hi-r*0.618
    hi,lo=hs[-1]["price"],ls[-1]["price"]
    if hi<=lo:return False
    r=hi-lo;return lo+r*0.618<=cur<=lo+r*0.79
async def rule_power_of_three(pair, tf, direction, cache):
    d=await get_candles(pair,"1d",3,cache)
    if not d:return False
    x=d[-1];body=abs(x["close"]-x["open"]);total=x["high"]-x["low"]
    return total>0 and body/total>0.5 and ((direction=="bullish" and x["close"]>x["open"]) or (direction!="bullish" and x["close"]<x["open"]))
async def rule_judas_swing(pair, tf, direction, cache):
    if not is_in_session("London"):return False
    c=await get_candles(pair,tf,10,cache)
    if len(c)<4:return False
    first,recent=c[-4],c[-1]
    return (first["close"]<first["open"] and recent["close"]>c[-3]["open"]) if direction=="bullish" else (first["close"]>first["open"] and recent["close"]<c[-3]["open"])
async def rule_silver_bullet_window(pair, tf, direction, cache):
    now=datetime.now(timezone.utc)
    if now.hour not in {15,19}:return False
    c=await get_candles(pair,"5m",20,cache)
    return len(find_fvg(c[-12:],direction))>0 if c else False
async def rule_midnight_open(pair, tf, direction, cache):
    c=await get_candles(pair,"1h",25,cache)
    mid=None
    for x in reversed(c):
        if datetime.fromtimestamp(x["time"]/1000,tz=timezone.utc).hour==0: mid=x; break
    return bool(mid and abs(c[-1]["close"]-mid["open"])<=mid["open"]*0.001)
async def rule_three_confluences(pair, tf, direction, cache):
    checks=[await (rule_htf_bullish if direction=="bullish" else rule_htf_bearish)(pair,tf,direction,cache),await (rule_mss_bullish if direction=="bullish" else rule_mss_bearish)(pair,tf,direction,cache),await (rule_bullish_fvg if direction=="bullish" else rule_bearish_fvg)(pair,tf,direction,cache),await rule_volume_spike(pair,tf,direction,cache)]
    return sum(bool(x) for x in checks)>=3
async def rule_news_clear(pair, tf, direction, cache):
    if not CRYPTOPANIC_TOKEN:return True
    try:
        symbol=pair.replace("USDT","").replace("/","")
        async with httpx.AsyncClient(timeout=5) as client:
            r=await client.get("https://cryptopanic.com/api/v1/posts/",params={"auth_token":CRYPTOPANIC_TOKEN,"currencies":symbol,"filter":"important","public":"true"})
            data=r.json()
        cutoff=datetime.now(timezone.utc)-timedelta(minutes=30)
        recent=[p for p in data.get("results",[]) if datetime.fromisoformat(p["created_at"].replace("Z","+00:00"))>cutoff]
        return len(recent)==0
    except Exception:
        return True
async def rule_higher_high_confirmation(pair, tf, direction, cache): return await rule_bos_bullish(pair,tf,direction,cache)
async def rule_lower_low_confirmation(pair, tf, direction, cache): return await rule_bos_bearish(pair,tf,direction,cache)

RULE_FUNCTIONS = {k:v for k,v in globals().items() if k.startswith("rule_")}

async def evaluate_rule(rule: dict, pair: str, timeframe: str, direction: str, cache: dict) -> bool:
    """
    Evaluate a rule against the current market context.

    Master model rules can use descriptive IDs (for example
    MM_ADV_09_rule_1) that do not directly map to RULE_FUNCTIONS.
    This resolver tries multiple fields and normalization strategies
    to find the real callable key.
    """
    rule = rule or {}
    lookup_fields = [
        rule.get("tag"),
        rule.get("rule_id"),
        rule.get("function"),
        rule.get("rule_name"),
        rule.get("id"),
        rule.get("name"),
    ]

    fn = None
    matched_key = None
    for candidate in lookup_fields:
        if not candidate:
            continue
        candidate = str(candidate).strip()
        if not candidate:
            continue

        if candidate in RULE_FUNCTIONS:
            fn = RULE_FUNCTIONS[candidate]
            matched_key = candidate
            break

        prefixed = f"rule_{candidate}"
        if prefixed in RULE_FUNCTIONS:
            fn = RULE_FUNCTIONS[prefixed]
            matched_key = prefixed
            break

        normalized = candidate.lower().replace(" ", "_").replace("-", "_").replace("/", "_")
        if normalized in RULE_FUNCTIONS:
            fn = RULE_FUNCTIONS[normalized]
            matched_key = normalized
            break

        normalized_prefixed = f"rule_{normalized}"
        if normalized_prefixed in RULE_FUNCTIONS:
            fn = RULE_FUNCTIONS[normalized_prefixed]
            matched_key = normalized_prefixed
            break

    if fn is None:
        name = str(rule.get("name", "")).strip().lower()
        if name:
            name_words = set(name.replace("-", " ").replace("_", " ").split())
            for rule_key in RULE_FUNCTIONS:
                comparable_key = rule_key.removeprefix("rule_")
                key_words = set(comparable_key.split("_"))
                if len(key_words & name_words) >= 2:
                    fn = RULE_FUNCTIONS[rule_key]
                    matched_key = rule_key
                    log.debug("Fuzzy matched rule '%s' -> '%s'", rule.get("name"), comparable_key)
                    break

    if fn is None:
        log.warning(
            "No function found for rule: id='%s' name='%s' tag='%s' — returning False",
            rule.get("id"),
            rule.get("name"),
            rule.get("tag"),
        )
        return False

    try:
        return bool(await fn(pair, timeframe, direction, cache))
    except Exception as exc:
        log.error(
            "Rule '%s' failed on %s/%s/%s: %s: %s",
            matched_key,
            pair,
            timeframe,
            direction,
            type(exc).__name__,
            exc,
        )
        return False
