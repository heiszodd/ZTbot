import os
from dotenv import load_dotenv

load_dotenv()

TOKEN   = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID", "0"))
DB_URL  = os.getenv("DB_URL", "")

# ── Tier risk sizing ──────────────────────────────────
TIER_RISK = {"A": 2.0, "B": 1.0, "C": 0.5}

# ── ATR volatility bands (ratio vs rolling avg) ───────
ATR_BANDS = [
    (0.0,  0.7,  "Low",     0.0),
    (0.7,  1.3,  "Normal",  0.0),
    (1.3,  2.0,  "High",    0.5),
    (2.0,  999,  "Extreme", -1.0),
]

# ── Session windows (UTC hours) ───────────────────────
SESSIONS = {
    "Overlap": (12, 16),
    "London":  (8,  16),
    "NY":      (13, 21),
    "Asia":    (23, 8),
}

NEWS_BLACKOUT_MIN = 30

# ── Discipline penalties ──────────────────────────────
VIOLATION_PENALTIES = {
    "V1": 10,
    "V2": 5,
    "V3": 10,
    "V4": 10,
    "V5": 5,
}
VIOLATION_LABELS = {
    "V1": "Entered without an alert firing",
    "V2": "Entered below Tier C threshold",
    "V3": "Position sized above tier limit",
    "V4": "SL moved further from entry",
    "V5": "Early exit — no reason logged",
}
CLEAN_TRADE_BONUS = 2

# ── Supported assets ──────────────────────────────────
CRYPTO_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]
FOREX_PAIRS  = ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY", "AUDUSD", "GBPJPY"]
ALL_PAIRS    = CRYPTO_PAIRS + FOREX_PAIRS

TIMEFRAMES = ["1m", "5m", "15m", "30m", "1H", "4H"]
SESSIONS_LIST = ["London", "NY", "Asia", "Overlap", "Any"]
BIASES = ["Bullish", "Bearish"]

# ── CoinGecko ID map ──────────────────────────────────
COINGECKO_IDS = {
    "BTCUSDT":  "bitcoin",
    "ETHUSDT":  "ethereum",
    "SOLUSDT":  "solana",
    "BNBUSDT":  "binancecoin",
    "XRPUSDT":  "ripple",
    "DOGEUSDT": "dogecoin",
}
SCANNER_INTERVAL = 60
SUPPORTED_PAIRS = ALL_PAIRS
SUPPORTED_TIMEFRAMES = TIMEFRAMES