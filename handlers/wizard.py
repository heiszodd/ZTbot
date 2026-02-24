import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

import db
from config import CHAT_ID, SUPPORTED_PAIRS, SUPPORTED_SESSIONS, SUPPORTED_TIMEFRAMES
from formatters import fmt_bias

log = logging.getLogger(__name__)

(
    WIZARD_NAME,
    WIZARD_PAIR,
    WIZARD_TF,
    WIZARD_SESSION,
    WIZARD_BIAS,
    WIZARD_RULES,
    WIZARD_WEIGHTS,
    WIZARD_PHASE_ASSIGN,
    WIZARD_PHASE_CONFIG,
    WIZARD_REVIEW,
) = range(10)

PERPS_RULE_LIBRARY = [
    {"id": "htf_bullish", "category": "Trend", "name": "HTF Trend Bullish", "description": "Higher timeframe (4H/1D) trend is bullish", "default_weight": 3.0},
    {"id": "htf_bearish", "category": "Trend", "name": "HTF Trend Bearish", "description": "Higher timeframe (4H/1D) trend is bearish", "default_weight": 3.0},
    {"id": "ltf_bullish_structure", "category": "Trend", "name": "LTF Structure Bullish", "description": "Lower timeframe making higher highs and higher lows", "default_weight": 2.5},
    {"id": "ltf_bearish_structure", "category": "Trend", "name": "LTF Structure Bearish", "description": "Lower timeframe making lower highs and lower lows", "default_weight": 2.5},
    {"id": "htf_ltf_aligned_bull", "category": "Trend", "name": "HTF/LTF Aligned Bullish", "description": "Both higher and lower timeframes are bullish", "default_weight": 3.5},
    {"id": "htf_ltf_aligned_bear", "category": "Trend", "name": "HTF/LTF Aligned Bearish", "description": "Both higher and lower timeframes are bearish", "default_weight": 3.5},
    {"id": "bullish_ob_present", "category": "Order Blocks", "name": "Bullish OB Present", "description": "A fresh unmitigated bullish order block is in play", "default_weight": 2.5},
    {"id": "bearish_ob_present", "category": "Order Blocks", "name": "Bearish OB Present", "description": "A fresh unmitigated bearish order block is in play", "default_weight": 2.5},
    {"id": "ob_respected", "category": "Order Blocks", "name": "OB Being Respected", "description": "Price is reacting to the order block with rejection", "default_weight": 2.0},
    {"id": "breaker_block", "category": "Order Blocks", "name": "Breaker Block", "description": "A broken OB is being retested as a breaker", "default_weight": 2.5},
    {"id": "ob_on_htf", "category": "Order Blocks", "name": "OB on HTF", "description": "Order block exists on the higher timeframe", "default_weight": 3.0},
    {"id": "bullish_fvg", "category": "Fair Value Gaps", "name": "Bullish FVG Present", "description": "Open bullish fair value gap acting as support", "default_weight": 2.0},
    {"id": "bearish_fvg", "category": "Fair Value Gaps", "name": "Bearish FVG Present", "description": "Open bearish fair value gap acting as resistance", "default_weight": 2.0},
    {"id": "fvg_within_ob", "category": "Fair Value Gaps", "name": "FVG Within OB", "description": "FVG is nested inside an order block — double confluence", "default_weight": 2.5},
    {"id": "nested_fvg", "category": "Fair Value Gaps", "name": "Nested FVG (LTF inside HTF)", "description": "LTF FVG is nested within a HTF FVG", "default_weight": 3.0},
    {"id": "liquidity_swept_bull", "category": "Liquidity", "name": "Buy-Side Liquidity Swept", "description": "Equal highs or prior swing highs swept before reversal", "default_weight": 3.0},
    {"id": "liquidity_swept_bear", "category": "Liquidity", "name": "Sell-Side Liquidity Swept", "description": "Equal lows or prior swing lows swept before reversal", "default_weight": 3.0},
    {"id": "asian_range_swept", "category": "Liquidity", "name": "Asian Range Swept", "description": "London session swept Asian session high or low", "default_weight": 2.5},
    {"id": "stop_hunt", "category": "Liquidity", "name": "Stop Hunt Confirmed", "description": "Wick below/above key level then strong reversal close", "default_weight": 3.0},
    {"id": "mss_bullish", "category": "Market Structure", "name": "Bullish MSS Confirmed", "description": "Market structure shift to bullish on entry timeframe", "default_weight": 3.0},
    {"id": "mss_bearish", "category": "Market Structure", "name": "Bearish MSS Confirmed", "description": "Market structure shift to bearish on entry timeframe", "default_weight": 3.0},
    {"id": "bos_bullish", "category": "Market Structure", "name": "Bullish BOS", "description": "Break of structure to the upside", "default_weight": 2.0},
    {"id": "bos_bearish", "category": "Market Structure", "name": "Bearish BOS", "description": "Break of structure to the downside", "default_weight": 2.0},
    {"id": "choch_bullish", "category": "Market Structure", "name": "Bullish CHoCH", "description": "Change of character to bullish — early reversal signal", "default_weight": 2.5},
    {"id": "choch_bearish", "category": "Market Structure", "name": "Bearish CHoCH", "description": "Change of character to bearish — early reversal signal", "default_weight": 2.5},
    {"id": "session_london", "category": "Sessions", "name": "London Session Active", "description": "Trade is taken during London session (07:00-16:00 UTC)", "default_weight": 1.5},
    {"id": "session_ny", "category": "Sessions", "name": "NY Session Active", "description": "Trade is taken during New York session (13:00-22:00 UTC)", "default_weight": 1.5},
    {"id": "session_overlap", "category": "Sessions", "name": "London/NY Overlap", "description": "Highest volume period — both sessions active", "default_weight": 2.0},
    {"id": "london_open_sweep", "category": "Sessions", "name": "London Open Sweep", "description": "London swept Asian lows/highs within first hour", "default_weight": 2.5},
    {"id": "ny_open_reversal", "category": "Sessions", "name": "NY Open Reversal", "description": "NY open reversed the London session direction", "default_weight": 2.5},
    {"id": "premium_zone", "category": "Price Context", "name": "Price in Premium Zone", "description": "Price is above the equilibrium of the range — favour shorts", "default_weight": 1.5},
    {"id": "discount_zone", "category": "Price Context", "name": "Price in Discount Zone", "description": "Price is below the equilibrium of the range — favour longs", "default_weight": 1.5},
    {"id": "equilibrium", "category": "Price Context", "name": "Price at Equilibrium (50%)", "description": "Price is at the midpoint of the range", "default_weight": 1.0},
    {"id": "near_htf_level", "category": "Price Context", "name": "Near Major HTF Level", "description": "Price within 0.5% of a key weekly or monthly level", "default_weight": 2.5},
    {"id": "bullish_engulfing", "category": "Candle Patterns", "name": "Bullish Engulfing", "description": "Large bullish candle engulfs previous bearish candle", "default_weight": 1.5},
    {"id": "bearish_engulfing", "category": "Candle Patterns", "name": "Bearish Engulfing", "description": "Large bearish candle engulfs previous bullish candle", "default_weight": 1.5},
    {"id": "pin_bar_bull", "category": "Candle Patterns", "name": "Bullish Pin Bar", "description": "Long lower wick rejection showing strong buying", "default_weight": 1.5},
    {"id": "pin_bar_bear", "category": "Candle Patterns", "name": "Bearish Pin Bar", "description": "Long upper wick rejection showing strong selling", "default_weight": 1.5},
    {"id": "doji_rejection", "category": "Candle Patterns", "name": "Doji at Key Level", "description": "Indecision candle at a significant level", "default_weight": 1.0},
    {"id": "volume_spike", "category": "Volume", "name": "Volume Spike", "description": "Volume significantly above 20-period average", "default_weight": 1.5},
    {"id": "volume_declining_pullback", "category": "Volume", "name": "Volume Declining on Pullback", "description": "Volume dropping as price retraces — weak pullback", "default_weight": 1.5},
    {"id": "volume_expanding_breakout", "category": "Volume", "name": "Volume Expanding on Breakout", "description": "Volume increasing as price breaks a level", "default_weight": 2.0},
    {"id": "ote_zone", "category": "ICT Concepts", "name": "OTE Zone (61.8-79%)", "description": "Price in the Optimal Trade Entry retracement zone", "default_weight": 2.5},
    {"id": "power_of_three", "category": "ICT Concepts", "name": "Power of Three Setup", "description": "Accumulation, manipulation, and distribution pattern", "default_weight": 3.0},
    {"id": "judas_swing", "category": "ICT Concepts", "name": "Judas Swing", "description": "False move against bias before true direction", "default_weight": 2.5},
    {"id": "silver_bullet_window", "category": "ICT Concepts", "name": "Silver Bullet Window", "description": "Entry taken during 10-11AM or 2-3PM NY time window", "default_weight": 2.0},
    {"id": "midnight_open", "category": "ICT Concepts", "name": "Midnight Open Level", "description": "Price returning to the midnight NY open reference level", "default_weight": 2.0},
    {"id": "three_confluences", "category": "Confluence", "name": "Minimum 3 Confluences", "description": "At least 3 independent factors confirm the setup", "default_weight": 2.0},
    {"id": "news_clear", "category": "Confluence", "name": "No High Impact News", "description": "No major news event in the next 30 minutes", "default_weight": 1.5},
    {"id": "higher_high_confirmation", "category": "Confluence", "name": "Previous High Broken (Bull)", "description": "Price has broken above the previous significant high", "default_weight": 2.0},
    {"id": "lower_low_confirmation", "category": "Confluence", "name": "Previous Low Broken (Bear)", "description": "Price has broken below the previous significant low", "default_weight": 2.0},
]

