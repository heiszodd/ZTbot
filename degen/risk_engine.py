from __future__ import annotations

import math
import statistics
import time
from datetime import datetime, timezone
from typing import Any

import requests

_SOLSCAN_CREATION_CACHE: dict[str, float] = {}


def get_token_profile(token_data: dict) -> str:
    is_pump = bool(token_data.get("is_pumpfun") or "pump.fun" in str(token_data.get("url", "")).lower())
    graduated = bool(token_data.get("graduated") or token_data.get("raydium_pool"))
    age_h = float(token_data.get("age_hours") or 0)
    if is_pump and not graduated:
        return "pumpfun_prebonding"
    if is_pump and graduated:
        return "pumpfun_graduated"
    if age_h and age_h > 24 * 7:
        return "established"
    return "dexscreener_new"


def score_trajectory(first_score: dict, second_score: dict) -> dict:
    a = int(first_score.get("risk_score") or first_score.get("score") or 0)
    b = int(second_score.get("risk_score") or second_score.get("score") or 0)
    delta = b - a
    warning = None
    if delta > 20:
        label = "🚨 Rapidly worsening — possible rug in progress"
        trajectory = "worsening"
        significant = True
        warning = label
    elif delta > 10:
        label = "⚠️ Risk increasing — monitor closely"
        trajectory = "worsening"
        significant = True
        warning = label
    elif delta > 0:
        label = "📊 Slightly worse — within normal range"
        trajectory = "worsening"
        significant = False
    elif delta == 0:
        label = "✅ Stable"
        trajectory = "stable"
        significant = False
    else:
        label = "✅ Improving — risk reducing"
        trajectory = "improving"
        significant = False
    return {"delta": delta, "trajectory": trajectory, "trajectory_label": label, "significant": significant, "warning_message": warning}


def _safe_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def check_liquidity_depth(token_data: dict) -> dict:
    providers = token_data.get("lp_providers") or []
    if not providers and token_data.get("pairAddress") and token_data.get("chain"):
        try:
            url = f"https://api.dexscreener.com/latest/dex/pairs/{token_data['chain']}/{token_data['pairAddress']}"
            payload = requests.get(url, timeout=8).json()
            pair = (payload.get("pair") or {}) if isinstance(payload, dict) else {}
            providers = pair.get("liquidityProviders") or []
        except Exception:
            providers = []
    if providers:
        vals = [float(p.get("usd") or p.get("value") or 0) for p in providers]
        total = sum(vals) or 1
        top_lp_pct = (max(vals) / total) * 100 if vals else 100.0
        lp_count = len([v for v in vals if v > 0])
    else:
        liq = float(token_data.get("liquidity_usd") or 0)
        top = float(token_data.get("top_lp_usd") or (liq * 0.9 if liq else 0))
        top_lp_pct = (top / liq) * 100 if liq else 100.0
        lp_count = int(token_data.get("lp_provider_count") or (1 if liq else 0))

    risk_added, label = 0, ""
    if lp_count == 1:
        risk_added += 20
        label = "🚨 Single LP provider — can drain instantly"
    if top_lp_pct > 80:
        risk_added += 15
        label = "🚨 LP highly concentrated in one wallet"
    elif top_lp_pct > 50:
        risk_added += 8
        label = "⚠️ LP concentration above 50%"
    if lp_count >= 5:
        risk_added -= 5
        label = "✅ LP spread across multiple providers"
    return {"lp_provider_count": lp_count, "top_lp_pct": round(top_lp_pct, 2), "lp_concentration_risk": top_lp_pct > 80, "risk_added": risk_added, "label": label}


def check_volume_authenticity(token_data: dict, recent_txs: list) -> dict:
    amounts = [float(t.get("amount") or t.get("amount_usd") or t.get("value") or 0) for t in recent_txs if float(t.get("amount") or t.get("amount_usd") or t.get("value") or 0) > 0]
    times = [float(t.get("timestamp") or t.get("time") or 0) for t in recent_txs if t.get("timestamp") or t.get("time")]
    flags, risk = [], 0

    round_hits = 0
    for a in amounts:
        if any(abs(a % d) < 1e-9 for d in (10, 100, 1000)):
            round_hits += 1
    round_pct = (round_hits / len(amounts) * 100) if amounts else 0
    if round_pct > 60:
        risk += 10
        flags.append("⚠️ Unusual number of round-number transactions")

    mean = _safe_mean(amounts)
    std = statistics.pstdev(amounts) if len(amounts) > 1 else 0
    if mean > 0 and (std / mean) < 0.15:
        risk += 15
        flags.append("🚨 Suspiciously uniform transaction sizes")

    timing_uniform = False
    if len(times) > 3:
        times = sorted(times)
        gaps = [times[i] - times[i - 1] for i in range(1, len(times))]
        centered = _safe_mean(gaps)
        close = sum(1 for g in gaps if abs(g - centered) <= 2)
        timing_uniform = close / len(gaps) > 0.5 if gaps else False
        if timing_uniform:
            risk += 10
            flags.append("⚠️ Bot-like transaction timing")

    buyers = [t.get("buyer") or t.get("wallet") for t in recent_txs if t.get("buyer") or t.get("wallet")]
    top_buyers = list(dict.fromkeys(buyers))[:10]
    funder_counts: dict[str, int] = {}
    for w in top_buyers:
        funder = (token_data.get("wallet_funders") or {}).get(w)
        if not funder:
            continue
        funder_counts[funder] = funder_counts.get(funder, 0) + 1
    max_cluster = max(funder_counts.values()) if funder_counts else 0
    wallet_clustering = max_cluster >= 3
    if max_cluster >= 5:
        risk += 25
        flags.append("🚨 Coordinated wallets — same funding source")
    elif max_cluster >= 3:
        risk += 12
        flags.append("⚠️ Some wallet clustering detected")

    score = max(0, min(100, risk))
    if score < 20:
        label = "✅ Volume appears organic"
    elif score <= 40:
        label = "📊 Some suspicious patterns"
    elif score <= 60:
        label = "⚠️ Likely partial wash trading"
    else:
        label = "🚨 Strong wash trading signals"
    return {"authenticity_score": score, "authenticity_label": label, "risk_added": risk, "flags": flags, "round_number_pct": round(round_pct, 2), "wallet_clustering": wallet_clustering, "timing_uniform": timing_uniform}


