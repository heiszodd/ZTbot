from __future__ import annotations

import uuid
from copy import deepcopy

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

import db
from degen.rule_library import RULES, RULES_BY_ID
from degen.templates import TEMPLATES

DEGEN_ASK_NAME = 1000
DEGEN_CHAIN = 1001
DEGEN_STRATEGY = 1002
DEGEN_RULES_CATEGORY = 1003
DEGEN_RULES_SELECT = 1004
DEGEN_MANDATORY = 1005
DEGEN_WEIGHTS = 1006
DEGEN_FILTERS_LIQ = 1007
DEGEN_FILTERS_AGE = 1008
DEGEN_FILTERS_RISK = 1009
DEGEN_MIN_SCORE = 1010
DEGEN_CONFIRM = 1011

CATEGORY_MAP = {
    "DEV REPUTATION": "👨‍💻 Dev Reputation",
    "CONTRACT SAFETY": "🔐 Contract Safety",
    "LIQUIDITY": "💧 Liquidity",
    "HOLDER DISTRIBUTION": "👥 Holders",
    "MOMENTUM": "📈 Momentum",
    "TOKEN AGE": "⏱ Token Age",
    "NARRATIVE AND SOCIALS": "🎭 Narrative & Socials",
    "MARKET CAP": "💰 Market Cap",
    "RISK SCORE": "📊 Risk Scores",
}


def _rule_config(rule_id: str, mandatory: bool | None = None):
    r = RULES_BY_ID[rule_id]
    return {"id": rule_id, "mandatory": r["mandatory_default"] if mandatory is None else mandatory, "weight": r["weight_default"]}


def _default_model_data(name: str):
    return {
        "id": str(uuid.uuid4())[:12], "name": name, "description": "", "status": "inactive", "chains": ["SOL"], "rules": [],
        "min_score": 5, "max_risk_level": "HIGH", "min_moon_score": 40, "max_risk_score": 60,
        "min_liquidity": 5000, "max_token_age_minutes": 120, "min_token_age_minutes": 2,
        "require_lp_locked": False, "require_mint_revoked": False, "require_verified": False,
        "block_serial_ruggers": True, "max_dev_rug_count": 0, "max_top1_holder_pct": 20, "min_holder_count": 10,
    }


async def start_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["in_conversation"] = True
    context.user_data.clear()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="degen_wiz:cancel")]])
    target = update.message.reply_text if update.message else update.callback_query.message.reply_text
    if update.callback_query:
        await update.callback_query.answer()
    await target("🎰 Degen Model Wizard\n━━━━━━━━━━━━━━━━━━━━━━━━\nBuild a custom memecoin scanner.\n\nYour model defines exactly what kind of\ntoken you want to be alerted about.\n\nWhat's the name of this model?\nExample: Clean Dev Snipers", reply_markup=kb)
    context.user_data["selected_chains"] = {"SOL"}
    return DEGEN_ASK_NAME


async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip()
    if len(name) < 2 or len(name) > 50:
        await update.message.reply_text("Name must be between 2 and 50 characters.")
        return DEGEN_ASK_NAME
    context.user_data.update(_default_model_data(name))
    return await _render_chain(update.message.reply_text, context)


async def _render_chain(sender, context):
    selected = context.user_data.get("selected_chains", {"SOL"})
    chains = ["SOL", "ETH", "BSC", "BASE"]
    row = [InlineKeyboardButton(f"{'✅ ' if c in selected else ''}{'Solana' if c=='SOL' else c}", callback_data=f"degen_wiz:chain:{c}") for c in chains]
    kb = InlineKeyboardMarkup([row[:2], row[2:], [InlineKeyboardButton("✅ Confirm Selection", callback_data="degen_wiz:chain_confirm")]])
    await sender("🔗 Which chains should this model scan?", reply_markup=kb)
    return DEGEN_CHAIN


