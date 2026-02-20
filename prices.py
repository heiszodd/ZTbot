"""
prices.py — Live price fetching via CoinGecko (free, no API key needed).
"""
import logging
import requests
from config import COINGECKO_IDS

log = logging.getLogger(__name__)

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"


def get_crypto_prices(pairs: list[str]) -> dict[str, float]:
    """
    Fetch live USD prices for a list of pairs (e.g. ['BTCUSDT', 'ETHUSDT']).
    Returns {pair: price} dict. Missing pairs return 0.0.
    """
    ids = [COINGECKO_IDS[p] for p in pairs if p in COINGECKO_IDS]
    if not ids:
        return {}
    try:
        resp = requests.get(
            COINGECKO_URL,
            params={"ids": ",".join(ids), "vs_currencies": "usd"},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        result = {}
        for pair in pairs:
            cg_id = COINGECKO_IDS.get(pair)
            if cg_id and cg_id in data:
                result[pair] = data[cg_id]["usd"]
        return result
    except Exception as e:
        log.error(f"CoinGecko error: {e}")
        return {}


def get_price(pair: str) -> float | None:
    """Get a single pair's live price. Returns None on failure."""
    prices = get_crypto_prices([pair])
    return prices.get(pair)


def fmt_price(price: float) -> str:
    """Format price nicely depending on magnitude."""
    if price >= 1000:
        return f"${price:,.2f}"
    if price >= 1:
        return f"${price:.4f}"
    return f"${price:.6f}"


def get_all_prices() -> dict[str, float]:
    """Fetch all supported crypto pairs at once."""
    from config import CRYPTO_PAIRS
    return get_crypto_prices(CRYPTO_PAIRS)
