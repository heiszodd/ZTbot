import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import db, engine, formatters, prices as px
from config import CHAT_ID, SUPPORTED_PAIRS

log = logging.getLogger(__name__)


def _guard(update: Update) -> bool:
    return update.effective_chat.id == CHAT_ID


def main_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏠 Home",         callback_data="nav:home"),
            InlineKeyboardButton("⚙️ Models",        callback_data="nav:models"),
        ],
        [
            InlineKeyboardButton("📊 Stats",         callback_data="nav:stats"),
            InlineKeyboardButton("🛡️ Discipline",    callback_data="nav:discipline"),
        ],
        [
            InlineKeyboardButton("📋 Alert Log",     callback_data="nav:alerts"),
            InlineKeyboardButton("💹 Prices",        callback_data="nav:prices"),
        ],
        [
            InlineKeyboardButton("⚡ Status",        callback_data="nav:status"),
            InlineKeyboardButton("➕ New Model",     callback_data="wiz:start"),
        ],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    await _render_home(update.message.reply_text)


async def _render_home(reply_fn):
    active   = db.get_active_models()
    setups   = db.get_recent_alerts(hours=2, limit=5)
    all_pairs = list({m["pair"] for m in active}) + SUPPORTED_PAIRS[:5]
    live_px  = px.fetch_prices(list(set(all_pairs)))
    text     = formatters.fmt_home(active, setups, live_px)
    await reply_fn(text, reply_markup=main_kb(), parse_mode="Markdown")


async def handle_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    dest = query.data.split(":")[1]

    if dest == "home":
        active   = db.get_active_models()
        setups   = db.get_recent_alerts(hours=2, limit=5)
        all_pairs = list({m["pair"] for m in active}) + SUPPORTED_PAIRS[:5]
        live_px  = px.fetch_prices(list(set(all_pairs)))
        text     = formatters.fmt_home(active, setups, live_px)
        await query.message.reply_text(text, reply_markup=main_kb(), parse_mode="Markdown")

    elif dest == "models":
        await _render_models(query)

    elif dest == "stats":
        row      = db.get_stats_30d()
        tiers    = db.get_tier_breakdown()
        sessions = db.get_session_breakdown()
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="nav:home")]])
        await query.message.reply_text(
            formatters.fmt_stats(row, tiers, sessions),
            reply_markup=kb, parse_mode="Markdown"
        )

    elif dest == "discipline":
        violations = db.get_violations_30d()
        score      = _disc_score(violations)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="nav:home")]])
        await query.message.reply_text(
            formatters.fmt_discipline(score, violations),
            reply_markup=kb, parse_mode="Markdown"
        )

    elif dest == "alerts":
        alerts = db.get_recent_alerts(hours=24, limit=15)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="nav:home")]])
        await query.message.reply_text(
            formatters.fmt_alert_log(alerts),
            reply_markup=kb, parse_mode="Markdown"
        )

    elif dest == "prices":
        live_px = px.fetch_prices(SUPPORTED_PAIRS)
        lines   = ["💹 *Live Prices*", "─" * 26]
        for pair in SUPPORTED_PAIRS:
            if pair in live_px:
                lines.append(f"  `{pair:<12}` {px.fmt_price(live_px[pair])}")
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 Refresh", callback_data="nav:prices"),
                InlineKeyboardButton("🏠 Home",    callback_data="nav:home"),
            ]
        ])
        await query.message.reply_text(
            "\n".join(lines), reply_markup=kb, parse_mode="Markdown"
        )

    elif dest == "status":
        session = engine.get_session()
        active  = len(db.get_active_models())
        try:
            db.get_conn().close(); db_ok = True
        except Exception:
            db_ok = False
        prices_ok = bool(px.fetch_prices(["BTCUSDT"]))
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="nav:home")]])
        await query.message.reply_text(
            formatters.fmt_status(session, db_ok, active, prices_ok),
            reply_markup=kb, parse_mode="Markdown"
        )


async def _render_models(query):
    models  = db.get_all_models()
    pairs   = [m["pair"] for m in models]
    live_px = px.fetch_prices(pairs)
    text    = formatters.fmt_models(models, live_px)

    rows = []
    for m in models:
        dot = "🟢" if m["status"] == "active" else "⚫"
        rows.append([InlineKeyboardButton(
            f"{dot}  {m['name']}  ({m['pair']})",
            callback_data=f"model:detail:{m['id']}"
        )])
    rows.append([InlineKeyboardButton("➕ New Model", callback_data="wiz:start")])
    rows.append([InlineKeyboardButton("🏠 Home",      callback_data="nav:home")])

    await query.message.reply_text(
        text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown"
    )


