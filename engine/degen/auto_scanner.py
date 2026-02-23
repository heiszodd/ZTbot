import asyncio
import logging
import uuid
from datetime import datetime, timezone

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import db
from config import CHAT_ID
from engine.degen.contract_scanner import scan_contract
from engine.degen.early_entry import calculate_early_score
from engine.degen.narrative_detector import detect_token_narrative
from engine.degen.social_velocity import get_token_mention_velocity

log = logging.getLogger(__name__)


def _grade_index(grade: str) -> int:
    grade_order = ["F", "D", "C", "B", "A"]
    if grade not in grade_order:
        return 0
    return grade_order.index(grade)


def _md_escape(text: str) -> str:
    raw = str(text or "")
    for ch in ("_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"):
        raw = raw.replace(ch, "\\" + ch)
    return raw


async def discover_candidates(settings: dict) -> list:
    """
    Fetch candidate tokens from multiple sources.
    Returns deduplicated list of token addresses.
    """
    candidates: dict[str, dict] = {}
    min_liq = settings.get("min_liquidity", 50000)
    max_liq = settings.get("max_liquidity", 5000000)
    min_vol = settings.get("min_volume_1h", 10000)
    max_age = settings.get("max_age_hours", 72)

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.get("https://api.dexscreener.com/token-boosts/top/v1")
            if r.status_code == 200:
                for item in (r.json() or [])[:30]:
                    addr = item.get("tokenAddress", "")
                    chain = (item.get("chainId", "solana") or "solana").lower()
                    if addr and chain == "solana":
                        candidates[addr] = {
                            "address": addr,
                            "chain": chain,
                            "source": "trending",
                            "boost": item.get("amount", 0),
                        }
        except Exception as exc:
            log.warning("DexScreener boosts error: %s", exc)

        try:
            r = await client.get("https://api.dexscreener.com/token-profiles/latest/v1")
            if r.status_code == 200:
                for item in (r.json() or [])[:30]:
                    addr = item.get("tokenAddress", "")
                    chain = (item.get("chainId", "solana") or "solana").lower()
                    if addr and chain == "solana" and addr not in candidates:
                        candidates[addr] = {
                            "address": addr,
                            "chain": chain,
                            "source": "new_profile",
                        }
        except Exception as exc:
            log.warning("DexScreener profiles error: %s", exc)

        try:
            r = await client.get(
                "https://api.dexscreener.com/latest/dex/search",
                params={"q": "solana", "sort": "volume"},
            )
            if r.status_code == 200:
                pairs = (r.json() or {}).get("pairs", [])
                for pair in pairs[:30]:
                    if (pair.get("chainId", "") or "").lower() != "solana":
                        continue

                    base_token = pair.get("baseToken") or {}
                    addr = base_token.get("address", "")
                    if not addr:
                        continue

                    liq = float(((pair.get("liquidity") or {}).get("usd")) or 0)
                    vol = float(((pair.get("volume") or {}).get("h1")) or 0)
                    if liq <= 0 or vol <= 0:
                        continue
                    if liq < min_liq or liq > max_liq:
                        continue
                    if vol < min_vol:
                        continue

                    created = pair.get("pairCreatedAt")
                    if created:
                        age_hours = (
                            datetime.now(timezone.utc)
                            - datetime.fromtimestamp(created / 1000, tz=timezone.utc)
                        ).total_seconds() / 3600
                        if age_hours > max_age:
                            continue

                    if addr not in candidates:
                        candidates[addr] = {
                            "address": addr,
                            "chain": "solana",
                            "source": "volume_search",
                            "liquidity": liq,
                            "volume_1h": vol,
                        }
        except Exception as exc:
            log.warning("DexScreener search error: %s", exc)

    ignored = set(db.get_ignored_addresses())
    result = [candidate for addr, candidate in candidates.items() if addr not in ignored]
    log.info("Auto scanner: discovered %s candidates", len(result))
    return result


