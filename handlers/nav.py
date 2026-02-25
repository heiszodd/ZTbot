from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def _kb(rows):
    return InlineKeyboardMarkup(rows)


def _btn(label, data):
    return InlineKeyboardButton(label, callback_data=data)


async def _edit_or_reply(query, text, kb):
    try:
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def show_home(update, context):
    from datetime import datetime, timezone
    import db
    from security.key_manager import key_exists
    from security.emergency_stop import is_halted

    now = datetime.now(timezone.utc)

    try:
        hl_pnl = db.get_hl_pnl_today()
    except Exception:
        hl_pnl = 0.0
    try:
        sol_pnl = db.get_sol_pnl_today()
    except Exception:
        sol_pnl = 0.0
    try:
        poly_cnt = db.count_open_poly_positions()
    except Exception:
        poly_cnt = 0
    try:
        pending = db.get_pending_signals(active_only=True)
    except Exception:
        pending = []
    try:
        hl_ok = key_exists("hl_api_wallet")
        sol_ok = key_exists("sol_hot_wallet")
        poly_ok = key_exists("poly_hot_wallet")
    except Exception:
        hl_ok = sol_ok = poly_ok = False

    halted = is_halted()

    hl_dot = "🟢" if hl_ok else "🔴"
    sol_dot = "🟢" if sol_ok else "🔴"
    poly_dot = "🟢" if poly_ok else "🔴"

    pending_cnt = len(pending)
    pending_str = f"  ⏳ {pending_cnt} pending signal{'s' if pending_cnt != 1 else ''}\n" if pending_cnt else ""

    halt_str = "\n🛑 *TRADING HALTED — /resume to restart*\n" if halted else ""

    text = (
        f"🤖 *Trading Intelligence Bot*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 {now.strftime('%a %b %d  %H:%M')} UTC"
        f"{halt_str}\n\n"
        f"*Performance Today*\n"
        f"  📈 Perps   {hl_dot}  ${hl_pnl:+.2f}\n"
        f"  🔥 Degen   {sol_dot}  ${sol_pnl:+.2f}\n"
        f"  🎯 Predict {poly_dot}  {poly_cnt} open\n"
        f"{pending_str}"
    )

    bottom_rows = []
    if pending_cnt > 0:
        bottom_rows.append([_btn("⏳ Pending Signals", "perps:pending")])
    bottom_rows.append([_btn("🔐 Security", "settings:security")])

    kb = _kb([
        [_btn("📈 Perps", "perps"), _btn("🔥 Degen", "degen")],
        [_btn("🎯 Predictions", "predictions"), _btn("⚙️ Settings", "settings")],
        *bottom_rows,
    ])

    if update.callback_query:
        try:
            await update.callback_query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            await update.callback_query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def show_security_status(update, context):
    from security.emergency_stop import is_halted
    from security.key_manager import key_exists
    from security.spending_limits import get_daily_summary

    halted = is_halted()
    spend = get_daily_summary()
    text = (
        "🔐 *Security Status*\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        + f"Trading: {'🛑 HALTED' if halted else '🟢 Active'}\n\n"
        + "*Wallets*\n"
        + f"HL:   {'🟢' if key_exists('hl_api_wallet') else '🔴'}\n"
        + f"SOL:  {'🟢' if key_exists('sol_hot_wallet') else '🔴'}\n"
        + f"POLY: {'🟢' if key_exists('poly_hot_wallet') else '🔴'}\n\n"
        + "*Today's Spend*\n"
    )
    for s, d in spend.items():
        text += f"  {s}: ${d['spent']:.2f} / ${d['limit']:.0f}\n"

    kb = _kb([[_btn("🏠 Home", "home")]])
    if update.callback_query:
        await _edit_or_reply(update.callback_query, text, kb)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def show_help(update, context):
    text = "❓ *Help*\n━━━━━━━━━━━━━━━━━━━━━━━━\nSelect a topic:"
    kb = _kb(
        [
            [_btn("📈 Perps", "help:perps"), _btn("🔥 Degen", "help:degen")],
            [_btn("🎯 Predictions", "help:predictions"), _btn("🔐 Wallets", "help:wallets")],
            [_btn("📊 Phase System", "help:phases"), _btn("🧩 Models", "help:models")],
            [_btn("💰 Risk", "help:risk"), _btn("⌨️ Commands", "help:commands")],
            [_btn("🏠 Home", "home")],
        ]
    )
    if update.callback_query:
        await _edit_or_reply(update.callback_query, text, kb)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def show_help_topic(query, context, topic):
    mapping = {
        "perps": "📈 *Perps Help*\n\nUse scanner, models, live/demo and pending flows.",
        "degen": "🔥 *Degen Help*\n\nPaste contract address or links for quick scans.",
        "predictions": "🎯 *Predictions Help*\n\nUse scanner and live/demo Polymarket flows.",
        "wallets": "🔐 *Wallet Setup*\n\nWallet secrets are encrypted and key-entry messages are deleted.",
        "phases": "📊 *Phase System*\n\nSignals move through phase 1→4; alerts fire at phase 4.",
        "models": "🧩 *Models Help*\n\nEach section supports independent model sets.",
        "risk": "💰 *Risk Management*\n\nUse hard limits + configurable risk settings.",
        "commands": "⌨️ *Commands*\n\n/start, /stop, /resume, /security, /help",
    }
    kb = _kb([[_btn("← Help", "help")], [_btn("🏠 Home", "home")]])
    await _edit_or_reply(query, mapping.get(topic, "Help topic not found."), kb)
