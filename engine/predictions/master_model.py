from __future__ import annotations

from typing import Any

import db

from engine.predictions.checks import evaluate_market_against_model


async def evaluate_master_predictions(market: dict[str, Any]) -> dict[str, Any]:
    """Evaluate active prediction models using the new ICT feature/confluence engine."""
    models = db.get_active_prediction_models() or []
    if not models:
        return {"passed": False, "reason": "No active prediction models"}

    passing_models: list[str] = []
    failing_models: list[str] = []
    weighted_scores: list[float] = []
    best_model: dict[str, Any] | None = None

    for model in models:
        result = await evaluate_market_against_model(market, model)
        result["model_name"] = model.get("name")
        if result.get("passed"):
            passing_models.append(model.get("name", "unknown"))
            weighted_scores.append(float(result.get("score", 0.0)))
            if best_model is None or float(result.get("score", 0.0)) > float(best_model.get("score", 0.0)):
                best_model = result
        else:
            failing_models.append(model.get("name", "unknown"))

    avg_score = float(sum(weighted_scores) / len(weighted_scores)) if weighted_scores else 0.0
    grade = "A" if avg_score >= 5 else "B" if avg_score >= 4 else "C" if avg_score >= 3 else "D"

    return {
        "passed": bool(passing_models),
        "master_score": round(avg_score, 3),
        "master_grade": grade,
        "passing_models": passing_models,
        "failing_models": failing_models,
        "recommended_position": "BUY" if (best_model and best_model.get("direction") == "bullish") else "SELL" if (best_model and best_model.get("direction") == "bearish") else "SKIP",
        "best_model": best_model,
        "total_models": len(models),
    }
