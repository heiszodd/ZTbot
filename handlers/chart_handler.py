import asyncio
import io
import json
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import db
import formatters

log = logging.getLogger(__name__)

SINGLE_CHART_PROMPT = """
You are an expert price action trader and technical analyst.
You are analysing a trading chart screenshot sent by a trader.

The chart has a WHITE background with GREEN bullish candles
and RED bearish candles. Prices are shown on the right axis.

Analyse this chart completely and respond ONLY in the exact
JSON format below. No extra text before or after the JSON.

{
  "chart_detected": true or false,
  "timeframe_estimate": "estimated timeframe or unknown",
  "pair_estimate": "asset name if visible or unknown",

  "trend": {
    "direction": "bullish" or "bearish" or "ranging",
    "strength": "strong" or "moderate" or "weak",
    "description": "one sentence describing the overall trend"
  },

  "market_structure": {
    "type": "uptrend" or "downtrend" or "range" or "reversal",
    "last_swing_high": "price level if readable or null",
    "last_swing_low": "price level if readable or null",
    "structure_break": true or false,
    "structure_break_direction": "bullish" or "bearish" or null,
    "description": "describe the market structure in 1-2 sentences"
  },

  "key_levels": [
    {
      "type": "resistance" or "support" or "order_block" or "fvg" or "liquidity",
      "price": "price level if readable or approximate description",
      "strength": "strong" or "moderate" or "weak",
      "description": "brief description of this level"
    }
  ],

  "patterns": [
    {
      "name": "pattern name",
      "location": "where on the chart",
      "implication": "bullish" or "bearish" or "neutral",
      "description": "brief description"
    }
  ],

  "order_blocks": [
    {
      "direction": "bullish" or "bearish",
      "location": "describe where on chart",
      "price_zone": "approximate price zone",
      "respected": true or false,
      "description": "brief description"
    }
  ],

  "fair_value_gaps": [
    {
      "direction": "bullish" or "bearish",
      "location": "describe where on chart",
      "price_zone": "approximate price zone",
      "filled": true or false
    }
  ],

  "liquidity": {
    "buy_side": "describe buy side liquidity location",
    "sell_side": "describe sell side liquidity location",
    "recent_sweep": true or false,
    "sweep_direction": "buy" or "sell" or null,
    "description": "1 sentence on liquidity context"
  },

  "current_price_context": {
    "in_premium_or_discount": "premium" or "discount" or "equilibrium",
    "near_key_level": true or false,
    "key_level_description": "describe nearest key level",
    "price_action_quality": "strong" or "moderate" or "weak"
  },

  "bias": {
    "direction": "bullish" or "bearish" or "neutral",
    "confidence": "high" or "medium" or "low",
    "reasoning": "explain the bias in 2-3 sentences"
  },

  "setup": {
    "setup_present": true or false,
    "setup_type": "describe the setup type or null",
    "entry_zone": "price zone for entry or null",
    "stop_loss": "suggested stop loss price or zone or null",
    "take_profit_1": "first target or null",
    "take_profit_2": "second target or null",
    "take_profit_3": "third target or null",
    "risk_reward": "estimated RR ratio or null",
    "entry_condition": "what needs to happen before entering",
    "invalidation": "what would invalidate this setup"
  },

  "confluence_score": 0 to 10,
  "confluence_factors": ["list each confluence factor present"],

  "warnings": ["list any red flags or caution points"],

  "summary": "3-4 sentence complete analysis summary for a trader",

  "action": "buy" or "sell" or "wait" or "avoid"
}

If this is not a trading chart, set chart_detected to false
and return only {"chart_detected": false, "reason": "explain"}.
"""