def calculate_probability_score(scan: dict, early: dict, vel: dict, settings: dict) -> dict:
    score = 0.0
    breakdown: dict[str, float] = {}
    flags: list[str] = []

    rug_score = float(scan.get("rug_score", 0) or 0)
    rug_grade = str(scan.get("rug_grade", "F") or "F")
    min_grade = str(settings.get("min_rug_grade", "C") or "C")

    if scan.get("is_honeypot"):
        return {
            "score": 0,
            "grade": "F",
            "blocked": True,
            "reason": "Honeypot",
            "breakdown": {},
            "flags": ["HONEYPOT"],
        }

    if _grade_index(rug_grade) < _grade_index(min_grade):
        return {
            "score": 0,
            "grade": "F",
            "blocked": True,
            "reason": f"Safety grade {rug_grade} below minimum {min_grade}",
            "breakdown": {},
            "flags": [f"Grade {rug_grade}"],
        }

    if settings.get("require_mint_revoked") and scan.get("mint_enabled"):
        flags.append("⚠️ Mint not revoked")
        rug_score *= 0.7

    if settings.get("require_lp_locked") and float(scan.get("lp_locked_pct", 0) or 0) < 80:
        flags.append("⚠️ LP not locked")
        rug_score *= 0.7

    max_top = float(settings.get("max_top_holder_pct", 15) or 15)
    top_h = float(scan.get("top_holder_pct", scan.get("top10_holder_pct", 0)) or 0)
    if top_h > max_top:
        flags.append(f"⚠️ Top holder {top_h:.1f}% > {max_top}% limit")
        rug_score *= 0.8

    safety_pts = max(0.0, min((rug_score / 100) * 30, 30))
    score += safety_pts
    breakdown["safety"] = round(safety_pts, 1)

    liq = float(scan.get("liquidity_usd", 0) or 0)
    vol = float(scan.get("volume_24h", 0) or 0)
    buys = float(scan.get("buys_1h", 0) or 0)
    sells = float(scan.get("sells_1h", 0) or 0)
    momentum_pts = 0.0

    vol_liq_ratio = vol / liq if liq > 0 else 0
    if vol_liq_ratio >= 3:
        momentum_pts += 15
    elif vol_liq_ratio >= 1:
        momentum_pts += 10
    elif vol_liq_ratio >= 0.5:
        momentum_pts += 5

    total_txns = buys + sells
    if total_txns > 0:
        buy_ratio = buys / total_txns
        if buy_ratio >= 0.6:
            momentum_pts += 10
        elif buy_ratio >= 0.5:
            momentum_pts += 5

    momentum_pts = min(momentum_pts, 25)
    score += momentum_pts
    breakdown["momentum"] = round(momentum_pts, 1)

    early_raw = float(early.get("early_score", 0) or 0)
    early_pts = max(0.0, min((early_raw / 100) * 25, 25))
    score += early_pts
    breakdown["early"] = round(early_pts, 1)

    trend = vel.get("trend", "none")
    if trend == "viral":
        social_pts = 20
    elif trend == "accelerating":
        social_pts = 15
    elif trend == "emerging":
        social_pts = 12
    elif trend == "growing":
        social_pts = 8
    elif trend == "stable":
        social_pts = 4
    else:
        social_pts = 0

    score += social_pts
    breakdown["social"] = round(social_pts, 1)

    score = round(min(score, 100), 1)
    if score >= 75:
        grade = "A"
    elif score >= 60:
        grade = "B"
    elif score >= 45:
        grade = "C"
    elif score >= 30:
        grade = "D"
    else:
        grade = "F"

    return {
        "score": score,
        "grade": grade,
        "blocked": False,
        "reason": "",
        "breakdown": breakdown,
        "flags": flags,
    }


