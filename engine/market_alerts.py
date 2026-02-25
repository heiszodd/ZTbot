"""
engine/market_alerts.py
Automated notifications for market session opens, significant price changes,
and other time-based market events.
"""

import logging
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)

# ── Session schedule (UTC hours) ──────────────────────────────
SESSIONS = {
    "sydney": {"open": 21, "close": 6, "label": "🇦🇺 Sydney Session", "emoji": "🌏"},
    "tokyo": {"open": 0, "close": 9, "label": "🇯🇵 Tokyo Session", "emoji": "🌸"},
    "london": {"open": 7, "close": 16, "label": "🇬🇧 London Session", "emoji": "🏰"},
    "new_york": {"open": 12, "close": 21, "label": "🇺🇸 New York Session", "emoji": "🗽"},
}

# Track which sessions we've already notified about today
_session_notified: dict[str, str] = {}

# Track last known prices for change detection
_last_prices: dict[str, float] = {}


async def check_session_opens(context) -> None:
    """
    Scheduled job: check if any market session is opening now.
    Sends a Telegram notification when a session opens.
    """
    from config import CHAT_ID
    from telegram import InlineKeyboardButton as IKB, InlineKeyboardMarkup as IKM

    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    current_hour = now.hour

    for key, session in SESSIONS.items():
        notify_key = f"{key}_{today_str}"
        if notify_key in _session_notified:
            continue

        if current_hour == session["open"]:
            _session_notified[notify_key] = today_str

            text = (
                f"{session['emoji']} *{session['label']} Open*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"⏰ {now.strftime('%H:%M UTC')}\n"
                f"Session runs until {session['close']:02d}:00 UTC\n\n"
                f"_Check your setups and watchlist._"
            )

            try:
                await context.bot.send_message(
                    chat_id=CHAT_ID,
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=IKM([
                        [IKB("📈 Perps", callback_data="perps"), IKB("🔥 Degen", callback_data="degen")],
                        [IKB("🏠 Home", callback_data="home")],
                    ]),
                )
            except Exception as e:
                log.error("Session alert error: %s", e)

    # Cleanup old entries
    for k in list(_session_notified.keys()):
        if not k.endswith(today_str):
            del _session_notified[k]


async def check_price_changes(context) -> None:
    """
    Scheduled job: monitor major pairs for significant price changes (5%+ in 24h).
    Sends alert when a pair moves significantly.
    """
    from config import CHAT_ID
    from telegram import InlineKeyboardButton as IKB, InlineKeyboardMarkup as IKM

    pairs = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
    threshold_pct = 5.0

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            for pair in pairs:
                try:
                    resp = await client.get(
                        "https://api.binance.com/api/v3/ticker/24hr",
                        params={"symbol": pair},
                    )
                    if resp.status_code != 200:
                        continue
                    data = resp.json()

                    change_pct = float(data.get("priceChangePercent", 0))
                    price = float(data.get("lastPrice", 0))
                    high = float(data.get("highPrice", 0))
                    low = float(data.get("lowPrice", 0))
                    volume = float(data.get("quoteVolume", 0))

                    # Only alert if change exceeds threshold
                    if abs(change_pct) < threshold_pct:
                        continue

                    # Don't spam: check if we already alerted for this level
                    alert_key = f"{pair}_{int(change_pct)}"
                    if alert_key in _last_prices:
                        continue
                    _last_prices[alert_key] = price

                    direction = "📈" if change_pct > 0 else "📉"
                    color = "🟢" if change_pct > 0 else "🔴"
                    coin = pair.replace("USDT", "")

                    vol_str = (
                        f"${volume / 1_000_000_000:.1f}B"
                        if volume >= 1_000_000_000
                        else f"${volume / 1_000_000:.1f}M"
                    )

                    text = (
                        f"{direction} *{coin} Price Alert*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"{color} *{change_pct:+.1f}%* in 24h\n\n"
                        f"Price:   ${price:,.2f}\n"
                        f"24h H/L: ${high:,.2f} / ${low:,.2f}\n"
                        f"Volume:  {vol_str}\n\n"
                        f"_Significant move detected._"
                    )

                    await context.bot.send_message(
                        chat_id=CHAT_ID,
                        text=text,
                        parse_mode="Markdown",
                        reply_markup=IKM([
                            [IKB(f"📈 {coin} Perps", callback_data="perps:scanner"), IKB("🔥 Degen", callback_data="degen")],
                        ]),
                    )

                except Exception as e:
                    log.debug("Price check error for %s: %s", pair, e)

    except Exception as e:
        log.error("Price change monitor error: %s", e)

    # Cleanup old price alerts (reset every 6 hours)
    now = datetime.now(timezone.utc)
    if now.hour % 6 == 0 and now.minute < 5:
        _last_prices.clear()