MTF_CHART_PROMPT = """
You are an expert price action trader and technical analyst.
You are analysing TWO trading chart screenshots sent by a trader.

The FIRST image is the HIGHER TIMEFRAME (HTF) chart.
The SECOND image is the LOWER TIMEFRAME (LTF) chart.

Both charts have WHITE backgrounds with GREEN bullish candles
and RED bearish candles.

Analyse both charts together as a multi-timeframe analysis
and respond ONLY in the exact JSON format below.
No extra text before or after the JSON.

{
  "htf": {
    "timeframe_estimate": "estimated timeframe or unknown",
    "trend_direction": "bullish" or "bearish" or "ranging",
    "trend_strength": "strong" or "moderate" or "weak",
    "market_structure": "uptrend" or "downtrend" or "range" or "reversal",
    "key_levels": [
      {
        "type": "support" or "resistance" or "order_block" or "fvg",
        "price": "price or zone",
        "strength": "strong" or "moderate" or "weak"
      }
    ],
    "bias": "bullish" or "bearish" or "neutral",
    "bias_reasoning": "explain HTF bias in 2 sentences",
    "premium_discount": "premium" or "discount" or "equilibrium",
    "liquidity_above": "describe",
    "liquidity_below": "describe"
  },

  "ltf": {
    "timeframe_estimate": "estimated timeframe or unknown",
    "trend_direction": "bullish" or "bearish" or "ranging",
    "market_structure": "uptrend" or "downtrend" or "range" or "reversal",
    "structure_break": true or false,
    "structure_break_direction": "bullish" or "bearish" or null,
    "order_blocks": [
      {
        "direction": "bullish" or "bearish",
        "price_zone": "approximate zone",
        "respected": true or false
      }
    ],
    "fair_value_gaps": [
      {
        "direction": "bullish" or "bearish",
        "price_zone": "approximate zone",
        "filled": true or false
      }
    ],
    "current_pattern": "describe current candle pattern or price action",
    "entry_trigger": "what specific price action would trigger entry"
  },

  "alignment": {
    "htf_ltf_aligned": true or false,
    "alignment_description": "describe how HTF and LTF relate",
    "alignment_quality": "perfect" or "good" or "partial" or "conflicting"
  },

  "setup": {
    "setup_present": true or false,
    "setup_quality": "A+" or "A" or "B" or "C" or "wait",
    "setup_type": "describe the complete setup",
    "direction": "long" or "short" or null,
    "entry_zone": "price zone or null",
    "entry_condition": "exact condition needed before entering",
    "stop_loss": "price or zone",
    "stop_loss_reasoning": "why this stop location",
    "take_profit_1": "first target",
    "take_profit_2": "second target",
    "take_profit_3": "third target",
    "risk_reward": "estimated RR",
    "invalidation": "what invalidates this setup",
    "ideal_entry_description": "describe the perfect entry in plain language"
  },

  "confluence_score": 0 to 10,
  "confluence_factors": [
    "list every confluence factor present across both timeframes"
  ],

  "missing_confluence": [
    "list what is missing that would make this a higher quality setup"
  ],

  "warnings": ["list any red flags or risks"],

  "htf_summary": "2 sentence HTF analysis summary",
  "ltf_summary": "2 sentence LTF analysis summary",
  "overall_summary": "3-4 sentence complete MTF analysis for the trader",

  "action": "buy" or "sell" or "wait" or "avoid",
  "urgency": "immediate" or "prepare" or "watch" or "ignore"
}
"""


async def download_image(update: Update) -> bytes:
    message = update.message
    if message.document and message.document.file_size and message.document.file_size > 20 * 1024 * 1024:
        raise ValueError("IMAGE_TOO_LARGE")
    if message.photo:
        file = await message.photo[-1].get_file()
    elif message.document:
        file = await message.document.get_file()
    else:
        raise ValueError("No image found")
    buf = io.BytesIO()
    await file.download_to_memory(buf)
    return buf.getvalue()


