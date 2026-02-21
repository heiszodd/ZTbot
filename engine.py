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
    if conflict: return {"modifier": -1.0, "label": "HTF conflict ❌"}
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
        "vol_label": "Normal", "htf_label": "Neutral",
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
    try:
        raw = px.fetch_cryptocompare_ohlcv(symbol, "1m", start_unix * 1000, end_time_ms=end_unix * 1000, use_cache=True)
    except Exception as exc:
        print(f"Data fetch failed: {exc}")
        return

    candles_1m = [_to_candle_dict(c) for c in raw]
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
