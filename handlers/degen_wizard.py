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

DEGEN_RULE_LIBRARY = [
    {"id": "dev_no_rugs", "category": "Dev Reputation", "name": "Dev Has No Rugs", "description": "Developer wallet has zero confirmed rug history", "default_weight": 3.0},
    {"id": "dev_wallet_old", "category": "Dev Reputation", "name": "Dev Wallet Age 7+ Days", "description": "Developer wallet is at least 7 days old", "default_weight": 2.0},
    {"id": "dev_wallet_30d", "category": "Dev Reputation", "name": "Dev Wallet Age 30+ Days", "description": "Developer wallet is at least 30 days old", "default_weight": 3.0},
    {"id": "dev_low_supply", "category": "Dev Reputation", "name": "Dev Holds Less Than 5%", "description": "Developer wallet holds less than 5% of total supply", "default_weight": 2.0},
    {"id": "dev_very_low_supply", "category": "Dev Reputation", "name": "Dev Holds Less Than 2%", "description": "Developer wallet holds less than 2% of total supply", "default_weight": 3.0},
    {"id": "not_serial_rugger", "category": "Dev Reputation", "name": "Not a Serial Rugger", "description": "Dev wallet not flagged as serial rugger in any database", "default_weight": 3.5},
    {"id": "mint_revoked", "category": "Contract Safety", "name": "Mint Authority Revoked", "description": "Token mint authority has been permanently revoked", "default_weight": 3.0},
    {"id": "freeze_revoked", "category": "Contract Safety", "name": "Freeze Authority Revoked", "description": "Token freeze authority has been permanently revoked", "default_weight": 2.5},
    {"id": "contract_verified", "category": "Contract Safety", "name": "Contract Verified", "description": "Smart contract source code is publicly verified", "default_weight": 1.5},
    {"id": "no_honeypot", "category": "Contract Safety", "name": "Not a Honeypot", "description": "Token passes honeypot detection checks", "default_weight": 4.0},
    {"id": "rugcheck_low", "category": "Contract Safety", "name": "RugCheck Score Below 300", "description": "RugCheck.xyz risk score is under 300 (low risk)", "default_weight": 2.0},
    {"id": "rugcheck_very_low", "category": "Contract Safety", "name": "RugCheck Score Below 150", "description": "RugCheck.xyz risk score is under 150 (very low risk)", "default_weight": 3.0},
    {"id": "lp_locked", "category": "Liquidity", "name": "LP Locked", "description": "Liquidity pool tokens are locked", "default_weight": 3.0},
    {"id": "lp_locked_50", "category": "Liquidity", "name": "LP 50%+ Locked", "description": "More than 50% of LP tokens are locked", "default_weight": 2.0},
    {"id": "lp_locked_80", "category": "Liquidity", "name": "LP 80%+ Locked", "description": "More than 80% of LP tokens are locked", "default_weight": 3.0},
    {"id": "lp_burned", "category": "Liquidity", "name": "LP Burned", "description": "Liquidity pool tokens have been burned permanently", "default_weight": 3.5},
    {"id": "liquidity_10k", "category": "Liquidity", "name": "Liquidity Above $10K", "description": "Total liquidity exceeds $10,000 USD", "default_weight": 2.0},
    {"id": "liquidity_50k", "category": "Liquidity", "name": "Liquidity Above $50K", "description": "Total liquidity exceeds $50,000 USD", "default_weight": 3.0},
    {"id": "liquidity_100k", "category": "Liquidity", "name": "Liquidity Above $100K", "description": "Total liquidity exceeds $100,000 USD", "default_weight": 4.0},
    {"id": "top_holder_under_10", "category": "Holder Distribution", "name": "Top Holder Below 10%", "description": "Largest single holder owns less than 10% of supply", "default_weight": 2.0},
    {"id": "top_holder_under_5", "category": "Holder Distribution", "name": "Top Holder Below 5%", "description": "Largest single holder owns less than 5% of supply", "default_weight": 3.0},
    {"id": "top5_under_30", "category": "Holder Distribution", "name": "Top 5 Holders Below 30%", "description": "Combined top 5 holders own less than 30% of supply", "default_weight": 2.0},
    {"id": "holder_count_100", "category": "Holder Distribution", "name": "100+ Holders", "description": "Token has more than 100 unique holders", "default_weight": 1.5},
    {"id": "holder_count_500", "category": "Holder Distribution", "name": "500+ Holders", "description": "Token has more than 500 unique holders", "default_weight": 2.5},
    {"id": "holder_count_1000", "category": "Holder Distribution", "name": "1000+ Holders", "description": "Token has more than 1,000 unique holders", "default_weight": 3.5},
    {"id": "price_positive_1h", "category": "Momentum", "name": "Positive 1H Price Action", "description": "Price is up in the last hour", "default_weight": 1.5},
    {"id": "price_up_50pct", "category": "Momentum", "name": "Up 50%+ in Last Hour", "description": "Price has increased over 50% in the last hour", "default_weight": 2.0},
    {"id": "buy_sell_ratio", "category": "Momentum", "name": "Buy/Sell Ratio Above 1.5", "description": "Buys outpacing sells by at least 1.5x", "default_weight": 2.0},
    {"id": "buy_sell_ratio_2", "category": "Momentum", "name": "Buy/Sell Ratio Above 2.0", "description": "Buys outpacing sells by at least 2x", "default_weight": 3.0},
    {"id": "volume_above_5k", "category": "Momentum", "name": "Volume Above $5K", "description": "Trading volume exceeds $5,000 in last hour", "default_weight": 1.5},
    {"id": "volume_above_25k", "category": "Momentum", "name": "Volume Above $25K", "description": "Trading volume exceeds $25,000 in last hour", "default_weight": 2.5},
    {"id": "holder_growth", "category": "Momentum", "name": "Holder Count Growing", "description": "Number of holders is actively increasing", "default_weight": 2.0},
    {"id": "age_under_30min", "category": "Token Age", "name": "Under 30 Minutes Old", "description": "Token launched less than 30 minutes ago", "default_weight": 2.0},
    {"id": "age_under_1h", "category": "Token Age", "name": "Under 1 Hour Old", "description": "Token launched less than 1 hour ago", "default_weight": 1.5},
    {"id": "age_over_1h", "category": "Token Age", "name": "Over 1 Hour Old", "description": "Token is more than 1 hour old — has survived initial dump", "default_weight": 1.5},
    {"id": "graduated_pumpfun", "category": "Token Age", "name": "Graduated from Pump.fun", "description": "Token completed the bonding curve and listed on Raydium", "default_weight": 2.5},
    {"id": "has_twitter", "category": "Narrative & Socials", "name": "Has Twitter/X Account", "description": "Token has a linked Twitter or X profile", "default_weight": 1.0},
    {"id": "has_telegram", "category": "Narrative & Socials", "name": "Has Telegram Group", "description": "Token has an active Telegram community", "default_weight": 1.0},
    {"id": "has_website", "category": "Narrative & Socials", "name": "Has Website", "description": "Token has a linked website", "default_weight": 0.5},
    {"id": "full_socials", "category": "Narrative & Socials", "name": "Full Social Presence", "description": "Has Twitter, Telegram, AND website", "default_weight": 2.0},
    {"id": "meme_narrative", "category": "Narrative & Socials", "name": "Strong Meme Narrative", "description": "Token has a clear and trending meme concept", "default_weight": 1.5},
    {"id": "telegram_500", "category": "Narrative & Socials", "name": "Telegram 500+ Members", "description": "Telegram group has more than 500 members", "default_weight": 2.0},
    {"id": "mcap_under_50k", "category": "Market Cap", "name": "Market Cap Under $50K", "description": "Very low market cap — maximum upside potential", "default_weight": 2.0},
    {"id": "mcap_under_500k", "category": "Market Cap", "name": "Market Cap Under $500K", "description": "Low market cap with significant room to grow", "default_weight": 1.5},
    {"id": "mcap_under_1m", "category": "Market Cap", "name": "Market Cap Under $1M", "description": "Sub-million market cap — early stage", "default_weight": 1.0},
    {"id": "risk_under_30", "category": "Risk Scores", "name": "Risk Score Below 30", "description": "Internal risk score is below 30 — low risk", "default_weight": 3.0},
    {"id": "risk_under_50", "category": "Risk Scores", "name": "Risk Score Below 50", "description": "Internal risk score is below 50 — medium risk", "default_weight": 2.0},
    {"id": "moon_above_50", "category": "Risk Scores", "name": "Moon Score Above 50", "description": "Internal moon potential score above 50", "default_weight": 2.0},
    {"id": "moon_above_70", "category": "Risk Scores", "name": "Moon Score Above 70", "description": "Internal moon potential score above 70 — high potential", "default_weight": 3.0},
]

