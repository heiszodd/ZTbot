from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


@dataclass
class FeatureCondition:
    type: str
    tf: str
    direction: str | None = None
    entry: str | None = None
    weight: float = 1.0


@dataclass
class ICTModel:
    name: str
    features: list[FeatureCondition]
    min_score: float
    max_time_delta: int
    price_proximity_threshold: float


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


# Compatibility aliases for merged branches.
ModelCondition = FeatureCondition
TradingModel = ICTModel


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


class DataLayer:
    """OHLCV ingestion and deterministic timeframe resampling."""

    TF_MINUTES = {
        "1m": 1,
        "3m": 3,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "2h": 120,
        "4h": 240,
        "1d": 1440,
    }

    @staticmethod
    def validate_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
        missing = [c for c in OHLCV_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"Missing OHLCV columns: {missing}")
        out = df.loc[:, OHLCV_COLUMNS].copy()
        out["timestamp"] = pd.to_datetime(out["timestamp"], unit="ms", errors="coerce").fillna(pd.to_datetime(out["timestamp"], errors="coerce"))
        for c in ["open", "high", "low", "close", "volume"]:
            out[c] = pd.to_numeric(out[c], errors="coerce")
        out = out.dropna(subset=["timestamp", "open", "high", "low", "close"]).sort_values("timestamp").reset_index(drop=True)
        return out

    def resample(self, df: pd.DataFrame, tf: str) -> pd.DataFrame:
        base = self.validate_ohlcv(df)
        if tf not in self.TF_MINUTES:
            raise ValueError(f"Unsupported timeframe '{tf}'")
        if tf == "1m":
            return base
        out = (
            base.set_index("timestamp")
            .resample(f"{self.TF_MINUTES[tf]}min", label="left", closed="left")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
            .dropna(subset=["open", "high", "low", "close"])
            .reset_index()
        )
        return out


