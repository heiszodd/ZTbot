from __future__ import annotations

import logging
from datetime import datetime

import db
from degen.model_engine import evaluate_token_against_model

log = logging.getLogger(__name__)


async def send_model_alert(bot, chat_id: int, model: dict, token_data: dict, result: dict):
    passed_names = ", ".join([r["name"] for r in result["passed_rules"][:8]]) or "None"
    failed_names = ", ".join([r["name"] for r in result["failed_rules"][:8]]) or "None"
    msg = (
        f"🎰 {model['name']} — ALERT\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Token: {token_data.get('symbol','?')} ({token_data.get('address','N/A')})\n"
        f"Score: {result['score']} / {result['max_possible_score']} ({result['confluence_fraction']})\n"
        f"Risk score: {token_data.get('risk_score','N/A')}\n"
        f"Moon score: {token_data.get('moon_score','N/A')}\n"
        f"Liquidity: ${token_data.get('liquidity_usd',0):,.0f}\n"
        f"Passed rules: {passed_names}\n"
        f"Failed rules: {failed_names}"
    )
    await bot.send_message(chat_id=chat_id, text=msg)


async def degen_scan_job(context):
    bot = context.application.bot
    chat_id = getattr(context, "chat_id", None)
    tokens = db.get_recent_degen_tokens(limit=100)
    models = db.get_active_degen_models()
    for token in tokens:
        token_data = dict(token)
        for model in models:
            try:
                result = evaluate_token_against_model(token_data, model)
                if not result["passed"]:
                    continue
                if db.has_recent_degen_model_alert(model["id"], token_data.get("address")):
                    continue
                await send_model_alert(bot, chat_id, model, token_data, result)
                db.log_degen_model_alert(model["id"], token_data.get("id"), token_data.get("address"), token_data.get("symbol"), result["score"], token_data.get("risk_score"), token_data.get("moon_score"), result["passed_rules"])
                db.increment_degen_model_alert_count(model["id"])
            except Exception as exc:
                log.exception("degen scan failed for model=%s token=%s err=%s", model.get("id"), token_data.get("symbol"), exc)
