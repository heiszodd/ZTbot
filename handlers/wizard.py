import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

import db
from config import CHAT_ID, SUPPORTED_PAIRS, SUPPORTED_TIMEFRAMES, SUPPORTED_SESSIONS, SUPPORTED_MODEL_RULES
from formatters import fmt_bias

log = logging.getLogger(__name__)

(
    WIZARD_NAME,
    WIZARD_PAIR,
    WIZARD_TF,
    WIZARD_SESSION,
    WIZARD_BIAS,
    WIZARD_RULES,
    WIZARD_REVIEW,
) = range(7)


async def start_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["in_conversation"] = True
    context.user_data["model_rules"] = []
    if update.callback_query:
        await update.callback_query.answer()
        sender = update.callback_query.message.reply_text
    else:
        if not update.effective_chat or update.effective_chat.id != CHAT_ID:
            return ConversationHandler.END
        sender = update.message.reply_text
    await sender(
        "⚙️ *Model Wizard*\n\nSend model name:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="wizard:cancel")]]),
    )
    return WIZARD_NAME


async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["model_name"] = (update.message.text or "").strip()
    buttons = [[InlineKeyboardButton(p, callback_data=f"wizard:pair:{p}") for p in SUPPORTED_PAIRS[i:i+3]] for i in range(0, len(SUPPORTED_PAIRS), 3)]
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="wizard:cancel")])
    await update.message.reply_text("🪙 Select pair", reply_markup=InlineKeyboardMarkup(buttons))
    return WIZARD_PAIR


async def handle_pair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["model_pair"] = q.data.split(":", 2)[2]
    buttons = [[InlineKeyboardButton(tf, callback_data=f"wizard:tf:{tf}") for tf in SUPPORTED_TIMEFRAMES[i:i+3]] for i in range(0, len(SUPPORTED_TIMEFRAMES), 3)]
    buttons.append([InlineKeyboardButton("« Back", callback_data="wizard:back")])
    await q.message.edit_text("⏱ Select timeframe", reply_markup=InlineKeyboardMarkup(buttons))
    return WIZARD_TF


async def handle_tf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["model_timeframe"] = q.data.split(":", 2)[2]
    buttons = [[InlineKeyboardButton(s, callback_data=f"wizard:session:{s}") for s in SUPPORTED_SESSIONS[i:i+2]] for i in range(0, len(SUPPORTED_SESSIONS), 2)]
    buttons.append([InlineKeyboardButton("« Back", callback_data="wizard:back")])
    await q.message.edit_text("🧭 Select session", reply_markup=InlineKeyboardMarkup(buttons))
    return WIZARD_SESSION


async def handle_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["model_session"] = q.data.split(":", 2)[2]
    await q.message.edit_text(
        "📈 Directional Bias",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📈 Bullish", callback_data="wizard:bias:Bullish"), InlineKeyboardButton("📉 Bearish", callback_data="wizard:bias:Bearish")],
            [InlineKeyboardButton("↔️ Both Directions", callback_data="wizard:bias:Both")],
            [InlineKeyboardButton("« Back", callback_data="wizard:back")],
        ]),
    )
    return WIZARD_BIAS


async def handle_bias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    bias = q.data.split(":", 2)[2]
    context.user_data["model_bias"] = bias
    note = ""
    if bias == "Both":
        note = (
            "\n\n↔️ Bias: Both Directions\n"
            "This model will scan for bullish AND bearish setups\n"
            "using the same rules. Each direction is scored\n"
            "independently and alerted separately."
        )
    buttons = [[InlineKeyboardButton(rule, callback_data=f"wizard:rule:{idx}")] for idx, rule in enumerate(SUPPORTED_MODEL_RULES)]
    buttons.append([InlineKeyboardButton("✅ Review", callback_data="wizard:review")])
    buttons.append([InlineKeyboardButton("« Back", callback_data="wizard:back")])
    await q.message.edit_text(f"📋 Add rules (tap to add).{note}", reply_markup=InlineKeyboardMarkup(buttons))
    return WIZARD_RULES


async def handle_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "wizard:review":
        return await show_review(update, context)
    idx = int(q.data.split(":", 2)[2])
    rule_name = SUPPORTED_MODEL_RULES[idx]
    rules = context.user_data.setdefault("model_rules", [])
    if any(r.get("name") == rule_name for r in rules):
        await q.answer("Rule already added", show_alert=True)
        return WIZARD_RULES
    rules.append({"id": f"r{len(rules)+1}", "name": rule_name, "weight": 1.0, "mandatory": False})
    await q.answer(f"Added {rule_name}")
    return WIZARD_RULES


