from datetime import datetime, timezone
from config import ATR_BANDS, SESSIONS, NEWS_BLACKOUT_MIN, TIER_RISK
from collections import defaultdict
from typing import Any
from decimal import Decimal
import prices as px

try:
    import db
except Exception:  # DB may be unavailable in local CLI usage
    db = None


def classify_volatility(atr_ratio: float) -> dict:
    for lo, hi, label, modifier in ATR_BANDS:
        if lo <= atr_ratio < hi:
            return {"label": label, "modifier": modifier}
    return {"label": "Extreme", "modifier": -1.0}


def calc_htf_modifier(htf_1h: str, htf_4h: str, bias: str) -> dict:
    aligned  = (htf_1h == bias) and (htf_4h == bias)
    conflict = (htf_1h != bias and htf_1h != "Neutral") or \
               (htf_4h != bias and htf_4h != "Neutral")
    if aligned:  return {"modifier":  0.5, "label": "Both 1H+4H aligned ✅"}
    if conflict: return {"modifier": -1.5, "label": "HTF conflict ❌"}
    return               {"modifier":  0.0, "label": "HTF neutral"}


def get_session(utc_hour: int = None) -> str:
    if utc_hour is None:
        utc_hour = datetime.now(timezone.utc).hour
    if 12 <= utc_hour < 16: return "Overlap"
    if  8 <= utc_hour < 16: return "London"
    if 13 <= utc_hour < 21: return "NY"
    if utc_hour >= 23 or utc_hour < 8: return "Asia"
    return "Off-Hours"


def score_setup(setup: dict, model: dict) -> dict:
    result = {
        "valid": True, "invalid_reason": None,
        "mandatory_failed": [], "passed_rules": [], "failed_rules": [],
        "raw_score": 0.0, "modifiers": [], "modifier_total": 0.0,
        "final_score": 0.0, "tier": None, "risk_pct": None,
        "vol_label": "Normal", "htf_label": "Neutral", "htf_confirmed": False, "htf_partial": False, "htf_conflict": False,
        "session": get_session(),
    }
    passed_ids = set(setup.get("passed_rule_ids", []))

    # ① Mandatory gate
    for rule in model.get("rules", []):
        if rule.get("mandatory") and rule["id"] not in passed_ids:
            result["valid"] = False
            result["mandatory_failed"].append(rule["name"])
    if not result["valid"]:
        result["invalid_reason"] = "Mandatory rule failed: " + ", ".join(result["mandatory_failed"])
        return result

    # ② News gate
    news_min = setup.get("news_minutes")
    if news_min is not None and news_min <= NEWS_BLACKOUT_MIN:
        result["valid"] = False
        result["invalid_reason"] = f"High-impact news in {news_min} min"
        return result

    # ③ Raw score
    for rule in model.get("rules", []):
        if rule["id"] in passed_ids:
            result["raw_score"] += rule["weight"]
            result["passed_rules"].append(rule)
        else:
            result["failed_rules"].append(rule)

    # ④ Modifiers
    vol = classify_volatility(setup.get("atr_ratio", 1.0))
    result["vol_label"] = vol["label"]
    if vol["modifier"] != 0:
        result["modifiers"].append({"label": f"Volatility ({vol['label']})", "value": vol["modifier"]})


    htf1 = setup.get("htf_1h", "Neutral")
    htf4 = setup.get("htf_4h", "Neutral")
    bias = model.get("bias", "Bullish")
    result["htf_confirmed"] = (htf1 == bias and htf4 == bias and htf1 != "Neutral" and htf4 != "Neutral")
    result["htf_partial"] = ((htf1 == bias) ^ (htf4 == bias))
    result["htf_conflict"] = (htf1 != bias and htf4 != bias and htf1 != "Neutral" and htf4 != "Neutral")
    htf = calc_htf_modifier(
        setup.get("htf_1h", "Neutral"),
        setup.get("htf_4h", "Neutral"),
        model.get("bias", "Bullish")
    )
    result["htf_label"] = htf["label"]
    if htf["modifier"] != 0:
        result["modifiers"].append({"label": htf["label"], "value": htf["modifier"]})

    result["modifier_total"] = sum(m["value"] for m in result["modifiers"])
    result["final_score"]    = round(result["raw_score"] + result["modifier_total"], 2)

    # ⑤ Tier
    if   result["final_score"] >= model.get("tier_a", 9.5):
        result["tier"] = "A"; result["risk_pct"] = TIER_RISK["A"]
    elif result["final_score"] >= model.get("tier_b", 7.5):
        result["tier"] = "B"; result["risk_pct"] = TIER_RISK["B"]
    elif result["final_score"] >= model.get("tier_c", 5.5):
        result["tier"] = "C"; result["risk_pct"] = TIER_RISK["C"]

    return result