PERPS_RULE_CATEGORIES = {}
for rule in PERPS_RULE_LIBRARY:
    PERPS_RULE_CATEGORIES.setdefault(rule["category"], []).append(rule)


@require_auth
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


@require_auth
async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["model_name"] = (update.message.text or "").strip()
    buttons = [[InlineKeyboardButton(p, callback_data=f"wizard:pair:{p}") for p in SUPPORTED_PAIRS[i:i + 3]] for i in range(0, len(SUPPORTED_PAIRS), 3)]
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="wizard:cancel")])
    await update.message.reply_text("🪙 Select pair", reply_markup=InlineKeyboardMarkup(buttons))
    return WIZARD_PAIR


async def show_rule_categories(query, context):
    selected_rules = context.user_data.get("model_rules", [])
    selected_ids = {r["id"] for r in selected_rules}
    total_selected = len(selected_rules)
    text = (
        "📋 *Add Rules* (Step 6)\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Select rules from each category.\n"
        "Tap a category to see its rules.\n\n"
        f"✅ Rules selected: {total_selected}"
    )
    buttons = []
    for cat_name, cat_rules in PERPS_RULE_CATEGORIES.items():
        selected_in_cat = sum(1 for r in cat_rules if r["id"] in selected_ids)
        total_in_cat = len(cat_rules)
        label = f"✅ {cat_name} ({selected_in_cat}/{total_in_cat})" if selected_in_cat > 0 else f"○ {cat_name} ({total_in_cat})"
        buttons.append([InlineKeyboardButton(label, callback_data=f"wizard:rules_cat:{cat_name}")])
    if total_selected > 0:
        buttons.append([InlineKeyboardButton(f"✅ Done — {total_selected} rule(s) selected", callback_data="wizard:rules_done")])
    else:
        buttons.append([InlineKeyboardButton("⚠️ Select at least 1 rule", callback_data="wizard:rules_cat:Trend")])
    buttons.append([InlineKeyboardButton("« Back", callback_data="wizard:back_to_session")])
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))


