import os
from dotenv import load_dotenv

load_dotenv()

TOKEN    = os.getenv("BOT_TOKEN")
CHAT_ID  = int(os.getenv("CHAT_ID", "0"))
DB_URL   = os.getenv("DB_URL", "postgresql://tradingbot:password@localhost/tradingbot")

# ── Scoring thresholds ────────────────────────────────
TIER_RISK = {"A": 2.0, "B": 1.0, "C": 0.5}

# ── ATR volatility bands ──────────────────────────────
ATR_BANDS = [
    (0.0,  0.7,  "Low",     0.0),
    (0.7,  1.3,  "Normal",  0.0),
    (1.3,  2.0,  "High",    0.5),
    (2.0,  999,  "Extreme", -1.0),
]

# ── Session windows (UTC hours) ───────────────────────
SESSIONS = {
    "Asia":    (23, 8),
    "London":  (8,  16),
    "Overlap": (12, 16),
    "NY":      (13, 21),
}

# ── News blackout window (minutes) ───────────────────
NEWS_BLACKOUT_MIN = 30

# ── Discipline score penalties ────────────────────────
VIOLATION_PENALTIES = {
    "V1": 10,  # entered without alert  — MAJOR
    "V2": 5,   # below Tier C threshold — MINOR
    "V3": 10,  # oversized position     — MAJOR
    "V4": 10,  # SL moved further       — MAJOR
    "V5": 5,   # early exit no reason   — MINOR
}
VIOLATION_LABELS = {
    "V1": "Entered without alert firing",
    "V2": "Entered below Tier C threshold",
    "V3": "Position sized above tier limit",
    "V4": "SL moved further from entry",
    "V5": "Early exit — no reason logged",
}
CLEAN_TRADE_BONUS = 2
