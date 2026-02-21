import logging, json, uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    CallbackQueryHandler, MessageHandler, filters
)
import db
from config import (
    CHAT_ID, SUPPORTED_PAIRS, SUPPORTED_TIMEFRAMES,
    SUPPORTED_SESSIONS, SUPPORTED_BIASES, SUPPORTED_MODEL_RULES, TIER_RISK
)

log = logging.getLogger(__name__)

# ── States ────────────────────────────────────────────
(
    ASK_NAME, ASK_PAIR, ASK_TF, ASK_SESSION,
    ASK_BIAS, ASK_RULES, ASK_RULE_WEIGHT,
    ASK_RULE_MANDATORY, ASK_MORE_RULES, ASK_TIERS,
    ASK_TIER_B, ASK_TIER_C, CONFIRM
, CONFLICT_WARN) = range(14)


def _guard(update: Update) -> bool:
    return update.effective_chat.id == CHAT_ID


def _kb(options, prefix, cols=2, back=None):
    """Build an inline keyboard from a list of strings."""
    rows = []
    for i in range(0, len(options), cols):
        rows.append([
            InlineKeyboardButton(o, callback_data=f"{prefix}:{o}")
            for o in options[i:i+cols]
        ])
    if back:
        rows.append([InlineKeyboardButton("❌ Cancel", callback_data="wiz:cancel")])
    return InlineKeyboardMarkup(rows)


def _rule_kb():
    rows = [
        [InlineKeyboardButton(rule, callback_data=f"wiz_rule:{idx}")]
        for idx, rule in enumerate(SUPPORTED_MODEL_RULES)
    ]
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="wiz:cancel")])
    return InlineKeyboardMarkup(rows)


def _find_rule_conflict(rules):
    names=[r["name"].lower() for r in rules]
    for i,a in enumerate(names):
        for b in names[i+1:]:
            if (("bullish" in a and "bearish" in b) or ("bearish" in a and "bullish" in b) or ("buy" in a and "sell" in b) or ("sell" in a and "buy" in b)):
                return a,b
    return None

def _progress(step, total=6):
    filled = "●" * step + "○" * (total - step)
    return f"`[{filled}]`  Step {step}/{total}"


