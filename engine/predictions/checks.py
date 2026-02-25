from __future__ import annotations

from typing import Any

import pandas as pd

from engine.ict_engine import ConfluenceEngine, FeatureLayer, ModelFactory


async def evaluate_market_against_model(market: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a dynamic ICT model against multi-timeframe OHLCV market payload.

    Expected payload format:
    {
      "ohlcv": {"4h": DataFrame, "15m": DataFrame, "5m": DataFrame},
      "price": float,
      "funding_rate": Optional[pd.Series]
    }
    """

    ohlcv = market.get("ohlcv") or {}
    if not isinstance(ohlcv, dict) or not ohlcv:
        return {"passed": False, "score": 0.0, "grade": "F", "reason": "missing_ohlcv", "triggered_features": []}

    ict_model = ModelFactory.create_model(
        {
            "name": model.get("name", "ICT_DYNAMIC_MODEL"),
            "features": model.get("features", model.get("conditions", [])),
            "min_score": model.get("min_score", model.get("min_passing_score", 3)),
            "max_time_delta": model.get("max_time_delta", 180),
            "price_proximity_threshold": model.get("price_proximity_threshold", 0.3),
        }
    )

    layer = FeatureLayer()
    event_map: dict[str, list[dict[str, Any]]] = {}
    for tf, frame in ohlcv.items():
        if not isinstance(frame, pd.DataFrame):
            continue
        _, structure_events = layer.detect_structure_events(frame)
        sweeps = layer.detect_liquidity_sweeps(frame)
        fvgs = layer.detect_fvg(frame)
        event_map[tf] = structure_events + sweeps + fvgs

    price = float(market.get("price") or 0.0)
    if price <= 0:
        tf0 = next(iter(ohlcv.values()))
        price = float(tf0["close"].iloc[-1]) if isinstance(tf0, pd.DataFrame) and not tf0.empty else 0.0

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
