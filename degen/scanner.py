from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

import httpx

import db
from degen.model_engine import evaluate_token_against_model
from degen.moon_engine import score_moonshot_potential
from degen.narrative_tracker import update_narrative_trends
from degen.postmortem import create_postmortem
from degen.risk_engine import score_token_risk, score_trajectory
from engine.degen.contract_scanner import calculate_degen_position, scan_contract
from engine.degen.early_entry import calculate_early_score
from engine.degen.narrative_detector import detect_token_narrative
from engine.degen.social_velocity import format_social_velocity, get_token_mention_velocity
from handlers.degen_journal_handler import auto_create_degen_journal

log = logging.getLogger(__name__)

SOLSCAN_RATE_LIMIT_DELAY = 0.2
_RESCORING_JOBS: dict[str, object] = {}
_executor = ThreadPoolExecutor(max_workers=2)


async def send_model_alert(bot, chat_id: int, model: dict, token_data: dict, result: dict, intel: dict | None = None):
    passed_names = ", ".join([r["name"] for r in result["passed_rules"][:8]]) or "None"
    failed_names = ", ".join([r["name"] for r in result["failed_rules"][:8]]) or "None"
    conf = (token_data.get("confluence") or {}).get("confidence_label", "")
    msg = (
        f"🎰 {model['name']} — ALERT\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Token: {token_data.get('symbol','?')} ({token_data.get('address','N/A')})\n"
        f"Score: {result['score']} / {result['max_possible_score']} ({result['confluence_fraction']})\n"
        f"Risk score: {token_data.get('risk_score','N/A')}\n"
        f"Moon score: {token_data.get('moon_score','N/A')}\n"
        f"📊 Confluence: {(token_data.get('confluence') or {}).get('contributing_categories',0)}/6 categories  {conf}\n"
        f"Liquidity: ${token_data.get('liquidity_usd',0):,.0f}\n"
        f"Passed rules: {passed_names}\n"
        f"Failed rules: {failed_names}"
    )
    if intel:
        msg += intel.get("scan_summary", "")
        msg += intel.get("early_section", "")
        if intel.get("social_text"):
            msg += f"\n{intel['social_text']}\n"
        msg += intel.get("position_section", "")
    await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")


async def score_token_async(token_data: dict) -> dict:
    loop = asyncio.get_event_loop()
    risk = await loop.run_in_executor(_executor, score_token_risk, token_data)
    moon = await loop.run_in_executor(_executor, score_moonshot_potential, token_data, risk.get("profile"))
    return {"risk": risk, "moon": moon}


async def _fetch_external_data(token: dict) -> dict:
    out = dict(token)
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            payload = (await client.get(f"https://api.dexscreener.com/latest/dex/tokens/{token.get('address')}" )).json()
        pair = (payload.get("pairs") or [{}])[0]
        out.update({
            "liquidity_usd": float((pair.get("liquidity") or {}).get("usd") or out.get("liquidity_usd") or 0),
            "mcap": float(pair.get("fdv") or pair.get("marketCap") or out.get("mcap") or 0),
            "price_usd": float(pair.get("priceUsd") or out.get("price_usd") or 0),
            "pairAddress": pair.get("pairAddress"),
            "url": pair.get("url", out.get("url")),
        })
    except Exception:
        pass
    return out


async def rescore_token_job(context):
    data = context.job.data
    address, chain = data["token_address"], data["chain"]
    tok = db.get_degen_token_by_address(address)
    if not tok or tok.get("rugged"):
        return
    fresh = await _fetch_external_data(tok)
    risk2 = (await score_token_async(fresh))["risk"]
    traj = score_trajectory({"risk_score": tok.get("initial_risk_score") or tok.get("risk_score")}, risk2)
    payload = {**fresh, **risk2, "trajectory": traj["trajectory"]}
    db.update_degen_token_rescore(address, chain, payload)


async def holder_accumulation_check(context):
    tokens = db.get_recent_degen_tokens(limit=150)
    for t in tokens:
        old = int(t.get("holder_count") or 0)
        new = int(t.get("live_holder_count") or old)
        hrs = max(float(t.get("hours_since_last_holder_check") or 1), 1)
        growth = (new - old) / hrs
        if growth > 50 and float(t.get("age_hours") or 0) > 2:
            msg = (
                "📈 HOLDER ACCUMULATION ALERT\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🪙 {t.get('name',t.get('symbol'))} ({t.get('symbol')})\n"
                f"👥 Holders: {old} → {new} (+{new-old} in {hrs:.1f} hours)\n"
                f"📈 Growth rate: +{growth:.1f} holders/hour\n"
                f"💰 Current price: ${float(t.get('price_usd') or 0):,.8f}\n"
                f"📊 Market cap: ${float(t.get('mcap') or 0):,.0f}\n\n"
                "⚡ Second-wave momentum may be building."
            )
            await context.application.bot.send_message(chat_id=context.job.chat_id or context.application.bot_data.get("chat_id"), text=msg)


