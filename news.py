import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from config import CRYPTOPANIC_TOKEN, WAT

log = logging.getLogger(__name__)

CRYPTO_PANIC_URL = "https://cryptopanic.com/api/v1/posts/"
FOREX_FACTORY_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

CACHE_TTL = timedelta(minutes=15)
_EVENT_CACHE: dict[str, Any] = {"expires_at": datetime.min.replace(tzinfo=timezone.utc), "data": []}

RECURRING_EVENTS = [
    {"name": "US CPI", "day": 2, "hour": 13, "minute": 30, "impact": "high", "pairs": ["BTCUSDT", "XAUUSD", "EURUSD"]},
    {"name": "US NFP", "day": 4, "hour": 13, "minute": 30, "impact": "high", "pairs": ["BTCUSDT", "XAUUSD", "EURUSD", "GBPUSD"]},
    {"name": "FOMC Rate Decision", "day": 2, "hour": 19, "minute": 0, "impact": "high", "pairs": ["BTCUSDT", "ETHUSDT", "XAUUSD", "EURUSD"]},
    {"name": "US GDP", "day": 3, "hour": 13, "minute": 30, "impact": "high", "pairs": ["BTCUSDT", "XAUUSD"]},
    {"name": "Fed Chair Speech", "day": 2, "hour": 18, "minute": 0, "impact": "high", "pairs": ["BTCUSDT", "XAUUSD", "EURUSD"]},
]


def _normalize_impact(raw: str) -> str:
    value = (raw or "").strip().lower()
    if "high" in value or "red" in value:
        return "high"
    if "medium" in value or "orange" in value:
        return "medium"
    return "low"


def _safe_float(raw: Any) -> float | None:
    if raw is None:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", str(raw))
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except Exception:
        return None


async def _fetch_cryptopanic_events(pairs: list[str], horizon_end: datetime) -> list[dict]:
    if not CRYPTOPANIC_TOKEN:
        return []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                CRYPTO_PANIC_URL,
                params={"auth_token": CRYPTOPANIC_TOKEN, "filter": "important", "kind": "news"},
            )
            resp.raise_for_status()
            payload = resp.json()
        now = datetime.now(timezone.utc)
        events: list[dict] = []
        for item in payload.get("results", []):
            published_at = item.get("published_at")
            try:
                event_time = datetime.fromisoformat(published_at.replace("Z", "+00:00")) if published_at else now
            except Exception:
                event_time = now
            if event_time > horizon_end:
                continue
            for pair in pairs:
                events.append(
                    {
                        "name": item.get("title", "Crypto News"),
                        "pair": pair,
                        "time_utc": event_time.astimezone(timezone.utc),
                        "time_wat": event_time.astimezone(WAT),
                        "impact": "high",
                        "forecast": None,
                        "previous": None,
                        "actual": None,
                        "source": "cryptopanic",
                        "description": item.get("domain") or "",
                    }
                )
        return events
    except Exception as exc:
        log.error("CryptoPanic fetch failed: %s", exc)
        return []


def _parse_calendar_time(raw_time: str, now_utc: datetime) -> datetime | None:
    cleaned = (raw_time or "").strip()
    if not cleaned:
        return None
    for fmt in ["%I:%M%p", "%H:%M", "%I:%M %p"]:
        try:
            tm = datetime.strptime(cleaned, fmt)
            dt = now_utc.replace(hour=tm.hour, minute=tm.minute, second=0, microsecond=0)
            if dt < now_utc - timedelta(hours=1):
                dt += timedelta(days=1)
            return dt
        except Exception:
            continue
    return None


async def fetch_economic_calendar() -> list:
    """Fetch today's economic events using ForexFactory JSON feed."""
    from datetime import datetime, timezone

    try:
        async with httpx.AsyncClient(
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0 (compatible; bot)"},
        ) as client:
            response = await client.get(FOREX_FACTORY_CALENDAR_URL)
            if response.status_code != 200:
                return []
            events = response.json()

        today = datetime.now(timezone.utc).strftime("%m-%d-%Y")
        return [
            {
                "title": event.get("title", ""),
                "impact": event.get("impact", ""),
                "country": event.get("country", ""),
                "time": event.get("date", ""),
            }
            for event in events
            if event.get("date", "").startswith(today)
            and event.get("impact") in ("High", "Medium")
        ][:10]
    except Exception as exc:
        log.warning(f"Economic calendar fetch failed: {exc}")
        return []


