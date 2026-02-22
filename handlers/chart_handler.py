import asyncio
import io
import json
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

import formatters

log = logging.getLogger(__name__)

CHART_WAITING_HTF_CONFIRM = 100
CHART_WAITING_LTF = 101

SINGLE_CHART_PROMPT = "Analyze this trading chart and return strict JSON."
MTF_CHART_PROMPT = "Analyze these HTF+LTF trading charts and return strict JSON."


async def download_image(update) -> bytes:
    if update.message.photo:
        file = await update.message.photo[-1].get_file()
    elif update.message.document:
        file = await update.message.document.get_file()
    else:
        raise ValueError("No image found in message")
    buf = io.BytesIO()
    await file.download_to_memory(buf)
    return buf.getvalue()


def make_image_part(image_bytes: bytes) -> dict:
    if image_bytes[:4] == b"\x89PNG":
        mime = "image/png"
    elif image_bytes[:2] == b"\xff\xd8":
        mime = "image/jpeg"
    elif image_bytes[:4] == b"RIFF":
        mime = "image/webp"
    else:
        mime = "image/jpeg"
    return {"mime_type": mime, "data": image_bytes}


async def call_gemini(parts: list, retries: int = 3) -> str:
    from config import GEMINI_MODEL, init_gemini

    model = GEMINI_MODEL or init_gemini()
    if model is None:
        raise RuntimeError("Gemini not available — check GEMINI_API_KEY")
    last_error = None
    for attempt in range(retries):
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, lambda: model.generate_content(parts))
            if not response or not response.text:
                raise ValueError("Empty response from Gemini")
            return response.text
        except Exception as e:
            last_error = e
            err = str(e).lower()
            if "429" in err or "quota" in err:
                wait = 30 * (attempt + 1)
                log.warning("Gemini rate limited. Waiting %ss (attempt %s)", wait, attempt + 1)
                await asyncio.sleep(wait)
            elif "api_key" in err or "401" in err:
                raise RuntimeError("Invalid Gemini API key. Check GEMINI_API_KEY in Railway.")
            elif attempt < retries - 1:
                await asyncio.sleep(5)
            else:
                raise
    raise last_error or RuntimeError("Gemini failed")


async def analyse_single_chart(image_bytes: bytes, context) -> dict:
    image_part = make_image_part(image_bytes)
    try:
        raw = await call_gemini([SINGLE_CHART_PROMPT, image_part])
        text = raw.strip()
        for fence in ["```json", "```JSON", "```"]:
            if text.startswith(fence):
                text = text[len(fence) :]
                break
        if text.endswith("```"):
            text = text[:-3]
        result = json.loads(text.strip())
        result["analysis_type"] = "single"
        result["analysed_at"] = datetime.utcnow().isoformat()
        return result
    except json.JSONDecodeError as e:
        log.error("Gemini bad JSON: %s", e)
        return {"chart_detected": False, "error": "Analysis returned invalid format. Try resending with better lighting."}
    except RuntimeError as e:
        return {"chart_detected": False, "error": str(e)}
    except Exception as e:
        log.error("Chart analysis error: %s", e)
        return {"chart_detected": False, "error": f"Analysis failed: {str(e)[:100]}"}


async def analyse_mtf_chart(htf_bytes: bytes, ltf_bytes: bytes, context) -> dict:
    try:
        raw = await call_gemini([MTF_CHART_PROMPT, make_image_part(htf_bytes), make_image_part(ltf_bytes)])
        text = raw.strip()
        for fence in ["```json", "```JSON", "```"]:
            if text.startswith(fence):
                text = text[len(fence) :]
                break
        if text.endswith("```"):
            text = text[:-3]
        result = json.loads(text.strip())
        result["analysis_type"] = "mtf"
        result["analysed_at"] = datetime.utcnow().isoformat()
        return result
    except json.JSONDecodeError as e:
        log.error("Gemini bad JSON: %s", e)
        return {"chart_detected": False, "error": "Analysis returned invalid format. Try resending with better lighting."}
    except RuntimeError as e:
        return {"chart_detected": False, "error": str(e)}
    except Exception as e:
        log.error("Chart analysis error: %s", e)
        return {"chart_detected": False, "error": f"Analysis failed: {str(e)[:100]}"}


