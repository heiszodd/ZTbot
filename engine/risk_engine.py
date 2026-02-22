import logging

import db

log = logging.getLogger(__name__)


def calculate_position_size(account_size: float, risk_pct: float, entry: float, stop_loss: float) -> dict:
    if entry <= 0 or stop_loss <= 0:
        return {"error": "Invalid entry or stop loss"}
    stop_distance = abs(entry - stop_loss)
    if stop_distance == 0:
        return {"error": "Entry and stop loss are equal"}
    risk_amount = account_size * (risk_pct / 100)
    stop_distance_pct = stop_distance / entry * 100
    position_size = risk_amount / stop_distance
    position_value = position_size * entry
    leverage_needed = position_value / account_size if account_size > 0 else 0
    return {
        "risk_amount": round(risk_amount, 2),
        "stop_distance": round(stop_distance, 6),
        "stop_distance_pct": round(stop_distance_pct, 3),
        "position_size": round(position_size, 6),
        "position_value": round(position_value, 2),
        "leverage_needed": round(leverage_needed, 2),
        "rr_ratio": None,
    }


def calculate_rr(entry: float, stop_loss: float, take_profit: float, direction: str) -> float:
    bullish = str(direction).lower() in {"bullish", "long", "buy"}
    if bullish:
        reward = take_profit - entry
        risk = entry - stop_loss
    else:
        reward = entry - take_profit
        risk = stop_loss - entry
    if risk <= 0:
        return 0.0
    return round(reward / risk, 2)


def check_daily_loss_limit(settings: dict, tracker: dict) -> dict:
    if tracker.get("daily_loss_hit"):
        return {"ok": False, "reason": "Daily loss limit already hit today", "used_pct": settings["max_daily_loss_pct"]}
    starting = tracker.get("starting_balance", 0)
    if starting <= 0:
        return {"ok": True, "used_pct": 0}
    realised_pnl = tracker.get("realised_pnl", 0)
    loss_pct = (realised_pnl / starting * 100) if realised_pnl < 0 else 0
    used_pct = abs(loss_pct)
    limit = settings.get("max_daily_loss_pct", 3.0)
    if used_pct >= limit:
        db.update_daily_tracker({"daily_loss_hit": True})
        return {"ok": False, "reason": f"Daily loss limit reached: {used_pct:.1f}% of {limit:.1f}% max", "used_pct": used_pct}
    return {"ok": True, "used_pct": used_pct}


def check_open_trades_limit(settings: dict, open_trades: list) -> dict:
    current = len(open_trades)
    maximum = settings.get("max_open_trades", 3)
    if current >= maximum:
        return {"ok": False, "reason": f"Max open trades reached: {current}/{maximum}"}
    return {"ok": True, "current": current, "maximum": maximum}


def check_pair_exposure(settings: dict, open_trades: list, new_pair: str, new_risk_amount: float, account_size: float) -> dict:
    pair_risk = sum(t.get("risk_amount", 0) or 0 for t in open_trades if t.get("pair") == new_pair)
    total_pair_risk = pair_risk + new_risk_amount
    pair_exposure_pct = total_pair_risk / account_size * 100 if account_size > 0 else 0
    max_pair = settings.get("max_pair_exposure", 2.0)
    if pair_exposure_pct > max_pair:
        return {"ok": False, "reason": f"Pair exposure too high: {new_pair} would be {pair_exposure_pct:.1f}% of account (max {max_pair}%)"}
    return {"ok": True, "pair_exposure_pct": pair_exposure_pct}


def check_total_exposure(settings: dict, open_trades: list, new_risk_amount: float, account_size: float) -> dict:
    open_risk = sum(t.get("risk_amount", 0) or 0 for t in open_trades)
    total_risk = open_risk + new_risk_amount
    exposure_pct = total_risk / account_size * 100 if account_size > 0 else 0
    max_exposure = settings.get("max_exposure_pct", 5.0)
    if exposure_pct > max_exposure:
        return {"ok": False, "reason": f"Total exposure too high: {exposure_pct:.1f}% of account (max {max_exposure}%)"}
    return {"ok": True, "exposure_pct": exposure_pct}


