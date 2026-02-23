import asyncio
import logging
from datetime import datetime

import db

log = logging.getLogger(__name__)


def get_pattern_keys(alert_data: dict) -> list:
    session = alert_data.get("session", "Unknown")
    pair = alert_data.get("pair", "?")
    model_id = alert_data.get("model_id", "?")
    direction = alert_data.get("direction", "?")
    grade = alert_data.get("quality_grade", "C")
    return [f"session_{session}", f"pair_{pair}", f"session_pair_{session}_{pair}", f"model_{model_id}", f"direction_{direction}", f"grade_{grade}"]


def should_suppress_alert(alert_data: dict) -> dict:
    keys = get_pattern_keys(alert_data)
    suppressed_patterns = []
    for key in keys:
        pattern = db.get_notification_pattern(key)
        if not pattern:
            continue
        if pattern.get("suppressed") and not pattern.get("override") and pattern.get("total_alerts", 0) >= 10 and not key.startswith("grade_"):
            suppressed_patterns.append({"key": key, "action_rate": pattern.get("action_rate", 0), "total": pattern.get("total_alerts", 0)})
    if suppressed_patterns:
        best = min(suppressed_patterns, key=lambda x: x["action_rate"])
        reason = f"You typically ignore alerts matching '{best['key']}' (acted on {best['action_rate']:.0%} of {best['total']} alerts)"
        return {"suppress": True, "reason": reason, "patterns": suppressed_patterns}
    return {"suppress": False, "reason": "", "patterns": []}


def record_alert_fired(alert_data: dict) -> None:
    for key in get_pattern_keys(alert_data):
        db.increment_pattern_alert(key)


def record_entry_touched(alert_data: dict) -> None:
    for key in get_pattern_keys(alert_data):
        db.increment_pattern_action(key)
        db.recalculate_action_rate(key)


async def run_pattern_analysis(context) -> None:
    try:
        await asyncio.wait_for(_run_pattern_analysis_inner(context), timeout=60)
    except asyncio.TimeoutError:
        log.warning("pattern_analysis timed out after 60 seconds")
    except Exception as e:
        log.error(f"pattern_analysis error: {e}")


async def _run_pattern_analysis_inner(context) -> None:
    from config import CHAT_ID

    patterns = db.get_all_notification_patterns()
    newly_suppressed, newly_cleared = [], []
    for p in patterns:
        total = p.get("total_alerts", 0)
        rate = p.get("action_rate", 1.0)
        key = p["pattern_key"]
        if total < 10:
            continue
        if rate < 0.15 and not p.get("suppressed"):
            db.update_notification_pattern(key, {"suppressed": True, "suppressed_at": datetime.utcnow().isoformat()})
            newly_suppressed.append(f"{key} ({rate:.0%} action rate)")
        elif rate >= 0.30 and p.get("suppressed") and not p.get("override"):
            db.update_notification_pattern(key, {"suppressed": False})
            newly_cleared.append(key)
    if newly_suppressed or newly_cleared:
        text = "🔔 *Notification Filter Updated*\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        if newly_suppressed:
            text += "*Suppressed (low action rate):*\n" + "\n".join([f"• {i}" for i in newly_suppressed]) + "\n\n"
        if newly_cleared:
            text += "*Re-enabled (action rate improved):*\n" + "\n".join([f"• {i}" for i in newly_cleared]) + "\n\n"
        text += "_Override any of these in:\nPerps → Notification Filter_"
        await context.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")
