from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from concurrent.futures import ThreadPoolExecutor

import db
from degen.model_engine import evaluate_token_against_model
from degen.moon_engine import score_moonshot_potential
from degen.narrative_tracker import update_narrative_trends
from degen.postmortem import create_postmortem
from degen.risk_engine import score_token_risk, score_trajectory

log = logging.getLogger(__name__)

SOLSCAN_RATE_LIMIT_DELAY = 0.2
_RESCORING_JOBS: dict[str, object] = {}
_executor = ThreadPoolExecutor(max_workers=2)


async def send_model_alert(bot, chat_id: int, model: dict, token_data: dict, result: dict):
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
    await bot.send_message(chat_id=chat_id, text=msg)




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
    if traj.get("trajectory") == "worsening" and traj.get("warning_message"):
        msg = (
            "⚠️ RISK TRAJECTORY WARNING\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 {tok.get('name',tok.get('symbol'))} ({tok.get('symbol')})\n"
            f"📊 Score 15 min ago:  {int(tok.get('initial_risk_score') or tok.get('risk_score') or 0)}/100\n"
            f"📊 Score now:         {risk2.get('risk_score')}/100\n"
            f"📈 Change:            {traj.get('delta',0):+d} points\n\n"
            f"{traj.get('warning_message')}\n\n"
            "If you are holding this token, review your position now."
        )
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📊 Full Report", callback_data=f"wallet:token:{address}"), InlineKeyboardButton("👀 Still watching", callback_data=f"wallet:watch:{address}"), InlineKeyboardButton("✅ Already exited", callback_data="wallet:dismiss")]])
        await context.application.bot.send_message(chat_id=context.job.chat_id or context.application.bot_data.get("chat_id"), text=msg, reply_markup=kb)


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
            if token_data.get("is_honeypot"):
                token_data["holder_cluster_skipped"] = True
            elif int(risk.get("risk_score") or 0) <= 30:
                token_data["holder_cluster_skipped"] = True
            token_id = db.upsert_degen_token_snapshot(token_data)
            update_narrative_trends(token_data, moon.get("moon_score", 0), risk.get("risk_score", 0))

            addr = token_data.get("address")
            if addr and addr not in _RESCORING_JOBS:
                _RESCORING_JOBS[addr] = context.application.job_queue.run_once(rescore_token_job, when=900, data={"token_address": addr, "chain": token_data.get("chain", "SOL")}, name=f"rescore:{addr}")

            hits = 0
            for model in models:
                try:
                    result = evaluate_token_against_model(token_data, model)
                    if not result["passed"]:
                        continue
                    if db.has_recent_degen_model_alert(model["id"], token_data.get("address")):
                        continue
                    await send_model_alert(bot, chat_id, model, token_data, result)
                    db.log_degen_model_alert(model["id"], token_id, token_data.get("address"), token_data.get("symbol"), result["score"], token_data.get("risk_score"), token_data.get("moon_score"), result["passed_rules"])
                    db.increment_degen_model_alert_count(model["id"])
                    hits += 1
                except Exception as exc:
                    log.exception("degen scan failed for model=%s token=%s err=%s", model.get("id"), token_data.get("symbol"), exc)
            return hits

    if tokens:
        await asyncio.gather(*[_process_token(token) for token in tokens])
    await holder_accumulation_check(context)
    await degen_exit_monitor(context)
