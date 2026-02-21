from __future__ import annotations

from datetime import datetime, timezone

from degen.risk_engine import analyze_volume_pattern, get_token_profile


def analyze_bonding_curve(token_data: dict) -> dict:
    is_pumpfun = bool(token_data.get("is_pumpfun") or "pump.fun" in str(token_data.get("url", "")).lower())
    graduated = bool(token_data.get("graduated"))
    graduation_threshold_sol = 85
    current_sol = float(token_data.get("virtual_sol_reserves") or 0) / 1e9
    curve_pct = min((current_sol / graduation_threshold_sol) * 100, 100) if graduation_threshold_sol else 0
    if curve_pct < 10:
        moon_bonus, label, note = 10, "🌱 Very early — massive upside if it graduates", "High risk — most tokens die here"
    elif curve_pct < 30:
        moon_bonus, label, note = 8, "📈 Early stage — good risk/reward", "Still needs to prove itself"
    elif curve_pct < 60:
        moon_bonus, label, note = 5, "🔥 Mid curve — momentum building", "Getting interesting — watch for graduation"
    elif curve_pct < 80:
        moon_bonus, label, note = 12, "🚀 Late curve — graduation likely", "Early buyers may dump at graduation"
    elif curve_pct < 95:
        moon_bonus, label, note = 6, "⚡ Near graduation — high volatility zone", "Dump risk at graduation is significant"
    else:
        moon_bonus, label, note = 8, "✅ Graduated to Raydium — survived the curve", "Now trading on open market"
    if graduated:
        curve_pct = 100
        moon_bonus, label, note = 8, "✅ Graduated to Raydium — survived the curve", "Now trading on open market"
    eta = "unknown"
    if curve_pct < 100:
        eta = "<1h" if curve_pct > 75 else "1-4h" if curve_pct > 40 else ">4h"
    return {"curve_pct": round(curve_pct, 2), "curve_label": label, "risk_note": note, "moon_bonus": moon_bonus if is_pumpfun else 0, "graduation_eta_estimate": eta, "is_pumpfun": is_pumpfun}


def check_social_velocity(token_data: dict) -> dict:
    moon_bonus = 0
    replies_per_hour = 0.0
    members_per_hour = 0.0
    now = datetime.now(timezone.utc)
    initial_replies = int(token_data.get("initial_reply_count") or 0)
    current_replies = int(token_data.get("reply_count") or initial_replies)
    detected_at = token_data.get("initial_detected_at") or token_data.get("created_at")
    if isinstance(detected_at, datetime):
        hours = max((now - detected_at.replace(tzinfo=timezone.utc)).total_seconds() / 3600, 1e-6)
    else:
        hours = max(float(token_data.get("hours_since_detection") or 1), 1e-6)
    replies_per_hour = max((current_replies - initial_replies) / hours, 0)
    if replies_per_hour > 50:
        moon_bonus += 10
        vlabel = "🔥 Viral community growth"
    elif replies_per_hour > 20:
        moon_bonus += 6
        vlabel = "📈 Active community"
    elif replies_per_hour < 2:
        moon_bonus -= 5
        vlabel = "📉 Dead community"
    else:
        vlabel = "📊 Neutral social growth"

    members = float(token_data.get("telegram_members") or 0)
    launch_hours = max(float(token_data.get("hours_since_launch") or hours), 1e-6)
    if members > 0:
        members_per_hour = members / launch_hours
        if members_per_hour > 100:
            moon_bonus += 8
            vlabel = "🔥 Explosive Telegram growth"
        elif members_per_hour > 30:
            moon_bonus += 4
            vlabel = "📈 Good Telegram growth"

    score = max(0, min(100, int(50 + moon_bonus * 3)))
    return {"velocity_score": score, "velocity_label": vlabel, "replies_per_hour": round(replies_per_hour, 2), "members_per_hour": round(members_per_hour, 2), "moon_bonus": moon_bonus}


def calculate_smart_exits(token_data: dict, entry_price: float) -> dict:
    liq = float(token_data.get("liquidity_usd") or 0)
    if liq < 10000:
        mx, note = 2.0, "Low liquidity — exit before 2x or you won't get filled"
    elif liq < 50000:
        mx, note = 5.0, "Moderate liquidity — 3-5x achievable before slippage kills exits"
    elif liq < 200000:
        mx, note = 15.0, "Good liquidity — double-digit X possible"
    else:
        mx, note = 50.0, "Strong liquidity — hold for larger moves"
    tp1 = entry_price * min(1.5, mx * 0.3)
    tp2 = entry_price * min(3.0, mx * 0.6)
    tp3 = entry_price * mx
    sl = entry_price * 0.75
    return {"tp1": tp1, "tp2": tp2, "tp3": tp3, "max_realistic_x": mx, "sl": sl, "liquidity_note": note, "time_stop_minutes": 30, "exit_strategy": "⏰ Time stop: if no significant move in 30 minutes, consider exiting to preserve capital"}


def score_moonshot_potential(token: dict, token_profile: str | None = None) -> dict:
    profile = token_profile or get_token_profile(token)
    score = 35
    categories = {k: [] for k in ["narrative", "momentum", "safety", "market", "community", "technical"]}
    mcap = float(token.get("mcap") or token.get("market_cap") or 0)
    liq = float(token.get("liquidity_usd") or 0)
    if mcap and mcap < 20_000_000:
        score += 18
        categories["market"].append("Early market cap stage")
    if liq > 50_000:
        score += 15
        categories["market"].append("Tradable liquidity")
    if token.get("mint_revoked"):
        score += 5
        categories["safety"].append("Mint revoked")
    if int(token.get("holder_count") or 0) >= (50 if profile == "pumpfun_prebonding" else 200 if profile == "pumpfun_graduated" else 100):
        score += 10
        categories["community"].append("Strong holder base")

    curve = analyze_bonding_curve(token)
    if profile == "pumpfun_prebonding":
        score += int(curve["moon_bonus"] * 2.0)
        categories["technical"].append("Bonding curve setup")
    velocity = check_social_velocity(token)
    vel_weight = 1.8 if profile == "pumpfun_prebonding" else 1.0
    score += int(velocity["moon_bonus"] * vel_weight)
    if velocity["moon_bonus"]:
        categories["narrative"].append(velocity["velocity_label"])

    volume = analyze_volume_pattern(token.get("recent_candles") or token.get("recent_txs") or [])
    score += int(volume.get("moon_added") or 0)
    if volume.get("moon_added"):
        categories["technical"].append(volume.get("pattern_label"))

    contributing = sum(1 for v in categories.values() if v)
    conf_label = "✅ Strong confluence"
    mult = 1.0
    if contributing == 3:
        mult = 0.85
        conf_label = "📊 Moderate confluence"
    elif contributing == 2:
        mult = 0.65
        conf_label = "⚠️ Weak confluence — only 2 categories"
    elif contributing <= 1:
        mult = 0.4
        conf_label = "❌ Single-category score — unreliable"
    score = int(max(1, min(100, score * mult)))
    label = "HIGH" if score >= 75 else "MEDIUM" if score >= 50 else "LOW"
    return {
        "moon_score": score,
        "label": label,
        "bull_factors": [x for vals in categories.values() for x in vals][:4],
        "confluence": {"contributing_categories": contributing, "confidence_label": conf_label, "breakdown": categories},
        "bonding_curve": curve,
        "social_velocity": velocity,
        "smart_exits": calculate_smart_exits(token, float(token.get("price_usd") or 0) or 0.0000001),
        "profile": profile,
    }