def calc_trade_levels(price: float, direction: str, atr: float) -> dict:
    """
    Calculate entry, SL, TP from live price and ATR.
    SL = 1.5× ATR from entry, TP = 3× ATR (RR 1:2).
    """
    if direction == "BUY":
        entry = price
        sl    = round(price - atr * 1.5, 5)
        tp    = round(price + atr * 3.0, 5)
    else:
        entry = price
        sl    = round(price + atr * 1.5, 5)
        tp    = round(price - atr * 3.0, 5)
    rr = 2.0
    return {"entry": entry, "sl": sl, "tp": tp, "rr": rr}


def build_live_setup(model: dict, prices_series: list[float]) -> dict:
    """Generate a deterministic setup snapshot from recent prices."""
    if len(prices_series) < 20:
        return {"pair": model["pair"], "passed_rule_ids": []}

    recent = prices_series[-1]
    prev = prices_series[-6]
    mom = (recent - prev) / prev if prev else 0
    direction = "BUY" if mom >= 0 else "SELL"
    if model.get("bias") == "Bearish":
        direction = "SELL"
    elif model.get("bias") == "Bullish":
        direction = "BUY"

    passed = []
    for idx, rule in enumerate(model.get("rules", []), start=1):
        # Staggered deterministic pass rates by momentum and rule index
        threshold = 0.0005 * idx
        cond = abs(mom) >= threshold or (idx % 2 == 0)
        if cond:
            passed.append(rule["id"])

    return {
        "pair": model["pair"],
        "passed_rule_ids": passed,
        "atr_ratio": 1.0 + min(abs(mom) * 80, 1.5),
        "htf_1h": model.get("bias", "Neutral"),
        "htf_4h": model.get("bias", "Neutral"),
        "news_minutes": None,
        "direction": direction,
    }


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period or period <= 0:
        return None
    sample = values[-period:]
    return sum(sample) / period


