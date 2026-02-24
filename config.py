from datetime import timezone, timedelta
import os
import sys
import logging
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)


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
DB_URL = os.getenv("DB_URL", "").strip() or os.getenv("DATABASE_URL", "").strip()
if not DB_URL:
    _fatal_env("DB_URL (or DATABASE_URL) is not set")

_chat_id_raw = _required_env("CHAT_ID")
try:
    CHAT_ID = int(_chat_id_raw)
except ValueError:
    _fatal_env("CHAT_ID must be a plain integer (no quotes)")

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BINANCE_BASE_URL = "https://api.binance.com"

CRYPTOCOMPARE_API_KEY = os.getenv("CRYPTOCOMPARE_API_KEY", "").strip()
CRYPTOCOMPARE_BASE_URL = os.getenv("CRYPTOCOMPARE_BASE_URL", "https://min-api.cryptocompare.com").strip()
CRYPTOCOMPARE_EXTRA_PARAMS = os.getenv("CRYPTOCOMPARE_EXTRA_PARAMS", "ZTbot").strip()


HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")
SOLANA_RPC_URL = (
    f"https://mainnet.helius-rpc.com"
    f"/?api-key={HELIUS_API_KEY}"
    if HELIUS_API_KEY
    else "https://api.mainnet-beta.solana.com"
)
POLYMARKET_CLOB = "https://clob.polymarket.com"
POLYMARKET_GAMMA = "https://gamma-api.polymarket.com"
ETHERSCAN_KEY = os.getenv("ETHERSCAN_KEY", "")
GOPLUSLABS_BASE = "https://api.gopluslabs.io/api/v1"
DEXSCREENER_BASE = "https://api.dexscreener.com/latest"
HONEYPOT_BASE = "https://api.honeypot.is/v2"
BSCSCAN_KEY = os.getenv("BSCSCAN_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
HL_INFO_URL = "https://api.hyperliquid.xyz/info"
HL_ADDRESS = os.getenv("HL_ADDRESS", "")
HL_API_KEY = os.getenv("HL_API_KEY", "")
HL_API_SECRET = os.getenv("HL_API_SECRET", "")

_gemini_state = {
    "client": None,
    "model_name": "gemini-2.0-flash",
    "initialised": False,
}


def init_gemini():
    """
    Initialise Gemini. Safe to call multiple times.
    Returns the model on success, None on failure.
    """
    if _gemini_state["initialised"] and _gemini_state["client"] is not None:
        return _gemini_state["client"]

    if not GEMINI_API_KEY:
        log.error(
            "GEMINI_API_KEY not set. "
            "Chart analysis disabled."
        )
        _gemini_state["initialised"] = True
        return None

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=_gemini_state["model_name"],
            contents="ping",
            config=types.GenerateContentConfig(max_output_tokens=10),
        )
        if not response or not response.text:
            raise ValueError("Empty test response")

        _gemini_state["client"] = client
        _gemini_state["initialised"] = True
        log.info(f"✅ Gemini connected: {_gemini_state['model_name']}")
        return client

    except ImportError:
        log.error(
            "google-genai not installed. "
            "Run: pip install google-genai"
        )
        _gemini_state["initialised"] = True
        return None

    except Exception as e:
        log.error(f"Gemini init failed: {type(e).__name__}: {e}")
        _gemini_state["initialised"] = True
        return None


def get_gemini_client():
    """Always call this — never import client directly."""
    if _gemini_state["client"] is None:
        return init_gemini()
    return _gemini_state["client"]


def get_gemini_model_name() -> str:
    return _gemini_state["model_name"]


# Backward-compatible alias used by older code paths.
def get_gemini_model():
    return get_gemini_client()

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
CRYPTO_PAIRS = ["BTCUSDT", "SOLUSDT"]
FOREX_PAIRS  = []
ALL_PAIRS    = CRYPTO_PAIRS

TIMEFRAMES = ["1m", "5m", "15m", "30m", "1H", "4H"]
SESSIONS_LIST = ["London", "NY", "Asia", "Overlap", "Any"]
BIASES = ["Bullish", "Bearish"]

SCANNER_INTERVAL = 300
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
    "BTCUSDT": ["SOLUSDT"],
    "SOLUSDT": ["BTCUSDT"],
}
