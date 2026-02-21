from datetime import timezone, timedelta
import os
import sys
from dotenv import load_dotenv

load_dotenv()


def _fatal_env(message: str) -> None:
    print(f"FATAL: {message}", flush=True)
    sys.exit(1)


def _required_env(name: str) -> str:
    value = os.getenv(name, "")
    if not value or not value.strip():
        _fatal_env(f"{name} is not set")
    return value.strip()



WAT = timezone(timedelta(hours=1), name="WAT")

TOKEN = _required_env("BOT_TOKEN")
DB_URL = _required_env("DB_URL")

_chat_id_raw = _required_env("CHAT_ID")
try:
    CHAT_ID = int(_chat_id_raw)
except ValueError:
    _fatal_env("CHAT_ID must be a plain integer (no quotes)")

CRYPTOCOMPARE_API_KEY = os.getenv("CRYPTOCOMPARE_API_KEY", "")
CRYPTOCOMPARE_BASE_URL = os.getenv("CRYPTOCOMPARE_BASE_URL", "https://min-api.cryptocompare.com")
CRYPTOCOMPARE_EXTRA_PARAMS = os.getenv("CRYPTOCOMPARE_EXTRA_PARAMS", "ztbot")

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
FOREX_PAIRS  = []
ALL_PAIRS    = CRYPTO_PAIRS

TIMEFRAMES = ["1m", "5m", "15m", "30m", "1H", "4H"]
SESSIONS_LIST = ["London", "NY", "Asia", "Overlap", "Any"]
BIASES = ["Bullish", "Bearish"]

SCANNER_INTERVAL = 60
CRYPTOPANIC_API_TOKEN = os.getenv("CRYPTOPANIC_API_TOKEN", "")
CRYPTOPANIC_TOKEN = os.getenv("CRYPTOPANIC_TOKEN", "")
SUPPORTED_PAIRS = ALL_PAIRS
SUPPORTED_TIMEFRAMES = TIMEFRAMES
SUPPORTED_SESSIONS = SESSIONS_LIST
SUPPORTED_BIASES = BIASES

# ── Model rule catalog (wizard selection) ────────────
SUPPORTED_MODEL_RULES = [
    "External Liquidity Sweep",
    "Market Structure Shift",
    "Fair Value Gap Reaction",
    "Order Block Respect",
    "Session High/Low Sweep",
    "Displacement Candle",
    "Premium/Discount Alignment",
    "Higher-Timeframe Bias Match",
    "Volume Expansion Confirmation",
    "News Risk Cleared",
]

CORRELATED_PAIRS = {
    "BTCUSDT": ["ETHUSDT", "SOLUSDT", "BNBUSDT"],
    "ETHUSDT": ["BTCUSDT", "SOLUSDT"],
    "SOLUSDT": ["BTCUSDT", "ETHUSDT"],
    "EURUSD": ["GBPUSD", "AUDUSD"],
    "GBPUSD": ["EURUSD"],
    "XAUUSD": ["XAGUSD"],
}