async def show_rules_in_category(query, context, category: str):
    cat_rules = PERPS_RULE_CATEGORIES.get(category, [])
    selected_ids = {r["id"] for r in context.user_data.get("model_rules", [])}
    text = (
        f"📋 *{category} Rules*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Tap to toggle rules on/off.\n"
        "✅ = selected   ○ = not selected"
    )
    buttons = [[InlineKeyboardButton(f"{'✅' if rule['id'] in selected_ids else '○'} {rule['name']}", callback_data=f"wizard:toggle_rule:{rule['id']}")] for rule in cat_rules]
    buttons.append([InlineKeyboardButton("« Back to Categories", callback_data="wizard:rules_back_to_cats")])
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))


async def show_weights_step(query, context):
    rules = context.user_data.get("model_rules", [])
    text = (
        "⚖️ *Rule Weights* (Step 7)\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Tap a rule to adjust its weight.\n"
        "Higher weight = more impact on score.\n\n"
        "Current rules and weights:"
    )
    buttons = [[InlineKeyboardButton(f"⚖️ {rule['name']}  [{rule['weight']}pts]", callback_data=f"wizard:weight_rule:{rule['id']}")] for rule in rules]
    buttons.append([InlineKeyboardButton("✅ Done — proceed to review", callback_data="wizard:weights_done")])
    buttons.append([InlineKeyboardButton("« Back to Rules", callback_data="wizard:rules")])
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))


