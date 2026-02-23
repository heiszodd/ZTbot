import logging
from datetime import datetime, timedelta, timezone

import httpx

from config import CRYPTOPANIC_TOKEN

log = logging.getLogger(__name__)


async def get_token_mention_velocity(symbol: str, hours: int = 2) -> dict:
    if not CRYPTOPANIC_TOKEN:
        return {"symbol": symbol, "velocity": 0, "trend": "unknown", "trend_emoji": "❓", "recent_count": 0, "prev_count": 0}

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(
                "https://cryptopanic.com/api/v1/posts/",
                params={"auth_token": CRYPTOPANIC_TOKEN, "currencies": symbol.upper(), "public": "true"},
            )
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        log.error("Social velocity error %s: %s", symbol, exc)
        return {"symbol": symbol, "velocity": 0, "trend": "unknown", "trend_emoji": "❓", "recent_count": 0, "prev_count": 0}

    now = datetime.now(timezone.utc)
    hour_ago = now - timedelta(hours=1)
    two_ago = now - timedelta(hours=2)

    posts = data.get("results") or []
    recent_count = 0
    prev_count = 0
    for post in posts:
        try:
            post_time = datetime.fromisoformat(post["created_at"].replace("Z", "+00:00"))
            if post_time >= hour_ago:
                recent_count += 1
            elif post_time >= two_ago:
                prev_count += 1
        except Exception:
            continue

    if prev_count == 0:
        velocity = recent_count * 10
        trend = "emerging" if recent_count > 0 else "none"
    else:
        velocity = ((recent_count - prev_count) / prev_count) * 100
        if velocity >= 100:
            trend = "viral"
        elif velocity >= 50:
            trend = "accelerating"
        elif velocity >= 10:
            trend = "growing"
        elif velocity >= -10:
            trend = "stable"
        else:
            trend = "declining"

    return {
        "symbol": symbol,
        "recent_count": recent_count,
        "prev_count": prev_count,
        "velocity": round(velocity, 1),
        "trend": trend,
        "trend_emoji": {
            "viral": "🚀",
            "accelerating": "📈",
            "emerging": "🌱",
            "growing": "📊",
            "stable": "➡️",
            "declining": "📉",
            "none": "😴",
            "unknown": "❓",
        }.get(trend, "❓"),
    }


def format_social_velocity(vel: dict) -> str:
    emoji = vel.get("trend_emoji", "❓")
    trend = vel.get("trend", "unknown")
    symbol = vel.get("symbol", "?")
    recent = vel.get("recent_count", 0)
    prev = vel.get("prev_count", 0)
    change = vel.get("velocity", 0)
    return (
        f"{emoji} *Social: {trend.title()}*\n"
        f"  Last hour: {recent} mentions\n"
        f"  Prev hour: {prev} mentions\n"
        f"  Change: {change:+.0f}%"
    )
