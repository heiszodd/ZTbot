import db

CRYPTO_KEYWORDS = ["bitcoin", "btc", "ethereum", "eth", "solana", "sol", "crypto", "blockchain", "defi", "nft", "altcoin", "binance", "coinbase", "sec", "etf", "halving", "fed", "rate", "inflation", "macro"]


def classify_market(question: str) -> str:
    q = (question or "").lower()
    for kw in CRYPTO_KEYWORDS:
        if kw in q:
            return "crypto"
    for kw in ["fed", "rate", "inflation", "gdp", "election", "president", "war", "recession", "oil", "gold"]:
        if kw in q:
            return "macro"
    return "other"


async def run_market_scanner(filters: dict = None) -> dict:
    from datetime import datetime, timezone, timedelta
    from engine.polymarket.market_reader import fetch_markets

    filters = filters or {}
    all_markets = await fetch_markets(limit=100)
    if not all_markets:
        return {}

    now = datetime.now(timezone.utc)
    week_from_now = now + timedelta(days=7)

    for m in all_markets:
        db.upsert_poly_market(m)

    high_volume, uncertain, crypto_markets, resolving_soon = [], [], [], []
    for m in all_markets:
        yes_pct = m["yes_pct"]
        vol = m["volume_24h"]
        category = classify_market(m["question"])
        if vol >= 50000:
            high_volume.append(m)
        if 40 <= yes_pct <= 60:
            uncertain.append(m)
        if category == "crypto":
            crypto_markets.append(m)
        end_str = m.get("end_date", "")
        if end_str:
            try:
                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                if now < end_dt <= week_from_now:
                    resolving_soon.append(m)
            except Exception:
                pass

    high_volume.sort(key=lambda x: x["volume_24h"], reverse=True)
    uncertain.sort(key=lambda x: x["volume_24h"], reverse=True)
    crypto_markets.sort(key=lambda x: x["volume_24h"], reverse=True)
    resolving_soon.sort(key=lambda x: x.get("end_date", ""))

    return {
        "high_volume": high_volume[:5],
        "uncertain": uncertain[:5],
        "crypto": crypto_markets[:10],
        "resolving_soon": resolving_soon[:5],
        "total_scanned": len(all_markets),
    }


def _format_market_line(m: dict) -> str:
    yes_pct = m["yes_pct"]
    vol = m["volume_24h"]
    q = m["question"]
    if len(q) > 50:
        q = q[:47] + "..."
    bar_filled = int(yes_pct / 10)
    bar = "█" * bar_filled + "░" * (10 - bar_filled)
    return f"  {q}\n  YES: {yes_pct:.0f}%  [{bar}]\n  Vol: ${vol:,.0f}\n"


def format_scanner_results(results: dict) -> str:
    text = f"🎯 *Polymarket Scanner*\n━━━━━━━━━━━━━━━━━━━━━━━━\nScanned {results.get('total_scanned', 0)} active markets\n\n"
    hv = results.get("high_volume", [])
    if hv:
        text += "*🔥 High Volume*\n"
        for m in hv[:3]:
            text += _format_market_line(m)
        text += "\n"
    un = results.get("uncertain", [])
    if un:
        text += "*⚖️ Uncertain (40-60%)*\n"
        for m in un[:3]:
            text += _format_market_line(m)
        text += "\n"
    cr = results.get("crypto", [])
    if cr:
        text += "*₿ Crypto Markets*\n"
        for m in cr[:3]:
            text += _format_market_line(m)
        text += "\n"
    rs = results.get("resolving_soon", [])
    if rs:
        text += "*⏰ Resolving Soon*\n"
        for m in rs[:3]:
            text += _format_market_line(m)
    return text
