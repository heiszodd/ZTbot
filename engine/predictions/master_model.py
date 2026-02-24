from __future__ import annotations

import db
from engine.predictions.checks import evaluate_market_against_model


async def evaluate_master_predictions(market: dict) -> dict:
    models = db.get_active_prediction_models()
    if not models:
        return {"passed": False, "reason": "No active prediction models"}

    passing_models = []
    failing_models = []
    total_score = 0.0
    best_model = None
    best_score = 0.0
    recommended_position = "SKIP"

    for model in models:
        result = await evaluate_market_against_model(market, model)
        result["model_name"] = model.get("name")
        if result["passed"]:
            passing_models.append(model.get("name"))
            total_score += result["score"]
            if result["score"] > best_score:
                best_score = result["score"]
                best_model = result
                recommended_position = model.get("position_type", "YES")
        else:
            failing_models.append(model.get("name"))

    avg_score = total_score / len(passing_models) if passing_models else 0
    master_grade = "A" if avg_score >= 85 else "B" if avg_score >= 70 else "C" if avg_score >= 55 else "D"
    return {
        "passed": len(passing_models) > 0,
        "master_score": round(avg_score, 1),
        "master_grade": master_grade,
        "passing_models": passing_models,
        "failing_models": failing_models,
        "recommended_position": recommended_position,
        "best_model": best_model,
        "total_models": len(models),
    }
