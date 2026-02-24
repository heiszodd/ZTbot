from telegram import InlineKeyboardButton as IKB, InlineKeyboardMarkup as IKM


def _kb(rows): return IKM(rows)
def _btn(l, d): return IKB(l, callback_data=d)


async def _edit(query, text, kb):
    try:
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def show_settings(query, context):
    await _edit(query, "⚙️ *Settings*", _kb([
        [_btn("🔐 Wallet Status", "settings:wallets"), _btn("🛡 Security", "settings:security")],
        [_btn("💸 Limits", "settings:limits")],
        [_btn("🏠 Home", "home")],
    ]))


async def show_wallet_status(query, context):
    from security.key_manager import key_exists
    text = (
        "🔐 *Wallet Status*\n"
        f"HL: {'✅' if key_exists('hl_api_wallet') else '❌'}\n"
        f"SOL: {'✅' if key_exists('sol_hot_wallet') else '❌'}\n"
        f"POLY: {'✅' if key_exists('poly_hot_wallet') else '❌'}"
    )
    await _edit(query, text, _kb([[_btn("← Settings", "settings")]]))


async def show_limits(query, context):
    from security.spending_limits import MAX_DAILY_SPEND_USD, MAX_SINGLE_TRADE_USD
    text = (
        "💸 *Limits*\n"
        f"Single trade: {MAX_SINGLE_TRADE_USD}\n"
        f"Daily spend: {MAX_DAILY_SPEND_USD}"
    )
    await _edit(query, text, _kb([[_btn("← Settings", "settings")]]))