def check_rr_minimum(settings: dict, entry: float, stop_loss: float, tp1: float, direction: str) -> dict:
    rr = calculate_rr(entry, stop_loss, tp1, direction)
    minimum = settings.get("risk_reward_min", 1.5)
    if rr < minimum:
        return {"ok": False, "reason": f"RR too low: {rr:.1f} (minimum {minimum:.1f})"}
    return {"ok": True, "rr": rr}


async def run_risk_checks(pair: str, direction: str, entry: float, stop_loss: float, tp1: float) -> dict:
    settings = db.get_risk_settings()
    tracker = db.get_daily_tracker()
    open_trades = db.get_open_demo_trades_all()
    if not settings.get("enabled", True):
        return {"approved": True, "risk_level": "green", "position": {}, "checks": [], "warnings": [], "blockers": [], "rr": calculate_rr(entry, stop_loss, tp1, direction), "summary": "Risk checks disabled"}
    account_size = settings.get("account_size", 1000.0)
    risk_pct = settings.get("risk_per_trade_pct", 1.0)
    position = calculate_position_size(account_size, risk_pct, entry, stop_loss)
    if "error" in position:
        return {"approved": False, "risk_level": "red", "position": position, "checks": [], "warnings": [], "blockers": [position["error"]], "rr": 0, "summary": f"Invalid levels: {position['error']}"}
    risk_amount = position["risk_amount"]
    rr = calculate_rr(entry, stop_loss, tp1, direction)
    position["rr_ratio"] = rr
    checks, warnings, blockers = [], [], []
    checks_to_run = [
        ("daily_loss", check_daily_loss_limit(settings, tracker)),
        ("open_trades", check_open_trades_limit(settings, open_trades)),
        ("pair_exposure", check_pair_exposure(settings, open_trades, pair, risk_amount, account_size)),
        ("total_exposure", check_total_exposure(settings, open_trades, risk_amount, account_size)),
        ("rr_minimum", check_rr_minimum(settings, entry, stop_loss, tp1, direction)),
    ]
    for check_name, result in checks_to_run:
        checks.append({"name": check_name, "ok": result["ok"], "detail": result.get("reason", "")})
        if not result["ok"]:
            if check_name in ("daily_loss", "rr_minimum"):
                blockers.append(result.get("reason", ""))
            else:
                warnings.append(result.get("reason", ""))
    approved = len(blockers) == 0
    risk_level = "red" if blockers else "yellow" if warnings else "green"
    summary = _build_summary(approved, risk_level, position, rr, warnings, blockers, account_size, risk_pct, pair)
    return {"approved": approved, "risk_level": risk_level, "position": position, "checks": checks, "warnings": warnings, "blockers": blockers, "rr": rr, "summary": summary}


def _build_summary(approved, risk_level, position, rr, warnings, blockers, account_size, risk_pct, pair) -> str:
    emoji = {"green": "✅", "yellow": "⚠️", "red": "🚫"}.get(risk_level, "⚠️")
    lines = [
        f"{emoji} Risk: {risk_level.upper()}",
        f"Size:  {position.get('position_size',0):.4f} {pair.replace('USDT','')}",
        f"Risk:  ${position.get('risk_amount',0):.2f} ({risk_pct}% of account)",
        f"RR:    {rr:.1f}:1",
        f"Lev:   {position.get('leverage_needed',1):.1f}x",
    ]
    if blockers:
        lines += ["", "🚫 Blocked:"] + [f"  • {b}" for b in blockers]
    if warnings:
        lines += ["", "⚠️ Warnings:"] + [f"  • {w}" for w in warnings]
    return "\n".join(lines)