# ── Step 0: Entry ─────────────────────────────────────
async def wiz_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point — works from both /create_model and wiz:start callback."""
    if hasattr(update, "callback_query") and update.callback_query:
        q = update.callback_query
        await q.answer()
        reply = q.message.reply_text
    else:
        if not _guard(update): return ConversationHandler.END
        reply = update.message.reply_text

    context.user_data.clear()
    context.user_data["rules"] = []

    await reply(
        "⚙️ *Model Wizard*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{_progress(1)}\n\n"
        "What's the name of this model?\n\n"
        "_Example: London Sweep Reversal_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancel", callback_data="wiz:cancel")
        ]])
    )
    return ASK_NAME


# ── Step 1: Name ──────────────────────────────────────
async def got_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("❗ Name is too short. Try again:")
        return ASK_NAME
    context.user_data["name"] = name
    await update.message.reply_text(
        f"✅ *{name}*\n\n"
        f"{_progress(2)}\n\n"
        "🪙 Which pair does this model trade?\n\n🧭 *Guide:* Choose the market where this setup is most reliable.",
        parse_mode="Markdown",
        reply_markup=_kb(SUPPORTED_PAIRS, "wiz_pair", cols=3, back=True)
    )
    return ASK_PAIR


# ── Step 2: Pair ──────────────────────────────────────
async def got_pair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pair = q.data.split(":")[1]
    context.user_data["pair"] = pair
    await q.message.reply_text(
        f"✅ Pair: *{pair}*\n\n"
        f"{_progress(3)}\n\n"
        "⏱ Choose the timeframe:\n\n🧭 *Guide:* Match this to the candles you use for entries.",
        parse_mode="Markdown",
        reply_markup=_kb(SUPPORTED_TIMEFRAMES, "wiz_tf", cols=3, back=True)
    )
    return ASK_TF


# ── Step 3: Timeframe ─────────────────────────────────
async def got_tf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    tf = q.data.split(":")[1]
    context.user_data["timeframe"] = tf
    await q.message.reply_text(
        f"✅ Timeframe: *{tf}*\n\n"
        f"{_progress(3)}\n\n"
        "🧭 Which session does this model trade?\n\n🧭 *Guide:* Pick when liquidity/volatility is best for this setup.",
        parse_mode="Markdown",
        reply_markup=_kb(SUPPORTED_SESSIONS, "wiz_session", cols=2, back=True)
    )
    return ASK_SESSION


# ── Step 4: Session ───────────────────────────────────
async def got_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    session = q.data.split(":")[1]
    context.user_data["session"] = session
    await q.message.reply_text(
        f"✅ Session: *{session}*\n\n"
        f"{_progress(4)}\n\n"
        "📈 Directional bias:\n\n🧭 *Guide:* Set your dominant direction to filter low-quality trades.",
        parse_mode="Markdown",
        reply_markup=_kb(SUPPORTED_BIASES, "wiz_bias", cols=2, back=True)
    )
    return ASK_BIAS


# ── Step 5: Bias ──────────────────────────────────────
async def got_bias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    bias = q.data.split(":")[1]
    context.user_data["bias"] = bias
    icon = "📈" if bias == "Bullish" else "📉"
    await q.message.reply_text(
        f"✅ Bias: *{icon} {bias}*\n\n"
        f"{_progress(5)}\n\n"
        "📋 *Add Rules*\n\n"
        "Rules are the conditions that must be met\n"
        "before this model fires an alert.\n\n"
        "Select your first rule from the list below.\n\n🧭 *Guide:* Start with your non-negotiable condition.",
        parse_mode="Markdown",
        reply_markup=_rule_kb()
    )
    return ASK_RULES


# ── Step 5a: Rule name ────────────────────────────────
async def got_rule_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    idx = int(q.data.split(":")[1])

    if idx < 0 or idx >= len(SUPPORTED_MODEL_RULES):
        await q.message.reply_text("❗ Invalid rule selection. Please choose again.", reply_markup=_rule_kb())
        return ASK_RULES

    name = SUPPORTED_MODEL_RULES[idx]

    if any(r["name"] == name for r in context.user_data.get("rules", [])):
        await q.message.reply_text(
            "⚠️ That rule is already added. Select a different one.",
            parse_mode="Markdown",
            reply_markup=_rule_kb(),
        )
        return ASK_RULES

    context.user_data["_current_rule"] = {"name": name}
    await q.message.reply_text(
        f"📋 Rule: *{name}*\n\n"
        "⚖️ Set the weight for this rule:\n"
        "_Higher weight = more influence on score_\n\n🧭 *Guide:* Use bigger weights for stronger confirmations.",
        parse_mode="Markdown",
        reply_markup=_kb(["0.5","1.0","1.5","2.0","2.5","3.0","3.5","4.0"], "wiz_weight", cols=4, back=True)
    )
    return ASK_RULE_WEIGHT


# ── Step 5b: Rule weight ──────────────────────────────
async def got_rule_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    weight = float(q.data.split(":")[1])
    context.user_data["_current_rule"]["weight"] = weight
    rule_name = context.user_data["_current_rule"]["name"]
    await q.message.reply_text(
        f"📋 Rule: *{rule_name}*  `+{weight}`\n\n"
        "🔒 Is this rule *mandatory*?\n\n"
        "• *Required* — setup is invalidated if this rule fails\n"
        "• *Optional* — adds score but won't block the alert\n\n🧭 *Guide:* Keep at least one required rule to avoid noisy alerts.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔒 Required",  callback_data="wiz_mand:yes"),
                InlineKeyboardButton("✨ Optional",  callback_data="wiz_mand:no"),
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data="wiz:cancel")]
        ])
    )
    return ASK_RULE_MANDATORY


# ── Step 5c: Mandatory toggle ─────────────────────────
async def got_rule_mandatory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    mandatory = q.data.split(":")[1] == "yes"
    rule = context.user_data.pop("_current_rule")
    rule["mandatory"] = mandatory
    rule["id"] = f"r{len(context.user_data['rules']) + 1}"
    context.user_data["rules"].append(rule)

    rules     = context.user_data["rules"]
    max_raw   = sum(r["weight"] for r in rules)
    max_score = round(max_raw + 1.0, 2)

    rules_lines = "\n".join(
        f"  {'🔒' if r['mandatory'] else '✨'} {r['name']}  `+{r['weight']}`"
        for r in rules
    )

    warns = []
    if not any(r["mandatory"] for r in rules):
        warns.append("⚠️ No required rules — any score can trigger alerts")
    if max_score < 5.5:
        warns.append(f"⚠️ Max score ({max_score}) is below default Tier C — model won't alert")
    warn_text = ("\n\n" + "\n".join(warns)) if warns else ""

    await q.message.reply_text(
        f"✅ Rule added!\n\n"
        f"📋 *Rules so far* ({len(rules)}):\n"
        f"{rules_lines}\n\n"
        f"🎯 Max possible score: `{max_score}`"
        f"{warn_text}\n\n"
        "Add another rule or continue?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("➕ Add Rule",  callback_data="wiz_more:yes"),
                InlineKeyboardButton("✅ Done",       callback_data="wiz_more:no"),
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data="wiz:cancel")]
        ])
    )
    return ASK_MORE_RULES


# ── Step 5d: More rules? ──────────────────────────────
async def got_more_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    val = q.data.split(":")[1]
    if q.data.startswith("wiz_conflict:"):
        want_more = (val == "edit")
    else:
        want_more = val == "yes"

    if want_more:
        await q.message.reply_text(
            "📋 *Add another rule*\n\nSelect the next rule:",
            parse_mode="Markdown",
            reply_markup=_rule_kb()
        )
        return ASK_RULES

    c = _find_rule_conflict(context.user_data["rules"])
    if c:
        context.user_data["_conflict"]=c
        await q.message.reply_text(f"⚠️ Rule Conflict Detected\nThese rules may contradict each other:\n• {c[0]}\n• {c[1]}\nContinue anyway or go back to edit?", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Continue", callback_data="wiz_conflict:continue"), InlineKeyboardButton("Edit Rules", callback_data="wiz_conflict:edit")]]))
        return CONFLICT_WARN

    # Move to tiers step
    await q.message.reply_text(
        f"{_progress(6)}\n\n"
        "🏆 *Set Tier Thresholds*\n\n"
        "Choose the minimum score for each tier.\n"
        "_Tier A is the highest conviction._\n\n"
        "Choose *Tier A* minimum score:\n\n🧭 *Guide:* Tier A should represent your best, highest-conviction setups.",
        parse_mode="Markdown",
        reply_markup=_kb(
            ["7.0","7.5","8.0","8.5","9.0","9.5","10.0","10.5"],
            "wiz_tierA", cols=4, back=True
        )
    )
    return ASK_TIERS


# ── Step 6: Tiers ─────────────────────────────────────
async def got_tier_a(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["tier_a"] = float(q.data.split(":")[1])
    await q.message.reply_text(
        f"✅ Tier A ≥ `{context.user_data['tier_a']}`\n\n"
        "🥈 Choose *Tier B* minimum score:\n\n🧭 *Guide:* Tier B should capture solid but not elite setups.",
        parse_mode="Markdown",
        reply_markup=_kb(
            ["5.0","5.5","6.0","6.5","7.0","7.5","8.0","8.5"],
            "wiz_tierB", cols=4, back=True
        )
    )
    return ASK_TIER_B


async def got_tier_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["tier_b"] = float(q.data.split(":")[1])
    await q.message.reply_text(
        f"✅ Tier B ≥ `{context.user_data['tier_b']}`\n\n"
        "🥉 Choose *Tier C* minimum score:\n\n🧭 *Guide:* Tier C is your minimum acceptable quality floor.",
        parse_mode="Markdown",
        reply_markup=_kb(
            ["3.0","3.5","4.0","4.5","5.0","5.5","6.0","6.5"],
            "wiz_tierC", cols=4, back=True
        )
    )
    return ASK_TIER_C


async def got_tier_c(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["tier_c"] = float(q.data.split(":")[1])
    await _show_review(q.message.reply_text, context.user_data)
    return CONFIRM


async def _show_review(reply_fn, d):
    rules     = d["rules"]
    max_raw   = sum(r["weight"] for r in rules)
    max_score = round(max_raw + 1.0, 2)

    rules_lines = "\n".join(
        f"  {'🔒' if r['mandatory'] else '✨'} {r['name']}  `+{r['weight']}`"
        for r in rules
    )

    tier_reach = []
    for label, thresh in [("A", d["tier_a"]), ("B", d["tier_b"]), ("C", d["tier_c"])]:
        ok = max_score >= thresh
        tier_reach.append(
            f"  {'✅' if ok else '❌'} Tier {label} ≥ {thresh}  →  {TIER_RISK[label]}% risk"
        )

    await reply_fn(
        "📋 *Review Your Model*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 *{d['name']}*\n"
        f"🪙 Pair:       `{d['pair']}`\n"
        f"⏱ Timeframe:  `{d['timeframe']}`\n"
        f"🧭 Session:    `{d['session']}`\n"
        f"📈 Bias:       `{d['bias']}`\n"
        f"\n📋 *Rules* ({len(rules)}):\n{rules_lines}\n"
        f"🎯 Max score: `{max_score}`\n"
        f"\n🏅 *Tiers*:\n" + "\n".join(tier_reach) + "\n\n"
        "⚡ Status will be *INACTIVE* until you activate it.\n\n🧭 *Guide:* Save now, then activate from the model detail screen.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Save Model",  callback_data="wiz_confirm:yes"),
                InlineKeyboardButton("❌ Cancel",      callback_data="wiz_confirm:no"),
            ]
        ])
    )


# ── Confirm ───────────────────────────────────────────
async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    choice = q.data.split(":")[1]

    if choice == "no":
        context.user_data.clear()
        await q.message.reply_text(
            "❌ *Cancelled* — model not saved.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Home", callback_data="nav:home")
            ]])
        )
        return ConversationHandler.END

    d = context.user_data
    model_id = str(uuid.uuid4())[:8]
    model = {
        "id":        model_id,
        "name":      d["name"],
        "pair":      d["pair"],
        "timeframe": d["timeframe"],
        "session":   d["session"],
        "bias":      d["bias"],
        "tier_a":    d["tier_a"],
        "tier_b":    d["tier_b"],
        "tier_c":    d["tier_c"],
        "rules":     d["rules"],
    }
    try:
        db.insert_model(model)
    except Exception as e:
        await q.message.reply_text(f"❌ Error saving model: `{e}`", parse_mode="Markdown")
        return ConversationHandler.END

    context.user_data.clear()
    await q.message.reply_text(
        f"✅ *Model Saved!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 {model['name']}\n"
        f"🆔 ID: `{model_id}`\n"
        f"⚡ Status: *inactive*\n\n"
        f"Tap *Activate* to start scanning.\n\n🧭 *Guide:* Once active, the scanner checks this model automatically.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Activate Now", callback_data=f"model:toggle:{model_id}"),
                InlineKeyboardButton("⚙️ View Models",  callback_data="nav:models"),
            ],
            [InlineKeyboardButton("🏠 Home", callback_data="nav:home")]
        ])
    )
    return ConversationHandler.END


# ── Cancel ────────────────────────────────────────────
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        reply = update.callback_query.message.reply_text
    else:
        reply = update.message.reply_text
    context.user_data.clear()
    await reply(
        "❌ *Wizard cancelled.*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 Home", callback_data="nav:home")
        ]])
    )
    return ConversationHandler.END


# ── Build the ConversationHandler ─────────────────────
def build_wizard_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("create_model", wiz_start),
            CallbackQueryHandler(wiz_start, pattern="^wiz:start$"),
        ],
        states={
            ASK_NAME:          [MessageHandler(filters.TEXT & ~filters.COMMAND, got_name)],
            ASK_PAIR:          [CallbackQueryHandler(got_pair,          pattern="^wiz_pair:")],
            ASK_TF:            [CallbackQueryHandler(got_tf,            pattern="^wiz_tf:")],
            ASK_SESSION:       [CallbackQueryHandler(got_session,       pattern="^wiz_session:")],
            ASK_BIAS:          [CallbackQueryHandler(got_bias,          pattern="^wiz_bias:")],
            ASK_RULES:         [CallbackQueryHandler(got_rule_name,   pattern="^wiz_rule:")],
            ASK_RULE_WEIGHT:   [CallbackQueryHandler(got_rule_weight,   pattern="^wiz_weight:")],
            ASK_RULE_MANDATORY:[CallbackQueryHandler(got_rule_mandatory,pattern="^wiz_mand:")],
            ASK_MORE_RULES:    [CallbackQueryHandler(got_more_rules,    pattern="^wiz_more:")],
            ASK_TIERS:         [CallbackQueryHandler(got_tier_a,        pattern="^wiz_tierA:")],
            CONFLICT_WARN:     [CallbackQueryHandler(got_more_rules,     pattern="^wiz_conflict:")],
            ASK_TIER_B:        [CallbackQueryHandler(got_tier_b,        pattern="^wiz_tierB:")],
            ASK_TIER_C:        [CallbackQueryHandler(got_tier_c,        pattern="^wiz_tierC:")],
            CONFIRM:           [CallbackQueryHandler(confirm,           pattern="^wiz_confirm:")],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(cancel, pattern="^wiz:cancel$"),
        ],
        allow_reentry=True,
    )
