import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import db

log = logging.getLogger(__name__)

DEGEN_CHAINS = {
    "SOL": "🟣 Solana",
    "ETH": "🔵 Ethereum",
    "BSC": "🟡 BSC",
    "BASE": "🔵 Base",
}


async def start_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["in_conversation"] = True
    for key in [k for k in list(context.user_data) if k.startswith("degen_")]:
        context.user_data.pop(key, None)
    context.user_data["degen_chains"] = ["SOL"]
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text("🧪 Degen Wizard\n\nSend model name:")
    else:
        await update.message.reply_text("🧪 Degen Wizard\n\nSend model name:")


async def handle_degen_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("in_conversation"):
        return
    text = (update.message.text or "").strip()
    if not text:
        return
    context.user_data["degen_model_name"] = text
    context.user_data["degen_rules"] = [{"id": "liq", "name": "Liquidity", "weight": 1.0}]
    context.user_data["degen_mandatory"] = []
    await show_chain_step(update.message, context)


async def show_chain_step(update_or_query, context):
    selected = context.user_data.get("degen_chains", [])

    def btn(code):
        label = DEGEN_CHAINS[code]
        prefix = "✅ " if code in selected else ""
        return InlineKeyboardButton(
            f"{prefix}{label}",
            callback_data=f"dgwiz:chain:{code}"
        )

    next_label = (
        f"➡️ Next ({len(selected)} selected)"
        if selected else "➡️ Next"
    )

    keyboard = InlineKeyboardMarkup([
        [btn("SOL"), btn("ETH")],
        [btn("BSC"), btn("BASE")],
        [InlineKeyboardButton("✅ Select All", callback_data="dgwiz:chain:ALL")],
        [InlineKeyboardButton(next_label, callback_data="dgwiz:chain:DONE")],
        [InlineKeyboardButton("❌ Cancel", callback_data="dgwiz:cancel")],
    ])

    text = (
        f"🔗 *Select Chains* (Step 2)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Choose which chains this model scans.\n"
        f"Tap to toggle. Select one or more.\n\n"
        f"✅ Selected: "
        f"{', '.join(DEGEN_CHAINS[c] for c in selected) if selected else 'None'}"
    )

    if hasattr(update_or_query, "reply_text"):
        await update_or_query.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    elif hasattr(update_or_query, "message"):
        await update_or_query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await update_or_query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def show_strategy_step(query, context):
    await query.message.edit_text(
        "⚡ *Select Strategy* (Step 3)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 Custom", callback_data="dgwiz:strategy:custom")],
            [InlineKeyboardButton("❌ Cancel", callback_data="dgwiz:cancel")],
        ])
    )


async def show_rules_step(query, context):
    await query.message.edit_text(
        "📋 Rules selected. Save model?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Save", callback_data="dgwiz:confirm_save")],
            [InlineKeyboardButton("❌ Cancel", callback_data="dgwiz:cancel")],
        ])
    )


async def handle_degen_wizard_cb(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("dgwiz:chain:"):
        token = data.split("dgwiz:chain:")[1]

        if token == "ALL":
            context.user_data["degen_chains"] = list(DEGEN_CHAINS.keys())
            await show_chain_step(query, context)

        elif token == "DONE":
            selected = context.user_data.get("degen_chains", [])
            if not selected:
                await query.answer("⚠️ Select at least one chain", show_alert=True)
                return
            await show_strategy_step(query, context)

        elif token in DEGEN_CHAINS:
            chains = context.user_data.get("degen_chains", [])
            if token in chains:
                chains.remove(token)
            else:
                chains.append(token)
            context.user_data["degen_chains"] = chains
            await show_chain_step(query, context)
        return

    elif data.startswith("dgwiz:strategy:"):
        context.user_data["degen_strategy"] = data.split("dgwiz:strategy:")[1]
        await show_rules_step(query, context)

    elif data == "dgwiz:confirm_save":
        await handle_degen_confirm_save(update, context)

    elif data == "dgwiz:cancel":
        await handle_degen_cancel(update, context)


async def handle_degen_confirm_save(update, context):
    query = update.callback_query
    await query.answer("Saving...")

    try:
        model_id = (
            context.user_data.get("degen_model_id")
            or f"degen_{int(time.time())}"
        )

        rules = context.user_data.get("degen_rules", [])
        mandatory = context.user_data.get("degen_mandatory", [])
        chains = context.user_data.get("degen_chains", ["SOL"])
        name = context.user_data.get("degen_model_name", "Unnamed")

        if not rules:
            await query.answer("❌ No rules selected", show_alert=True)
            return

        max_score = sum(r.get("weight", 1.0) for r in rules)
        threshold = context.user_data.get("degen_min_score", 50)
        min_score = (threshold / 100) * max_score

        model = {
            "id": model_id,
            "name": name,
            "chains": chains,
            "strategy": context.user_data.get("degen_strategy", "custom"),
            "rules": rules,
            "mandatory_rules": mandatory,
            "min_liquidity": context.user_data.get("degen_min_liquidity", 5000),
            "min_age_minutes": context.user_data.get("degen_min_age", 0),
            "max_age_minutes": context.user_data.get("degen_max_age", 120),
            "max_risk_score": context.user_data.get("degen_max_risk", 70),
            "min_moon_score": context.user_data.get("degen_min_moon", 40),
            "block_serial_ruggers": context.user_data.get("degen_block_ruggers", True),
            "min_score_threshold": threshold,
            "min_score": round(min_score, 2),
            "status": "active",
        }

        db.save_degen_model(model)

        for key in [k for k in list(context.user_data) if k.startswith("degen_")]:
            context.user_data.pop(key, None)
        context.user_data.pop("in_conversation", None)

        chain_display = ", ".join(DEGEN_CHAINS.get(c, c) for c in chains)

        await query.message.edit_text(
            f"✅ *Degen Model Saved*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ {name}\n"
            f"🔗 Chains:  {chain_display}\n"
            f"📋 Rules:   {len(rules)}\n"
            f"🚀 Min moon: {model['min_moon_score']}\n"
            f"🛡️ Max risk: {model['max_risk_score']}\n\n"
            f"Model is active and scanning now.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Degen Models", callback_data="nav:degen_models")],
                [InlineKeyboardButton("🎰 Degen Home", callback_data="nav:degen_home")],
            ])
        )

    except Exception as e:
        log.error(f"Degen save failed: {type(e).__name__}: {e}")
        await query.message.edit_text(
            f"❌ *Save failed*\n\n"
            f"`{type(e).__name__}: {str(e)[:200]}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Retry", callback_data="dgwiz:confirm_save")
            ]])
        )


async def handle_degen_cancel(update, context):
    q = update.callback_query
    if q:
        await q.answer()
        await q.message.edit_text("❌ Degen wizard cancelled")
    for key in [k for k in list(context.user_data) if k.startswith("degen_")]:
        context.user_data.pop(key, None)
    context.user_data.pop("in_conversation", None)
