import logging, re, json, uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    MessageHandler, CallbackQueryHandler, filters
)
import db, formatters
from config import CHAT_ID

log = logging.getLogger(__name__)

# ── Conversation states ───────────────────────────────
(
    ASK_NAME, ASK_PAIR, ASK_TF, ASK_SESSION,
    ASK_BIAS, ASK_RULES, ASK_TIERS, CONFIRM
) = range(8)

PAIRS     = ["EURUSD","GBPUSD","XAUUSD","BTCUSDT","ETHUSDT","USDJPY","AUDUSD"]
TFS       = ["1m","5m","15m","1H","4H","1D"]
SESSIONS  = ["London","NY","Asia","Overlap"]
BIASES    = ["Bullish","Bearish"]


def _guard(update: Update) -> bool:
    return update.effective_chat.id == CHAT_ID


def _keyboard(options: list, prefix: str = "wiz") -> InlineKeyboardMarkup:
    """Build a 2-column inline keyboard from a list of strings."""
    rows = []
    for i in range(0, len(options), 2):
        row = [InlineKeyboardButton(o, callback_data=f"{prefix}:{o}") for o in options[i:i+2]]
        rows.append(row)
    return InlineKeyboardMarkup(rows)


# ── Entry ─────────────────────────────────────────────
async def create_model_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return ConversationHandler.END
    context.user_data.clear()
    context.user_data["rules"] = []

    await update.message.reply_text(
        "⚙️ Model Wizard\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Step 1/7 — Model name\n\n"
        "Send a short name for this model.\n"
        "Example:  London Sweep Reversal\n\n"
        "Send /cancel to abort."
    )
    return ASK_NAME


# ── Step 1: Name ──────────────────────────────────────
async def got_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 3:
        await update.message.reply_text("Name too short. Try again:")
        return ASK_NAME

    context.user_data["name"] = name
    await update.message.reply_text(
        f"✅ Name: {name}\n\n"
        f"Step 2/7 — Pair\n"
        f"Choose the pair this model trades:",
        reply_markup=_keyboard(PAIRS)
    )
    return ASK_PAIR


# ── Step 2: Pair ──────────────────────────────────────
async def got_pair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pair = query.data.split(":")[1]
    context.user_data["pair"] = pair

    await query.message.reply_text(
        f"✅ Pair: {pair}\n\n"
        f"Step 3/7 — Timeframe:",
        reply_markup=_keyboard(TFS)
    )
    return ASK_TF


# ── Step 3: Timeframe ─────────────────────────────────
async def got_tf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tf = query.data.split(":")[1]
    context.user_data["timeframe"] = tf

    await query.message.reply_text(
        f"✅ Timeframe: {tf}\n\n"
        f"Step 4/7 — Session this model trades:",
        reply_markup=_keyboard(SESSIONS)
    )
    return ASK_SESSION


# ── Step 4: Session ───────────────────────────────────
async def got_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    session = query.data.split(":")[1]
    context.user_data["session"] = session

    await query.message.reply_text(
        f"✅ Session: {session}\n\n"
        f"Step 5/7 — Directional bias:",
        reply_markup=_keyboard(BIASES)
    )
    return ASK_BIAS


# ── Step 5: Bias ──────────────────────────────────────
async def got_bias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bias = query.data.split(":")[1]
    context.user_data["bias"] = bias

    await query.message.reply_text(
        f"✅ Bias: {bias}\n\n"
        f"Step 6/7 — Rules\n\n"
        f"Add rules one at a time. Format:\n\n"
        f"  NAME | WEIGHT | MANDATORY\n\n"
        f"Examples:\n"
        f"  Liquidity Sweep | 3.2 | yes\n"
        f"  4H Order Block | 2.8 | yes\n"
        f"  SMT Divergence | 2.4 | no\n\n"
        f"Rules added so far: 0\n\n"
        f"Send a rule, or /done when finished."
    )
    return ASK_RULES


# ── Step 6: Rules (loop) ──────────────────────────────
async def got_rule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Parse   NAME | WEIGHT | MANDATORY
    parts = [p.strip() for p in text.split("|")]
    if len(parts) != 3:
        await update.message.reply_text(
            "Format: NAME | WEIGHT | yes/no\n"
            "Example: Liquidity Sweep | 3.2 | yes"
        )
        return ASK_RULES

    name_r, weight_str, mandatory_str = parts
    try:
        weight = float(weight_str)
    except ValueError:
        await update.message.reply_text("Weight must be a number. Try again:")
        return ASK_RULES

    mandatory = mandatory_str.lower() in ("yes", "y", "true", "1")
    rule_id   = f"r{len(context.user_data['rules']) + 1}"

    context.user_data["rules"].append({
        "id":        rule_id,
        "name":      name_r,
        "weight":    weight,
        "mandatory": mandatory,
    })

    rules     = context.user_data["rules"]
    rules_str = "\n".join(
        f"  {'[REQ]' if r['mandatory'] else '[OPT]'} {r['name']}  +{r['weight']}"
        for r in rules
    )
    max_raw   = sum(r["weight"] for r in rules)
    max_score = round(max_raw + 1.0, 2)  # +1.0 best modifier

    # Warnings
    warns = []
    if not any(r["mandatory"] for r in rules):
        warns.append("⚠️ No mandatory rules set")
    if max_score < 5.5:
        warns.append(f"⚠️ Max score ({max_score}) below default Tier C — model won't alert")
    warn_block = ("\n" + "\n".join(warns)) if warns else ""

    await update.message.reply_text(
        f"✅ Rule added.\n\n"
        f"Rules so far ({len(rules)}):\n{rules_str}\n\n"
        f"Max possible score: {max_score}"
        f"{warn_block}\n\n"
        f"Add another rule, or /done to continue."
    )
    return ASK_RULES