def _solscan_first_tx_ts(wallet: str) -> float:
    if wallet in _SOLSCAN_CREATION_CACHE:
        return _SOLSCAN_CREATION_CACHE[wallet]
    time.sleep(0.2)
    try:
        url = f"https://public-api.solscan.io/account/transactions?account={wallet}&limit=1&offset=0"
        rows = requests.get(url, timeout=8).json()
        ts = float(rows[-1].get("blockTime") if rows else 0)
    except Exception:
        ts = 0.0
    _SOLSCAN_CREATION_CACHE[wallet] = ts
    return ts


def check_holder_clustering(top_holders: list, chain: str) -> dict:
    holders = [h for h in top_holders[:15] if h]
    if chain.upper() != "SOL" or not holders:
        return {"cluster_pct": 0.0, "largest_cluster_size": 0, "total_checked": 0, "risk_added": 0, "label": "N/A", "coordinated_launch": False}
    dates = [int(_solscan_first_tx_ts(w)) for w in holders if _solscan_first_tx_ts(w) > 0]
    dates.sort()
    largest = 0
    for i, ts in enumerate(dates):
        count = sum(1 for x in dates if abs(x - ts) <= 48 * 3600)
        largest = max(largest, count)
    total = len(dates)
    cluster_pct = (largest / total) if total else 0
    risk, label = 0, ""
    if cluster_pct > 0.7:
        risk, label = 25, "🚨 70%+ of top holders created at same time — pre-loaded wallets"
    elif cluster_pct > 0.5:
        risk, label = 15, "⚠️ Majority of holders have similar creation dates"
    elif cluster_pct > 0.3:
        risk, label = 8, "📊 Some holder wallet clustering"
    elif cluster_pct < 0.2 and total:
        risk, label = -5, "✅ Holder wallets have diverse ages"
    return {"cluster_pct": round(cluster_pct, 3), "largest_cluster_size": largest, "total_checked": total, "risk_added": risk, "label": label, "coordinated_launch": cluster_pct > 0.5}


