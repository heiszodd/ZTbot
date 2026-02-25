import logging

import httpx

log = logging.getLogger(__name__)


async def run_market_scanner() -> list:
    """
    Fetch markets from Polymarket.
    Returns empty list on timeout or error.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://gamma-api.polymarket.com/markets",
                params={
                    "limit": 20,
                    "active": "true",
                    "closed": "false",
                    "order": "volume24hr",
                    "ascending": "false",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("markets", [])
    except httpx.TimeoutException:
        return []
    except Exception as e:
        log.error("Market scanner: %s", e)
        return []


def format_scanner_results(markets: list) -> str:
    if not markets:
        return (
            "🔍 *Prediction Scanner*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "No markets found.\n"
            "Polymarket API may be unavailable.\n"
            "Try again in a moment."
        )

    text = (
        "🔍 *Prediction Scanner*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Found {len(markets)} markets:\n\n"
    )

    for m in markets[:8]:
        q = (m.get("question") or "?")[:55]
        yes = float(m.get("bestAsk") or m.get("yes_bid") or 0.5)
        no = 1 - yes
        vol = float(m.get("volume24hr") or 0)
        vol_s = f"${vol/1000:.0f}K" if vol >= 1000 else f"${vol:.0f}"
        e = "🟢" if yes >= 0.5 else "🔴"
        text += f"{e} *{q}*\n   YES {yes*100:.0f}%  NO {no*100:.0f}%  Vol {vol_s}\n\n"

    return text
