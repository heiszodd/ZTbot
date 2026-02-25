from __future__ import annotations

from typing import Any

import pandas as pd

from engine.ict_engine import ConfluenceEngine, FeatureLayer, ModelFactory


def _coerce_model_features(model: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve merge-conflicting model schemas into ICT feature config.

    Supports both:
    - new schema: {features:[...]}
    - transitional schema: {conditions:[...]}
    - legacy prediction schema: {mandatory_checks:[...], weighted_checks:[...]}
    """
    if model.get("features"):
        return list(model.get("features") or [])
    if model.get("conditions"):
        return list(model.get("conditions") or [])

    # Legacy fallback mapping (best-effort).
    mapped: list[dict[str, Any]] = []
    for name in model.get("mandatory_checks", []) or []:
        mapped.append({"type": str(name), "tf": "5m", "weight": 1.0})
    for wc in model.get("weighted_checks", []) or []:
        mapped.append(
            {
                "type": str(wc.get("check", "unknown")),
                "tf": str(wc.get("tf", "5m")),
                "weight": float(wc.get("weight", 1.0) or 1.0),
            }
        )
    return mapped


def _coerce_ohlcv_payload(market: dict[str, Any]) -> dict[str, pd.DataFrame]:
    raw = market.get("ohlcv") or market.get("tf_ohlcv") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, pd.DataFrame] = {}
    for tf, frame in raw.items():
        if isinstance(frame, pd.DataFrame) and not frame.empty:
            out[str(tf)] = frame
    return out


async def evaluate_market_against_model(market: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    """Evaluate dynamic ICT model against multi-timeframe OHLCV payload."""

    ohlcv = _coerce_ohlcv_payload(market)
    if not ohlcv:
        return {"passed": False, "score": 0.0, "grade": "F", "reason": "missing_ohlcv", "triggered_features": []}

    features = _coerce_model_features(model)
    if not features:
        return {"passed": False, "score": 0.0, "grade": "F", "reason": "missing_model_features", "triggered_features": []}

    ict_model = ModelFactory.create_model(
        {
            "name": model.get("name", "ICT_DYNAMIC_MODEL"),
            "features": features,
            "min_score": model.get("min_score", model.get("min_passing_score", 3)),
            "max_time_delta": model.get("max_time_delta", 180),
            "price_proximity_threshold": model.get("price_proximity_threshold", 0.3),
        }
    )

    layer = FeatureLayer()
    event_map: dict[str, list[dict[str, Any]]] = {}
    for tf, frame in ohlcv.items():
        _, structure_events = layer.detect_structure_events(frame)
        sweeps = layer.detect_liquidity_sweeps(frame)
        fvgs = layer.detect_fvg(frame)
        event_map[tf] = structure_events + sweeps + fvgs

    price = float(market.get("price") or 0.0)
    if price <= 0:
        first_df = next(iter(ohlcv.values()))
        price = float(first_df["close"].iloc[-1])

    confluence = ConfluenceEngine().evaluate(ict_model, event_map, price=price)
    score = float(confluence["score"])
    grade = "A" if score >= ict_model.min_score * 1.25 else "B" if score >= ict_model.min_score else "C" if score >= ict_model.min_score * 0.8 else "F"
    return {
        "passed": bool(confluence["passed"]),
        "score": round(score, 3),
        "grade": grade,
        "triggered_features": confluence["triggered_features"],
        "confidence_score": confluence["confidence_score"],
        "direction": confluence["direction"],
        "time_span_minutes": confluence["time_span_minutes"],
        "hierarchy_ok": confluence["hierarchy_ok"],
        "directional_ok": confluence["directional_ok"],
    }
