from __future__ import annotations

from engine.degen.checks import get_check_function


async def evaluate_token_against_model(token_data: dict, model: dict) -> dict:
    mandatory_fails = []
    passed_checks = []
    failed_checks = []
    weighted_score = 0.0
    total_weight = 0.0

    for check_name in model.get("mandatory_checks", []):
        check_fn = get_check_function(check_name)
        if check_fn is None:
            continue
        result = await check_fn(token_data, model)
        if not result:
            mandatory_fails.append(check_name)
        else:
            passed_checks.append(check_name)

    if mandatory_fails:
        return {
            "passed": False,
            "score": 0.0,
            "grade": "F",
            "passed_checks": passed_checks,
            "failed_checks": mandatory_fails,
            "mandatory_fails": mandatory_fails,
            "weighted_score": 0.0,
            "recommendation": f"Failed mandatory: {', '.join(mandatory_fails)}",
        }

    for wc in model.get("weighted_checks", []):
        check_name = wc.get("check", "")
        weight = float(wc.get("weight", 1) or 1)
        check_fn = get_check_function(check_name)
        if check_fn is None:
            continue
        total_weight += weight
        result = await check_fn(token_data, model)
        if result:
            weighted_score += weight
            passed_checks.append(check_name)
        else:
            failed_checks.append(check_name)

    score = weighted_score / total_weight * 100 if total_weight > 0 else 0
    grade = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 55 else "D" if score >= 40 else "F"
    passed = score >= float(model.get("min_score", 60) or 60)
    recommendation = "Strong buy — A/B" if score >= 80 else "Potential — verify manually" if score >= 60 else "Weak — skip or watch"
    return {
        "passed": passed,
        "score": round(score, 1),
        "grade": grade,
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "mandatory_fails": [],
        "weighted_score": round(weighted_score, 1),
        "recommendation": recommendation,
    }
