CRYPTO_MARKET_PATTERNS = {
    "btc": ["bitcoin", "btc above", "btc price", "bitcoin price", "btc hit", "btc reach"],
    "eth": ["ethereum", "eth above", "eth price", "eth etf", "ethereum etf"],
    "sol": ["solana", "sol above", "sol price"],
    "macro_bull": ["fed cut", "rate cut", "soft landing", "no recession"],
    "macro_bear": ["fed hike", "recession", "rate hike", "inflation above"],
}


async def get_crypto_sentiment() -> dict:
    from engine.polymarket.market_reader import fetch_markets

    markets = await fetch_markets(limit=100)
    if not markets:
        return {}

    sentiment = {
        "btc": {"bull": [], "bear": [], "neutral": []},
        "eth": {"bull": [], "bear": [], "neutral": []},
        "sol": {"bull": [], "bear": [], "neutral": []},
        "macro": {"bull": [], "bear": [], "neutral": []},
    }

    for m in markets:
        q = m["question"].lower()
        yes_pct = m["yes_pct"]
        weight = m["volume_24h"]

        asset = None
        for a, patterns in CRYPTO_MARKET_PATTERNS.items():
            if any(p in q for p in patterns):
                asset = "btc" if "btc" in a else "eth" if "eth" in a else "sol" if "sol" in a else "macro"
                break
        if not asset:
            continue

        bull_keywords = ["above", "reach", "hit", "exceed", "higher", "bull", "up", "gain"]
        bear_keywords = ["below", "fall", "drop", "crash", "lower", "bear", "down", "lose"]
        is_bull_question = any(kw in q for kw in bull_keywords)
        is_bear_question = any(kw in q for kw in bear_keywords)

        if is_bull_question:
            if yes_pct >= 60:
                sentiment[asset]["bull"].append((yes_pct, weight, m["question"]))
            elif yes_pct <= 40:
                sentiment[asset]["bear"].append((yes_pct, weight, m["question"]))
            else:
                sentiment[asset]["neutral"].append((yes_pct, weight, m["question"]))
        elif is_bear_question:
            if yes_pct >= 60:
                sentiment[asset]["bear"].append((yes_pct, weight, m["question"]))
            elif yes_pct <= 40:
                sentiment[asset]["bull"].append((yes_pct, weight, m["question"]))

    summary = {}
    for asset, dirs in sentiment.items():
        bull_w = sum(w for _, w, _ in dirs["bull"])
        bear_w = sum(w for _, w, _ in dirs["bear"])
        total_w = bull_w + bear_w
        if total_w == 0:
            bias, confidence = "neutral", 0
        elif bull_w > bear_w * 1.5:
            bias, confidence = "bullish", bull_w / total_w * 100
        elif bear_w > bull_w * 1.5:
            bias, confidence = "bearish", bear_w / total_w * 100
        else:
            bias, confidence = "mixed", 50

        all_markets = dirs["bull"] + dirs["bear"] + dirs["neutral"]
        top_market = max(all_markets, key=lambda x: x[1], default=None)
        summary[asset] = {
            "bias": bias,
            "confidence": round(confidence, 1),
            "bull_count": len(dirs["bull"]),
            "bear_count": len(dirs["bear"]),
            "top_question": top_market[2][:60] if top_market else "",
            "top_yes_pct": top_market[0] if top_market else 0,
        }
    return summary


def format_sentiment_dashboard(sentiment: dict) -> str:
    if not sentiment:
        return "❓ *Polymarket Sentiment*\nNo data available."
    bias_emoji = {"bullish": "📈", "bearish": "📉", "mixed": "↔️", "neutral": "❓"}
    text = "🌊 *Polymarket Sentiment*\n━━━━━━━━━━━━━━━━━━━━━━━━\n_Crowd probability → perps bias_\n\n"
    for asset in ["btc", "eth", "sol", "macro"]:
        s = sentiment.get(asset)
        if not s:
            continue
        text += f"{bias_emoji.get(s['bias'],'❓')} *{asset.upper()}*: {s['bias'].title()} ({s['confidence']:.0f}% confidence)\n"
        if s["top_question"]:
            q = s["top_question"]
            if len(q) > 45:
                q = q[:42] + "..."
            text += f"  Top: \"{q}\"\n  YES: {s['top_yes_pct']:.0f}%\n"
        text += "\n"
    text += "_Based on volume-weighted Polymarket probabilities._\n_High confidence = strong crowd signal._"
    return text
