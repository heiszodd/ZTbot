from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import db


async def run_pre_session_checklist(context) -> dict:
    from config import CHAT_ID, CRYPTOPANIC_TOKEN
    from engine.rules import get_candles, is_bullish_trend, is_bearish_trend

    cache = {}
    settings = db.get_risk_settings()
    tracker = db.get_daily_tracker()
    pairs = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    checks = []

    daily_hit = tracker.get("daily_loss_hit", False)
    daily_pnl = tracker.get("realised_pnl", 0)
    acct = settings.get("account_size", 1000)
    daily_pct = abs(daily_pnl) / acct * 100 if daily_pnl < 0 and acct > 0 else 0
    limit = settings.get("max_daily_loss_pct", 3.0)
    checks.append({"label": "Daily loss limit", "ok": (not daily_hit and daily_pct < limit * 0.8), "detail": "Clear" if daily_pct < limit * 0.5 else (f"Used {daily_pct:.1f}% of {limit:.1f}% limit" if not daily_hit else "LIMIT HIT — do not trade today")})

    warm = [p for p in db.get_active_setup_phases() if p.get("overall_status") in ("phase1", "phase2", "phase3")]
    checks.append({"label": "Active setups", "ok": len(warm) > 0, "detail": f"{len(warm)} model(s) in active phases" if warm else "No active phases — scanner may need more time"})

    clear_bias, bias_notes = 0, []
    for pair in pairs:
        try:
            h4 = await get_candles(pair, "4h", 30, cache)
            d1 = await get_candles(pair, "1d", 20, cache)
            if not h4 or not d1:
                continue
            h4_bull, h4_bear = is_bullish_trend(h4), is_bearish_trend(h4)
            d1_bull, d1_bear = is_bullish_trend(d1), is_bearish_trend(d1)
            if (h4_bull and d1_bull) or (h4_bear and d1_bear):
                clear_bias += 1
                bias_notes.append(f"{pair}: {'bullish' if h4_bull else 'bearish'}")
        except Exception:
            pass
    checks.append({"label": "HTF bias clarity", "ok": clear_bias >= 1, "detail": ", ".join(bias_notes) if bias_notes else "Mixed signals on all pairs — wait for clarity"})

    news_clear, news_note = True, "No major news detected"
    try:
        if CRYPTOPANIC_TOKEN:
            import httpx
            from datetime import datetime, timezone, timedelta
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get("https://cryptopanic.com/api/v1/posts/", params={"auth_token": CRYPTOPANIC_TOKEN, "filter": "important", "public": "true"})
            data = r.json()
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
            recent = [p for p in data.get("results", []) if datetime.fromisoformat(p["created_at"].replace("Z", "+00:00")) > cutoff]
            if recent:
                news_clear, news_note = False, f"{len(recent)} important news item(s) in last 5 minutes"
    except Exception:
        pass
    checks.append({"label": "News environment", "ok": news_clear, "detail": news_note})

    acct_set = settings.get("account_size", 0) > 0
    risk_set = settings.get("risk_per_trade_pct", 0) > 0
    checks.append({"label": "Risk settings", "ok": acct_set and risk_set, "detail": f"Account ${settings['account_size']:,.0f} @ {settings['risk_per_trade_pct']}% risk" if acct_set and risk_set else "Account size not configured — set in Risk Settings"})

    result = {"checks": checks, "green": sum(1 for c in checks if c["ok"]), "total": len(checks), "all_clear": sum(1 for c in checks if c["ok"]) == len(checks)}
    await context.bot.send_message(chat_id=CHAT_ID, text=format_checklist(result), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data="nav:checklist"), InlineKeyboardButton("💰 Risk Settings", callback_data="nav:risk")]]))
    return result


def format_checklist(result: dict) -> str:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    green, total = result["green"], result["total"]
    header_emoji = "✅" if result["all_clear"] else "⚠️" if green >= 3 else "🚫"
    text = f"{header_emoji} *Pre-Session Checklist*\n━━━━━━━━━━━━━━━━━━━━━━━━\nLondon open in ~30 min  •  {now.strftime('%H:%M UTC')}\nScore: {green}/{total}\n\n"
    for check in result["checks"]:
        text += f"{'✅' if check['ok'] else '❌'} *{check['label']}*\n   {check['detail']}\n\n"
    if result["all_clear"]:
        text += "🟢 _All clear — good conditions to trade._"
    elif green >= 3:
        text += "🟡 _Some flags present — trade selectively._"
    else:
        text += "🔴 _Multiple flags — consider sitting this session out._"
    return text