DEGEN_RULE_CATEGORIES = {}
for rule in DEGEN_RULE_LIBRARY:
    DEGEN_RULE_CATEGORIES.setdefault(rule["category"], []).append(rule)


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
    context.user_data["degen_rules"] = []
    context.user_data["degen_mandatory"] = []
    await show_chain_step(update.message, context)


async def show_chain_step(update_or_query, context):
    selected = context.user_data.get("degen_chains", [])

    def btn(code):
        label = DEGEN_CHAINS[code]
        return InlineKeyboardButton(f"{'✅ ' if code in selected else ''}{label}", callback_data=f"dgwiz:chain:{code}")

    keyboard = InlineKeyboardMarkup([
        [btn("SOL"), btn("ETH")],
        [btn("BSC"), btn("BASE")],
        [InlineKeyboardButton("✅ Select All", callback_data="dgwiz:chain:ALL")],
        [InlineKeyboardButton(f"➡️ Next ({len(selected)} selected)" if selected else "➡️ Next", callback_data="dgwiz:chain:DONE")],
        [InlineKeyboardButton("❌ Cancel", callback_data="dgwiz:cancel")],
    ])
    text = (
        "🔗 *Select Chains* (Step 2)\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Choose which chains this model scans.\n"
        "Tap to toggle. Select one or more.\n\n"
        f"✅ Selected: {', '.join(DEGEN_CHAINS[c] for c in selected) if selected else 'None'}"
    )
    if hasattr(update_or_query, "reply_text"):
        await update_or_query.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await update_or_query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def show_strategy_step(query, context):
    await query.message.edit_text(
        "⚡ *Select Strategy* (Step 3)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 Custom", callback_data="dgwiz:strategy:custom")],
            [InlineKeyboardButton("❌ Cancel", callback_data="dgwiz:cancel")],
        ]),
    )


