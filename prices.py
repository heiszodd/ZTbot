"""Market data and utility pricing functions."""
import logging
from statistics import mean
import requests

from config import COINGECKO_IDS

log = logging.getLogger(__name__)

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
COINGECKO_CHART_URL = "https://api.coingecko.com/api/v3/coins/{id}/market_chart"
FALLBACK_PRICES = {
    "BTCUSDT": 50000.0, "ETHUSDT": 3000.0, "SOLUSDT": 120.0, "BNBUSDT": 450.0,
    "XRPUSDT": 0.6, "DOGEUSDT": 0.11, "EURUSD": 1.08, "GBPUSD": 1.27,
    "XAUUSD": 2030.0, "USDJPY": 150.0, "AUDUSD": 0.65, "GBPJPY": 191.0,
}


def _fallback_series(pair: str, days: int) -> list[float]:
    base = FALLBACK_PRICES.get(pair)
    if not base:
        return []
    return [base * (1 + ((i % 10) - 5) * 0.0012) for i in range(days * 24)]


def get_crypto_prices(pairs: list[str]) -> dict[str, float]:
    ids = [COINGECKO_IDS[p] for p in pairs if p in COINGECKO_IDS]
    if not ids:
        return {p: FALLBACK_PRICES[p] for p in pairs if p in FALLBACK_PRICES}

    try:
        resp = requests.get(
            COINGECKO_URL,
            params={"ids": ",".join(sorted(set(ids))), "vs_currencies": "usd"},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        result = {}
        for pair in pairs:
            cg_id = COINGECKO_IDS.get(pair)
            if cg_id and cg_id in data:
                result[pair] = float(data[cg_id]["usd"])
        return result
    except Exception as e:
        log.error("CoinGecko price error: %s", e)
        return {p: FALLBACK_PRICES[p] for p in pairs if p in FALLBACK_PRICES}


def fetch_prices(pairs: list[str]) -> dict[str, float]:
    return get_crypto_prices(pairs)


def get_price(pair: str) -> float | None:
    return fetch_prices([pair]).get(pair)


def get_recent_series(pair: str, days: int = 7) -> list[float]:
    cg_id = COINGECKO_IDS.get(pair)
    days = max(1, min(days, 90))
    if not cg_id:
        return _fallback_series(pair, days)

    try:
        resp = requests.get(
            COINGECKO_CHART_URL.format(id=cg_id),
            params={"vs_currency": "usd", "days": days},
            timeout=10,
        )
        resp.raise_for_status()
        return [float(row[1]) for row in resp.json().get("prices", [])]
    except Exception as e:
        log.error("CoinGecko chart error: %s", e)
        return _fallback_series(pair, days)


def estimate_atr(prices: list[float], window: int = 14) -> float:
    if len(prices) < 3:
        return 0.0
    diffs = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
    sample = diffs[-window:] if len(diffs) >= window else diffs
    return mean(sample) if sample else 0.0


def calc_sl_tp(price: float, direction: str, atr: float | None = None):
    atr = atr if atr is not None and atr > 0 else max(price * 0.003, 0.0001)
    if direction == "BUY":
        sl = round(price - atr * 1.5, 6)
        tp = round(price + atr * 3.0, 6)
    else:
        sl = round(price + atr * 1.5, 6)
        tp = round(price - atr * 3.0, 6)
    return sl, tp, 2.0


def fmt_price(price: float | None) -> str:
    if price is None:
        return "N/A"
    if price >= 1000:
        return f"${price:,.2f}"
    if price >= 1:
        return f"${price:.4f}"
    return f"${price:.6f}"


def get_all_prices() -> dict[str, float]:
    from config import CRYPTO_PAIRS
    return fetch_prices(CRYPTO_PAIRS)