async def send_scanner_alert(context, token: dict, rank: int, run_id: str, total_scanned: int) -> int | None:
    scan = token["scan"]
    prob = token["prob"]
    early = token["early"]
    vel = token["vel"]
    narrative = token["narrative"]
    address = token["address"]

    symbol = scan.get("token_symbol", "?")
    name = scan.get("token_name", "Unknown")
    symbol_safe = _md_escape(symbol)
    name_safe = _md_escape(name)
    price = float(scan.get("price_usd", 0) or 0)
    mcap = float(scan.get("market_cap", 0) or 0)
    liq = float(scan.get("liquidity_usd", 0) or 0)
    vol_1h = float(scan.get("volume_1h", scan.get("volume_24h", 0) / 24) or 0)
    age_h = float(early.get("age_hours", 0) or 0)
    holders = int(scan.get("holder_count", 0) or 0)
    rug_grade = scan.get("rug_grade", "?")
    score = float(prob.get("score", 0) or 0)
    breakdown = prob.get("breakdown", {})

    rank_emoji = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, "📊")
    grade_emoji = {"A": "✅", "B": "👍", "C": "⚠️", "D": "🔴", "F": "💀"}.get(rug_grade, "⚠️")

    vel_emoji = vel.get("trend_emoji", "❓")
    early_label = early.get("label", "?")

    if age_h < 1:
        age_str = f"{int(age_h * 60)}m old"
    elif age_h < 24:
        age_str = f"{age_h:.1f}h old"
    else:
        age_str = f"{age_h / 24:.1f}d old"

    filled = int(score / 100 * 10)
    bar = "█" * filled + "░" * (10 - filled)

    buys = int(scan.get("buys_1h", 0) or 0)
    sells = int(scan.get("sells_1h", 0) or 0)
    total_txns = buys + sells
    buy_pct = (buys / total_txns * 100) if total_txns > 0 else 0

    text = (
        f"{rank_emoji} *Auto Scan #{rank}/3*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 *{name_safe}* ({symbol_safe})\n"
        f"`{address}`\n\n"
        f"🎯 *Probability: {score:.0f}/100*\n"
        f"[{bar}]\n"
        f"Safety {grade_emoji}: {breakdown.get('safety',0):.0f}/30  Momentum: {breakdown.get('momentum',0):.0f}/25\n"
        f"Entry: {breakdown.get('early',0):.0f}/25  Social: {breakdown.get('social',0):.0f}/20\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Market*\n"
        f"Price:   ${price:.8f}\n"
        f"MCap:    ${mcap:>12,.0f}\n"
        f"Liq:     ${liq:>12,.0f}\n"
        f"Vol 1h:  ${vol_1h:>12,.0f}\n"
        f"Buys/Sells: {buys}/{sells} ({buy_pct:.0f}% buys)\n\n"
        f"⏱ Age: {age_str}  👥 Holders: {holders:,}\n"
        f"{vel_emoji} Social: {_md_escape(vel.get('trend','?').title())}  🌊 Narrative: {_md_escape(narrative)}\n"
        f"⏰ Entry: {early_label}\n\n"
        f"🛡 Safety: {rug_grade}  LP locked: {float(scan.get('lp_locked_pct',0) or 0):.0f}%  Mint: {'✅' if not scan.get('mint_enabled') else '❌'}\n\n"
    )

    flags = prob.get("flags", [])
    if flags:
        text += "*⚠️ Flags*\n"
        for flag in flags[:2]:
            text += f"{_md_escape(flag)}\n"
        text += "\n"

    if price > 0:
        sl = price * 0.75
        tp1 = price * 1.5
        tp2 = price * 3.0
        tp3 = price * 10.0
        text += (
            f"🎯 *If entering:*\n"
            f"Entry: ${price:.8f}\n"
            f"SL:    ${sl:.8f}  (-25%)\n"
            f"TP1:   ${tp1:.8f}  (1.5x)\n"
            f"TP2:   ${tp2:.8f}  (3x)\n"
            f"TP3:   ${tp3:.8f}  (10x)\n\n"
        )

    text += f"_Scanned {total_scanned} tokens • Run {run_id}_"

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Whitelist", callback_data=f"scan:whitelist:{address}"),
                InlineKeyboardButton("❌ Ignore", callback_data=f"scan:ignore:{address}"),
                InlineKeyboardButton("📲 Ape In", callback_data=f"scan:ape:{address}"),
            ],
            [
                InlineKeyboardButton("🔍 Full Scan", callback_data=f"scan:full:{address}"),
                InlineKeyboardButton("👁 Watch Dev", callback_data=f"degen:watch_dev:{address}"),
            ],
        ]
    )

    try:
        msg = await context.bot.send_message(
            chat_id=CHAT_ID,
            text=text,
            parse_mode="Markdown",
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
        return msg.message_id
    except Exception as exc:
        log.error("send_scanner_alert telegram error for %s: %s", symbol, exc)
        return None


async def run_auto_scanner(context) -> None:
    try:
        await asyncio.wait_for(_run_auto_scanner_inner(context), timeout=300)
    except asyncio.TimeoutError:
        log.warning("auto_scanner timed out after 5 minutes")
    except Exception as e:
        log.error(f"auto_scanner error: {e}")


async def _run_auto_scanner_inner(context) -> None:
    settings = db.get_scanner_settings()
    if not settings.get("enabled", True):
        log.info("Auto scanner disabled — skipping")
        return

    scan_run_id = str(uuid.uuid4())[:8]
    log.info("Auto scanner run %s started", scan_run_id)

    candidates = await discover_candidates(settings)
    if not candidates:
        log.warning("Auto scanner: no candidates found")
        return

    semaphore = asyncio.Semaphore(3)

    async def score_candidate(candidate: dict):
        async with semaphore:
            address = candidate["address"]
            chain = candidate.get("chain", "solana")
            try:
                scan = await scan_contract(address, chain, force_refresh=True)

                if scan.get("is_honeypot"):
                    return None
                if not scan.get("liquidity_usd"):
                    return None

                early = calculate_early_score(scan)
                symbol = scan.get("token_symbol", "")
                vel = await get_token_mention_velocity(symbol) if symbol else {"velocity": 0, "trend": "none"}
                prob = calculate_probability_score(scan, early, vel, settings)

                if prob.get("blocked"):
                    log.debug("Blocked %s: %s", address[:12], prob.get("reason"))
                    return None

                min_score = float(settings.get("min_probability_score", 55) or 55)
                if prob["score"] < min_score:
                    return None

                narrative = detect_token_narrative(scan.get("token_name", ""), scan.get("token_symbol", ""))
                return {
                    "address": address,
                    "chain": chain,
                    "scan": scan,
                    "early": early,
                    "vel": vel,
                    "prob": prob,
                    "narrative": narrative,
                    "source": candidate.get("source", ""),
                }
            except Exception as exc:
                log.error("Score candidate error %s: %s", address[:12], exc)
                return None

    tasks = [score_candidate(c) for c in candidates[:30]]
    results = await asyncio.gather(*tasks)
    scored = [r for r in results if r is not None]

    if not scored:
        log.info("Auto scanner: no tokens passed filters")
        return

    scored.sort(key=lambda item: item["prob"]["score"], reverse=True)
    top3 = scored[:3]
    log.info("Auto scanner run %s: top 3 from %s qualifying tokens", scan_run_id, len(scored))

    for rank, token in enumerate(top3, 1):
        try:
            msg_id = await send_scanner_alert(context, token, rank, scan_run_id, len(scored))
            db.save_auto_scan_result(
                {
                    "scan_run_id": scan_run_id,
                    "contract_address": token["address"],
                    "chain": token["chain"],
                    "token_symbol": token["scan"].get("token_symbol", ""),
                    "token_name": token["scan"].get("token_name", ""),
                    "probability_score": token["prob"]["score"],
                    "risk_score": token["scan"].get("rug_score", 0),
                    "early_score": token["early"].get("early_score", 0),
                    "social_score": token["vel"].get("velocity", 0),
                    "momentum_score": token["prob"]["breakdown"].get("momentum", 0),
                    "rank": rank,
                    "alert_message_id": msg_id,
                    "scan_data": {
                        "prob": token["prob"],
                        "early": token["early"],
                        "narrative": token["narrative"],
                    },
                }
            )
            await asyncio.sleep(1.5)
        except Exception as exc:
            log.error("Send scanner alert error: %s", exc)


async def run_watchlist_scanner(context) -> None:
    try:
        await asyncio.wait_for(_run_watchlist_scanner_inner(context), timeout=120)
    except asyncio.TimeoutError:
        log.warning("watchlist_scanner timed out after 2 minutes")
    except Exception as e:
        log.error(f"watchlist_scanner error: {e}")


async def _run_watchlist_scanner_inner(context) -> None:
    watchlist = db.get_active_watchlist()
    if not watchlist:
        return

    settings = db.get_scanner_settings()

    for item in watchlist:
        address = item["contract_address"]
        chain = item.get("chain", "solana")
        symbol = item.get("token_symbol", "?")
        last_score = float(item.get("last_score", 0) or 0)

        try:
            scan = await scan_contract(address, chain, force_refresh=True)
            early = calculate_early_score(scan)
            vel = await get_token_mention_velocity(symbol)
            prob = calculate_probability_score(scan, early, vel, settings)
            new_score = float(prob.get("score", 0) or 0)

            db.update_watchlist_item(
                address,
                {
                    "last_scanned": datetime.utcnow().isoformat(),
                    "last_score": new_score,
                },
            )

            improvement = new_score - last_score
            if improvement >= 10 and new_score >= 60:
                try:
                    await context.bot.send_message(
                        chat_id=CHAT_ID,
                        text=(
                            f"📈 *Watchlist Score Update*\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"🪙 {symbol}\n"
                            f"Score: {last_score:.0f} → *{new_score:.0f}* (+{improvement:.0f})\n\n"
                            f"Safety:   {prob['breakdown'].get('safety',0):.0f}/30\n"
                            f"Momentum: {prob['breakdown'].get('momentum',0):.0f}/25\n"
                            f"Entry:    {prob['breakdown'].get('early',0):.0f}/25\n"
                            f"Social:   {prob['breakdown'].get('social',0):.0f}/20\n\n"
                            f"_Score improving — worth another look._"
                        ),
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton("📲 Ape In", callback_data=f"scan:ape:{address}"),
                                    InlineKeyboardButton("🔍 Full Scan", callback_data=f"scan:full:{address}"),
                                    InlineKeyboardButton("❌ Remove", callback_data=f"scan:ignore:{address}"),
                                ]
                            ]
                        ),
                    )
                except Exception as exc:
                    log.error("Watchlist alert telegram error %s: %s", symbol, exc)

        except Exception as exc:
            log.error("Watchlist rescan error %s: %s", symbol, exc)