async def show_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = context.user_data
    rules = d.get("model_rules", [])
    lines = [
        "📋 *Review Model*",
        f"⚙️ {d.get('model_name', '-')}",
        f"🪙 {d.get('model_pair', '-')}",
        f"⏱ {d.get('model_timeframe', '-')}",
        f"🧭 {d.get('model_session', '-')}",
        f"📊 Bias: {fmt_bias(d.get('model_bias', 'Both'))}",
        f"📋 Rules: {len(rules)}",
    ]
    await q.message.edit_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Save Model", callback_data="wizard:confirm_save")],
            [InlineKeyboardButton("« Back", callback_data="wizard:back")],
            [InlineKeyboardButton("❌ Cancel", callback_data="wizard:cancel")],
        ]),
    )
    return WIZARD_REVIEW


async def handle_confirm_save(update, context):
    query = update.callback_query
    await query.answer("Saving...")

    try:
        model_id = (
            context.user_data.get("model_id")
            or f"model_{int(datetime.utcnow().timestamp())}"
        )
        name = context.user_data.get("model_name", "Unnamed Model")
        pair = context.user_data.get("model_pair", "BTCUSDT")
        timeframe = context.user_data.get("model_timeframe", "1h")
        session = context.user_data.get("model_session", "Any")
        bias = context.user_data.get("model_bias", "Both")
        rules = context.user_data.get("model_rules", [])
        desc = context.user_data.get("model_description", "")

        if not rules:
            await query.answer(
                "❌ No rules added — go back and add rules first",
                show_alert=True,
            )
            return WIZARD_RULES

        max_score = sum(r.get("weight", 1.0) for r in rules)
        model = {
            "id": model_id,
            "name": name,
            "pair": pair,
            "timeframe": timeframe,
            "session": session,
            "bias": bias,
            "status": "inactive",
            "rules": rules,
            "tier_a_threshold": round(max_score * 0.80, 2),
            "tier_b_threshold": round(max_score * 0.65, 2),
            "tier_c_threshold": round(max_score * 0.50, 2),
            "min_score": round(max_score * 0.50, 2),
            "description": desc,
        }

        saved_id = db.save_model(model)

        for key in [k for k in list(context.user_data) if k.startswith("model_")]:
            context.user_data.pop(key, None)
        context.user_data.pop("in_conversation", None)

        await query.message.edit_text(
            f"✅ *Model Saved Successfully*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ {name}\n"
            f"🪙 {pair}   {timeframe}\n"
            f"📊 Bias:   {fmt_bias(bias)}\n"
            f"📋 Rules:  {len(rules)}\n"
            f"🏆 Min score: {model['min_score']}\n\n"
            f"Model saved as inactive.\n"
            f"Activate it to start receiving alerts.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ Activate Now", callback_data=f"model:toggle:{saved_id}")],
                [InlineKeyboardButton("⚙️ View All Models", callback_data="nav:models")],
                [InlineKeyboardButton("🏠 Perps Home", callback_data="nav:perps_home")],
            ]),
        )
        return ConversationHandler.END

    except Exception as e:
        log.error(f"Wizard save failed: {type(e).__name__}: {e}")
        await query.message.edit_text(
            f"❌ *Save failed*\n\n"
            f"`{type(e).__name__}: {str(e)[:200]}`\n\n"
            f"Your model data is still in memory.\n"
            f"Tap Retry to try again.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Retry Save", callback_data="wizard:confirm_save")]]),
        )
        return WIZARD_REVIEW


async def handle_wizard_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    return await show_review(update, context)


async def handle_wizard_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query if update.callback_query else None
    if q:
        await q.answer()
        await q.message.edit_text("❌ Wizard cancelled")
    context.user_data.pop("in_conversation", None)
    for key in [k for k in list(context.user_data) if k.startswith("model_")]:
        context.user_data.pop(key, None)
    return ConversationHandler.END


# backward compatibility exports
wiz_start = start_wizard
cancel = handle_wizard_cancel


def build_wizard_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_wizard, pattern="^wizard:start$|^wiz:start$"),
            CommandHandler("newmodel", start_wizard),
            CommandHandler("create_model", start_wizard),
        ],
        states={
            WIZARD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name)],
            WIZARD_PAIR: [CallbackQueryHandler(handle_pair, pattern="^wizard:pair:")],
            WIZARD_TF: [CallbackQueryHandler(handle_tf, pattern="^wizard:tf:")],
            WIZARD_SESSION: [CallbackQueryHandler(handle_session, pattern="^wizard:session:")],
            WIZARD_BIAS: [CallbackQueryHandler(handle_bias, pattern="^wizard:bias:")],
            WIZARD_RULES: [
                CallbackQueryHandler(handle_rules, pattern="^wizard:rule:"),
                CallbackQueryHandler(handle_rules, pattern="^wizard:review$"),
            ],
            WIZARD_REVIEW: [
                CallbackQueryHandler(handle_confirm_save, pattern="^wizard:confirm_save$"),
                CallbackQueryHandler(handle_wizard_back, pattern="^wizard:back$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(handle_wizard_cancel, pattern="^wizard:cancel$|^wiz:cancel$"),
            CommandHandler("cancel", handle_wizard_cancel),
        ],
        per_message=False,
        per_chat=True,
        allow_reentry=True,
    )
