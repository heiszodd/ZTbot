import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup

from config import CRYPTOPANIC_TOKEN, WAT

log = logging.getLogger(__name__)

CRYPTO_PANIC_URL = "https://cryptopanic.com/api/v1/posts/"
COINGECKO_NEWS_URL = "https://api.coingecko.com/api/v3/news"
INVESTING_CALENDAR_URL = "https://www.investing.com/economic-calendar/"

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


async def _fetch_coingecko_events(pairs: list[str], horizon_end: datetime) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(COINGECKO_NEWS_URL)
            resp.raise_for_status()
            payload = resp.json()
        now = datetime.now(timezone.utc)
        events: list[dict] = []
        items = payload.get("data") if isinstance(payload, dict) else payload
        for item in items or []:
            updated = item.get("updated_at") or item.get("created_at")
            try:
                event_time = datetime.fromtimestamp(int(updated), tz=timezone.utc) if updated else now
            except Exception:
                event_time = now
            if event_time > horizon_end:
                continue
            title = item.get("title") or "Crypto News"
            desc = item.get("description") or ""
            for pair in pairs:
                events.append(
                    {
                        "name": title,
                        "pair": pair,
                        "time_utc": event_time,
                        "time_wat": event_time.astimezone(WAT),
                        "impact": "high",
                        "forecast": None,
                        "previous": None,
                        "actual": None,
                        "source": "coingecko",
                        "description": desc,
                    }
                )
        return events
    except Exception as exc:
        log.error("CoinGecko news fetch failed: %s", exc)
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


async def _fetch_investing_calendar(pairs: list[str], horizon_end: datetime) -> list[dict]:
    now = datetime.now(timezone.utc)
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(INVESTING_CALENDAR_URL, headers=headers)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
        rows = soup.select("tr.js-event-item")
        events: list[dict] = []
        pair_set = set(pairs)
        for row in rows:
            name_el = row.select_one("td.event")
            cur_el = row.select_one("td.flagCur")
            impact_el = row.select_one("td.sentiment")
            time_el = row.select_one("td.time")
            forecast_el = row.select_one("td.fore")
            prev_el = row.select_one("td.prev")
            actual_el = row.select_one("td.act")
            if not name_el or not time_el:
                continue
            impact = _normalize_impact(impact_el.get_text(" ", strip=True) if impact_el else "")
            if impact != "high":
                continue
            event_name = name_el.get_text(" ", strip=True)
            currency = cur_el.get_text(" ", strip=True) if cur_el else "USD"
            event_time = _parse_calendar_time(time_el.get_text(" ", strip=True), now)
            if not event_time or event_time > horizon_end:
                continue
            mapped_pairs = [p for p in pair_set if currency in p or p.startswith("BTC") or p.startswith("ETH") or p == "XAUUSD"]
            if not mapped_pairs:
                mapped_pairs = [p for p in pair_set if p.endswith("USD")]
            for pair in mapped_pairs:
                events.append(
                    {
                        "name": event_name,
                        "pair": pair,
                        "time_utc": event_time,
                        "time_wat": event_time.astimezone(WAT),
                        "impact": impact,
                        "forecast": (forecast_el.get_text(" ", strip=True) if forecast_el else None) or None,
                        "previous": (prev_el.get_text(" ", strip=True) if prev_el else None) or None,
                        "actual": (actual_el.get_text(" ", strip=True) if actual_el else None) or None,
                        "source": "investing",
                    }
                )
        return events
    except Exception as exc:
        log.error("Investing calendar fetch failed: %s", exc)
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
    events = await _fetch_investing_calendar(pairs, horizon_end)
    if not events:
        events = _fallback_recurring_events(pairs, horizon_end)

    crypto_news = await _fetch_cryptopanic_events(pairs, horizon_end)
    if not crypto_news:
        crypto_news = await _fetch_coingecko_events(pairs, horizon_end)

    all_events = [e for e in (events + crypto_news) if e.get("impact") == "high" and now <= e.get("time_utc", now) <= horizon_end]
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