async def rules_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rules = context.user_data.get("rules", [])
    if not rules:
        await update.message.reply_text("Add at least one rule first.")
        return ASK_RULES

    await update.message.reply_text(
        f"Step 7/7 — Tier thresholds & risk\n\n"
        f"Send three numbers on one line:\n\n"
        f"  TIER_A  TIER_B  TIER_C\n\n"
        f"Example:  9.5  7.5  5.5\n\n"
        f"Risk is fixed:\n"
        f"  Tier A = 2.0%\n"
        f"  Tier B = 1.0%\n"
        f"  Tier C = 0.5%"
    )
    return ASK_TIERS


# ── Step 7: Tiers ─────────────────────────────────────
async def got_tiers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = update.message.text.strip().split()
    if len(parts) != 3:
        await update.message.reply_text("Send exactly 3 numbers:  9.5  7.5  5.5")
        return ASK_TIERS
    try:
        a, b, c = float(parts[0]), float(parts[1]), float(parts[2])
    except ValueError:
        await update.message.reply_text("Numbers only. Try again:")
        return ASK_TIERS

    if not (a > b > c > 0):
        await update.message.reply_text("Must be decreasing: A > B > C > 0. Try again:")
        return ASK_TIERS

    context.user_data["tier_a"] = a
    context.user_data["tier_b"] = b
    context.user_data["tier_c"] = c

    d = context.user_data
    rules     = d["rules"]
    max_raw   = sum(r["weight"] for r in rules)
    max_score = round(max_raw + 1.0, 2)
    rules_str = "\n".join(
        f"  {'[REQ]' if r['mandatory'] else '[OPT]'} {r['name']}  +{r['weight']}"
        for r in rules
    )
    tier_reach = []
    for label, thresh in [("A",a),("B",b),("C",c)]:
        ok = max_score >= thresh
        tier_reach.append(f"  Tier {label} ≥{thresh}  {'✅' if ok else '❌ unreachable'}")

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm & Save", callback_data="wiz_confirm:yes"),
        InlineKeyboardButton("❌ Cancel",         callback_data="wiz_confirm:no"),
    ]])
    await update.message.reply_text(
        f"📋 Review — confirm to save\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Name:      {d['name']}\n"
        f"Pair:      {d['pair']}\n"
        f"Timeframe: {d['timeframe']}\n"
        f"Session:   {d['session']}\n"
        f"Bias:      {d['bias']}\n\n"
        f"Rules ({len(rules)}):\n{rules_str}\n\n"
        f"Tiers:\n" + "\n".join(tier_reach) + "\n\n"
        f"Max possible score: {max_score}\n\n"
        f"Status will be INACTIVE until backtested.",
        reply_markup=keyboard
    )
    return CONFIRM


# ── Step 8: Confirm ───────────────────────────────────
async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":")[1]

    if choice == "no":
        context.user_data.clear()
        await query.message.reply_text("❌ Cancelled. Model was not saved.")
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
        await query.message.reply_text(f"❌ DB error saving model: {e}")
        return ConversationHandler.END

    context.user_data.clear()
    await query.message.reply_text(
        f"✅ Model saved!\n"
        f"{'─'*22}\n"
        f"Name:   {model['name']}\n"
        f"ID:     {model_id}\n"
        f"Status: inactive\n\n"
        f"Run backtest before activating:\n"
        f"  /activate {model_id}"
    )
    return ConversationHandler.END


# ── Cancel ────────────────────────────────────────────
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Wizard cancelled.")
    return ConversationHandler.END


# ── Build handler ─────────────────────────────────────
def build_wizard_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("create_model", create_model_start)],
        states={
            ASK_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, got_name)],
            ASK_PAIR:    [CallbackQueryHandler(got_pair,    pattern="^wiz:")],
            ASK_TF:      [CallbackQueryHandler(got_tf,      pattern="^wiz:")],
            ASK_SESSION: [CallbackQueryHandler(got_session, pattern="^wiz:")],
            ASK_BIAS:    [CallbackQueryHandler(got_bias,    pattern="^wiz:")],
            ASK_RULES:   [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_rule),
                CommandHandler("done", rules_done),
            ],
            ASK_TIERS:   [MessageHandler(filters.TEXT & ~filters.COMMAND, got_tiers)],
            CONFIRM:     [CallbackQueryHandler(confirm, pattern="^wiz_confirm:")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
