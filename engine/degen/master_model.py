from __future__ import annotations

import db
from engine.degen.model_evaluator import evaluate_token_against_model


async def evaluate_master_degen(token_data: dict) -> dict:
    models = db.get_active_degen_models()
    if not models:
        return {"passed": False, "reason": "No active degen models"}

    model_results = []
    any_passed = False
    total_score = 0.0
    passing_models = []
    failing_models = []

    for model in models:
        result = await evaluate_token_against_model(token_data, model)
        result["model_name"] = model.get("name")
        model_results.append(result)
        if result["passed"]:
            any_passed = True
            passing_models.append(model.get("name"))
            total_score += result["score"]
        else:
            failing_models.append(model.get("name"))

    avg_score = total_score / len(passing_models) if passing_models else 0
    master_grade = "A" if avg_score >= 85 else "B" if avg_score >= 70 else "C" if avg_score >= 55 else "D"
    return {
        "passed": any_passed,
        "master_score": round(avg_score, 1),
        "master_grade": master_grade,
        "passing_models": passing_models,
        "failing_models": failing_models,
        "model_results": model_results,
        "total_models": len(models),
    }
