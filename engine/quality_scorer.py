from datetime import datetime


def score_setup_quality(phase1_result: dict, phase2_result: dict, phase3_result: dict, pair: str, direction: str, model: dict, candle_cache: dict = None) -> dict:
    score = 0.0
    breakdown = {}
    p1_pct = phase1_result.get("score_pct", 0)
    p2_pct = phase2_result.get("score_pct", 0)
    p3_pct = phase3_result.get("score_pct", 0)
    p1_pts = p1_pct / 100 * 15
    p2_pts = p2_pct / 100 * 15
    p3_pts = p3_pct / 100 * 10
    score += p1_pts + p2_pts + p3_pts
    breakdown["phase_scores"] = round(p1_pts + p2_pts + p3_pts, 1)

    from engine.rules import is_in_session
    if is_in_session("Overlap"):
        sess_pts, sess_label = 20, "Overlap"
    elif is_in_session("London"):
        sess_pts, sess_label = 20, "London"
    elif is_in_session("NY"):
        sess_pts, sess_label = 20, "NY"
    elif is_in_session("Asia"):
        sess_pts, sess_label = 10, "Asia"
    else:
        sess_pts, sess_label = 5, "Off-hours"
    score += sess_pts
    breakdown["session"] = {"points": sess_pts, "label": sess_label}

    align_pts = 0
    if phase1_result.get("passed") and phase2_result.get("passed"):
        align_pts += 10
    if p1_pct > 70:
        align_pts += 5
    if p2_pct > 65:
        align_pts += 5
    score += align_pts
    breakdown["alignment"] = align_pts

    speed_pts = 2
    try:
        p1_time = phase1_result.get("completed_at")
        p2_time = phase2_result.get("completed_at")
        if p1_time and p2_time:
            if isinstance(p1_time, str):
                p1_time = datetime.fromisoformat(p1_time)
            if isinstance(p2_time, str):
                p2_time = datetime.fromisoformat(p2_time)
            mins = (p2_time - p1_time).total_seconds() / 60
            if mins <= 30:
                speed_pts = 10
            elif mins <= 60:
                speed_pts = 7
            elif mins <= 120:
                speed_pts = 4
    except Exception:
        pass
    score += speed_pts
    breakdown["speed"] = speed_pts

    all_mandatory_failed = (phase1_result.get("mandatory_failed", []) + phase2_result.get("mandatory_failed", []) + phase3_result.get("mandatory_failed", []))
    mand_pts = 10 if len(all_mandatory_failed) == 0 else 5 if len(all_mandatory_failed) == 1 else 0
    score += mand_pts
    breakdown["mandatory"] = mand_pts
    score = round(min(score, 100), 1)

    if score >= 88:
        grade = "A+"
    elif score >= 78:
        grade = "A"
    elif score >= 65:
        grade = "B"
    elif score >= 50:
        grade = "C"
    else:
        grade = "D"

    grade_emoji = {"A+": "🏆", "A": "✅", "B": "👍", "C": "⚠️", "D": "❌"}.get(grade, "⚠️")
    return {
        "score": score,
        "grade": grade,
        "grade_emoji": grade_emoji,
        "breakdown": breakdown,
        "session": sess_label,
        "passed_rules_count": len(phase1_result.get("passed_rules", [])) + len(phase2_result.get("passed_rules", [])) + len(phase3_result.get("passed_rules", [])),
        "phase_pcts": {"p1": round(p1_pct, 1), "p2": round(p2_pct, 1), "p3": round(p3_pct, 1)},
    }


def format_quality_badge(quality: dict) -> str:
    grade = quality["grade"]
    score = quality["score"]
    emoji = quality["grade_emoji"]
    pcts = quality["phase_pcts"]
    return f"{emoji} *Grade: {grade}*  ({score}/100)\nP1: {pcts['p1']:.0f}%  P2: {pcts['p2']:.0f}%  P3: {pcts['p3']:.0f}%  Session: {quality['session']}"