async def fetch_crypto_news() -> list:
    """Fetch crypto headlines from CryptoPanic or CoinGecko trending."""
    if CRYPTOPANIC_TOKEN:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(
                    CRYPTO_PANIC_URL,
                    params={
                        "auth_token": CRYPTOPANIC_TOKEN,
                        "filter": "hot",
                        "public": "true",
                        "kind": "news",
                    },
                )
                if response.status_code == 200:
                    posts = response.json().get("results", [])
                    return [
                        {"title": post.get("title", ""), "url": post.get("url", "")}
                        for post in posts[:5]
                    ]
        except Exception:
            pass

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get("https://api.coingecko.com/api/v3/search/trending")
            if response.status_code == 200:
                coins = response.json().get("coins", [])
                return [
                    {
                        "title": f"Trending: {coin['item']['name']} ({coin['item']['symbol']})",
                        "url": "",
                    }
                    for coin in coins[:5]
                ]
    except Exception as exc:
        log.warning(f"News fetch failed: {exc}")

    return []


def _fallback_recurring_events(pairs: list[str], horizon_end: datetime) -> list[dict]:
    now = datetime.now(timezone.utc)
    out: list[dict] = []
    for item in RECURRING_EVENTS:
        for day_offset in range(0, 8):
            dt = (now + timedelta(days=day_offset)).replace(hour=item["hour"], minute=item["minute"], second=0, microsecond=0)
            if dt.weekday() != item["day"]:
                continue
            if now <= dt <= horizon_end:
                for pair in pairs:
                    if pair in item["pairs"]:
                        out.append(
                            {
                                "name": item["name"],
                                "pair": pair,
                                "time_utc": dt,
                                "time_wat": dt.astimezone(WAT),
                                "impact": item["impact"],
                                "forecast": None,
                                "previous": None,
                                "actual": None,
                                "source": "recurring",
                            }
                        )
                break
    return out