def _rsi(values: list[float], period: int = 14) -> float:
    if len(values) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(len(values) - period, len(values)):
        delta = values[i] - values[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(candles: list[dict], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0.0
    tr = []
    for i in range(1, len(candles)):
        hi, lo = candles[i]["high"], candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr.append(max(hi - lo, abs(hi - prev_close), abs(lo - prev_close)))
    sample = tr[-period:] if len(tr) >= period else tr
    return (sum(sample) / len(sample)) if sample else 0.0


def _trend_label(closes: list[float]) -> str:
    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    if sma20 is None or sma50 is None:
        return "Neutral"
    if closes[-1] > sma20 > sma50:
        return "Bullish"
    if closes[-1] < sma20 < sma50:
        return "Bearish"
    return "Neutral"


def _evaluate_rule(rule_name: str, direction: str, candles: list[dict], stats: dict[str, float | str]) -> bool:
    n = rule_name.lower()
    close = candles[-1]["close"]
    open_ = candles[-1]["open"]
    high = candles[-1]["high"]
    low = candles[-1]["low"]
    prev_high = candles[-2]["high"]
    prev_low = candles[-2]["low"]
    prev_close = candles[-2]["close"]
    prev_open = candles[-2]["open"]

    bullish = direction == "BUY"
    trend_up = stats["trend"] == "Bullish"
    trend_down = stats["trend"] == "Bearish"
    rsi = float(stats["rsi"])
    vol_ratio = float(stats["volume_ratio"])

    if "engulf" in n:
        if bullish:
            return close > open_ and prev_close < prev_open and close > prev_open and open_ <= prev_close
        return close < open_ and prev_close > prev_open and close < prev_open and open_ >= prev_close
    if "trend" in n or "structure" in n or "higher highs" in n or "lower highs" in n:
        return trend_up if bullish else trend_down
    if "rsi below" in n or "discount" in n or "pullback" in n:
        return rsi < 45 if bullish else rsi > 55
    if "rsi above" in n or "premium" in n or "bounce" in n:
        return rsi > 55 if bullish else rsi < 45
    if "volume" in n and ("spike" in n or "above" in n or "breakout" in n):
        return vol_ratio >= 1.2
    if "volume" in n and ("declining" in n or "lower" in n):
        return vol_ratio <= 0.95
    if "liquidity sweep" in n or "sweep" in n:
        return low < prev_low and close > prev_low if bullish else high > prev_high and close < prev_high
    if "fvg" in n or "fair value gap" in n:
        return candles[-3]["high"] < low if bullish else candles[-3]["low"] > high
    if "session" in n or "london" in n or "ny" in n or "asia" in n:
        return True
    if "ob" in n or "order block" in n or "demand" in n or "supply" in n:
        body_mid = (open_ + close) / 2
        return low <= body_mid <= high

    # Fallback: directional close and volatility sanity
    return (close >= open_) if bullish else (close <= open_)


def build_live_setup_from_ohlcv(model: dict, candles: list[dict]) -> dict:
    if len(candles) < 60:
        return {"pair": model["pair"], "passed_rule_ids": []}
    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]
    atr = _atr(candles, 14)
    atr_ratio = atr / closes[-1] if closes[-1] else 0.0
    direction = "BUY" if model.get("bias") != "Bearish" else "SELL"
    if model.get("bias") == "Both":
        direction = "BUY" if closes[-1] >= closes[-6] else "SELL"

    stats = {
        "trend": _trend_label(closes),
        "rsi": _rsi(closes, 14),
        "volume_ratio": (volumes[-1] / (sum(volumes[-20:]) / 20)) if len(volumes) >= 20 and sum(volumes[-20:]) > 0 else 1.0,
    }

    passed = []
    for rule in model.get("rules", []):
        if _evaluate_rule(rule.get("name", ""), direction, candles, stats):
            passed.append(rule["id"])

    return {
        "pair": model["pair"],
        "passed_rule_ids": passed,
        "atr_ratio": 1.0 + min(atr_ratio * 100, 1.5),
        "htf_1h": stats["trend"],
        "htf_4h": stats["trend"],
        "news_minutes": None,
        "direction": direction,
    }


def backtest_model(model: dict, prices_series: list[float]) -> dict:
    """Simple bar-by-bar backtest returning win-rate and sample stats."""
    if len(prices_series) < 40:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "avg_rr": 0.0,
        }

    wins = losses = 0
    rr_values = []

    for i in range(30, len(prices_series) - 8, 3):
        window = prices_series[: i + 1]
        setup = build_live_setup(model, window)
        scored = score_setup(setup, model)
        if not scored["valid"] or not scored["tier"]:
            continue

        entry = prices_series[i]
        if setup["direction"] == "BUY":
            future_max = max(prices_series[i + 1 : i + 7])
            future_min = min(prices_series[i + 1 : i + 7])
            hit_tp = (future_max - entry) / entry >= 0.006
            hit_sl = (entry - future_min) / entry >= 0.003
        else:
            future_max = max(prices_series[i + 1 : i + 7])
            future_min = min(prices_series[i + 1 : i + 7])
            hit_tp = (entry - future_min) / entry >= 0.006
            hit_sl = (future_max - entry) / entry >= 0.003

        if hit_tp and not hit_sl:
            wins += 1
            rr_values.append(2.0)
        elif hit_sl:
            losses += 1
            rr_values.append(-1.0)

    trades = wins + losses
    avg_rr = round(sum(rr_values) / len(rr_values), 2) if rr_values else 0.0
    win_rate = round((wins / trades * 100), 2) if trades else 0.0

    return {
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "avg_rr": avg_rr,
    }