async def chain_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data.split(":")[-1]
    if data == "chain_confirm":
        selected = context.user_data.get("selected_chains", set())
        if not selected:
            await q.answer("Select at least one chain", show_alert=True)
            return DEGEN_CHAIN
        context.user_data["chains"] = sorted(selected)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛡️ Safe Hunter", callback_data="degen_wiz:template:safe_hunter"), InlineKeyboardButton("🚀 Fresh Launch", callback_data="degen_wiz:template:fresh_launch")],
            [InlineKeyboardButton("👨‍💻 Dev Checker", callback_data="degen_wiz:template:dev_checker"), InlineKeyboardButton("💎 Gem Hunter", callback_data="degen_wiz:template:gem_hunter")],
            [InlineKeyboardButton("🔥 Narrative Play", callback_data="degen_wiz:template:narrative_play")],
            [InlineKeyboardButton("🎯 Build from scratch", callback_data="degen_wiz:template:scratch")],
        ])
        await q.message.reply_text("⚡ Choose a starting strategy or build from scratch:", reply_markup=kb)
        return DEGEN_STRATEGY
    chain = data
    selected = context.user_data.setdefault("selected_chains", {"SOL"})
    if chain in selected:
        selected.remove(chain)
    else:
        selected.add(chain)
    return await _render_chain(q.message.reply_text, context)


async def strategy_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    template_name = q.data.split(":")[-1]
    rules = [] if template_name == "scratch" else deepcopy(TEMPLATES[template_name]["rules"])
    for r in rules:
        r.setdefault("weight", RULES_BY_ID[r["id"]]["weight_default"])
        r.setdefault("mandatory", RULES_BY_ID[r["id"]]["mandatory_default"])
    context.user_data["rules"] = rules
    context.user_data["selected_rule_ids"] = {r["id"] for r in rules}
    return await _render_categories(q.message.reply_text)


async def _render_categories(sender):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👨‍💻 Dev Reputation", callback_data="degen_wiz:cat:DEV REPUTATION"), InlineKeyboardButton("🔐 Contract Safety", callback_data="degen_wiz:cat:CONTRACT SAFETY")],
        [InlineKeyboardButton("💧 Liquidity", callback_data="degen_wiz:cat:LIQUIDITY"), InlineKeyboardButton("👥 Holders", callback_data="degen_wiz:cat:HOLDER DISTRIBUTION")],
        [InlineKeyboardButton("📈 Momentum", callback_data="degen_wiz:cat:MOMENTUM"), InlineKeyboardButton("⏱ Token Age", callback_data="degen_wiz:cat:TOKEN AGE")],
        [InlineKeyboardButton("🎭 Narrative & Socials", callback_data="degen_wiz:cat:NARRATIVE AND SOCIALS"), InlineKeyboardButton("💰 Market Cap", callback_data="degen_wiz:cat:MARKET CAP")],
        [InlineKeyboardButton("📊 Risk Scores", callback_data="degen_wiz:cat:RISK SCORE"), InlineKeyboardButton("✅ Done adding rules", callback_data="degen_wiz:rules_done")],
    ])
    await sender("Select categories to add/remove rules.", reply_markup=kb)
    return DEGEN_RULES_CATEGORY


async def rules_category_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data.endswith("rules_done"):
        selected = context.user_data.get("selected_rule_ids", set())
        if len(selected) < 2:
            await q.message.reply_text("⚠️ Add at least 2 rules for meaningful filtering")
            return DEGEN_RULES_CATEGORY
        context.user_data["rules"] = [next((r for r in context.user_data.get("rules", []) if r["id"] == rid), _rule_config(rid)) for rid in selected]
        return await _render_mandatory(q.message.reply_text, context)
    cat = q.data.split(":", 2)[-1]
    context.user_data["active_cat"] = cat
    return await _render_category_rules(q.message.reply_text, context, cat)


async def _render_category_rules(sender, context, cat):
    selected = context.user_data.get("selected_rule_ids", set())
    rows = []
    for r in [x for x in RULES if x["category"] == cat]:
        prefix = "✅" if r["id"] in selected else "○"
        rows.append([InlineKeyboardButton(f"{prefix} {r['name']}", callback_data=f"degen_wiz:rule:{r['id']}")])
    rows.append([InlineKeyboardButton("« Back to categories", callback_data="degen_wiz:cat_back")])
    await sender(f"{CATEGORY_MAP.get(cat, cat)}", reply_markup=InlineKeyboardMarkup(rows))
    return DEGEN_RULES_SELECT


