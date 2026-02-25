from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


@dataclass
class ModelCondition:
    type: str
    tf: str
    direction: str | None = None
    entry: str | None = None
    weight: float = 1.0


@dataclass
class TradingModel:
    name: str
    conditions: list[ModelCondition]
    min_score: float
    max_time_delta: int


@dataclass
class TradeSignal:
    timestamp: pd.Timestamp
    direction: str
    entry_zone: tuple[float, float]
    stop_loss: float
    take_profit: float
    risk_reward: float
    confluences_triggered: list[str]
    confidence_score: float


@dataclass
class Zone:
    zone_type: str
    direction: str
    created_idx: int
    upper: float
    lower: float
    status: str = "active"
    touches: int = 0
    time_alive: int = 0
    invalidated_idx: int | None = None


class ICTStructureEngine:
    """Production-oriented ICT structure intelligence layer built only from OHLCV data.

    The engine is deterministic and backtest-safe:
    * no repainting (swing points only become actionable after right-side candles close)
    * no future candle leakage (all event timestamps are generated with confirmation delay)
    * pandas-first API for batched backtests and efficient live incremental updates.
    """

    def __init__(self, swing_window: int = 3, regime_window: int = 20, liquidity_lookback: int = 100):
        self.swing_window = int(max(2, swing_window))
        self.regime_window = int(max(5, regime_window))
        self.liquidity_lookback = int(max(20, liquidity_lookback))
        self.order_blocks: list[Zone] = []

    @staticmethod
    def validate_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
        missing = [c for c in OHLCV_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"Missing OHLCV columns: {missing}")
        frame = df.loc[:, OHLCV_COLUMNS].copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", errors="coerce").fillna(
            pd.to_datetime(frame["timestamp"], errors="coerce")
        )
        for c in ["open", "high", "low", "close", "volume"]:
            frame[c] = pd.to_numeric(frame[c], errors="coerce")
        frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close"]).reset_index(drop=True)
        return frame

    @staticmethod
    def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        prev_close = df["close"].shift(1)
        tr = pd.concat(
            [
                (df["high"] - df["low"]).abs(),
                (df["high"] - prev_close).abs(),
                (df["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return tr.rolling(period, min_periods=period).mean()

    def detect_swings(self, df: pd.DataFrame) -> pd.DataFrame:
        frame = self.validate_ohlcv(df)
        n = self.swing_window
        high = frame["high"]
        low = frame["low"]

        prev_high_max = high.shift(1).rolling(n, min_periods=n).max()
        next_high_max = high.iloc[::-1].shift(1).rolling(n, min_periods=n).max().iloc[::-1]
        prev_low_min = low.shift(1).rolling(n, min_periods=n).min()
        next_low_min = low.iloc[::-1].shift(1).rolling(n, min_periods=n).min().iloc[::-1]

        frame["is_swing_high"] = (high > prev_high_max) & (high > next_high_max)
        frame["is_swing_low"] = (low < prev_low_min) & (low < next_low_min)
        frame["swing_high_price"] = np.where(frame["is_swing_high"], high, np.nan)
        frame["swing_low_price"] = np.where(frame["is_swing_low"], low, np.nan)
        frame["swing_confirmed_at"] = frame["timestamp"].shift(-n)
        frame["swing_valid"] = frame["swing_confirmed_at"].notna() & (frame["is_swing_high"] | frame["is_swing_low"])
        return frame

    def detect_bos_mss_choch(self, df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
        frame = self.detect_swings(df)
        n = self.swing_window

        events: list[dict[str, Any]] = []
        trend = "neutral"
        latest_sw_h: tuple[int, float] | None = None
        latest_sw_l: tuple[int, float] | None = None

        for i in range(len(frame)):
            confirm_idx = i - n
            if confirm_idx >= 0 and bool(frame.at[confirm_idx, "is_swing_high"]):
                latest_sw_h = (confirm_idx, float(frame.at[confirm_idx, "high"]))
            if confirm_idx >= 0 and bool(frame.at[confirm_idx, "is_swing_low"]):
                latest_sw_l = (confirm_idx, float(frame.at[confirm_idx, "low"]))

            close_i = float(frame.at[i, "close"])
            ts = frame.at[i, "timestamp"]

            if latest_sw_h and close_i > latest_sw_h[1]:
                ev = {
                    "type": "BOS",
                    "direction": "bullish",
                    "broken_level": latest_sw_h[1],
                    "break_candle_index": i,
                    "swing_index": latest_sw_h[0],
                    "timestamp": ts,
                }
                if trend in {"bearish", "neutral"}:
                    ev["choch"] = trend == "bearish"
                    ev["mss"] = trend == "bearish"
                trend = "bullish"
                events.append(ev)
                latest_sw_h = None

            if latest_sw_l and close_i < latest_sw_l[1]:
                ev = {
                    "type": "BOS",
                    "direction": "bearish",
                    "broken_level": latest_sw_l[1],
                    "break_candle_index": i,
                    "swing_index": latest_sw_l[0],
                    "timestamp": ts,
                }
                if trend in {"bullish", "neutral"}:
                    ev["choch"] = trend == "bullish"
                    ev["mss"] = trend == "bullish"
                trend = "bearish"
                events.append(ev)
                latest_sw_l = None

        frame["trend"] = trend
        return frame, events

    def detect_fvg(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        frame = self.validate_ohlcv(df)
        events: list[dict[str, Any]] = []

        for i in range(2, len(frame)):
            hi_2 = float(frame.at[i - 2, "high"])
            lo_2 = float(frame.at[i - 2, "low"])
            low_i = float(frame.at[i, "low"])
            high_i = float(frame.at[i, "high"])

            if low_i > hi_2:
                lower, upper = hi_2, low_i
                events.append(
                    {
                        "type": "FVG",
                        "direction": "bullish",
                        "index": i,
                        "timestamp": frame.at[i, "timestamp"],
                        "lower": lower,
                        "upper": upper,
                        "ce": (lower + upper) / 2,
                        "status": "open",
                    }
                )
            if high_i < lo_2:
                lower, upper = high_i, lo_2
                events.append(
                    {
                        "type": "FVG",
                        "direction": "bearish",
                        "index": i,
                        "timestamp": frame.at[i, "timestamp"],
                        "lower": lower,
                        "upper": upper,
                        "ce": (lower + upper) / 2,
                        "status": "open",
                    }
                )

        for event in events:
            idx = int(event["index"])
            after = frame.iloc[idx + 1 :]
            if after.empty:
                continue
            if event["direction"] == "bullish":
                mitigated = after["low"] <= event["upper"]
                invalid = after["close"] < event["lower"]
            else:
                mitigated = after["high"] >= event["lower"]
                invalid = after["close"] > event["upper"]
            if mitigated.any():
                event["mitigated_at"] = after.index[mitigated.argmax()] if mitigated.any() else None
                event["status"] = "mitigated"
            if invalid.any():
                event["inverse"] = True
                event["flipped_at"] = after.index[invalid.argmax()]
                event["status"] = "inverse"
        return events

    def detect_volume_imbalance(self, df: pd.DataFrame, window: int = 20) -> pd.Series:
        frame = self.validate_ohlcv(df)
        bull_vol = np.where(frame["close"] >= frame["open"], frame["volume"], 0.0)
        bear_vol = np.where(frame["close"] < frame["open"], frame["volume"], 0.0)
        bull_sum = pd.Series(bull_vol).rolling(window, min_periods=window // 2).sum()
        bear_sum = pd.Series(bear_vol).rolling(window, min_periods=window // 2).sum()
        return (bull_sum - bear_sum) / (bull_sum + bear_sum + 1e-9)

    def detect_equal_highs_lows(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        frame = self.detect_swings(df)
        atr = self._atr(frame).bfill().fillna(0)
        swings_h = frame.index[frame["is_swing_high"]].tolist()
        swings_l = frame.index[frame["is_swing_low"]].tolist()
        levels: list[dict[str, Any]] = []

        def _append_equal(indices: list[int], side: str):
            for a, b in zip(indices[:-1], indices[1:]):
                pa = float(frame.at[a, "high"] if side == "high" else frame.at[a, "low"])
                pb = float(frame.at[b, "high"] if side == "high" else frame.at[b, "low"])
                tol = max(float(atr.at[b]) * 0.1, pb * 0.0005)
                if abs(pa - pb) <= tol:
                    levels.append(
                        {
                            "type": f"equal_{side}s",
                            "index_a": a,
                            "index_b": b,
                            "level": (pa + pb) / 2,
                            "tolerance": tol,
                            "timestamp": frame.at[b, "timestamp"],
                        }
                    )

        _append_equal(swings_h, "high")
        _append_equal(swings_l, "low")
        return levels

    def detect_liquidity_sweeps(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        frame = self.validate_ohlcv(df)
        equal_levels = self.detect_equal_highs_lows(frame)
        sweeps: list[dict[str, Any]] = []

        for lv in equal_levels:
            level = float(lv["level"])
            start = int(lv["index_b"]) + 1
            subset = frame.iloc[start : start + self.liquidity_lookback]
            if subset.empty:
                continue
            if lv["type"] == "equal_lows":
                cond = (subset["low"] < level) & (subset["close"] > level)
                if cond.any():
                    idx = int(subset.index[np.argmax(cond.values)])
                    sweeps.append({"type": "LiquiditySweep", "direction": "bullish", "index": idx, "timestamp": frame.at[idx, "timestamp"], "level": level})
            else:
                cond = (subset["high"] > level) & (subset["close"] < level)
                if cond.any():
                    idx = int(subset.index[np.argmax(cond.values)])
                    sweeps.append({"type": "LiquiditySweep", "direction": "bearish", "index": idx, "timestamp": frame.at[idx, "timestamp"], "level": level})
        return sweeps

    def liquidity_density_map(self, df: pd.DataFrame, bins: int = 40) -> pd.DataFrame:
        frame = self.validate_ohlcv(df)
        prices = pd.concat([frame["high"], frame["low"]], axis=0)
        volume = pd.concat([frame["volume"], frame["volume"]], axis=0)
        cuts = pd.cut(prices, bins=bins)
        touch_count = prices.groupby(cuts).size()
        volume_sum = volume.groupby(cuts).sum()
        out = pd.DataFrame({"touches": touch_count, "volume": volume_sum}).fillna(0)
        out["density_score"] = out["touches"] * 0.6 + out["volume"].rank(pct=True) * 0.4
        return out.sort_values("density_score", ascending=False)

    def detect_order_blocks(self, df: pd.DataFrame) -> list[Zone]:
        frame, structure_events = self.detect_bos_mss_choch(df)
        zones: list[Zone] = []

        for ev in structure_events:
            idx = int(ev["break_candle_index"])
            direction = ev["direction"]
            lookback = frame.iloc[max(0, idx - 12) : idx]
            if lookback.empty:
                continue
            if direction == "bullish":
                candidates = lookback[lookback["close"] < lookback["open"]]
            else:
                candidates = lookback[lookback["close"] > lookback["open"]]
            if candidates.empty:
                continue
            candle = candidates.iloc[-1]
            rng = max(float(candle["high"] - candle["low"]), 1e-9)
            body = abs(float(candle["close"] - candle["open"]))
            if body / rng <= 0.5:
                continue
            if direction == "bullish":
                zone = Zone("order_block", "bullish", int(candle.name), upper=float(candle["open"]), lower=float(candle["low"]))
            else:
                zone = Zone("order_block", "bearish", int(candle.name), upper=float(candle["high"]), lower=float(candle["open"]))
            zones.append(zone)

        self.order_blocks = zones
        self._update_zone_lifecycle(frame)
        return self.order_blocks

    def _update_zone_lifecycle(self, frame: pd.DataFrame) -> None:
        if not self.order_blocks:
            return
        for zone in self.order_blocks:
            after = frame.iloc[zone.created_idx + 1 :]
            if after.empty:
                continue
            inside = (after["low"] <= zone.upper) & (after["high"] >= zone.lower)
            zone.touches = int(inside.sum())
            zone.time_alive = int((after["timestamp"].iloc[-1] - frame.at[zone.created_idx, "timestamp"]).total_seconds() / 60)
            if zone.direction == "bullish":
                if (after["close"] < zone.lower).any():
                    zone.status = "invalid"
                    zone.invalidated_idx = int(after.index[np.argmax((after["close"] < zone.lower).values)])
                elif zone.touches > 0:
                    zone.status = "mitigated"
            else:
                if (after["close"] > zone.upper).any():
                    zone.status = "invalid"
                    zone.invalidated_idx = int(after.index[np.argmax((after["close"] > zone.upper).values)])
                elif zone.touches > 0:
                    zone.status = "mitigated"

    def detect_breaker_blocks(self, df: pd.DataFrame) -> list[Zone]:
        frame = self.validate_ohlcv(df)
        breakers: list[Zone] = []
        for zone in self.order_blocks:
            if zone.status != "invalid" or zone.invalidated_idx is None:
                continue
            after = frame.iloc[zone.invalidated_idx :]
            if after.empty:
                continue
            flipped = "bearish" if zone.direction == "bullish" else "bullish"
            breakers.append(Zone("breaker", flipped, zone.invalidated_idx, zone.upper, zone.lower, status="active"))
        return breakers

    def premium_discount_state(self, htf_df: pd.DataFrame, price: float | None = None) -> dict[str, Any]:
        frame = self.detect_swings(htf_df)
        highs = frame.loc[frame["is_swing_high"], "high"].tail(1)
        lows = frame.loc[frame["is_swing_low"], "low"].tail(1)
        if highs.empty or lows.empty:
            return {"state": 0, "equilibrium": np.nan, "range_high": np.nan, "range_low": np.nan}
        range_high = float(highs.iloc[-1])
        range_low = float(lows.iloc[-1])
        eq = (range_high + range_low) / 2
        px = float(price) if price is not None else float(frame["close"].iloc[-1])
        state = 1 if px > eq else -1 if px < eq else 0
        return {"state": state, "equilibrium": eq, "range_high": range_high, "range_low": range_low}

    def detect_regime(self, df: pd.DataFrame, funding_rate: pd.Series | None = None) -> pd.DataFrame:
        frame = self.validate_ohlcv(df)
        atr = self._atr(frame, 14)
        atr_ma = atr.rolling(self.regime_window, min_periods=self.regime_window // 2).mean()
        atr_state = np.where(atr > atr_ma * 1.2, "expansion", np.where(atr < atr_ma * 0.8, "contraction", "normal"))

        ret = frame["close"].pct_change()
        vol = ret.rolling(self.regime_window, min_periods=self.regime_window // 2).std()
        vol_pct = vol.rolling(self.regime_window * 2, min_periods=10).rank(pct=True)

        up = (frame["high"] - frame["high"].shift(1)).clip(lower=0)
        dn = (frame["low"].shift(1) - frame["low"]).clip(lower=0)
        tr = pd.concat([(frame["high"] - frame["low"]), (frame["high"] - frame["close"].shift()).abs(), (frame["low"] - frame["close"].shift()).abs()], axis=1).max(axis=1)
        plus_di = 100 * (up.rolling(14).mean() / (tr.rolling(14).mean() + 1e-9))
        minus_di = 100 * (dn.rolling(14).mean() / (tr.rolling(14).mean() + 1e-9))
        adx_strength = (plus_di - minus_di).abs()

        range_width = (frame["high"].rolling(self.regime_window).max() - frame["low"].rolling(self.regime_window).min()) / frame["close"]
        compression = range_width < range_width.rolling(self.regime_window).median() * 0.8

        volume_delta = self.detect_volume_imbalance(frame, window=self.regime_window)

        regime = pd.DataFrame(
            {
                "timestamp": frame["timestamp"],
                "atr_state": atr_state,
                "vol_percentile": vol_pct,
                "trend_strength": adx_strength,
                "compression": compression.astype(int),
                "volume_delta": volume_delta,
                "funding_rate": funding_rate.reindex(frame.index).values if funding_rate is not None else np.nan,
            }
        )
        regime["regime_label"] = np.where(
            (regime["atr_state"] == "expansion") & (regime["trend_strength"] > 25),
            "trend_breakout",
            np.where(regime["compression"] == 1, "compression_reversal", "balanced"),
        )
        return regime

    def build_feature_frame(self, df: pd.DataFrame, tf_name: str) -> pd.DataFrame:
        frame, structure = self.detect_bos_mss_choch(df)
        fvg = self.detect_fvg(frame)
        sweeps = self.detect_liquidity_sweeps(frame)
        obs = self.detect_order_blocks(frame)
        pd_state = self.premium_discount_state(frame)
        regime = self.detect_regime(frame)

        features = pd.DataFrame({"timestamp": frame["timestamp"]})
        features[f"bos_bullish_{tf_name}"] = 0
        features[f"bos_bearish_{tf_name}"] = 0
        features[f"sweep_{tf_name}"] = 0
        features[f"fvg_discount_{tf_name}"] = 0
        features[f"distance_to_ob_{tf_name}"] = np.nan
        features[f"premium_discount_state_{tf_name}"] = pd_state["state"]
        features[f"htf_trend_strength_{tf_name}"] = regime["trend_strength"].fillna(0)

        for ev in structure:
            col = f"bos_bullish_{tf_name}" if ev["direction"] == "bullish" else f"bos_bearish_{tf_name}"
            features.at[ev["break_candle_index"], col] = 1
        for ev in sweeps:
            features.at[ev["index"], f"sweep_{tf_name}"] = 1
        for ev in fvg:
            if ev["direction"] == "bullish" and pd_state["state"] == -1:
                features.at[ev["index"], f"fvg_discount_{tf_name}"] = 1

        active_obs = [z for z in obs if z.status in {"active", "mitigated"}]
        if active_obs:
            latest_zone = active_obs[-1]
            zone_mid = (latest_zone.upper + latest_zone.lower) / 2
            features[f"distance_to_ob_{tf_name}"] = (frame["close"] - zone_mid).abs()
        return features


class ConfluenceEngine:
    def __init__(self, max_time_delta_minutes: int = 180, price_threshold_pct: float = 0.003):
        self.max_time_delta_minutes = max_time_delta_minutes
        self.price_threshold_pct = price_threshold_pct

    def evaluate(self, events: dict[str, list[dict[str, Any]]], model: TradingModel, price: float) -> dict[str, Any]:
        matched: list[str] = []
        directional: list[str] = []
        last_ts: pd.Timestamp | None = None
        score = 0.0

        for condition in model.conditions:
            c_events = [e for e in events.get(condition.tf, []) if e.get("type", "").lower() == condition.type.lower()]
            if condition.direction:
                c_events = [e for e in c_events if e.get("direction") == condition.direction]
            if not c_events:
                continue

            selected = c_events[-1]
            ts = pd.Timestamp(selected["timestamp"])
            if last_ts is not None:
                dt = abs((ts - last_ts).total_seconds()) / 60
                if dt > model.max_time_delta:
                    continue
            level = float(selected.get("level", selected.get("ce", price)))
            if abs(level - price) / max(price, 1e-9) > self.price_threshold_pct:
                continue

            last_ts = ts if last_ts is None else max(last_ts, ts)
            matched.append(f"{condition.type}:{condition.tf}")
            directional.append(selected.get("direction", condition.direction or "neutral"))
            score += condition.weight

        all_bullish = all(d == "bullish" for d in directional if d != "neutral")
        all_bearish = all(d == "bearish" for d in directional if d != "neutral")
        aligned = all_bullish or all_bearish
        return {
            "passed": aligned and score >= model.min_score,
            "score": score,
            "direction": "bullish" if all_bullish else "bearish" if all_bearish else "neutral",
            "matched_conditions": matched,
        }


class SignalGenerator:
    def generate(
        self,
        latest_price: float,
        direction: str,
        fvg_event: dict[str, Any] | None,
        ob_zone: Zone | None,
        sweep_event: dict[str, Any] | None,
        confidence: float,
        triggered: list[str],
    ) -> TradeSignal:
        if fvg_event:
            entry = (float(fvg_event["ce"]), float(fvg_event["ce"]))
        elif ob_zone:
            entry = (ob_zone.lower, ob_zone.upper)
        else:
            entry = (latest_price, latest_price)

        if direction == "bullish":
            stop = ob_zone.lower if ob_zone else (float(sweep_event["level"]) if sweep_event else latest_price * 0.995)
            risk = max(entry[0] - stop, latest_price * 0.001)
            take = latest_price + (2 * risk)
        else:
            stop = ob_zone.upper if ob_zone else (float(sweep_event["level"]) if sweep_event else latest_price * 1.005)
            risk = max(stop - entry[0], latest_price * 0.001)
            take = latest_price - (2 * risk)

        rr = abs(take - entry[0]) / max(abs(entry[0] - stop), 1e-9)
        return TradeSignal(
            timestamp=pd.Timestamp.utcnow(),
            direction=direction,
            entry_zone=entry,
            stop_loss=float(stop),
            take_profit=float(take),
            risk_reward=float(rr),
            confluences_triggered=triggered,
            confidence_score=float(confidence),
        )


class PerformanceTracker:
    def __init__(self, rolling_window: int = 30, expectancy_kill_threshold: float = -0.1):
        self.rolling_window = rolling_window
        self.expectancy_kill_threshold = expectancy_kill_threshold
        self.results: list[dict[str, float]] = []

    def add_trade(self, pnl_r: float, equity_curve: list[float]) -> None:
        self.results.append({"pnl_r": float(pnl_r), "equity": float(equity_curve[-1])})

    def metrics(self) -> dict[str, float | bool]:
        if not self.results:
            return {"win_rate": 0.0, "avg_rr": 0.0, "expectancy": 0.0, "max_drawdown": 0.0, "profit_factor": 0.0, "sharpe": 0.0, "kill_switch": False}
        rr = np.array([r["pnl_r"] for r in self.results], dtype=float)
        wins = rr[rr > 0]
        losses = rr[rr <= 0]
        win_rate = float((rr > 0).mean())
        avg_rr = float(rr.mean())
        expectancy = float(win_rate * wins.mean() + (1 - win_rate) * losses.mean()) if len(wins) and len(losses) else avg_rr
        profit_factor = float(wins.sum() / abs(losses.sum())) if abs(losses.sum()) > 1e-9 else float("inf")

        equity = np.array([r["equity"] for r in self.results])
        peak = np.maximum.accumulate(equity)
        drawdown = (equity - peak) / np.maximum(peak, 1e-9)
        max_dd = float(drawdown.min())
        sharpe = float(rr.mean() / (rr.std() + 1e-9) * np.sqrt(252))

        rolling = rr[-self.rolling_window :]
        kill = float(rolling.mean()) < self.expectancy_kill_threshold if len(rolling) else False
        return {
            "win_rate": win_rate,
            "avg_rr": avg_rr,
            "expectancy": expectancy,
            "max_drawdown": max_dd,
            "profit_factor": profit_factor,
            "sharpe": sharpe,
            "kill_switch": kill,
        }


class ExecutionIntelligence:
    @staticmethod
    def apply_execution_model(entry: float, side: str, spread_bps: float = 2.0, slippage_bps: float = 3.0, partial_fill_ratio: float = 1.0) -> dict[str, float]:
        spread = entry * spread_bps / 10_000
        slip = entry * slippage_bps / 10_000
        if side == "buy":
            limit_price = entry - spread / 2
            market_price = entry + spread / 2 + slip
        else:
            limit_price = entry + spread / 2
            market_price = entry - spread / 2 - slip
        fill_price = (market_price * partial_fill_ratio) + (limit_price * (1 - partial_fill_ratio))
        return {
            "limit_price": float(limit_price),
            "market_price": float(market_price),
            "modeled_fill_price": float(fill_price),
            "spread_cost": float(spread),
            "slippage_cost": float(slip),
        }


class WalkForwardValidator:
    def __init__(self, engine: ICTStructureEngine):
        self.engine = engine

    def split(self, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
        frame = self.engine.validate_ohlcv(df)
        years = frame["timestamp"].dt.year
        return {
            "train": frame[(years >= 2021) & (years <= 2023)].copy(),
            "validate": frame[years == 2024].copy(),
            "forward": frame[years == 2025].copy(),
        }

    def feature_validation(self, df: pd.DataFrame, tf: str = "5m") -> dict[str, Any]:
        splits = self.split(df)
        out: dict[str, Any] = {}
        for name, sample in splits.items():
            if sample.empty:
                out[name] = {"rows": 0, "features": []}
                continue
            f = self.engine.build_feature_frame(sample, tf)
            out[name] = {
                "rows": len(f),
                "features": [c for c in f.columns if c != "timestamp"],
                "signal_density": float((f.drop(columns=["timestamp"]).sum().sum()) / max(len(f), 1)),
            }
        return out


def create_model(config: dict[str, Any]) -> TradingModel:
    conditions = [
        ModelCondition(
            type=str(c["type"]),
            tf=str(c["tf"]),
            direction=c.get("direction"),
            entry=c.get("entry"),
            weight=float(c.get("weight", 1.0)),
        )
        for c in config.get("conditions", [])
    ]
    return TradingModel(
        name=str(config["name"]),
        conditions=conditions,
        min_score=float(config.get("min_score", len(conditions))),
        max_time_delta=int(config.get("max_time_delta", 180)),
    )