class FeatureLayer:
    """ICT feature calculations with no future leakage."""

    def __init__(self, swing_window: int = 3, regime_window: int = 20, liquidity_lookback: int = 120):
        self.data = DataLayer()
        self.swing_window = max(2, int(swing_window))
        self.regime_window = max(5, int(regime_window))
        self.liquidity_lookback = max(20, int(liquidity_lookback))
        self.order_blocks: list[Zone] = []

    @staticmethod
    def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        prev_close = df["close"].shift(1)
        tr = pd.concat([
            (df["high"] - df["low"]).abs(),
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(period, min_periods=period).mean()

    def detect_swings(self, df: pd.DataFrame) -> pd.DataFrame:
        frame = self.data.validate_ohlcv(df)
        n = self.swing_window

        ph = frame["high"].shift(1).rolling(n, min_periods=n).max()
        nh = frame["high"].iloc[::-1].shift(1).rolling(n, min_periods=n).max().iloc[::-1]
        pl = frame["low"].shift(1).rolling(n, min_periods=n).min()
        nl = frame["low"].iloc[::-1].shift(1).rolling(n, min_periods=n).min().iloc[::-1]

        frame["is_swing_high"] = (frame["high"] > ph) & (frame["high"] > nh)
        frame["is_swing_low"] = (frame["low"] < pl) & (frame["low"] < nl)

        # Confirmed only after right-side n bars close.
        frame["confirmed_swing_high"] = frame["is_swing_high"].shift(n, fill_value=False).astype(bool)
        frame["confirmed_swing_low"] = frame["is_swing_low"].shift(n, fill_value=False).astype(bool)
        frame["confirmed_swing_high_level"] = frame["high"].shift(n).where(frame["confirmed_swing_high"])
        frame["confirmed_swing_low_level"] = frame["low"].shift(n).where(frame["confirmed_swing_low"])
        return frame

    def detect_structure_events(self, df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
        frame = self.detect_swings(df)
        events: list[dict[str, Any]] = []

        last_high: float | None = None
        last_low: float | None = None
        trend = "neutral"

        for i in range(len(frame)):
            if bool(frame.at[i, "confirmed_swing_high"]):
                last_high = float(frame.at[i, "confirmed_swing_high_level"])
            if bool(frame.at[i, "confirmed_swing_low"]):
                last_low = float(frame.at[i, "confirmed_swing_low_level"])

            close_i = float(frame.at[i, "close"])

            if last_high is not None and close_i > last_high:
                choch = trend == "bearish"
                events.append(
                    {
                        "type": "BOS",
                        "direction": "bullish",
                        "timestamp": frame.at[i, "timestamp"],
                        "index": i,
                        "broken_level": last_high,
                        "choch": choch,
                        "mss": choch,
                    }
                )
                trend = "bullish"
                last_high = None

            if last_low is not None and close_i < last_low:
                choch = trend == "bullish"
                events.append(
                    {
                        "type": "BOS",
                        "direction": "bearish",
                        "timestamp": frame.at[i, "timestamp"],
                        "index": i,
                        "broken_level": last_low,
                        "choch": choch,
                        "mss": choch,
                    }
                )
                trend = "bearish"
                last_low = None

        frame["trend"] = trend
        return frame, events

    # Compatibility alias retained for merged branch references.
    def detect_bos_mss_choch(self, df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
        frame, events = self.detect_structure_events(df)
        remapped = []
        for e in events:
            remapped.append({
                **e,
                "break_candle_index": int(e.get("index", -1)),
                "swing_index": int(e.get("index", -1)),
            })
        return frame, remapped

    def detect_fvg(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        frame = self.data.validate_ohlcv(df)
        events: list[dict[str, Any]] = []

        for i in range(2, len(frame)):
            if float(frame.at[i, "low"]) > float(frame.at[i - 2, "high"]):
                lower = float(frame.at[i - 2, "high"])
                upper = float(frame.at[i, "low"])
                events.append({"type": "FVG", "direction": "bullish", "index": i, "timestamp": frame.at[i, "timestamp"], "lower": lower, "upper": upper, "ce": (lower + upper) / 2, "ifvg": 0})

            if float(frame.at[i, "high"]) < float(frame.at[i - 2, "low"]):
                lower = float(frame.at[i, "high"])
                upper = float(frame.at[i - 2, "low"])
                events.append({"type": "FVG", "direction": "bearish", "index": i, "timestamp": frame.at[i, "timestamp"], "lower": lower, "upper": upper, "ce": (lower + upper) / 2, "ifvg": 0})

        for e in events:
            after = frame.iloc[int(e["index"]) + 1 :]
            if after.empty:
                continue
            if e["direction"] == "bullish":
                if (after["close"] < e["lower"]).any():
                    e["ifvg"] = 1
                    e["status"] = "inverse"
                elif (after["low"] <= e["upper"]).any():
                    e["status"] = "mitigated"
                else:
                    e["status"] = "open"
            else:
                if (after["close"] > e["upper"]).any():
                    e["ifvg"] = 1
                    e["status"] = "inverse"
                elif (after["high"] >= e["lower"]).any():
                    e["status"] = "mitigated"
                else:
                    e["status"] = "open"
        return events

    def detect_volume_imbalance(self, df: pd.DataFrame, window: int = 20) -> pd.Series:
        frame = self.data.validate_ohlcv(df)
        bull = np.where(frame["close"] >= frame["open"], frame["volume"], 0.0)
        bear = np.where(frame["close"] < frame["open"], frame["volume"], 0.0)
        bsum = pd.Series(bull).rolling(window, min_periods=max(3, window // 2)).sum()
        ssum = pd.Series(bear).rolling(window, min_periods=max(3, window // 2)).sum()
        return (bsum - ssum) / (bsum + ssum + 1e-9)

    def detect_equal_levels(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        frame = self.detect_swings(df)
        atr = self._atr(frame).bfill().fillna(0)

        equal: list[dict[str, Any]] = []
        for side, is_col, px_col in [
            ("high", "is_swing_high", "high"),
            ("low", "is_swing_low", "low"),
        ]:
            idxs = frame.index[frame[is_col]].tolist()
            for a, b in zip(idxs[:-1], idxs[1:]):
                p1 = float(frame.at[a, px_col])
                p2 = float(frame.at[b, px_col])
                tol = max(float(atr.at[b]) * 0.1, p2 * 0.0005)
                if abs(p1 - p2) <= tol:
                    equal.append({"type": f"equal_{side}s", "index_a": a, "index_b": b, "level": (p1 + p2) / 2, "tolerance": tol, "timestamp": frame.at[b, "timestamp"]})
        return equal

    # Compatibility alias retained for merged branch references.
    def detect_equal_highs_lows(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        return self.detect_equal_levels(df)

    def detect_liquidity_sweeps(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        frame = self.data.validate_ohlcv(df)
        levels = self.detect_equal_levels(frame)
        out: list[dict[str, Any]] = []

        for lv in levels:
            start = int(lv["index_b"]) + 1
            sub = frame.iloc[start : start + self.liquidity_lookback]
            if sub.empty:
                continue
            level = float(lv["level"])
            if lv["type"] == "equal_lows":
                cond = (sub["low"] < level) & (sub["close"] > level)
                if cond.any():
                    idx = int(sub.index[np.argmax(cond.values)])
                    out.append({"type": "LiquiditySweep", "direction": "bullish", "timestamp": frame.at[idx, "timestamp"], "index": idx, "level": level})
            else:
                cond = (sub["high"] > level) & (sub["close"] < level)
                if cond.any():
                    idx = int(sub.index[np.argmax(cond.values)])
                    out.append({"type": "LiquiditySweep", "direction": "bearish", "timestamp": frame.at[idx, "timestamp"], "index": idx, "level": level})
        return out

    def liquidity_density_map(self, df: pd.DataFrame, bins: int = 40) -> pd.DataFrame:
        frame = self.data.validate_ohlcv(df)
        px = pd.concat([frame["high"], frame["low"]], axis=0)
        vol = pd.concat([frame["volume"], frame["volume"]], axis=0)
        buckets = pd.cut(px, bins=bins)
        touches = px.groupby(buckets, observed=False).size()
        volume = vol.groupby(buckets, observed=False).sum()
        out = pd.DataFrame({"touches": touches, "volume": volume}).fillna(0)
        out["density_score"] = out["touches"] * 0.6 + out["volume"].rank(pct=True) * 0.4
        return out.sort_values("density_score", ascending=False)

    def detect_order_blocks(self, df: pd.DataFrame) -> list[Zone]:
        frame, structure_events = self.detect_structure_events(df)
        zones: list[Zone] = []

        for e in structure_events:
            idx = int(e["index"])
            lookback = frame.iloc[max(0, idx - 15) : idx]
            if lookback.empty:
                continue
            if e["direction"] == "bullish":
                candidates = lookback[lookback["close"] < lookback["open"]]
            else:
                candidates = lookback[lookback["close"] > lookback["open"]]
            if candidates.empty:
                continue
            c = candidates.iloc[-1]
            body = abs(float(c["close"] - c["open"]))
            rng = max(float(c["high"] - c["low"]), 1e-9)
            if body / rng <= 0.5:
                continue
            if e["direction"] == "bullish":
                zones.append(Zone("order_block", "bullish", int(c.name), upper=float(c["open"]), lower=float(c["low"])))
            else:
                zones.append(Zone("order_block", "bearish", int(c.name), upper=float(c["high"]), lower=float(c["open"])))

        self.order_blocks = zones
        self._update_zone_lifecycle(frame)
        return self.order_blocks

    def _update_zone_lifecycle(self, frame: pd.DataFrame) -> None:
        for z in self.order_blocks:
            after = frame.iloc[z.created_idx + 1 :]
            if after.empty:
                continue
            inside = (after["low"] <= z.upper) & (after["high"] >= z.lower)
            z.touches = int(inside.sum())
            z.time_alive = int((after["timestamp"].iloc[-1] - frame.at[z.created_idx, "timestamp"]).total_seconds() / 60)
            if z.direction == "bullish":
                if (after["close"] < z.lower).any():
                    z.status = "invalid"
                    z.invalidated_idx = int(after.index[np.argmax((after["close"] < z.lower).values)])
                elif z.touches:
                    z.status = "mitigated"
            else:
                if (after["close"] > z.upper).any():
                    z.status = "invalid"
                    z.invalidated_idx = int(after.index[np.argmax((after["close"] > z.upper).values)])
                elif z.touches:
                    z.status = "mitigated"

    def detect_breaker_blocks(self, df: pd.DataFrame) -> list[Zone]:
        frame = self.data.validate_ohlcv(df)
        out: list[Zone] = []
        for z in self.order_blocks:
            if z.status == "invalid" and z.invalidated_idx is not None and z.invalidated_idx < len(frame):
                out.append(Zone("breaker", "bearish" if z.direction == "bullish" else "bullish", z.invalidated_idx, z.upper, z.lower))
        return out

    def premium_discount_state(self, htf_df: pd.DataFrame, price: float | None = None) -> dict[str, float]:
        frame = self.detect_swings(htf_df)
        highs = frame.loc[frame["is_swing_high"], "high"].tail(1)
        lows = frame.loc[frame["is_swing_low"], "low"].tail(1)
        if highs.empty or lows.empty:
            return {"state": 0.0, "equilibrium": np.nan, "range_high": np.nan, "range_low": np.nan}
        hi = float(highs.iloc[-1])
        lo = float(lows.iloc[-1])
        eq = (hi + lo) / 2
        px = float(price) if price is not None else float(frame["close"].iloc[-1])
        state = 1.0 if px > eq else -1.0 if px < eq else 0.0
        return {"state": state, "equilibrium": eq, "range_high": hi, "range_low": lo}

    def detect_regime(self, df: pd.DataFrame, funding_rate: pd.Series | None = None) -> pd.DataFrame:
        frame = self.data.validate_ohlcv(df)
        atr = self._atr(frame, 14)
        atr_ma = atr.rolling(self.regime_window, min_periods=max(5, self.regime_window // 2)).mean()
        atr_state = np.where(atr > atr_ma * 1.2, 1, np.where(atr < atr_ma * 0.8, -1, 0))

        ret = frame["close"].pct_change()
        vol = ret.rolling(self.regime_window, min_periods=max(5, self.regime_window // 2)).std()
        vol_pct = vol.rolling(self.regime_window * 2, min_periods=10).rank(pct=True)

        up = (frame["high"] - frame["high"].shift(1)).clip(lower=0)
        dn = (frame["low"].shift(1) - frame["low"]).clip(lower=0)
        tr = pd.concat([(frame["high"] - frame["low"]), (frame["high"] - frame["close"].shift()).abs(), (frame["low"] - frame["close"].shift()).abs()], axis=1).max(axis=1)
        plus_di = 100 * (up.rolling(14).mean() / (tr.rolling(14).mean() + 1e-9))
        minus_di = 100 * (dn.rolling(14).mean() / (tr.rolling(14).mean() + 1e-9))
        adx_like = (plus_di - minus_di).abs()

        width = (frame["high"].rolling(self.regime_window).max() - frame["low"].rolling(self.regime_window).min()) / frame["close"]
        compression = (width < width.rolling(self.regime_window).median() * 0.8).astype(int)

        vol_delta = self.detect_volume_imbalance(frame, self.regime_window)
        funding = funding_rate.reindex(frame.index).values if funding_rate is not None else np.full(len(frame), np.nan)

        return pd.DataFrame(
            {
                "timestamp": frame["timestamp"],
                "atr_state": atr_state,
                "vol_percentile": vol_pct.fillna(0),
                "trend_strength": adx_like.fillna(0),
                "compression": compression,
                "volume_delta": vol_delta.fillna(0),
                "funding_rate": funding,
            }
        )

    def build_feature_frame(self, df: pd.DataFrame, tf_name: str, funding_rate: pd.Series | None = None) -> pd.DataFrame:
        frame, structure = self.detect_structure_events(df)
        fvgs = self.detect_fvg(frame)
        sweeps = self.detect_liquidity_sweeps(frame)
        obs = self.detect_order_blocks(frame)
        breakers = self.detect_breaker_blocks(frame)
        regime = self.detect_regime(frame, funding_rate=funding_rate)
        pd_state = self.premium_discount_state(frame)

        f = pd.DataFrame({"timestamp": frame["timestamp"]})
        f[f"bos_bullish_{tf_name}"] = 0
        f[f"bos_bearish_{tf_name}"] = 0
        f[f"mss_bullish_{tf_name}"] = 0
        f[f"mss_bearish_{tf_name}"] = 0
        f[f"choch_bullish_{tf_name}"] = 0
        f[f"choch_bearish_{tf_name}"] = 0
        f[f"sweep_{tf_name}"] = 0
        f[f"fvg_{tf_name}"] = 0
        f[f"ifvg_{tf_name}"] = 0
        f[f"fvg_ce_{tf_name}"] = np.nan
        f[f"volume_imbalance_{tf_name}"] = self.detect_volume_imbalance(frame).fillna(0)
        f[f"ob_active_count_{tf_name}"] = len([z for z in obs if z.status == "active"])
        f[f"breaker_count_{tf_name}"] = len(breakers)
        f[f"premium_discount_state_{tf_name}"] = pd_state["state"]
        f[f"regime_atr_state_{tf_name}"] = regime["atr_state"]
        f[f"regime_vol_pct_{tf_name}"] = regime["vol_percentile"]
        f[f"regime_trend_strength_{tf_name}"] = regime["trend_strength"]
        f[f"regime_compression_{tf_name}"] = regime["compression"]
        f[f"regime_volume_delta_{tf_name}"] = regime["volume_delta"]

        for e in structure:
            idx = int(e["index"])
            d = e["direction"]
            f.at[idx, f"bos_{d}_{tf_name}"] = 1
            if e.get("mss"):
                f.at[idx, f"mss_{d}_{tf_name}"] = 1
            if e.get("choch"):
                f.at[idx, f"choch_{d}_{tf_name}"] = 1
        for e in sweeps:
            f.at[int(e["index"]), f"sweep_{tf_name}"] = 1
        for e in fvgs:
            idx = int(e["index"])
            f.at[idx, f"fvg_{tf_name}"] = 1
            f.at[idx, f"ifvg_{tf_name}"] = int(e.get("ifvg", 0))
            f.at[idx, f"fvg_ce_{tf_name}"] = float(e["ce"])

        active_obs = [z for z in obs if z.status in {"active", "mitigated"}]
        if active_obs:
            z = active_obs[-1]
            mid = (z.upper + z.lower) / 2
            f[f"distance_to_ob_{tf_name}"] = (frame["close"] - mid).abs()
        else:
            f[f"distance_to_ob_{tf_name}"] = np.nan

        density = self.liquidity_density_map(frame)
        f[f"liquidity_density_score_{tf_name}"] = float(density["density_score"].iloc[0]) if not density.empty else 0.0
        return f

    def build_multi_tf_features(self, tf_data: dict[str, pd.DataFrame], funding_rate: pd.Series | None = None) -> dict[str, pd.DataFrame]:
        return {tf: self.build_feature_frame(df, tf, funding_rate=funding_rate) for tf, df in tf_data.items()}


class ConfluenceEngine:
    """Weighted, directional, hierarchical confluence validation."""

    def evaluate(self, model_or_events: ICTModel | dict[str, list[dict[str, Any]]], events_or_model: dict[str, list[dict[str, Any]]] | ICTModel, price: float) -> dict[str, Any]:
        # Supports both call orders from conflicting branches:
        # evaluate(model, events, price) and evaluate(events, model, price)
        if isinstance(model_or_events, dict):
            events_by_tf = model_or_events
            model = events_or_model  # type: ignore[assignment]
        else:
            model = model_or_events
            events_by_tf = events_or_model  # type: ignore[assignment]

        score = 0.0
        matches: list[str] = []
        directions: list[str] = []
        timestamps: list[pd.Timestamp] = []

        for cond in model.features:
            tf_events = [e for e in events_by_tf.get(cond.tf, []) if str(e.get("type", "")).lower() == cond.type.lower()]
            if cond.direction:
                tf_events = [e for e in tf_events if e.get("direction") == cond.direction]
            if not tf_events:
                continue

            picked = tf_events[-1]
            lvl = float(picked.get("level", picked.get("ce", picked.get("broken_level", price))))
            proximity = abs(lvl - price) / max(abs(price), 1e-9)
            if proximity > model.price_proximity_threshold / 100.0:
                continue

            ts = pd.Timestamp(picked["timestamp"])
            timestamps.append(ts)
            matches.append(f"{cond.type}:{cond.tf}")
            directions.append(str(picked.get("direction", cond.direction or "neutral")))
            score += cond.weight

        if len(timestamps) > 1:
            dt_minutes = (max(timestamps) - min(timestamps)).total_seconds() / 60
        else:
            dt_minutes = 0

        # HTF -> ITF -> LTF ordering
        hierarchy_ok = True
        tf_rank = {"1d": 5, "4h": 4, "1h": 3, "15m": 2, "5m": 1, "1m": 0}
        ordered = sorted(
            [(c, next((e for e in events_by_tf.get(c.tf, []) if str(e.get("type", "")).lower() == c.type.lower()), None)) for c in model.features],
            key=lambda x: tf_rank.get(x[0].tf.lower(), 0),
            reverse=True,
        )
        last_ts: pd.Timestamp | None = None
        for cond, ev in ordered:
            if ev is None:
                continue
            ts = pd.Timestamp(ev["timestamp"])
            if last_ts is not None and ts < last_ts:
                hierarchy_ok = False
                break
            last_ts = ts

        non_neutral = [d for d in directions if d != "neutral"]
        directional_ok = bool(non_neutral) and (all(d == "bullish" for d in non_neutral) or all(d == "bearish" for d in non_neutral))

        passed = directional_ok and hierarchy_ok and dt_minutes <= model.max_time_delta and score >= model.min_score
        return {
            "passed": passed,
            "score": score,
            "confidence_score": round(score / max(model.min_score, 1.0), 3),
            "direction": non_neutral[0] if directional_ok else "neutral",
            "triggered_features": matches,
            "time_span_minutes": dt_minutes,
            "hierarchy_ok": hierarchy_ok,
            "directional_ok": directional_ok,
        }


class SignalGenerator:
    @staticmethod
    def generate(price: float, direction: str, fvg: dict[str, Any] | None = None, ob: Zone | None = None, sweep: dict[str, Any] | None = None, triggered_features: list[str] | None = None, confidence_score: float = 0.0) -> dict[str, Any]:
        if fvg is not None:
            entry_zone = (float(fvg["ce"]), float(fvg["ce"]))
        elif ob is not None:
            entry_zone = (float(ob.lower), float(ob.upper))
        else:
            entry_zone = (float(price), float(price))

        if direction == "bullish":
            stop_loss = float(ob.lower) if ob else (float(sweep["level"]) if sweep else price * 0.995)
            risk = max(entry_zone[0] - stop_loss, price * 0.001)
            take_profit = price + 2 * risk
        else:
            stop_loss = float(ob.upper) if ob else (float(sweep["level"]) if sweep else price * 1.005)
            risk = max(stop_loss - entry_zone[0], price * 0.001)
            take_profit = price - 2 * risk

        rr = abs(take_profit - entry_zone[0]) / max(abs(entry_zone[0] - stop_loss), 1e-9)
        signal = TradeSignal(
            timestamp=pd.Timestamp.utcnow(),
            direction=direction,
            entry_zone=entry_zone,
            stop_loss=float(stop_loss),
            take_profit=float(take_profit),
            risk_reward=float(rr),
            confluences_triggered=(triggered_features or []),
            confidence_score=float(confidence_score),
        )
        # dict-style output preserved for compatibility with existing callers.
        return {
            "timestamp": signal.timestamp,
            "direction": signal.direction,
            "entry_zone": signal.entry_zone,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "risk_reward": signal.risk_reward,
            "triggered_features": signal.confluences_triggered,
            "confluences_triggered": signal.confluences_triggered,
            "confidence_score": signal.confidence_score,
        }


class PerformanceTracker:
    def __init__(self, rolling_window: int = 30, kill_threshold: float = -0.1):
        self.rolling_window = rolling_window
        self.kill_threshold = kill_threshold
        self.ledger: list[dict[str, float]] = []

    def add_trade(self, pnl_r: float, equity: float) -> None:
        self.ledger.append({"pnl_r": float(pnl_r), "equity": float(equity)})

    def metrics(self) -> dict[str, float | bool]:
        if not self.ledger:
            return {"win_rate": 0.0, "avg_rr": 0.0, "expectancy": 0.0, "max_drawdown": 0.0, "profit_factor": 0.0, "sharpe_ratio": 0.0, "kill_switch": False}
        rr = np.array([r["pnl_r"] for r in self.ledger], dtype=float)
        wins = rr[rr > 0]
        losses = rr[rr <= 0]
        win_rate = float((rr > 0).mean())
        avg_rr = float(rr.mean())
        expectancy = float(avg_rr)
        pf = float(wins.sum() / abs(losses.sum())) if abs(losses.sum()) > 1e-9 else float("inf")

        eq = np.array([r["equity"] for r in self.ledger], dtype=float)
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / np.maximum(peak, 1e-9)
        max_dd = float(dd.min())
        sharpe = float(rr.mean() / (rr.std() + 1e-9) * np.sqrt(252))

        rolling_exp = float(rr[-self.rolling_window :].mean()) if len(rr) else 0.0
        return {
            "win_rate": win_rate,
            "avg_rr": avg_rr,
            "expectancy": expectancy,
            "max_drawdown": max_dd,
            "profit_factor": pf,
            "sharpe_ratio": sharpe,
            "kill_switch": rolling_exp < self.kill_threshold,
        }


class ExecutionIntelligence:
    @staticmethod
    def model_fill(entry: float, side: str, spread_bps: float = 2.0, slippage_bps: float = 3.0, partial_fill_ratio: float = 1.0) -> dict[str, float]:
        spread = entry * spread_bps / 10_000
        slippage = entry * slippage_bps / 10_000
        if side.lower() == "buy":
            limit = entry - spread / 2
            market = entry + spread / 2 + slippage
        else:
            limit = entry + spread / 2
            market = entry - spread / 2 - slippage
        fill = market * partial_fill_ratio + limit * (1 - partial_fill_ratio)
        return {"limit_price": float(limit), "market_price": float(market), "modeled_fill_price": float(fill), "spread_cost": float(spread), "slippage_cost": float(slippage)}


    @staticmethod
    def apply_execution_model(entry: float, side: str, spread_bps: float = 2.0, slippage_bps: float = 3.0, partial_fill_ratio: float = 1.0) -> dict[str, float]:
        return ExecutionIntelligence.model_fill(entry, side, spread_bps, slippage_bps, partial_fill_ratio)


class WalkForwardValidator:
    def __init__(self, feature_layer: FeatureLayer):
        self.feature_layer = feature_layer

    def split(self, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
        frame = self.feature_layer.data.validate_ohlcv(df)
        years = frame["timestamp"].dt.year
        return {
            "train": frame[(years >= 2021) & (years <= 2023)].copy(),
            "validate": frame[years == 2024].copy(),
            "forward": frame[years == 2025].copy(),
        }

    def validate_features(self, df: pd.DataFrame, tf: str = "5m") -> dict[str, Any]:
        out: dict[str, Any] = {}
        for split_name, chunk in self.split(df).items():
            if chunk.empty:
                out[split_name] = {"rows": 0, "feature_columns": [], "signal_density": 0.0}
                continue
            feat = self.feature_layer.build_feature_frame(chunk, tf)
            cols = [c for c in feat.columns if c != "timestamp"]
            out[split_name] = {
                "rows": len(feat),
                "feature_columns": cols,
                "signal_density": float(feat[cols].sum(numeric_only=True).sum() / max(len(feat), 1)),
            }
        return out


    # Compatibility alias retained for merged branch references.
    def feature_validation(self, df: pd.DataFrame, tf: str = "5m") -> dict[str, Any]:
        return self.validate_features(df, tf)


class ModelFactory:
    """Dynamic model builder replacing legacy hardcoded master model sets."""

    @staticmethod
    def create_model(config: dict[str, Any]) -> ICTModel:
        feats = [
            FeatureCondition(
                type=str(f["type"]),
                tf=str(f["tf"]),
                direction=f.get("direction"),
                entry=f.get("entry"),
                weight=float(f.get("weight", 1.0)),
            )
            for f in config.get("features", config.get("conditions", []))
        ]
        if not feats:
            raise ValueError("Model config requires at least one feature condition")
        return ICTModel(
            name=str(config["name"]),
            features=feats,
            min_score=float(config.get("min_score", len(feats))),
            max_time_delta=int(config.get("max_time_delta", 180)),
            price_proximity_threshold=float(config.get("price_proximity_threshold", 0.3)),
        )


# Backward-compatible aliases
ICTStructureEngine = FeatureLayer


def create_model(config: dict[str, Any]) -> ICTModel:
    return ModelFactory.create_model(config)