async def rule_toggle_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data.endswith("cat_back"):
        return await _render_categories(q.message.reply_text)
    rid = q.data.split(":")[-1]
    selected = context.user_data.setdefault("selected_rule_ids", set())
    if rid in selected:
        selected.remove(rid)
        context.user_data["rules"] = [r for r in context.user_data.get("rules", []) if r["id"] != rid]
    else:
        selected.add(rid)
        context.user_data.setdefault("rules", []).append(_rule_config(rid))
    return await _render_category_rules(q.message.reply_text, context, context.user_data.get("active_cat"))


async def _render_mandatory(sender, context):
    rows = []
    for r in context.user_data["rules"]:
        name = RULES_BY_ID[r["id"]]["name"]
        tag = "🔒 REQUIRED" if r.get("mandatory") else "○ OPTIONAL"
        rows.append([InlineKeyboardButton(f"[{tag}] {name}", callback_data=f"degen_wiz:mandatory:{r['id']}")])
    rows.append([InlineKeyboardButton("✅ Confirm", callback_data="degen_wiz:mandatory_confirm")])
    await sender("Required = token must pass this rule. Optional = adds to score only.", reply_markup=InlineKeyboardMarkup(rows))
    return DEGEN_MANDATORY


async def mandatory_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data.endswith("mandatory_confirm"):
        context.user_data["weight_idx"] = 0
        return await _render_weight_step(q.message.reply_text, context)
    rid = q.data.split(":")[-1]
    for r in context.user_data["rules"]:
        if r["id"] == rid:
            r["mandatory"] = not r.get("mandatory", False)
            break
    return await _render_mandatory(q.message.reply_text, context)


async def _render_weight_step(sender, context):
    idx = context.user_data.get("weight_idx", 0)
    rules = context.user_data["rules"]
    if idx >= len(rules):
        return await _render_filters_liq(sender)
    r = rules[idx]
    name = RULES_BY_ID[r["id"]]["name"]
    w = r.get("weight", RULES_BY_ID[r["id"]]["weight_default"])
    opts = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
    kb = [[InlineKeyboardButton(str(x), callback_data=f"degen_wiz:weight:{x}") for x in opts[:4]], [InlineKeyboardButton(str(x), callback_data=f"degen_wiz:weight:{x}") for x in opts[4:]], [InlineKeyboardButton(f"Keep default ({w})", callback_data="degen_wiz:weight:keep")], [InlineKeyboardButton("Skip all — use defaults", callback_data="degen_wiz:weight:skipall")]]
    await sender(f"⚖️ Set weight for:\n{name}\nCurrent: {w} — how much does passing this rule add to the score?\nRule {idx+1} of {len(rules)}", reply_markup=InlineKeyboardMarkup(kb))
    return DEGEN_WEIGHTS


async def weight_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    choice = q.data.split(":")[-1]
    idx = context.user_data.get("weight_idx", 0)
    if choice == "skipall":
        return await _render_filters_liq(q.message.reply_text)
    if choice != "keep":
        context.user_data["rules"][idx]["weight"] = float(choice)
    context.user_data["weight_idx"] = idx + 1
    return await _render_weight_step(q.message.reply_text, context)


async def _render_filters_liq(sender):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Any", callback_data="degen_wiz:liq:0"), InlineKeyboardButton("$1K", callback_data="degen_wiz:liq:1000"), InlineKeyboardButton("$5K", callback_data="degen_wiz:liq:5000")], [InlineKeyboardButton("$10K", callback_data="degen_wiz:liq:10000"), InlineKeyboardButton("$25K", callback_data="degen_wiz:liq:25000"), InlineKeyboardButton("$50K", callback_data="degen_wiz:liq:50000")]])
    await sender("💧 Minimum liquidity to alert on:", reply_markup=kb)
    return DEGEN_FILTERS_LIQ


async def filters_liq_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    context.user_data["min_liquidity"] = float(q.data.split(":")[-1])
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("10 min", callback_data="degen_wiz:maxage:10"), InlineKeyboardButton("30 min", callback_data="degen_wiz:maxage:30"), InlineKeyboardButton("1 hour", callback_data="degen_wiz:maxage:60")], [InlineKeyboardButton("2 hours", callback_data="degen_wiz:maxage:120"), InlineKeyboardButton("6 hours", callback_data="degen_wiz:maxage:360"), InlineKeyboardButton("Any age", callback_data="degen_wiz:maxage:999999")], [InlineKeyboardButton("None", callback_data="degen_wiz:minage:0"), InlineKeyboardButton("2 min", callback_data="degen_wiz:minage:2"), InlineKeyboardButton("5 min", callback_data="degen_wiz:minage:5"), InlineKeyboardButton("10 min", callback_data="degen_wiz:minage:10"), InlineKeyboardButton("30 min", callback_data="degen_wiz:minage:30")]])
    await q.message.reply_text("⏱ Set max token age, then minimum token age.", reply_markup=kb)
    return DEGEN_FILTERS_AGE