async def send_analysis_result(message, context, result: dict):
    if not result.get("chart_detected", True):
        error = result.get("error", "Unknown error")
        await message.reply_text(
            f"❌ *Analysis failed*\n\n`{error}`\n\nTips for best results:\n• White background chart\n• Green/red candles clearly visible\n• Price axis visible on right side\n• Screenshot not photo of screen",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Try Again", callback_data="chart:cancel")]]),
        )
        return
    text = formatters.fmt_chart_analysis_mtf(result) if result.get("analysis_type") == "mtf" else formatters.fmt_chart_analysis_single(result)
    await message.reply_text(text, parse_mode="Markdown")
    context.user_data["last_chart_analysis"] = result


async def chart_received_first(update, context):
    image_bytes = await download_image(update)
    context.user_data["htf_image"] = image_bytes
    context.user_data["in_conversation"] = True
    context.job_queue.run_once(expire_htf_image, when=300, chat_id=update.effective_chat.id, data={"chat_id": update.effective_chat.id}, name=f"expire_htf_{update.effective_chat.id}")
    await update.message.reply_text(
        "📊 *Chart received!*\n\nIs this your *HTF (Higher Timeframe)* chart?\n_(4H, Daily, Weekly — for context)_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("✅ Yes — this is my HTF", callback_data="chart:htf_yes"), InlineKeyboardButton("📊 Analyse this one only", callback_data="chart:single")],
                [InlineKeyboardButton("❌ Cancel", callback_data="chart:cancel")],
            ]
        ),
    )
    return CHART_WAITING_HTF_CONFIRM


async def handle_chart_type_choice(update, context):
    query = update.callback_query
    await query.answer()
    if query.data == "chart:single":
        image_bytes = context.user_data.pop("htf_image", None)
        context.user_data.pop("in_conversation", None)
        if not image_bytes:
            await query.message.edit_text("❌ Image expired. Please resend.")
            return ConversationHandler.END
        await query.message.edit_text("📊 *Analysing your chart...*\n⏳ This takes 5-10 seconds...", parse_mode="Markdown")
        await send_analysis_result(query.message, context, await analyse_single_chart(image_bytes, context))
        return ConversationHandler.END

    await query.message.edit_text(
        "✅ *HTF chart saved.*\n\nNow send your *LTF (Lower Timeframe)* chart.\n_(1H, 15M, 5M — for entry timing)_\n\nOr tap below to skip LTF.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭ Skip — analyse HTF only", callback_data="chart:skip_ltf")], [InlineKeyboardButton("❌ Cancel", callback_data="chart:cancel")]]),
    )
    return CHART_WAITING_LTF


async def chart_received_ltf(update, context):
    ltf_bytes = await download_image(update)
    htf_bytes = context.user_data.pop("htf_image", None)
    context.user_data.pop("in_conversation", None)
    if not htf_bytes:
        await update.message.reply_text("❌ HTF chart expired. Please start again.")
        return ConversationHandler.END
    await update.message.reply_text("📐 *Both charts received.*\n⏳ Running multi-timeframe analysis...\nThis takes 10-15 seconds.", parse_mode="Markdown")
    await send_analysis_result(update.message, context, await analyse_mtf_chart(htf_bytes, ltf_bytes, context))
    return ConversationHandler.END


async def handle_skip_ltf(update, context):
    query = update.callback_query
    await query.answer()
    image_bytes = context.user_data.pop("htf_image", None)
    context.user_data.pop("in_conversation", None)
    if not image_bytes:
        await query.message.edit_text("❌ Image expired. Please resend.")
        return ConversationHandler.END
    await query.message.edit_text("📊 *Analysing HTF chart only...*\n⏳ 5-10 seconds...", parse_mode="Markdown")
    await send_analysis_result(query.message, context, await analyse_single_chart(image_bytes, context))
    return ConversationHandler.END


async def handle_chart_cancel(update, context):
    query = update.callback_query
    await query.answer("Cancelled")
    context.user_data.pop("htf_image", None)
    context.user_data.pop("in_conversation", None)
    await query.message.edit_text("❌ Chart analysis cancelled.")
    return ConversationHandler.END


async def expire_htf_image(context):
    chat_id = context.job.chat_id
    user_data = context.application.user_data.get(chat_id, {})
    if "htf_image" in user_data:
        del user_data["htf_image"]
        try:
            await context.bot.send_message(chat_id=chat_id, text="⏰ HTF chart expired — please resend if you still want MTF analysis.")
        except Exception:
            pass


async def handle_chart_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "chart:cancel":
        return await handle_chart_cancel(update, context)
    if query.data == "chart:resend":
        await query.message.reply_text("📸 Send your chart image to start again.")