async def show_degen_rule_categories(query, context):
    selected = context.user_data.get("degen_rules", [])
    selected_ids = {r["id"] for r in selected}
    text = (
        "📋 *Select Rules*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Tap a category to see its rules.\n"
        f"✅ Rules selected: {len(selected)}"
    )
    buttons = []
    for cat_name, cat_rules in DEGEN_RULE_CATEGORIES.items():
        selected_in_cat = sum(1 for r in cat_rules if r["id"] in selected_ids)
        total_in_cat = len(cat_rules)
        label = f"✅ {cat_name} ({selected_in_cat}/{total_in_cat})" if selected_in_cat > 0 else f"○ {cat_name} ({total_in_cat})"
        buttons.append([InlineKeyboardButton(label, callback_data=f"dgwiz:rcat:{cat_name}")])
    if selected:
        buttons.append([InlineKeyboardButton(f"✅ Done — {len(selected)} rule(s) selected", callback_data="dgwiz:rules_done")])
    else:
        buttons.append([InlineKeyboardButton("⚠️ Select at least 1 rule", callback_data="dgwiz:rcat:Contract Safety")])
    buttons.append([InlineKeyboardButton("« Back", callback_data="dgwiz:back_to_filters")])
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))


async def show_degen_rules_in_category(query, context, category: str):
    cat_rules = DEGEN_RULE_CATEGORIES.get(category, [])
    selected_ids = {r["id"] for r in context.user_data.get("degen_rules", [])}
    buttons = [[InlineKeyboardButton(f"{'✅' if rule['id'] in selected_ids else '○'} {rule['name']}", callback_data=f"dgwiz:trule:{rule['id']}")] for rule in cat_rules]
    buttons.append([InlineKeyboardButton("« Back to Categories", callback_data="dgwiz:rules_back_cats")])
    await query.message.edit_text(
        f"📋 *{category}*\n━━━━━━━━━━━━━━━━━━━━━━━━\nTap to toggle. ✅ = selected",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def show_degen_mandatory_step(query, context):
    rules = context.user_data.get("degen_rules", [])
    mandatory = set(context.user_data.get("degen_mandatory", []))
    text = (
        "🔒 *Mandatory Rules* (Optional)\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Mark rules as mandatory to require them.\n"
        "If a mandatory rule fails the token is\n"
        "automatically rejected regardless of score.\n\n"
        "🔒 = mandatory   ○ = optional"
    )
    buttons = [[InlineKeyboardButton(f"{'🔒' if rule['id'] in mandatory else '○'} {rule['name']}", callback_data=f"dgwiz:mandatory:{rule['id']}")] for rule in rules]
    buttons.append([InlineKeyboardButton("✅ Done", callback_data="dgwiz:mandatory_done")])
    buttons.append([InlineKeyboardButton("« Back to Rules", callback_data="dgwiz:rules_back_cats")])
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))