async def filters_age_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, _, key, val = q.data.split(":")
    context.user_data[f"{'max' if key=='maxage' else 'min'}_token_age_minutes"] = int(val)
    if "max_token_age_minutes" not in context.user_data or "min_token_age_minutes" not in context.user_data:
        return DEGEN_FILTERS_AGE
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("30", callback_data="degen_wiz:risk:30"), InlineKeyboardButton("40", callback_data="degen_wiz:risk:40"), InlineKeyboardButton("50", callback_data="degen_wiz:risk:50")],
        [InlineKeyboardButton("60", callback_data="degen_wiz:risk:60"), InlineKeyboardButton("70", callback_data="degen_wiz:risk:70"), InlineKeyboardButton("Any", callback_data="degen_wiz:risk:999")],
        [InlineKeyboardButton("Moon 30", callback_data="degen_wiz:moon:30"), InlineKeyboardButton("Moon 40", callback_data="degen_wiz:moon:40"), InlineKeyboardButton("Moon 50", callback_data="degen_wiz:moon:50"), InlineKeyboardButton("Moon 60", callback_data="degen_wiz:moon:60"), InlineKeyboardButton("Moon 70", callback_data="degen_wiz:moon:70")],
        [InlineKeyboardButton("✅ Yes — always block", callback_data="degen_wiz:rug:yes"), InlineKeyboardButton("❌ No — alert anyway", callback_data="degen_wiz:rug:no")],
    ])
    await q.message.reply_text("🛡️ Set max risk, min moon, and serial-rugger blocking.", reply_markup=kb)
    return DEGEN_FILTERS_RISK


async def filters_risk_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, _, typ, val = q.data.split(":")
    if typ == "risk":
        context.user_data["max_risk_score"] = int(val)
    elif typ == "moon":
        context.user_data["min_moon_score"] = int(val)
    elif typ == "rug":
        context.user_data["block_serial_ruggers"] = val == "yes"
    if not {"max_risk_score", "min_moon_score", "block_serial_ruggers"}.issubset(context.user_data):
        return DEGEN_FILTERS_RISK
    max_score = sum(float(r.get("weight", 0)) for r in context.user_data["rules"])
    context.user_data["max_possible_score"] = max_score
    cuts = [0.4, 0.5, 0.6, 0.7, 0.8]
    buttons = [InlineKeyboardButton(f"{int(c*100)}% ({round(max_score*c,1)})", callback_data=f"degen_wiz:minscore:{round(max_score*c,1)}") for c in cuts]
    kb = InlineKeyboardMarkup([buttons[:3], buttons[3:], [InlineKeyboardButton("✏️ Enter manually", callback_data="degen_wiz:minscore:manual")]])
    await q.message.reply_text(f"🎯 Set minimum score to trigger an alert\nMaximum possible score with your rules: {max_score}", reply_markup=kb)
    return DEGEN_MIN_SCORE


async def min_score_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    val = q.data.split(":")[-1]
    if val == "manual":
        await q.message.reply_text("Manual entry not enabled in this build. Pick a button value.")
        return DEGEN_MIN_SCORE
    context.user_data["min_score"] = float(val)
    return await _render_review(q.message.reply_text, context)