async def clear_pending_htf(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data.get("chat_id")
    user_id = context.job.data.get("user_id")
    udata = context.application.user_data.get(user_id or chat_id, {})
    if udata.pop("pending_htf_image", None) is not None:
        udata.pop("htf_message_id", None)
        await context.bot.send_message(chat_id=chat_id, text="⏰ HTF chart expired — please resend if you still want MTF analysis.")


async def handle_chart_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📊 *Chart received — analysing...*\n"
        "⏳ Reading structure, levels, and patterns.\n"
        "_This takes 5-10 seconds_",
        parse_mode="Markdown"
    )

    try:
        if context.user_data.get("pending_htf_image"):
            htf_bytes = context.user_data.pop("pending_htf_image")
            context.user_data.pop("htf_message_id", None)
            ltf_bytes = await download_image(update)
            result = await analyse_mtf_chart(htf_bytes, ltf_bytes, context)
            await send_analysis_result(update.message, context, result)
            await _handle_chart_detection_failure(update.message, result)
            return

        image_bytes = await download_image(update)
        context.user_data["pending_htf_image"] = image_bytes
        context.user_data["htf_message_id"] = update.message.message_id
        context.job_queue.run_once(
            clear_pending_htf,
            when=300,
            data={"chat_id": update.effective_chat.id, "user_id": update.effective_user.id},
            name=f"chart_htf_expiry_{update.effective_chat.id}",
        )
        await update.message.reply_text(
            "📊 Got your chart.\n\n"
            "Is this a single chart or are you sending HTF + LTF?",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔍 Analyse this chart only", callback_data="chart:single"),
                    InlineKeyboardButton("📐 I'll send LTF next", callback_data="chart:wait_ltf")
                ]
            ])
        )
    except ValueError as exc:
        if str(exc) == "IMAGE_TOO_LARGE":
            await update.message.reply_text(
                "❌ *Image too large*\n"
                "Please send a screenshot under 20MB.\n"
                "A standard chart screenshot is usually 100-500KB.",
                parse_mode="Markdown"
            )
    except Exception as exc:
        log.error(f"Chart image handling error: {exc}")
        await update.message.reply_text("❌ Could not process image. Please try again.")


async def handle_chart_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "chart:single":
        image_bytes = context.user_data.pop("pending_htf_image", None)
        context.user_data.pop("htf_message_id", None)
        if not image_bytes:
            await query.answer("Image expired — please resend")
            return
        await query.answer("Analysing...")
        await query.message.edit_text(
            "📊 *Analysing your chart...*\n⏳ Reading structure and levels...",
            parse_mode="Markdown"
        )
        result = await analyse_single_chart(image_bytes, context)
        await send_analysis_result(query.message, context, result)
        await _handle_chart_detection_failure(query.message, result)
        return

    if data == "chart:wait_ltf":
        await query.answer("Ready — send your LTF chart now")
        await query.message.edit_text(
            "📐 *HTF saved.*\n\n"
            "Send your LTF chart now and I'll analyse both together.",
            parse_mode="Markdown"
        )
        return

    if data == "chart:demo:confirm":
        payload = context.user_data.get("pending_chart_trade")
        if not payload:
            await query.answer("Trade details expired")
            return
        await _open_chart_demo_trade(query, context, payload)
        return

    if data.startswith("chart:demo:"):
        payload = _parse_demo_callback(data)
        if not payload:
            await query.answer("Invalid trade payload")
            return
        await _open_chart_demo_trade(query, context, payload)
        return

    if data.startswith("chart:pending:"):
        _, _, pair, direction, model_id = data.split(":", 4)
        pending_id = db.save_pending_setup({
            "model_id": model_id,
            "model_name": "Chart Analysis",
            "pair": pair,
            "timeframe": "chart",
            "direction": direction.upper(),
            "entry_price": 0,
            "sl": 0,
            "tp1": 0,
            "tp2": 0,
            "tp3": 0,
            "current_score": 0,
            "max_possible_score": 10,
            "score_pct": 0,
            "min_score_threshold": 7,
            "passed_rules": [],
            "failed_rules": [],
            "mandatory_passed": [],
            "mandatory_failed": [],
            "rule_snapshots": {"source": "chart_analysis"},
            "telegram_message_id": query.message.message_id,
            "telegram_chat_id": query.message.chat_id,
            "status": "pending",
        })
        await query.message.reply_text(f"✅ Added to pending setups (ID #{pending_id}).")
        await query.message.reply_text("Open pending dashboard from Perps Home → ⏳ Pending.")
        return

    if data == "chart:resend":
        context.user_data.pop("pending_htf_image", None)
        context.user_data.pop("htf_message_id", None)
        await query.message.edit_text("Ready for a new chart — send it now.")
        return

    if data.startswith("chart:save:"):
        result = context.user_data.get("last_chart_analysis")
        if not result:
            await query.message.reply_text("No analysis found to save.")
            return
        analysis_id = db.save_chart_analysis(result)
        await query.message.reply_text(f"💾 Analysis saved (ID #{analysis_id}).")


