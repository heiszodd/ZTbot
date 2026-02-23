import logging

import db

NARRATIVE_KEYWORDS = {
    "AI": ["ai", "artificial intelligence", "gpt", "llm", "machine learning", "neural", "openai", "agent"],
    "DeFi": ["defi", "decentralized finance", "yield", "amm", "liquidity", "lending", "borrowing", "protocol"],
    "Gaming": ["gaming", "game", "play to earn", "p2e", "nft game", "metaverse", "virtual world", "gamefi"],
    "Meme": ["meme coin", "memecoin", "viral", "trending", "community driven", "no utility"],
    "RWA": ["real world asset", "rwa", "tokenized", "property", "real estate", "commodity", "treasury", "bond"],
    "Layer2": ["layer 2", "l2", "rollup", "zk", "optimism", "arbitrum", "base", "scaling", "ethereum l2"],
    "DePIN": ["depin", "physical infrastructure", "network", "wireless", "storage", "compute", "helium", "render"],
    "SocialFi": ["social", "socialfi", "friend", "creator", "content", "influencer", "token gated", "community"],
    "Liquid Staking": ["liquid staking", "lst", "staked eth", "lido", "restaking", "eigenlayer", "yield"],
    "NFT": ["nft", "non fungible", "digital art", "pfp", "collection", "opensea", "marketplace"],
    "DAO": ["dao", "governance", "vote", "proposal", "community treasury"],
    "Metaverse": ["metaverse", "virtual land", "avatar", "immersive", "virtual economy"],
}


def detect_narrative(text: str) -> str | None:
    text_lower = (text or "").lower()
    scores = {}
    for narrative, keywords in NARRATIVE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[narrative] = score
    if not scores:
        return None
    return max(scores, key=scores.get)


def detect_token_narrative(token_name: str, token_symbol: str, description: str = "") -> str:
    combined = f"{token_name} {token_symbol} {description}".lower()
    return detect_narrative(combined) or "Other"


async def update_narrative_momentum(context=None) -> dict:
    from config import CRYPTOPANIC_TOKEN
    import httpx

    if not CRYPTOPANIC_TOKEN:
        return {}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://cryptopanic.com/api/v1/posts/",
                params={"auth_token": CRYPTOPANIC_TOKEN, "public": "true", "kind": "news"},
            )
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logging.getLogger(__name__).error("CryptoPanic narrative fetch: %s", exc)
        return {}

    posts = data.get("results") or []
    counts = {n: 0 for n in NARRATIVE_KEYWORDS}
    token_map = {n: [] for n in NARRATIVE_KEYWORDS}

    for post in posts:
        title = post.get("title") or ""
        narrative = detect_narrative(title)
        if not narrative:
            continue
        counts[narrative] = counts.get(narrative, 0) + 1
        currencies = [c.get("code") for c in (post.get("currencies") or []) if c.get("code")]
        token_map[narrative].extend(currencies)

    results = {}
    for narrative, count in counts.items():
        prev = db.get_narrative_count(narrative)
        velocity = count - prev if prev else 0
        trend = "accelerating" if velocity > 3 else "declining" if velocity < -3 else "stable"
        tokens = list(set(token_map.get(narrative, [])))[:5]
        db.update_narrative(
            narrative,
            {"mention_count": count, "prev_count": prev or 0, "velocity": velocity, "trend": trend, "tokens": tokens},
        )
        results[narrative] = {"count": count, "velocity": velocity, "trend": trend, "tokens": tokens}

    return results


def format_narrative_dashboard(narratives: dict) -> str:
    text = "🌊 *Narrative Momentum*\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    trend_emoji = {"accelerating": "📈", "stable": "➡️", "declining": "📉"}
    sorted_narratives = sorted(narratives.items(), key=lambda x: x[1].get("velocity", 0), reverse=True)

    for narrative, data in sorted_narratives[:8]:
        count = data.get("count", 0)
        velocity = data.get("velocity", 0)
        trend = data.get("trend", "stable")
        tokens = data.get("tokens", [])
        emoji = trend_emoji.get(trend, "➡️")
        vel_str = f"+{velocity}" if velocity > 0 else str(velocity)
        text += f"{emoji} *{narrative}*  {count} mentions ({vel_str})\n"
        if tokens:
            text += f"   {', '.join(tokens[:3])}\n"

    text += "\n_Updated every 30 minutes._\n_Accelerating = gaining mentions fast._"
    return text