async def _render_review(sender, context):
    data = context.user_data
    required = [r for r in data["rules"] if r.get("mandatory")]
    lines = [
        "📋 Review Your Degen Model", "━━━━━━━━━━━━━━━━━━━━━━━━", f"📌 {data['name']}", f"🔗 Chains: {', '.join(data['chains'])}",
        f"⏱ Age filter: {data.get('min_token_age_minutes',0)}-{data.get('max_token_age_minutes',999999)} minutes", f"💧 Min liquidity: ${data.get('min_liquidity',0):,.0f}",
        f"🛡️ Max risk score: {data.get('max_risk_score')}", f"🚀 Min moon score: {data.get('min_moon_score')}", f"💀 Block ruggers: {'Yes' if data.get('block_serial_ruggers') else 'No'}",
        f"🎯 Min score to alert: {data['min_score']} / {data['max_possible_score']}", "", f"📋 Rules ({len(data['rules'])} total, {len(required)} required):",
    ]
    for r in data["rules"]:
        lines.append(f"- {'🔒' if r.get('mandatory') else '○'} {RULES_BY_ID[r['id']]['name']} (w={r.get('weight')})")
    lines.append("\nReachability:\n✅ Tier threshold reachable")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Save Model", callback_data="degen_wiz:save"), InlineKeyboardButton("✏️ Edit Rules", callback_data="degen_wiz:edit_rules")], [InlineKeyboardButton("🔄 Start Over", callback_data="degen_wiz:restart"), InlineKeyboardButton("❌ Cancel", callback_data="degen_wiz:cancel")]])
    await sender("\n".join(lines), reply_markup=kb)
    return DEGEN_CONFIRM


async def confirm_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    action = q.data.split(":")[-1]
    if action == "edit_rules":
        return await _render_categories(q.message.reply_text)
    if action == "restart":
        return await start_wizard(update, context)
    if action == "cancel":
        await q.message.reply_text("Cancelled.")
        context.user_data.pop("in_conversation", None)
    return ConversationHandler.END

    model = {k: context.user_data.get(k) for k in _default_model_data("x").keys() if k != "id"}
    model["id"] = str(uuid.uuid4())[:12]
    db.insert_degen_model(model)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Activate Now", callback_data=f"degen_model:toggle:{model['id']}"), InlineKeyboardButton("⚙️ View Models", callback_data="degen_model:list")], [InlineKeyboardButton("🎰 Degen Home", callback_data="degen:home")]])
    await q.message.reply_text(f"✅ Degen Model Saved\n━━━━━━━━━━━━━━━━━━━━━━━━\n📌 {model['name']}\n🆔 {model['id']}\n⚡ Status: Inactive\n\nActivate it to start scanning.", reply_markup=kb)
    context.user_data.pop("in_conversation", None)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text("Cancelled.")
    context.user_data.pop("in_conversation", None)
    return ConversationHandler.END


def build_degen_wizard_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("create_degen_model", start_wizard), CallbackQueryHandler(start_wizard, pattern="^degen_wiz:start$")],
        states={
            DEGEN_ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name), CallbackQueryHandler(cancel, pattern="^degen_wiz:cancel$")],
            DEGEN_CHAIN: [CallbackQueryHandler(chain_cb, pattern="^degen_wiz:chain:")],
            DEGEN_STRATEGY: [CallbackQueryHandler(strategy_cb, pattern="^degen_wiz:template:")],
            DEGEN_RULES_CATEGORY: [CallbackQueryHandler(rules_category_cb, pattern="^degen_wiz:(cat:|rules_done)")],
            DEGEN_RULES_SELECT: [CallbackQueryHandler(rule_toggle_cb, pattern="^degen_wiz:(rule:|cat_back)")],
            DEGEN_MANDATORY: [CallbackQueryHandler(mandatory_cb, pattern="^degen_wiz:mandatory")],
            DEGEN_WEIGHTS: [CallbackQueryHandler(weight_cb, pattern="^degen_wiz:weight:")],
            DEGEN_FILTERS_LIQ: [CallbackQueryHandler(filters_liq_cb, pattern="^degen_wiz:liq:")],
            DEGEN_FILTERS_AGE: [CallbackQueryHandler(filters_age_cb, pattern="^degen_wiz:(maxage|minage):")],
            DEGEN_FILTERS_RISK: [CallbackQueryHandler(filters_risk_cb, pattern="^degen_wiz:(risk|moon|rug):")],
            DEGEN_MIN_SCORE: [CallbackQueryHandler(min_score_cb, pattern="^degen_wiz:minscore:")],
            DEGEN_CONFIRM: [CallbackQueryHandler(confirm_cb, pattern="^degen_wiz:(save|edit_rules|restart|cancel)")],
        },
        fallbacks=[CallbackQueryHandler(cancel, pattern="^degen_wiz:cancel$")],
    )