async def get_upcoming_events(pairs: list, hours_ahead: int = 8) -> list[dict]:
    now = datetime.now(timezone.utc)
    cache_key = f"{','.join(sorted(pairs))}:{hours_ahead}"
    if _EVENT_CACHE.get("key") == cache_key and now < _EVENT_CACHE["expires_at"]:
        return _EVENT_CACHE["data"]

    horizon_end = now + timedelta(hours=hours_ahead)
    cal_rows = await fetch_economic_calendar()
    events = []
    for row in cal_rows:
        raw_dt = row.get("time", "")
        try:
            event_time = datetime.strptime(raw_dt, "%m-%d-%Y %H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if event_time > horizon_end:
            continue
        for pair in pairs:
            events.append({
                "name": row.get("title", "Economic Event"),
                "pair": pair,
                "time_utc": event_time,
                "time_wat": event_time.astimezone(WAT),
                "impact": "high" if row.get("impact") == "High" else "medium",
                "forecast": None,
                "previous": None,
                "actual": None,
                "source": "forexfactory",
                "description": row.get("country", ""),
            })

    if not events:
        events = _fallback_recurring_events(pairs, horizon_end)

    crypto_news_rows = await fetch_crypto_news()
    crypto_news = []
    for item in crypto_news_rows:
        for pair in pairs:
            crypto_news.append({
                "name": item.get("title") or "Crypto News",
                "pair": pair,
                "time_utc": now,
                "time_wat": now.astimezone(WAT),
                "impact": "high",
                "forecast": None,
                "previous": None,
                "actual": None,
                "source": "cryptonews",
                "description": item.get("url", ""),
            })

    all_events = [e for e in (events + crypto_news) if e.get("impact") in {"high", "medium"} and now <= e.get("time_utc", now) <= horizon_end]
    all_events.sort(key=lambda x: x["time_utc"])
    _EVENT_CACHE.update({"key": cache_key, "data": all_events, "expires_at": now + CACHE_TTL})
    return all_events


def get_event_sentiment(event: dict) -> dict:
    name = (event.get("name") or "").lower()
    pair = (event.get("pair") or "").upper()
    forecast = _safe_float(event.get("forecast"))
    previous = _safe_float(event.get("previous"))
    title = f"{event.get('name', '')} {event.get('description', '')}".lower()

    direction = "volatile"
    confidence = "low"
    reasoning = "Insufficient structured data — expect headline-driven volatility."
    move = 1.2

    if any(k in name for k in ["cpi", "inflation"]):
        if forecast is None or previous is None or forecast == previous:
            direction, confidence = "volatile", "low"
            reasoning = "CPI consensus unclear/flat — market can whip both ways."
        elif forecast < previous:
            direction = "bullish"
            confidence = "high"
            reasoning = "Cooling inflation supports risk assets and gold; weakens USD impulse."
        else:
            direction = "bearish"
            confidence = "high"
            reasoning = "Hotter inflation implies tighter policy pressure, weighing on risk assets."
        move = 1.6
    elif "nfp" in name or "non-farm" in name:
        confidence = "medium"
        if forecast is None or previous is None or forecast == previous:
            direction = "volatile"
            reasoning = "NFP setup is mixed — directional edge is weak pre-release."
        elif forecast > previous:
            direction = "bearish"
            reasoning = "Stronger labor print can lift USD/rates and pressure crypto risk appetite."
        else:
            direction = "bullish"
            reasoning = "Softer labor print may ease rate fears and support risk assets."
        move = 1.8
    elif "fomc" in name or "rate decision" in name:
        if forecast is None or previous is None or forecast == previous:
            direction, confidence = "volatile", "low"
            reasoning = "Rate hold expectation dominates — wait for statement and reaction candle."
        elif forecast < previous:
            direction, confidence = "bullish", "high"
            reasoning = "Expected rate cut is supportive for liquidity-sensitive assets."
        else:
            direction, confidence = "bearish", "high"
            reasoning = "Expected rate hike is restrictive and typically risk-negative."
        move = 2.0
    elif any(k in name for k in ["speech", "chair", "central bank"]):
        direction, confidence = "volatile", "low"
        reasoning = "Speech tone unknown until live — wait for first reaction candle"
        move = 1.4
    elif "gdp" in name:
        if forecast is None or previous is None or forecast == previous:
            direction, confidence = "volatile", "low"
            reasoning = "GDP consensus is flat/uncertain; likely two-way volatility first."
        elif forecast > previous:
            direction, confidence = "bullish", "medium"
            reasoning = "Growth acceleration tends to support risk sentiment."
        else:
            direction, confidence = "bearish", "medium"
            reasoning = "Growth slowdown can pressure risk assets."
        move = 1.3
    elif event.get("source") in {"cryptopanic", "coingecko"}:
        pos = ["etf", "approval", "adoption", "partnership", "upgrade", "halving", "launch"]
        neg = ["hack", "ban", "lawsuit", "sec", "regulation", "crash", "exploit", "shutdown"]
        if any(k in title for k in pos):
            direction = "bullish"
            reasoning = "Headline contains pro-crypto catalyst keywords."
        elif any(k in title for k in neg):
            direction = "bearish"
            reasoning = "Headline contains risk/regulatory negative keywords."
        else:
            direction = "volatile"
            reasoning = "No strong directional keyword edge in headline."
        confidence = "low"
        move = 1.0

    if pair.endswith("USD") and pair not in {"BTCUSDT", "ETHUSDT", "XAUUSD"} and direction in {"bullish", "bearish"}:
        # Invert risk-asset bias for major USD forex symbols.
        direction = "bearish" if direction == "bullish" else "bullish"

    return {
        "direction": direction,
        "confidence": confidence,
        "reasoning": reasoning,
        "expected_move_pct": move,
    }
