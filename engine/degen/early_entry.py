def calculate_early_score(scan: dict, dex_data: dict = None) -> dict:
    from datetime import datetime, timezone

    score = 0
    notes = []

    age_hours = 0
    pair_created = scan.get("pair_created_at")
    if pair_created:
        try:
            if isinstance(pair_created, str):
                created_dt = datetime.fromisoformat(pair_created.replace("Z", "+00:00"))
            else:
                created_dt = pair_created
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - created_dt).total_seconds() / 3600
        except Exception:
            age_hours = 0

    if 0 < age_hours <= 6:
        score += 30
        notes.append(f"🔥 Very fresh: {age_hours:.1f}h old")
    elif age_hours <= 24:
        score += 20
        notes.append(f"✅ New: {age_hours:.1f}h old")
    elif age_hours <= 72:
        score += 10
        notes.append(f"⏰ Recent: {age_hours:.1f}h old")
    elif age_hours <= 168:
        score += 5
        notes.append(f"📅 {age_hours / 24:.1f} days old")
    else:
        notes.append(f"🕰 Established: {age_hours / 24:.0f} days old")

    holders = int(scan.get("holder_count", 0) or 0)
    if 50 <= holders <= 500:
        score += 25
        notes.append(f"🌱 Early holders: {holders}")
    elif holders <= 50:
        score += 15
        notes.append(f"⚠️ Very few holders: {holders} (high risk / very early)")
    elif holders <= 2000:
        score += 15
        notes.append(f"📊 Growing: {holders:,} holders")
    elif holders <= 10000:
        score += 8
        notes.append(f"👥 Established: {holders:,} holders")
    else:
        notes.append(f"🏙 Mature: {holders:,} holders (not early)")

    vol = float(scan.get("volume_24h", 0) or 0)
    liq = float(scan.get("liquidity_usd", 0) or 0)
    vol_liq_ratio = vol / liq if liq > 0 else 0

    if vol_liq_ratio >= 5:
        score += 25
        notes.append(f"🚀 High volume/liq ratio: {vol_liq_ratio:.1f}x")
    elif vol_liq_ratio >= 2:
        score += 15
        notes.append(f"📈 Good volume: {vol_liq_ratio:.1f}x ratio")
    elif vol_liq_ratio >= 0.5:
        score += 8
        notes.append(f"📊 Moderate volume: {vol_liq_ratio:.1f}x ratio")
    else:
        notes.append("😴 Low volume activity")

    mcap = float(scan.get("market_cap", 0) or 0)
    if 0 < mcap <= 500_000:
        score += 20
        notes.append(f"💎 Micro cap: ${mcap:,.0f}")
    elif mcap <= 2_000_000:
        score += 15
        notes.append(f"🌱 Small cap: ${mcap:,.0f}")
    elif mcap <= 10_000_000:
        score += 8
        notes.append(f"📊 Mid cap: ${mcap:,.0f}")
    else:
        notes.append(f"🏙 Large cap: ${mcap:,.0f} (limited upside)")

    score = round(min(score, 100), 1)
    if score >= 75:
        label = "🔥 Very Early"
    elif score >= 55:
        label = "✅ Early"
    elif score >= 35:
        label = "⏰ On Time"
    elif score >= 15:
        label = "⚠️ Late"
    else:
        label = "❌ Too Late"

    return {"early_score": score, "label": label, "age_hours": age_hours, "notes": notes}