async def show_degen_review(query, context):
    name = context.user_data.get("degen_model_name", "Unnamed")
    chains = context.user_data.get("degen_chains", [])
    rules = context.user_data.get("degen_rules", [])
    mandatory = context.user_data.get("degen_mandatory", [])
    min_moon = context.user_data.get("degen_min_moon", 40)
    max_risk = context.user_data.get("degen_max_risk", 70)
    rules_text = "\n".join(f"  {'🔒' if r['id'] in mandatory else '✅'} {r['name']}  [{r['weight']}pts]" for r in rules) or "  None"
    await query.message.edit_text(
        "📋 *Review Degen Model*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ Name:      {name}\n"
        f"🔗 Chains:    {', '.join(DEGEN_CHAINS.get(c, c) for c in chains)}\n"
        f"🚀 Min moon:  {min_moon}\n"
        f"🛡️ Max risk:  {max_risk}\n\n"
        f"📋 *Rules ({len(rules)}):*\n{rules_text}\n\n"
        "Tap Save to activate.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💾 Save Model", callback_data="dgwiz:confirm_save")],
            [InlineKeyboardButton("✏️ Edit Rules", callback_data="dgwiz:rules_back_cats")],
            [InlineKeyboardButton("❌ Cancel", callback_data="dgwiz:cancel")],
        ]),
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
            if not context.user_data.get("degen_chains", []):
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
    elif data.startswith("dgwiz:strategy:"):
        context.user_data["degen_strategy"] = data.split("dgwiz:strategy:")[1]
        await show_degen_rule_categories(query, context)
    elif data.startswith("dgwiz:rcat:"):
        await show_degen_rules_in_category(query, context, data.split("dgwiz:rcat:")[1])
    elif data.startswith("dgwiz:trule:"):
        rule_id = data.split("dgwiz:trule:")[1]
        rule_def = next((r for r in DEGEN_RULE_LIBRARY if r["id"] == rule_id), None)
        if rule_def:
            rules = context.user_data.get("degen_rules", [])
            ids = {r["id"] for r in rules}
            if rule_id in ids:
                rules = [r for r in rules if r["id"] != rule_id]
                await query.answer("○ Removed")
            else:
                rules.append({"id": rule_def["id"], "name": rule_def["name"], "weight": rule_def["default_weight"], "mandatory": False, "category": rule_def["category"], "description": rule_def["description"]})
                await query.answer("✅ Added")
            context.user_data["degen_rules"] = rules
        cat = next((r["category"] for r in DEGEN_RULE_LIBRARY if r["id"] == rule_id), "Contract Safety")
        await show_degen_rules_in_category(query, context, cat)
    elif data == "dgwiz:rules_back_cats":
        await show_degen_rule_categories(query, context)
    elif data == "dgwiz:rules_done":
        if not context.user_data.get("degen_rules", []):
            await query.answer("⚠️ Add at least 1 rule", show_alert=True)
            return
        await show_degen_mandatory_step(query, context)
    elif data.startswith("dgwiz:mandatory:"):
        rule_id = data.split("dgwiz:mandatory:")[1]
        mandatory = set(context.user_data.get("degen_mandatory", []))
        if rule_id in mandatory:
            mandatory.remove(rule_id)
            await query.answer("○ Now optional")
        else:
            mandatory.add(rule_id)
            await query.answer("🔒 Now mandatory")
        context.user_data["degen_mandatory"] = list(mandatory)
        await show_degen_mandatory_step(query, context)
    elif data == "dgwiz:mandatory_done":
        await show_degen_review(query, context)
    elif data == "dgwiz:back_to_filters":
        await show_strategy_step(query, context)
    elif data == "dgwiz:confirm_save":
        await handle_degen_confirm_save(update, context)
    elif data == "dgwiz:cancel":
        await handle_degen_cancel(update, context)