async def handle_model_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    parts  = query.data.split(":")
    action = parts[1]

    if action == "detail":
        model_id = parts[2]
        m = db.get_model(model_id)
        if not m:
            await query.message.reply_text("❌ Model not found.")
            return
        price    = px.get_price(m["pair"])
        text     = formatters.fmt_model_detail(m, price)
        is_active = m["status"] == "active"
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⏸ Deactivate" if is_active else "✅ Activate",
                    callback_data=f"model:toggle:{model_id}"
                ),
                InlineKeyboardButton("🗑 Delete", callback_data=f"model:del_confirm:{model_id}"),
            ],
            [InlineKeyboardButton("« Back", callback_data="nav:models")],
        ])
        await query.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

    elif action == "toggle":
        model_id   = parts[2]
        m          = db.get_model(model_id)
        new_status = "inactive" if m["status"] == "active" else "active"
        db.set_model_status(model_id, new_status)
        if new_status == "active":
            await query.message.reply_text(
                f"✅ *{m['name']}* is now *active*\n\n"
                f"🔍 Scanning `{m['pair']}` every 60 seconds.\n"
                f"You'll be notified when a setup is found.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⚙️ Models", callback_data="nav:models"),
                    InlineKeyboardButton("🏠 Home",   callback_data="nav:home"),
                ]])
            )
        else:
            await query.message.reply_text(
                f"⏸ *{m['name']}* deactivated.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⚙️ Models", callback_data="nav:models"),
                    InlineKeyboardButton("🏠 Home",   callback_data="nav:home"),
                ]])
            )

    elif action == "del_confirm":
        model_id = parts[2]
        m = db.get_model(model_id)
        await query.message.reply_text(
            f"🗑 Delete *{m['name']}*?\n_This cannot be undone._",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Yes, delete", callback_data=f"model:delete:{model_id}"),
                InlineKeyboardButton("❌ Cancel",      callback_data=f"model:detail:{model_id}"),
            ]])
        )

    elif action == "delete":
        model_id = parts[2]
        m = db.get_model(model_id)
        db.delete_model(model_id)
        await query.message.reply_text(
            f"🗑 *{m['name']}* deleted.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⚙️ Models", callback_data="nav:models"),
                InlineKeyboardButton("🏠 Home",   callback_data="nav:home"),
            ]])
        )


async def handle_scan_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pair  = query.data.split(":")[1]

    await query.message.reply_text(f"🔍 Scanning `{pair}`...", parse_mode="Markdown")

    active = db.get_active_models()
    found  = 0
    for m in [x for x in active if x["pair"] == pair]:
        from handlers.alerts import _evaluate_and_send
        sent = await _evaluate_and_send(query.get_bot(), m, force=True)
        if sent:
            found += 1

    if found == 0:
        price = px.get_price(pair)
        await query.message.reply_text(
            f"📭 *No setup found for `{pair}`*\n"
            f"💹 Price: {px.fmt_price(price)}\n\n"
            f"Rules not met or score below Tier C threshold.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔄 Scan Again", callback_data=f"scan:{pair}"),
                    InlineKeyboardButton("🏠 Home",       callback_data="nav:home"),
                ]
            ])
        )


async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _guard(update): return
    active = db.get_active_models()
    if not active:
        await update.message.reply_text(
            "⚙️ *No active models*\n\nActivate a model first to start scanning.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⚙️ Models", callback_data="nav:models")
            ]])
        )
        return

    pair_set = list({m["pair"] for m in active})
    rows = []
    for i in range(0, len(pair_set), 2):
        rows.append([
            InlineKeyboardButton(pair_set[j], callback_data=f"scan:{pair_set[j]}")
            for j in range(i, min(i + 2, len(pair_set)))
        ])
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="nav:home")])
    await update.message.reply_text(
        "🔍 *Manual Scan*\n\nChoose a pair:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows)
    )


def _disc_score(violations):
    score = 100
    for v in violations:
        score -= 10 if v["violation"] in ("V1", "V3", "V4") else 5
    return max(0, score)