async def show_weight_picker(query, context, rule_id: str):
    rule = next((r for r in context.user_data.get("model_rules", []) if r["id"] == rule_id), None)
    if not rule:
        await query.answer("Rule not found")
        return
    buttons, weight_row = [], []
    for w in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]:
        marker = "✅" if rule["weight"] == w else ""
        weight_row.append(InlineKeyboardButton(f"{marker}{w}", callback_data=f"wizard:set_weight:{rule_id}:{w}"))
        if len(weight_row) == 4:
            buttons.append(weight_row)
            weight_row = []
    if weight_row:
        buttons.append(weight_row)
    buttons.append([InlineKeyboardButton("« Back to Weights", callback_data="wizard:weights")])
    await query.message.edit_text(
        f"⚖️ *{rule['name']}*\nCurrent weight: {rule['weight']} pts\n\nSelect new weight:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def show_model_review(query, context):
    name = context.user_data.get("model_name", "Unnamed")
    pair = context.user_data.get("model_pair", "BTCUSDT")
    tf = context.user_data.get("model_timeframe", "1h")
    session = context.user_data.get("model_session", "Any")
    bias = context.user_data.get("model_bias", "Both")
    rules = context.user_data.get("model_rules", [])
    max_score = sum(r.get("weight", 1.0) for r in rules)
    rules_text = "\n".join(f"  {'🔒' if r.get('mandatory') else '✅'} {r['name']}  [{r['weight']}pts]" for r in rules) or "  None"
    text = (
        "📋 *Review Your Model*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ Name:      {name}\n"
        f"🪙 Pair:      {pair}\n"
        f"⏱ Timeframe: {tf}\n"
        f"🕐 Session:   {session}\n"
        f"📊 Bias:      {fmt_bias(bias)}\n\n"
        f"📋 *Rules ({len(rules)}):*\n{rules_text}\n\n"
        f"🏆 Max score:  {max_score:.1f}\n🎯 Tier A:     {max_score * 0.8:.1f}+\n🥈 Tier B:     {max_score * 0.65:.1f}+\n🥉 Tier C:     {max_score * 0.5:.1f}+\n\n"
        "Looks good? Tap Save to activate."
    )
    await query.message.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💾 Save Model", callback_data="wizard:confirm_save")],
            [InlineKeyboardButton("✏️ Edit Rules", callback_data="wizard:rules")],
            [InlineKeyboardButton("❌ Cancel", callback_data="wizard:cancel")],
        ]),
    )


async def show_phase_assignment_step(query, context):
    rules = context.user_data.get("model_rules", [])
    if rules and not any("phase" in r for r in rules):
        n = len(rules)
        for idx, rule in enumerate(rules):
            pct = (idx + 1) / max(n, 1)
            rule["phase"] = 1 if pct <= 0.3 else 2 if pct <= 0.7 else 3 if pct <= 0.9 else 4
    phase_labels = {1: "P1", 2: "P2", 3: "P3", 4: "P4"}
    phase_colors = {1: "🔭", 2: "🔬", 3: "⚡", 4: "✅"}
    text = (
        "📐 *Assign Rules to Phases*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Tap a rule to cycle its phase:\n"
        "🔭 P1=HTF Context → 🔬 P2=MTF Setup\n"
        "→ ⚡ P3=LTF Trigger → ✅ P4=Confirm\n\n"
        "Rules fire in order. P2 only runs after P1\n"
        "passes. P3 only runs after P2 passes."
    )
    buttons = []
    for rule in rules:
        phase = int(rule.get("phase", 1))
        buttons.append([InlineKeyboardButton(f"{phase_colors[phase]} [{phase_labels[phase]}] {rule['name']}", callback_data=f"wizard:cycle_phase:{rule['id']}")])
    buttons.append([InlineKeyboardButton("✅ Done — phase timeframes", callback_data="wizard:phase_done")])
    buttons.append([InlineKeyboardButton("« Back to Weights", callback_data="wizard:weights")])
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))