async def handle_degen_confirm_save(update, context):
    query = update.callback_query
    await query.answer("Saving...")
    try:
        model_id = context.user_data.get("degen_model_id") or f"degen_{int(time.time())}"
        rules = context.user_data.get("degen_rules", [])
        mandatory = context.user_data.get("degen_mandatory", [])
        chains = context.user_data.get("degen_chains", ["SOL"])
        name = context.user_data.get("degen_model_name", "Unnamed")
        if not rules:
            await query.answer("❌ No rules selected", show_alert=True)
            return
        max_score = sum(r.get("weight", 1.0) for r in rules)
        threshold = context.user_data.get("degen_min_score", 50)
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
            "min_score": round((threshold / 100) * max_score, 2),
            "status": "active",
        }
        db.save_degen_model(model)
        for key in [k for k in list(context.user_data) if k.startswith("degen_")]:
            context.user_data.pop(key, None)
        context.user_data.pop("in_conversation", None)
        await query.message.edit_text(
            f"✅ *Degen Model Saved*\n━━━━━━━━━━━━━━━━━━━━━━━━\n⚙️ {name}\n🔗 Chains:  {', '.join(DEGEN_CHAINS.get(c, c) for c in chains)}\n📋 Rules:   {len(rules)}\n🚀 Min moon: {model['min_moon_score']}\n🛡️ Max risk: {model['max_risk_score']}\n\nModel is active and scanning now.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Degen Models", callback_data="nav:degen_models")],
                [InlineKeyboardButton("🎰 Degen Home", callback_data="nav:degen_home")],
            ]),
        )
    except Exception as e:
        log.error(f"Degen save failed: {type(e).__name__}: {e}")
        await query.message.edit_text(
            f"❌ *Save failed*\n\n`{type(e).__name__}: {str(e)[:200]}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Retry", callback_data="dgwiz:confirm_save")]]),
        )


async def handle_degen_cancel(update, context):
    q = update.callback_query
    if q:
        await q.answer()
        await q.message.edit_text("❌ Degen wizard cancelled")
    for key in [k for k in list(context.user_data) if k.startswith("degen_")]:
        context.user_data.pop(key, None)
    context.user_data.pop("in_conversation", None)