def _score_direction(pair: str, timeframe: str, model: dict, direction: str) -> dict | None:
    scan_model = {**model, "pair": pair, "timeframe": timeframe, "bias": direction}
    try:
        candles_raw = px.fetch_cryptocompare_ohlcv(
            pair,
            timeframe.lower(),
            int((datetime.now(timezone.utc).timestamp() - (7 * 24 * 3600)) * 1000),
            use_cache=True,
        )
    except Exception:
        return None
    candles = [{"open": float(c.open), "high": float(c.high), "low": float(c.low), "close": float(c.close), "volume": float(c.volume)} for c in candles_raw]
    if not candles:
        return None
    setup = build_live_setup_from_ohlcv(scan_model, candles)
    if not setup:
        return None
    scored = score_setup(setup, scan_model)
    atr = _atr(candles[-40:], 14)
    price = px.get_price(pair)
    if not price:
        return None
    sl, tp, _ = px.calc_sl_tp(price, setup.get("direction", "BUY"), atr=atr)
    scored["score"] = float(scored.get("final_score", 0) or 0)
    scored["entry"] = price
    scored["sl"] = sl
    scored["tp"] = tp
    scored["tp1"] = tp
    if setup.get("direction", "BUY") == "BUY":
        scored["tp2"] = round(tp + (tp - price) * 0.5, 5)
        scored["tp3"] = round(tp + (tp - price), 5)
    else:
        scored["tp2"] = round(tp - (price - tp) * 0.5, 5)
        scored["tp3"] = round(tp - (price - tp), 5)
    scored["direction"] = setup.get("direction", "BUY")
    scored["invalidated"] = not scored.get("valid", True)
    scored["invalidation_reason"] = scored.get("invalid_reason")
    return scored


def score_pair(pair: str, timeframe: str, model: dict) -> list[dict]:
    bias = model.get("bias", "Both")
    if bias == "Both":
        results = []
        for direction in ["Bullish", "Bearish"]:
            result = _score_direction(pair, timeframe, model, direction)
            if result and result.get("score", 0) >= model.get("min_score", 0):
                result["detected_direction"] = direction
                results.append(result)
        return results
    result = _score_direction(pair, timeframe, model, bias)
    if result:
        result["detected_direction"] = bias
    return [result] if result else []


MODELS = [
    "FVG Basic",
    "Sweep Reversal",
    "OB Confluence",
    "FVG + OB Filter",
    "Breaker Block",
]