async def _open_chart_demo_trade(query, context, payload: dict):
    acct = db.get_demo_account("perps")
    if not acct:
        await query.message.reply_text("🎮 No demo account found. Open Demo first from Perps Home.")
        return
    try:
        entry = _safe_float(payload.get("entry"))
        sl = _safe_float(payload.get("sl"))
        tp1 = _safe_float(payload.get("tp1"))
        tp2 = _safe_float(payload.get("tp2"))
        tp3 = _safe_float(payload.get("tp3"))
        direction = str(payload.get("direction") or "buy").upper()
        risk = max(25.0, float(acct.get("balance") or 0) * 0.01)
        position = (risk / abs((entry - sl) / entry)) if (entry and sl and entry != sl) else risk * 10
        trade_id = db.open_demo_trade({
            "section": "perps",
            "pair": payload.get("pair") or "UNKNOWN",
            "direction": "LONG" if direction in {"BUY", "LONG"} else "SHORT",
            "entry_price": entry or 1,
            "sl": sl or (entry * 0.99 if direction in {"BUY", "LONG"} else entry * 1.01),
            "tp1": tp1 or entry,
            "tp2": tp2 or entry,
            "tp3": tp3 or entry,
            "position_size_usd": position,
            "risk_amount_usd": risk,
            "risk_pct": (risk / max(1.0, float(acct.get("balance") or 1))) * 100,
            "model_id": "chart_analysis",
            "model_name": "Chart Analysis",
            "tier": "B",
            "score": 7,
            "source": "chart_analysis",
            "notes": json.dumps(payload),
        })
        last = context.user_data.get("last_chart_analysis")
        if last:
            analysis_id = db.save_chart_analysis(last)
            db.link_chart_to_demo_trade(analysis_id, trade_id)
        await query.message.reply_text(
            f"✅ Demo trade opened from chart analysis.\n"
            f"Pair: {payload.get('pair')}\nDirection: {direction}\nEntry: {payload.get('entry')}\nSL: {payload.get('sl')}\nTP1: {payload.get('tp1')}\nTrade ID: #{trade_id}"
        )
    except Exception as exc:
        log.error(f"chart demo open failed: {exc}")
        await query.message.reply_text("❌ Could not open demo trade from chart analysis.")


async def analyse_single_chart(image_bytes: bytes, context) -> dict:
    import google.generativeai as genai
    from config import GEMINI_MODEL

    image_part = {
        "mime_type": "image/jpeg",
        "data": image_bytes
    }
    raw_text = ""
    try:
        if GEMINI_MODEL is None:
            return {"chart_detected": False, "error": "Gemini model not initialised"}
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: GEMINI_MODEL.generate_content([SINGLE_CHART_PROMPT, image_part])
        )

        raw_text = response.text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        raw_text = raw_text.strip()

        result = json.loads(raw_text)
        result["analysis_type"] = "single"
        result["analysed_at"] = datetime.utcnow().isoformat()
        return result
    except json.JSONDecodeError as e:
        log.error(f"Gemini returned invalid JSON: {e}\nRaw: {raw_text[:500]}")
        return {"chart_detected": False, "error": "Invalid response format", "raw": raw_text[:200]}
    except Exception as e:
        log.error(f"Gemini API error: {e}")
        return {"chart_detected": False, "error": str(e)}


async def analyse_mtf_chart(htf_bytes: bytes, ltf_bytes: bytes, context) -> dict:
    import google.generativeai as genai
    from config import GEMINI_MODEL

    htf_part = {"mime_type": "image/jpeg", "data": htf_bytes}
    ltf_part = {"mime_type": "image/jpeg", "data": ltf_bytes}
    raw_text = ""
    try:
        if GEMINI_MODEL is None:
            return {"chart_detected": False, "error": "Gemini model not initialised"}
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: GEMINI_MODEL.generate_content([MTF_CHART_PROMPT, htf_part, ltf_part])
        )

        raw_text = response.text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        raw_text = raw_text.strip()

        result = json.loads(raw_text)
        result["analysis_type"] = "mtf"
        result["analysed_at"] = datetime.utcnow().isoformat()
        return result
    except json.JSONDecodeError as e:
        log.error(f"Gemini MTF returned invalid JSON: {e}\nRaw: {raw_text[:500]}")
        return {"chart_detected": False, "error": "Invalid response format"}
    except Exception as e:
        log.error(f"Gemini MTF API error: {e}")
        return {"chart_detected": False, "error": str(e)}