async def show_phase_timeframes_step(query, context):
    ptf = context.user_data.get("phase_timeframes", {"1": "4h", "2": "1h", "3": "15m", "4": "5m"})
    context.user_data["phase_timeframes"] = ptf
    rows = [
        [InlineKeyboardButton(f"P1: {ptf['1']}", callback_data="wizard:phase_tf:1"), InlineKeyboardButton(f"P2: {ptf['2']}", callback_data="wizard:phase_tf:2")],
        [InlineKeyboardButton(f"P3: {ptf['3']}", callback_data="wizard:phase_tf:3"), InlineKeyboardButton(f"P4: {ptf['4']}", callback_data="wizard:phase_tf:4")],
        [InlineKeyboardButton("✅ Done — go to review", callback_data="wizard:phase_cfg_done")],
    ]
    await query.message.edit_text("⏱ *Phase Timeframes*\nP1 (Context) scans on: [1D] [4H]\nP2 (Setup) scans on: [4H] [1H] [30M]\nP3 (Trigger) scans on: [1H] [15M] [5M]\nP4 (Confirm) scans on: [15M] [5M] [1M]", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))



@require_auth_callback
async def handle_wizard_cb(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("wizard:pair:"):
        context.user_data["model_pair"] = data.split(":", 2)[2]
        buttons = [[InlineKeyboardButton(tf, callback_data=f"wizard:tf:{tf}") for tf in SUPPORTED_TIMEFRAMES[i:i + 3]] for i in range(0, len(SUPPORTED_TIMEFRAMES), 3)]
        buttons.append([InlineKeyboardButton("« Back", callback_data="wizard:back")])
        await query.message.edit_text("⏱ Select timeframe", reply_markup=InlineKeyboardMarkup(buttons))
        return WIZARD_TF

    if data.startswith("wizard:tf:"):
        context.user_data["model_timeframe"] = data.split(":", 2)[2]
        buttons = [[InlineKeyboardButton(s, callback_data=f"wizard:session:{s}") for s in SUPPORTED_SESSIONS[i:i + 2]] for i in range(0, len(SUPPORTED_SESSIONS), 2)]
        buttons.append([InlineKeyboardButton("« Back", callback_data="wizard:back")])
        await query.message.edit_text("🧭 Select session", reply_markup=InlineKeyboardMarkup(buttons))
        return WIZARD_SESSION

    if data.startswith("wizard:session:"):
        context.user_data["model_session"] = data.split(":", 2)[2]
        await query.message.edit_text(
            "📈 Directional Bias",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📈 Bullish", callback_data="wizard:bias:Bullish"), InlineKeyboardButton("📉 Bearish", callback_data="wizard:bias:Bearish")],
                [InlineKeyboardButton("↔️ Both Directions", callback_data="wizard:bias:Both")],
                [InlineKeyboardButton("« Back", callback_data="wizard:back")],
            ]),
        )
        return WIZARD_BIAS

    if data.startswith("wizard:bias:"):
        context.user_data["model_bias"] = data.split(":", 2)[2]
        await show_rule_categories(query, context)
        return WIZARD_RULES

    if data in {"wizard:rules", "wizard:add_rules"}:
        await show_rule_categories(query, context)
        return WIZARD_RULES

    if data.startswith("wizard:rules_cat:"):
        await show_rules_in_category(query, context, data.split("wizard:rules_cat:")[1])
        return WIZARD_RULES

    if data.startswith("wizard:toggle_rule:"):
        rule_id = data.split("wizard:toggle_rule:")[1]
        rule_def = next((r for r in PERPS_RULE_LIBRARY if r["id"] == rule_id), None)
        if rule_def:
            rules = context.user_data.get("model_rules", [])
            existing_ids = {r["id"] for r in rules}
            if rule_id in existing_ids:
                rules = [r for r in rules if r["id"] != rule_id]
                await query.answer(f"○ Removed: {rule_def['name']}")
            else:
                rules.append({"id": rule_def["id"], "name": rule_def["name"], "weight": rule_def["default_weight"], "mandatory": False, "description": rule_def["description"], "category": rule_def["category"]})
                await query.answer(f"✅ Added: {rule_def['name']}")
            context.user_data["model_rules"] = rules
        cat = next((r["category"] for r in PERPS_RULE_LIBRARY if r["id"] == rule_id), "Trend")
        await show_rules_in_category(query, context, cat)
        return WIZARD_RULES

    if data == "wizard:rules_back_to_cats":
        await show_rule_categories(query, context)
        return WIZARD_RULES

    if data == "wizard:rules_done":
        if not context.user_data.get("model_rules", []):
            await query.answer("⚠️ Add at least one rule first", show_alert=True)
            return WIZARD_RULES
        await show_weights_step(query, context)
        return WIZARD_WEIGHTS

    if data == "wizard:weights":
        await show_weights_step(query, context)
        return WIZARD_WEIGHTS

    if data.startswith("wizard:weight_rule:"):
        await show_weight_picker(query, context, data.split("wizard:weight_rule:")[1])
        return WIZARD_WEIGHTS

    if data.startswith("wizard:set_weight:"):
        _, _, rule_id, weight = data.split(":")
        rules = context.user_data.get("model_rules", [])
        for r in rules:
            if r["id"] == rule_id:
                r["weight"] = float(weight)
                break
        context.user_data["model_rules"] = rules
        await query.answer(f"✅ Weight set to {weight}")
        await show_weight_picker(query, context, rule_id)
        return WIZARD_WEIGHTS

    if data == "wizard:weights_done":
        await show_phase_assignment_step(query, context)
        return WIZARD_PHASE_ASSIGN

    if data.startswith("wizard:cycle_phase:"):
        rule_id = data.split("wizard:cycle_phase:")[1]
        rules = context.user_data.get("model_rules", [])
        for rule in rules:
            if rule["id"] == rule_id:
                current = int(rule.get("phase", 1))
                rule["phase"] = (current % 4) + 1
                await query.answer(f"→ Phase {rule['phase']}")
                break
        context.user_data["model_rules"] = rules
        await show_phase_assignment_step(query, context)
        return WIZARD_PHASE_ASSIGN

    if data == "wizard:phase_done":
        await show_phase_timeframes_step(query, context)
        return WIZARD_PHASE_CONFIG

    if data.startswith("wizard:phase_tf:"):
        phase = data.split(":")[-1]
        options = {"1": ["1d", "4h"], "2": ["4h", "1h", "30m"], "3": ["1h", "15m", "5m"], "4": ["15m", "5m", "1m"]}
        ptf = context.user_data.get("phase_timeframes", {"1": "4h", "2": "1h", "3": "15m", "4": "5m"})
        vals = options[phase]
        idx = (vals.index(ptf.get(phase, vals[0])) + 1) % len(vals) if ptf.get(phase, vals[0]) in vals else 0
        ptf[phase] = vals[idx]
        context.user_data["phase_timeframes"] = ptf
        await show_phase_timeframes_step(query, context)
        return WIZARD_PHASE_CONFIG

    if data == "wizard:phase_cfg_done":
        await show_model_review(query, context)
        return WIZARD_REVIEW

    if data == "wizard:confirm_save":
        return await handle_confirm_save(update, context)

    if data == "wizard:back_to_session":
        buttons = [[InlineKeyboardButton(s, callback_data=f"wizard:session:{s}") for s in SUPPORTED_SESSIONS[i:i + 2]] for i in range(0, len(SUPPORTED_SESSIONS), 2)]
        buttons.append([InlineKeyboardButton("« Back", callback_data="wizard:back")])
        await query.message.edit_text("🧭 Select session", reply_markup=InlineKeyboardMarkup(buttons))
        return WIZARD_SESSION

    if data in {"wizard:back", "wizard:cancel"}:
        return await handle_wizard_cancel(update, context)


