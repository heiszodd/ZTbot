from __future__ import annotations

from degen.rule_library import get_rule


def evaluate_token_against_model(token_data: dict, model: dict) -> dict:
    token_data = token_data or {}
    model = model or {}

    if token_data.get("honeypot") is True:
        return {
            "passed": False,
            "invalidated": True,
            "invalidation_reason": "Honeypot detected",
            "score": 0.0,
            "max_possible_score": 0.0,
            "passed_rules": [],
            "failed_rules": [],
            "mandatory_failed": [],
            "gate_failures": ["Honeypot detected"],
            "confluence_count": 0,
            "confluence_fraction": "0/0",
        }

    gate_failures = []
    chains = model.get("chains") or ["SOL"]
    if token_data.get("chain") not in chains:
        gate_failures.append("Chain not enabled")

    age = token_data.get("token_age_minutes", 0)
    if age < model.get("min_token_age_minutes", 2) or age > model.get("max_token_age_minutes", 120):
        gate_failures.append("Token age outside configured range")

    if token_data.get("liquidity_usd", 0) < model.get("min_liquidity", 5000):
        gate_failures.append("Liquidity below minimum")

    if model.get("block_serial_ruggers", True) and token_data.get("dev_reputation") == "SERIAL_RUGGER":
        gate_failures.append("Serial rugger blocked")
    if model.get("require_lp_locked") and token_data.get("lp_locked_pct", 0) == 0:
        gate_failures.append("LP lock required")
    if model.get("require_mint_revoked") and token_data.get("mint_authority_revoked") is False:
        gate_failures.append("Mint revoke required")
    if model.get("require_verified") and token_data.get("contract_verified") is False:
        gate_failures.append("Verified contract required")
    if token_data.get("risk_score", 100) > model.get("max_risk_score", 60):
        gate_failures.append("Risk score too high")
    if token_data.get("moon_score", 0) < model.get("min_moon_score", 40):
        gate_failures.append("Moon score too low")

    passed_rules, failed_rules, mandatory_failed = [], [], []
    score = 0.0
    max_possible = 0.0

    for configured_rule in model.get("rules", []):
        rule_id = configured_rule.get("id") if isinstance(configured_rule, dict) else configured_rule
        rule_def = get_rule(rule_id)
        if not rule_def:
            continue
        mandatory = bool(configured_rule.get("mandatory", rule_def.get("mandatory_default", False))) if isinstance(configured_rule, dict) else rule_def.get("mandatory_default", False)
        weight = float(configured_rule.get("weight", rule_def.get("weight_default", 1.0))) if isinstance(configured_rule, dict) else float(rule_def.get("weight_default", 1.0))
        max_possible += weight

        try:
            passed = rule_def["evaluate"](token_data)
        except Exception:
            passed = False
        view = {"id": rule_id, "name": rule_def["name"], "weight": weight, "mandatory": mandatory}
        if passed:
            score += weight
            passed_rules.append(view)
        else:
            failed_rules.append(view)
            if mandatory:
                mandatory_failed.append(rule_def["name"])

    invalidated = bool(gate_failures or mandatory_failed)
    invalidation_reason = gate_failures[0] if gate_failures else (f"Mandatory rules failed: {', '.join(mandatory_failed)}" if mandatory_failed else None)
    passed = (not invalidated) and score >= float(model.get("min_score", 50))
    total_rules = len(passed_rules) + len(failed_rules)

    return {
        "passed": passed,
        "invalidated": invalidated,
        "invalidation_reason": invalidation_reason,
        "score": round(score, 2),
        "max_possible_score": round(max_possible, 2),
        "passed_rules": passed_rules,
        "failed_rules": failed_rules,
        "mandatory_failed": mandatory_failed,
        "gate_failures": gate_failures,
        "confluence_count": len(passed_rules),
        "confluence_fraction": f"{len(passed_rules)}/{total_rules}",
    }