async def send_analysis_result(message, context, result: dict):
    analysis_type = result.get("analysis_type", "single")

    if analysis_type == "mtf":
        text = formatters.fmt_chart_analysis_mtf(result)
    else:
        text = formatters.fmt_chart_analysis_single(result)

    buttons = []
    setup = result.get("setup", {})
    action = result.get("action", "wait")

    if setup.get("setup_present") and action in ["buy", "sell"]:
        direction = setup.get("direction", action)
        entry = setup.get("entry_zone", "market")
        sl = setup.get("stop_loss", "")
        tp1 = setup.get("take_profit_1", "")
        tp2 = setup.get("take_profit_2", "")
        tp3 = setup.get("take_profit_3", "")
        pair = result.get("pair_estimate", result.get("htf", {}).get("pair_estimate", "UNKNOWN"))

        def sanitise(s):
            return str(s).replace(" ", "").replace("/", "")[:10] if s else "N/A"

        cb = f"chart:demo:{sanitise(pair)}:{sanitise(direction)}:{sanitise(entry)}:{sanitise(sl)}:{sanitise(tp1)}:{sanitise(tp2)}:{sanitise(tp3)}"
        if len(cb) > 60:
            context.user_data["pending_chart_trade"] = {
                "pair": pair,
                "direction": direction,
                "entry": entry,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "tp3": tp3,
            }
            cb = "chart:demo:confirm"

        buttons.append([InlineKeyboardButton("🎮 Demo Trade This", callback_data=cb)])

    buttons.append([
        InlineKeyboardButton("🔄 Send Another Chart", callback_data="chart:resend"),
        InlineKeyboardButton("💾 Save Analysis", callback_data=f"chart:save:{result.get('analysed_at', '')[:19]}")
    ])
    buttons.append([
        InlineKeyboardButton("📈 Perps Home", callback_data="nav:perps_home"),
        InlineKeyboardButton("🎰 Degen Home", callback_data="nav:degen_home")
    ])

    keyboard = InlineKeyboardMarkup(buttons)
    if len(text) > 4096:
        parts = [text[i:i + 4000] for i in range(0, len(text), 4000)]
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                await message.reply_text(part, parse_mode="Markdown", reply_markup=keyboard)
            else:
                await message.reply_text(part, parse_mode="Markdown")
    else:
        await message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

    context.user_data["last_chart_analysis"] = result


async def _handle_chart_detection_failure(message, result: dict):
    err = str(result.get("error", ""))
    if "429" in err:
        await message.reply_text(
            "⏳ *Rate limit hit*\n"
            "Gemini free tier allows 15 requests/minute.\n"
            "Please wait 30 seconds and try again.",
            parse_mode="Markdown"
        )
        return
    if "500" in err:
        await message.reply_text(
            "❌ *Analysis failed*\n"
            "Gemini API returned an error.\n"
            "Please try again in a moment.",
            parse_mode="Markdown"
        )
        return

    if result.get("chart_detected") is False:
        await message.reply_text(
            "❓ *This doesn't look like a trading chart*\n\n"
            "For best results:\n"
            "• White background\n"
            "• Green and red candles\n"
            "• Price axis visible on right\n"
            "• No dark mode\n\n"
            "Send a fresh screenshot and try again.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Try Again", callback_data="chart:resend")
            ]])
        )


def _parse_demo_callback(data: str) -> dict | None:
    parts = data.split(":")
    if len(parts) != 9:
        return None
    _, _, pair, direction, entry, sl, tp1, tp2, tp3 = parts
    return {
        "pair": pair,
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
    }


def _safe_float(value):
    try:
        cleaned = str(value).replace(",", "")
        return float(cleaned)
    except Exception:
        return 0.0