async def degen_exit_monitor(context):
    tokens = db.get_recent_degen_tokens(limit=200)
    for t in tokens:
        peak = float(t.get("peak_price") or t.get("price_usd") or 0)
        cur = float(t.get("price_usd") or 0)
        if peak <= 0:
            continue
        drop = (peak - cur) / peak
        if drop > 0.7 and float(t.get("age_hours") or 0) <= 6 and not t.get("rugged"):
            db.mark_degen_token_rugged(t["id"])
            create_postmortem(t["id"])
            job = _RESCORING_JOBS.pop(t.get("address"), None)
            if job:
                job.schedule_removal()


async def degen_scan_job(context):
    bot = context.application.bot
    chat_id = getattr(context, "chat_id", None) or context.application.bot_data.get("chat_id")
    tokens = db.get_recent_degen_tokens(limit=100)
    models = db.get_active_degen_models()
    sem = asyncio.Semaphore(6)

    async def _process_token(token: dict):
        async with sem:
            token_data = await _fetch_external_data(dict(token))
            await asyncio.sleep(SOLSCAN_RATE_LIMIT_DELAY)
            scored = await score_token_async(token_data)
            risk = scored["risk"]
            moon = scored["moon"]
            token_data.update(risk)
            token_data.update(moon)
            token_data["confluence"] = moon.get("confluence")
            token_data["initial_risk_score"] = token_data.get("initial_risk_score") or risk.get("risk_score")
            token_data["latest_risk_score"] = risk.get("risk_score")
            token_data["token_profile"] = risk.get("profile")
            token_data["initial_reply_count"] = token_data.get("initial_reply_count") or int(token_data.get("reply_count") or 0)
            token_data["replies_per_hour"] = (moon.get("social_velocity") or {}).get("replies_per_hour")
            token_data["social_velocity_score"] = (moon.get("social_velocity") or {}).get("velocity_score")
            token_id = db.upsert_degen_token_snapshot(token_data)
            update_narrative_trends(token_data, moon.get("moon_score", 0), risk.get("risk_score", 0))

            addr = token_data.get("address")
            if addr and addr not in _RESCORING_JOBS:
                _RESCORING_JOBS[addr] = context.application.job_queue.run_once(
                    rescore_token_job,
                    when=900,
                    data={"token_address": addr, "chain": token_data.get("chain", "SOL")},
                    name=f"rescore:{addr}",
                )

            for model in models:
                try:
                    result = evaluate_token_against_model(token_data, model)
                    if not result["passed"]:
                        continue
                    if db.has_recent_degen_model_alert(model["id"], token_data.get("address")):
                        continue

                    intel = {}
                    contract_address = token_data.get("address")
                    if contract_address:
                        scan = await scan_contract(contract_address, (token_data.get("chain") or "eth").lower())
                        degen_settings = db.get_degen_risk_settings()
                        scan_summary = f"\n━━━━━━━━━━━━━━━━━━━━━━━━\n🛡 *Safety: {scan['rug_grade']}* ({scan['rug_score']}/100)\n"
                        for flag in (scan.get("safety_flags") or [])[:2]:
                            scan_summary += f"{flag}\n"
                        intel["scan_summary"] = scan_summary

                        grade_order = ["F", "D", "C", "B", "A"]
                        if scan.get("is_honeypot") and degen_settings.get("block_honeypots", True):
                            await bot.send_message(chat_id=chat_id, text=f"🚨 *HONEYPOT BLOCKED*\n{scan_summary}", parse_mode="Markdown")
                            continue
                        if grade_order.index(scan.get("rug_grade", "F")) < grade_order.index(degen_settings.get("min_rug_grade", "C")):
                            await bot.send_message(chat_id=chat_id, text=f"🛡 *Degen Alert Filtered*\n{scan_summary}", parse_mode="Markdown")
                            continue

                        early = calculate_early_score(scan)
                        intel["early_section"] = f"\n⏱ *Entry Timing: {early['label']}* ({early['early_score']}/100)\n" + "".join([f"  {n}\n" for n in early["notes"][:2]])
                        vel = await get_token_mention_velocity(scan.get("token_symbol", "?"))
                        intel["social_text"] = "Social: N/A" if vel.get("trend") == "unknown" else format_social_velocity(vel)
                        position = calculate_degen_position(
                            account_size=degen_settings["account_size"],
                            max_position_pct=degen_settings["max_position_pct"],
                            rug_score=scan.get("rug_score", 0),
                            early_score=early.get("early_score", 0),
                            social_velocity=vel.get("velocity", 0),
                        )
                        intel["position_section"] = f"\n💰 *Suggested Size: ${position['final_size']:.2f}*\n  _{position['note']}_"
                        narrative = detect_token_narrative(scan.get("token_name", ""), scan.get("token_symbol", ""))
                        auto_create_degen_journal(scan, early, vel, position, narrative)

                    await send_model_alert(bot, chat_id, model, token_data, result, intel)
                    db.log_degen_model_alert(
                        model["id"], token_id, token_data.get("address"), token_data.get("symbol"),
                        result["score"], token_data.get("risk_score"), token_data.get("moon_score"), result["passed_rules"]
                    )
                    db.increment_degen_model_alert_count(model["id"])
                except Exception as exc:
                    log.exception("degen scan failed for model=%s token=%s err=%s", model.get("id"), token_data.get("symbol"), exc)

    if tokens:
        await asyncio.gather(*[_process_token(token) for token in tokens])
    await holder_accumulation_check(context)
    await degen_exit_monitor(context)
