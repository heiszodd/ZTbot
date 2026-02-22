import logging
from datetime import date, datetime, timezone

import db
from engine.rules import find_swing_highs, find_swing_lows, get_candles

log = logging.getLogger(__name__)


async def record_session_data(context):
    pairs = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XAUUSD"]
    cache = {}
    for pair in pairs:
        try:
            candles = await get_candles(pair, "1h", 24, cache)
            if not candles or len(candles) < 8:
                continue
            asian = [c for c in candles if datetime.fromtimestamp(c["time"] / 1000, tz=timezone.utc).hour < 8]
            if not asian:
                continue
            asian_high = max(c["high"] for c in asian)
            asian_low = min(c["low"] for c in asian)
            london = [c for c in candles if 7 <= datetime.fromtimestamp(c["time"] / 1000, tz=timezone.utc).hour < 13]
            london_swept = None
            if london:
                if min(c["low"] for c in london) < asian_low:
                    london_swept = "lows"
                elif max(c["high"] for c in london) > asian_high:
                    london_swept = "highs"
            highs = find_swing_highs(candles, lookback=3)
            lows = find_swing_lows(candles, lookback=3)
            key_levels = ([{"type": "resistance", "price": h["price"]} for h in highs[-3:]] + [{"type": "support", "price": l["price"]} for l in lows[-3:]])
            db.save_session_journal({"session_date": date.today().isoformat(), "session_name": "London", "pair": pair, "asian_high": asian_high, "asian_low": asian_low, "asian_range_pts": asian_high - asian_low, "london_swept": london_swept, "key_levels": key_levels})
        except Exception as exc:
            log.error("Session journal error %s: %s", pair, exc)