@require_auth_callback
async def handle_confirm_save(update, context):
    query = update.callback_query
    await query.answer("Saving...")

    try:
        import time
        model_id = (
            context.user_data.get("model_id")
            or f"model_{int(time.time())}"
        )
        name      = context.user_data.get("model_name", "Unnamed Model")
        pair      = context.user_data.get("model_pair", "BTCUSDT")
        timeframe = context.user_data.get("model_timeframe", "1h")
        session   = context.user_data.get("model_session", "Any")
        bias      = context.user_data.get("model_bias", "Both")
        rules     = context.user_data.get("model_rules", [])
        phase_timeframes = context.user_data.get("phase_timeframes", {"1": "4h", "2": "1h", "3": "15m", "4": "5m"})
        for r in rules:
            r["timeframe"] = phase_timeframes.get(str(r.get("phase", 1)), timeframe)
        desc      = context.user_data.get("model_description", "")

        if not rules:
            await query.answer(
                "❌ No rules added — go back and add rules first",
                show_alert=True
            )
            return

        max_score = sum(r.get("weight", 1.0) for r in rules)

        model = {
            "id":                model_id,
            "name":              name,
            "pair":              pair,
            "timeframe":         timeframe,
            "session":           session,
            "bias":              bias,
            "status":            "inactive",
            "rules":             rules,
            "tier_a_threshold":  round(max_score * 0.80, 2),
            "tier_b_threshold":  round(max_score * 0.65, 2),
            "tier_c_threshold":  round(max_score * 0.50, 2),
            "min_score":         round(max_score * 0.50, 2),
            "description":       desc,
            "phase_timeframes":  phase_timeframes,
        }

        # This is the ONLY db call needed — everything
        # else happens inside db.save_model()
        saved_id = db.save_model(model)

        # Clear wizard state
        for key in [k for k in context.user_data
                    if k.startswith("model_")]:
            context.user_data.pop(key, None)
        context.user_data.pop("in_conversation", None)

        await query.message.edit_text(
            f"✅ *Model Saved*\n"
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
                [InlineKeyboardButton(
                    "▶️ Activate Now",
                    callback_data=f"model:toggle:{saved_id}"
                )],
                [InlineKeyboardButton(
                    "⚙️ View All Models",
                    callback_data="nav:models"
                )],
                [InlineKeyboardButton(
                    "🏠 Perps Home",
                    callback_data="nav:perps_home"
                )]
            ])
        )
        return ConversationHandler.END

    except Exception as e:
        import traceback
        log.error(f"Save model failed: {traceback.format_exc()}")
        await query.message.edit_text(
            f"❌ *Save failed*\n\n"
            f"`{type(e).__name__}: {str(e)[:300]}`\n\n"
            f"Tap retry to try again.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "🔄 Retry",
                    callback_data="wizard:confirm_save"
                )
            ]])
        )