def analyze_volume_pattern(candles_or_txs: list) -> dict:
    vols = [float(x.get("volume") or x.get("amount") or x.get("amount_usd") or 0) for x in candles_or_txs]
    vols = [v for v in vols if v > 0]
    if not vols:
        return {"pattern": "organic", "pattern_label": "No volume data", "risk_added": 0, "moon_added": 0, "cv": 0.0, "peak_to_now_ratio": 0.0}
    mean = _safe_mean(vols)
    std = statistics.pstdev(vols) if len(vols) > 1 else 0.0
    cv = std / mean if mean else 0
    first = sum(vols[: max(1, len(vols)//2)])
    second = sum(vols[max(1, len(vols)//2):])
    peak, now = max(vols), vols[-1]
    peak_now = (peak / max(now, 1e-9)) if now else 999

    pattern, label, risk, moon = "organic", "Organic volume", 0, 0
    if cv < 0.3:
        pattern, label, risk = "uniform", "Suspiciously uniform volume", 10
    if first > second * 5 and second > 0:
        pattern, label, risk = "pumped", "Classic pump-and-dump profile", max(risk, 12)
    if peak > 0 and now / peak < 0.2:
        pattern, label, risk = "dying", "Volume dying — momentum gone", max(risk, 10)
    if len(vols) >= 4 and all(vols[i] <= vols[i+1] for i in range(len(vols)-1)):
        pattern, label, moon = "accumulating", "📈 Organic accumulation pattern", 8
        risk = 0
    return {"pattern": pattern, "pattern_label": label, "risk_added": risk, "moon_added": moon, "cv": round(cv, 3), "peak_to_now_ratio": round(peak_now, 3)}


def analyze_token_description(name: str, description: str) -> dict:
    d = (description or "")
    dl = d.lower()
    red, green, risk = [], [], 0
    urgency_keywords = ["don't miss", "last chance", "limited time", "guaranteed", "100x guaranteed", "get in now", "buy now", "moon guaranteed", "sure thing", "can't lose", "next shib", "next doge", "1000x", "will moon"]
    hits = sum(1 for k in urgency_keywords if k in dl)
    if hits:
        add = min(20, hits * 8)
        risk += add
        red.append("⚠️ High-pressure language detected")
    caps_ratio = (sum(1 for c in d if c.isupper()) / max(len(d), 1))
    if caps_ratio > 0.4:
        risk += 5
        red.append("⚠️ Excessive capitalisation")
    promise_patterns = ["will 100x", "will moon", "guaranteed return", "risk free"]
    has_prom = any(p in dl for p in promise_patterns)
    if has_prom:
        risk += 15
        red.append("🚨 Explicit return promises — regulatory red flag")
    generic_phrases = ["to the moon", "diamond hands", "hodl", "revolutionary token", "deflationary", "yield farming", "the next big thing"]
    generic_count = sum(1 for p in generic_phrases if p in dl)
    if generic_count > 3:
        risk += 8
        red.append("⚠️ Generic copy-paste description")
    if len(d) > 200 and not red:
        risk -= 3
        green.append("✅ Detailed original description")
    if any(k in dl for k in ["utility", "platform", "payments", "game", "staking", "marketplace"]):
        risk -= 3
        green.append("✅ Clear use case")
    quality = "poor" if risk >= 20 else "generic" if risk >= 10 else "average" if risk >= 3 else "good"
    return {"risk_added": risk, "red_flags": red, "green_flags": green, "description_quality": quality, "has_promises": has_prom}


def detect_insider_accumulation(token_data: dict, early_txs: list) -> dict:
    dev = token_data.get("dev_wallet")
    connected = 0
    buyers = [t.get("buyer") for t in early_txs[:10] if t.get("buyer")]
    conn_map = token_data.get("dev_connections") or {}
    for b in buyers:
        if conn_map.get(b):
            connected += 1
    ts = sorted([float(t.get("timestamp") or 0) for t in early_txs if t.get("timestamp")])
    coordinated = sum(1 for t in ts if ts and t - ts[0] <= 60) >= 3 if ts else False
    init_pct = float(token_data.get("initial_accumulation_pct") or 0)
    pre_funded = int(token_data.get("pre_launch_funded_wallets") or 0) > 0
    risk = 0
    labels = []
    if connected >= 3:
        risk += 25
        labels.append(f"🚨 {connected} early buyers connected to dev wallet")
    if coordinated:
        risk += 15
        labels.append("⚠️ Coordinated buying in first 60 seconds")
    if init_pct > 20:
        risk += 20
        labels.append("🚨 Dev team accumulated 20%+ in first minute")
    if pre_funded:
        risk += 30
        labels.append("💀 Pre-funded wallets — insider setup confirmed")
    return {"insider_risk": risk > 0, "connected_early_buyers": connected, "coordinated_entry": coordinated, "initial_accumulation_pct": init_pct, "pre_launch_funded": pre_funded, "risk_added": risk, "label": "; ".join(labels) if labels else "No clear insider signals"}


def score_token_risk(token: dict, token_profile: str | None = None) -> dict:
    profile = token_profile or get_token_profile(token)
    liq = float(token.get("liquidity_usd") or 0)
    mcap = float(token.get("mcap") or token.get("market_cap") or 0)
    score = 35
    flags = []
    lp_weight = 1.0
    if profile == "pumpfun_prebonding":
        lp_weight = 0.3
    elif profile == "pumpfun_graduated":
        lp_weight = 1.5
    elif profile == "established":
        lp_weight = 2.0

    if liq < 10000:
        score += 20
        flags.append("Low liquidity")
    if mcap and mcap < 1_000_000:
        score += 12
        flags.append("Very low market cap")
    if liq and mcap and liq / max(mcap, 1) < 0.02:
        score += 8
        flags.append("Thin liquidity ratio")

    lp = check_liquidity_depth(token)
    score += int(lp["risk_added"] * lp_weight)
    if lp.get("label"):
        flags.append(lp["label"])

    desc = analyze_token_description(token.get("name", ""), token.get("description", ""))
    score += int(desc["risk_added"])
    flags.extend(desc["red_flags"][:2])

    volume = analyze_volume_pattern(token.get("recent_candles") or token.get("recent_txs") or [])
    score += int(volume["risk_added"])
    if volume.get("pattern_label"):
        flags.append(volume["pattern_label"])

    insider = detect_insider_accumulation(token, token.get("early_txs") or [])
    score += int(insider["risk_added"])
    if insider.get("insider_risk"):
        flags.append(insider.get("label"))

    score = max(1, min(100, int(score)))
    level = "LOW" if score < 35 else "MEDIUM" if score < 70 else "HIGH"
    return {
        "risk_score": score,
        "risk_level": level,
        "risk_flags": [f for f in flags if f][:5],
        "profile": profile,
        "lp_depth": lp,
        "description": desc,
        "volume_pattern": volume,
        "insider": insider,
    }