def _to_candle_dict(candle: Any) -> dict:
    return {
        "timestamp": int(candle.open_time_ms // 1000),
        "open": float(candle.open),
        "high": float(candle.high),
        "low": float(candle.low),
        "close": float(candle.close),
        "volume": float(candle.volume),
    }


def _resample_candles(candles_1m: list[dict], timeframe: str) -> list[dict]:
    tf_to_minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
    step = tf_to_minutes.get(timeframe, 1)
    if step == 1:
        return candles_1m

    out = []
    bucket = []
    for candle in candles_1m:
        bucket.append(candle)
        if len(bucket) == step:
            out.append(
                {
                    "timestamp": bucket[0]["timestamp"],
                    "open": bucket[0]["open"],
                    "high": max(x["high"] for x in bucket),
                    "low": min(x["low"] for x in bucket),
                    "close": bucket[-1]["close"],
                    "volume": sum(x["volume"] for x in bucket),
                }
            )
            bucket = []
    return out


def _default_sl_tp(candles: list[dict], idx: int, side: str, rr: float = 2.0) -> tuple[float, float]:
    entry = candles[idx]["close"]
    lookback = candles[max(0, idx - 10) : idx + 1]
    swing_low = min(c["low"] for c in lookback)
    swing_high = max(c["high"] for c in lookback)
    if side == "long":
        risk = max(entry - swing_low, entry * 0.002)
        sl = entry - risk
        tp = entry + risk * rr
    else:
        risk = max(swing_high - entry, entry * 0.002)
        sl = entry + risk
        tp = entry - risk * rr
    return sl, tp




def _to_cc_candle(c: dict) -> px.Candle:
    ts_ms = c["timestamp"] * 1000
    return px.Candle(
        open_time_ms=ts_ms,
        open=Decimal(str(c["open"])),
        high=Decimal(str(c["high"])),
        low=Decimal(str(c["low"])),
        close=Decimal(str(c["close"])),
        volume=Decimal(str(c["volume"])),
        close_time_ms=ts_ms + 59999,
        trades_count=0,
    )

def _setups_from_fvg(candles: list[dict]) -> list[dict]:
    candle_objs = [_to_cc_candle(c) for c in candles]
    fvgs = px.detect_fvg(candle_objs)
    out = []
    for f in fvgs:
        idx = f["index"]
        side = "long" if f["type"] == "bullish" else "short"
        out.append({"index": idx, "type": side})
    return out


def _setups_from_sweeps(candles: list[dict]) -> list[dict]:
    candle_objs = [_to_cc_candle(c) for c in candles]
    sweeps = px.detect_liquidity_sweeps(candle_objs)
    out = []
    for s in sweeps:
        side = "short" if s["side"] == "buy_side_liquidity" else "long"
        out.append({"index": s["index"], "type": side})
    return out


def _setups_from_obs(candles: list[dict]) -> list[dict]:
    candle_objs = [_to_cc_candle(c) for c in candles]
    obs = px.detect_order_blocks(candle_objs)
    out = []
    for ob in obs:
        side = "short" if ob["type"] == "supply" else "long"
        out.append({"index": ob["index"], "type": side})
    return out


def get_setups(model_name: str, candles: list[dict]) -> list[dict]:
    model_key = model_name.lower()
    if "sweep" in model_key:
        return _setups_from_sweeps(candles)
    if "ob" in model_key or "order block" in model_key or "breaker" in model_key:
        return _setups_from_obs(candles)
    return _setups_from_fvg(candles)


def _simulate_trade(candles: list[dict], setup: dict) -> dict:
    idx = setup["index"]
    if idx >= len(candles) - 1:
        return {"status": "open"}

    side = setup.get("type", "long")
    entry = setup.get("entry_price", candles[idx]["close"])
    sl = setup.get("sl")
    tp = setup.get("tp")
    if sl is None or tp is None:
        sl, tp = _default_sl_tp(candles, idx, side)

    risk = abs(entry - sl)
    if risk <= 0:
        return {"status": "open"}

    for j in range(idx + 1, len(candles)):
        c = candles[j]
        if side == "long":
            hit_sl = c["low"] <= sl
            hit_tp = c["high"] >= tp
        else:
            hit_sl = c["high"] >= sl
            hit_tp = c["low"] <= tp

        if hit_sl and hit_tp:
            return {"status": "loss", "exit_index": j, "rr": -1.0, "exit_reason": "SL+TP same candle (conservative SL)"}
        if hit_tp:
            rr = abs(tp - entry) / risk
            return {"status": "win", "exit_index": j, "rr": rr, "exit_reason": "TP hit"}
        if hit_sl:
            return {"status": "loss", "exit_index": j, "rr": -1.0, "exit_reason": "SL hit"}

    return {"status": "open", "rr": 0.0, "exit_reason": "still open at end"}


def _parse_date_to_unix(value: str) -> int:
    return int(datetime.strptime(value.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def _available_models() -> list[str]:
    if db is not None:
        try:
            names = [m.get("name") for m in db.get_all_models() if m.get("name")]
            if names:
                return sorted(set(names))
        except Exception:
            pass
    return MODELS


def run_backtest() -> dict | None:
    print("\n=== Interactive Backtest ===")
    print("Pair examples: BTCUSDT, ETHUSDT (or enter fsym/tsym separately)")

    fsym = input("Base symbol (fsym, e.g. BTC): ").strip().upper() or "BTC"
    tsym = input("Quote symbol (tsym, e.g. USDT/USD): ").strip().upper() or "USDT"

    models = _available_models()
    print("\nAvailable models:")
    for i, model_name in enumerate(models, start=1):
        print(f"  {i}. {model_name}")

    model_choice = input("Choose model by number or name: ").strip()
    selected_model = models[0]
    if model_choice.isdigit() and 1 <= int(model_choice) <= len(models):
        selected_model = models[int(model_choice) - 1]
    else:
        for m in models:
            if m.lower() == model_choice.lower():
                selected_model = m
                break

    timeframe = (input("Timeframe (1m/5m/15m/1h): ").strip().lower() or "1m")
    if timeframe not in {"1m", "5m", "15m", "1h"}:
        print("Unsupported timeframe, defaulting to 1m")
        timeframe = "1m"

    start_date = input("Start date (YYYY-MM-DD): ").strip()
    end_date = input("End date (YYYY-MM-DD): ").strip()
    start_unix = _parse_date_to_unix(start_date)
    end_unix = _parse_date_to_unix(end_date) + 86399

    if start_unix >= end_unix:
        print("Invalid date range: start must be before end")
        return

    symbol = f"{fsym}{tsym}"
    print(f"\nFetching 1m candles for {symbol} from {start_date} to {end_date}...")
    print("Checking cache...")
    candles_1m = []

    try:
        frame = px.fetch_historical_1m(
            fsym=fsym,
            tsym=tsym,
            start_unix_sec=start_unix,
            end_unix_sec=end_unix,
        )
        if hasattr(frame, "empty") and not frame.empty:
            print("Skipping fetch — using cache when available via fetch_historical_1m().")
            candles_1m = [
                {
                    "timestamp": int(row["timestamp_ms"] // 1000),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume_from"]),
                }
                for _, row in frame.iterrows()
            ]
    except Exception as exc:
        print(f"fetch_historical_1m unavailable or failed ({exc}); using cached candle fetch fallback.")

    if not candles_1m:
        try:
            raw = px.fetch_cryptocompare_ohlcv(symbol, "1m", start_unix * 1000, end_time_ms=end_unix * 1000, use_cache=True)
            candles_1m = [_to_candle_dict(c) for c in raw]
        except Exception as exc:
            print(f"Data fetch failed: {exc}")
            return

    if len(candles_1m) < 30:
        print("Insufficient data returned for the selected period.")
        return

    candles = _resample_candles(candles_1m, timeframe)
    if len(candles) < 20:
        print("Insufficient candles after resampling.")
        return

    setups = get_setups(selected_model, candles)
    if not setups:
        print("No setups found for selected model/timeframe in this range.")
        return

    wins = losses = breakevens = opens = 0
    rr_total = 0.0
    gross_profit = 0.0
    gross_loss = 0.0
    trade_logs = []
    wins_by_day = defaultdict(int)
    losses_by_day = defaultdict(int)

    current_streak = 0
    streak_side = None
    max_win_streak = 0
    max_loss_streak = 0

    for setup in setups:
        if setup["index"] >= len(candles) - 2:
            continue
        outcome = _simulate_trade(candles, setup)
        entry_ts = candles[setup["index"]]["timestamp"]
        session_day = datetime.fromtimestamp(entry_ts, tz=timezone.utc).strftime("%Y-%m-%d")

        status = outcome.get("status", "open")
        rr = float(outcome.get("rr", 0.0))
        rr_total += rr

        if status == "win":
            wins += 1
            gross_profit += rr
            wins_by_day[session_day] += 1
            if streak_side == "win":
                current_streak += 1
            else:
                streak_side = "win"
                current_streak = 1
            max_win_streak = max(max_win_streak, current_streak)
        elif status == "loss":
            losses += 1
            gross_loss += abs(rr)
            losses_by_day[session_day] += 1
            if streak_side == "loss":
                current_streak += 1
            else:
                streak_side = "loss"
                current_streak = 1
            max_loss_streak = max(max_loss_streak, current_streak)
        elif status == "breakeven":
            breakevens += 1
            streak_side = None
            current_streak = 0
        else:
            opens += 1
            streak_side = None
            current_streak = 0

        trade_logs.append(
            {
                "day": session_day,
                "side": setup.get("type", "long"),
                "status": status,
                "rr": round(rr, 2),
                "reason": outcome.get("exit_reason", "n/a"),
            }
        )

    total_setups = wins + losses + breakevens + opens
    if total_setups == 0:
        print("No executable setups found after filtering.")
        return

    avg_rr = (gross_profit / wins) if wins else 0.0
    winrate = (wins / total_setups) * 100 if total_setups else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    best_win_day = max(wins_by_day.items(), key=lambda x: x[1]) if wins_by_day else ("N/A", 0)
    worst_loss_day = max(losses_by_day.items(), key=lambda x: x[1]) if losses_by_day else ("N/A", 0)

    print("\n| Metric | Value |")
    print("|---|---:|")
    print(f"| Pair | {symbol} |")
    print(f"| Model | {selected_model} |")
    print(f"| Timeframe | {timeframe} |")
    print(f"| Total setups | {total_setups} |")
    print(f"| Wins / Losses | {wins} / {losses} |")
    print(f"| Winrate | {winrate:.2f}% |")
    print(f"| Average RR (wins) | {avg_rr:.2f} |")
    print(f"| Net Profit (R ~= %) | {rr_total:.2f}% |")
    print(f"| Profit Factor | {profit_factor:.2f} |")
    print(f"| Most win session | {best_win_day[0]}: {best_win_day[1]} wins |")
    print(f"| Most loss session | {worst_loss_day[0]}: {worst_loss_day[1]} losses |")
    print(f"| Max win streak | {max_win_streak} |")
    print(f"| Max loss streak | {max_loss_streak} |")

    print("\nFirst 5 trades:")
    for t in trade_logs[:5]:
        print(f"- {t['day']} | {t['side']} | {t['status']} | RR {t['rr']} | {t['reason']}")


    return {
        "pair": symbol,
        "model": selected_model,
        "timeframe": timeframe,
        "range": f"{start_date} to {end_date}",
        "total_setups": total_setups,
        "wins": wins,
        "losses": losses,
        "winrate": round(winrate, 2),
        "avg_rr": round(avg_rr, 2),
        "net_pnl_pct": round(rr_total, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else float("inf"),
        "best_day": best_win_day[0],
        "worst_day": worst_loss_day[0],
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
    }


def check_false_breakout(candles, direction):
    if len(candles) < 3:
        return False
    c3, c2 = candles[-3], candles[-2]
    if direction == "BUY":
        return c2.get("low", 0) < c3.get("low", 0) and c2.get("close", 0) > c3.get("low", 0)
    return c2.get("high", 0) > c3.get("high", 0) and c2.get("close", 0) < c3.get("high", 0)


def check_volume_spike(candles, threshold=2.0):
    if len(candles) < 21:
        return False, 0.0
    vols = [float(c.get("volume", 0)) for c in candles[-21:-1]]
    avg = sum(vols) / len(vols) if vols else 0.0
    cur = float(candles[-1].get("volume", 0))
    if avg <= 0:
        return False, 0.0
    mult = cur / avg
    return mult >= threshold, round(mult, 2)


def classify_score_result(score_result: dict, model: dict) -> dict:
    min_score = float(model.get("min_score") or model.get("tier_c") or 1.0)
    score_value = float(score_result.get("score", score_result.get("final_score", 0.0)) or 0.0)
    score_pct = (score_value / min_score * 100) if min_score else 0.0

    rules = model.get("rules", []) or []
    passed_rules = score_result.get("passed_rules", []) or []
    failed_rules = score_result.get("failed_rules", []) or []
    mandatory_failed = score_result.get("mandatory_failed", []) or []

    passed_names = {r.get("name") if isinstance(r, dict) else r for r in passed_rules}
    mandatory_passed = [
        r.get("name")
        for r in rules
        if r.get("mandatory") and r.get("name") in passed_names
    ]

    rules_passed_count = len(passed_rules)
    rules_total_count = len(rules)
    rules_pct = (rules_passed_count / max(rules_total_count, 1)) * 100
    mandatory_all_passed = len(mandatory_failed) == 0

    invalidated = bool(score_result.get("invalidated")) or (score_result.get("valid") is False)
    reason = score_result.get("invalidation_reason") or score_result.get("invalid_reason")

    if invalidated:
        classification = "INVALIDATED"
    elif score_pct >= 100 and mandatory_all_passed:
        classification = "FULL_ALERT"
    elif score_pct >= 50 or rules_pct >= 50:
        classification = "PENDING"
    else:
        classification = "INSUFFICIENT"

    failed_sorted = sorted(
        [r for r in failed_rules if isinstance(r, dict)],
        key=lambda x: float(x.get("weight", 0) or 0),
        reverse=True,
    )
    closest_rules = failed_sorted[:3]

    missing_score = max(0.0, min_score - score_value)
    running = 0.0
    missing_rules = []
    for rule in failed_sorted:
        missing_rules.append(rule)
        running += float(rule.get("weight", 0) or 0)
        if running >= missing_score:
            break

    return {
        "classification": classification,
        "reason": reason,
        "score_pct": round(score_pct, 2),
        "rules_pct": round(rules_pct, 2),
        "rules_passed_count": rules_passed_count,
        "rules_total_count": rules_total_count,
        "mandatory_all_passed": mandatory_all_passed,
        "mandatory_passed": mandatory_passed,
        "mandatory_failed": mandatory_failed,
        "passed_rules": passed_rules,
        "failed_rules": failed_rules,
        "missing_score": round(missing_score, 2),
        "missing_rules": missing_rules,
        "closest_rules": closest_rules,
    }