@require_auth_callback
async def handle_wizard_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query if update.callback_query else None
    if q:
        await q.answer()
        await q.message.edit_text("❌ Wizard cancelled")
    context.user_data.pop("in_conversation", None)
    for key in [k for k in list(context.user_data) if k.startswith("model_")]:
        context.user_data.pop(key, None)
    return ConversationHandler.END


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
            WIZARD_PAIR: [CallbackQueryHandler(handle_wizard_cb, pattern="^wizard:")],
            WIZARD_TF: [CallbackQueryHandler(handle_wizard_cb, pattern="^wizard:")],
            WIZARD_SESSION: [CallbackQueryHandler(handle_wizard_cb, pattern="^wizard:")],
            WIZARD_BIAS: [CallbackQueryHandler(handle_wizard_cb, pattern="^wizard:")],
            WIZARD_RULES: [CallbackQueryHandler(handle_wizard_cb, pattern="^wizard:")],
            WIZARD_WEIGHTS: [CallbackQueryHandler(handle_wizard_cb, pattern="^wizard:")],
            WIZARD_PHASE_ASSIGN: [CallbackQueryHandler(handle_wizard_cb, pattern="^wizard:")],
            WIZARD_PHASE_CONFIG: [CallbackQueryHandler(handle_wizard_cb, pattern="^wizard:")],
            WIZARD_REVIEW: [CallbackQueryHandler(handle_wizard_cb, pattern="^wizard:")],
        },
        fallbacks=[
            CallbackQueryHandler(handle_wizard_cancel, pattern="^wizard:cancel$|^wiz:cancel$"),
            CommandHandler("cancel", handle_wizard_cancel),
        ],
        per_message=False,
        per_chat=True,
        allow_reentry=True,
    )
