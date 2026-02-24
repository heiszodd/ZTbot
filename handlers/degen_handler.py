from telegram import InlineKeyboardButton as IKB, InlineKeyboardMarkup as IKM
import db


def _kb(rows): return IKM(rows)
def _btn(l, d): return IKB(l, callback_data=d)


async def _edit(query, text, kb):
    try:
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def show_degen_home(query, context):
    from security.key_manager import key_exists
    sol_ok = key_exists("sol_hot_wallet")
    await _edit(query, "🔥 *Degen*", _kb([
        [_btn("🔍 Scanner", "degen:scanner"), _btn("🔬 Scan Contract", "degen:scan_contract")],
        [_btn("🧩 Models", "degen:models"), _btn("💼 Live Wallet" + (" ✅" if sol_ok else " 🔴"), "degen:live")],
        [_btn("🎮 Demo Wallet", "degen:demo"), _btn("👁 Wallet Tracking", "degen:tracking")],
        [_btn("⭐ Watchlist", "degen:watchlist"), _btn("📦 Others", "degen:others")],
        [_btn("🏠 Home", "home")],
    ]))


async def show_degen_scanner(query, context):
    await _edit(query, "🔍 *Degen Scanner*", _kb([[_btn("🔬 Scan Contract", "degen:scan_contract")], [_btn("← Degen", "degen")]]))


async def show_scan_contract(query, context):
    await _edit(query, "🔬 *Scan Contract*\nSend a Solana contract address or supported link.", _kb([[_btn("← Degen", "degen")]]))


async def show_degen_models(query, context):
    models = db.get_active_degen_models() or []
    lines = "\n".join([f"• {m.get('name','?')}" for m in models[:8]]) or "No models yet."
    await _edit(query, f"🧩 *Degen Models*\n{lines}", _kb([[_btn("← Degen", "degen")]]))


async def show_degen_live(query, context):
    from security.key_manager import key_exists
    if not key_exists("sol_hot_wallet"):
        await _edit(query, "💼 *Live Wallet — Solana*\nConnect wallet to trade.", _kb([[_btn("🔑 Connect Solana Wallet", "sol:connect")], [_btn("← Degen", "degen")]]))
        return
    await _edit(query, "💼 *Live Wallet*", _kb([
        [_btn("🔄 Refresh", "degen:live:refresh"), _btn("📊 Positions", "degen:live:positions")],
        [_btn("💰 Buy", "degen:live:buy"), _btn("💸 Sell", "degen:live:sell")],
        [_btn("💰 Risk Settings", "degen:live:risk")],
        [_btn("← Degen", "degen")],
    ]))


async def show_live_risk(query, context):
    s = db.get_user_settings(query.message.chat_id)
    await _edit(query, f"💰 *Live Risk*\nSL: -{s.get('live_sl_pct',20)}%", _kb([[_btn("🛑 Set Stop Loss", "degen:live:risk:sl")], [_btn("⚡ Set Trailing", "degen:live:risk:trail")], [_btn("← Live Wallet", "degen:live")]]))


async def show_degen_demo(query, context):
    stats = db.get_demo_stats("solana") or {}
    await _edit(query, f"🎮 *Demo Wallet*\nBalance: ${stats.get('balance',10000):,.2f}", _kb([[_btn("💰 Risk Settings", "degen:demo:risk")], [_btn("← Degen", "degen")]]))


async def show_demo_risk(query, context):
    s = db.get_user_settings(query.message.chat_id)
    await _edit(query, f"💰 *Demo Risk*\nSL: -{s.get('demo_sl_pct',20)}%", _kb([[_btn("🛑 Set Stop Loss", "degen:demo:risk:sl")], [_btn("⚡ Set Trailing", "degen:demo:risk:trail")], [_btn("← Demo Wallet", "degen:demo")]]))


async def handle_live_risk_action(query, context, sub):
    chat_id = query.message.chat_id
    if sub.startswith("sl:"):
        db.update_user_settings(chat_id, {"live_sl_pct": int(sub.split(":", 1)[1])})
        await query.answer("✅ Saved", show_alert=True)
        return await show_live_risk(query, context)
    if sub.startswith("trail:"):
        db.update_user_settings(chat_id, {"live_trail_pct": int(sub.split(":", 1)[1])})
        await query.answer("✅ Saved", show_alert=True)
        return await show_live_risk(query, context)
    if sub == "sl":
        return await _edit(query, "Select live SL", _kb([[_btn("-10%", "degen:live:risk:sl:10"), _btn("-20%", "degen:live:risk:sl:20"), _btn("-30%", "degen:live:risk:sl:30")], [_btn("← Risk", "degen:live:risk")]]))
    if sub == "trail":
        return await _edit(query, "Select trailing", _kb([[_btn("10%", "degen:live:risk:trail:10"), _btn("20%", "degen:live:risk:trail:20"), _btn("30%", "degen:live:risk:trail:30")], [_btn("← Risk", "degen:live:risk")]]))
    await _edit(query, "Unknown action", _kb([[_btn("← Risk", "degen:live:risk")]]))


async def handle_demo_risk_action(query, context, sub):
    chat_id = query.message.chat_id
    if sub.startswith("sl:"):
        db.update_user_settings(chat_id, {"demo_sl_pct": int(sub.split(":", 1)[1])})
        await query.answer("✅ Saved", show_alert=True)
        return await show_demo_risk(query, context)
    if sub.startswith("trail:"):
        db.update_user_settings(chat_id, {"demo_trail_pct": int(sub.split(":", 1)[1])})
        await query.answer("✅ Saved", show_alert=True)
        return await show_demo_risk(query, context)
    if sub == "sl":
        return await _edit(query, "Select demo SL", _kb([[_btn("-10%", "degen:demo:risk:sl:10"), _btn("-20%", "degen:demo:risk:sl:20"), _btn("-30%", "degen:demo:risk:sl:30")], [_btn("← Risk", "degen:demo:risk")]]))
    await _edit(query, "Unknown action", _kb([[_btn("← Risk", "degen:demo:risk")]]))


async def show_wallet_tracking(query, context):
    items = db.get_tracked_wallets() or []
    lines = "\n".join([f"• {w.get('label','?')}" for w in items[:5]]) or "No wallets tracked."
    await _edit(query, f"👁 *Wallet Tracking*\n{lines}", _kb([[_btn("← Degen", "degen")]]))


async def show_degen_watchlist(query, context):
    items = db.get_solana_watchlist() or []
    lines = "\n".join([f"• {i.get('symbol','?')}" for i in items[:8]]) or "Watchlist is empty."
    await _edit(query, f"⭐ *Watchlist*\n{lines}", _kb([[_btn("← Degen", "degen")]]))


async def show_degen_others(query, context):
    await _edit(query, "📦 *Degen — Others*", _kb([[_btn("← Degen", "degen")]]))


async def show_buy_screen(query, context):
    await _edit(query, "💰 *Buy Token*\nPaste a contract address in chat.", _kb([[_btn("← Live Wallet", "degen:live")]]))


async def show_sell_screen(query, context):
    positions = db.get_all_open_sol_positions() or []
    rows = []
    text = "💸 *Sell — Select Position*\n"
    for p in positions:
        addr = p.get("token_address", "")
        sym = p.get("token_symbol", "?")
        rows.append([_btn(f"25% {sym}", f"degen:sell:{addr}:25"), _btn(f"50% {sym}", f"degen:sell:{addr}:50"), _btn(f"100% {sym}", f"degen:sell:{addr}:100")])
    rows.append([_btn("← Live", "degen:live")])
    await _edit(query, text if positions else "💸 *Sell Token*\nNo open positions.", _kb(rows))


async def show_autosell_config(query, context, address):
    await _edit(query, f"⚙️ *Auto Sell*\n{address[:8]}...", _kb([[_btn("← Live Wallet", "degen:live")]]))


async def show_position_detail(query, context, address):
    pos = db.get_sol_position(address)
    if not pos:
        return await _edit(query, "Position not found.", _kb([[_btn("← Live", "degen:live")]]))
    await _edit(query, f"📊 *{pos.get('token_symbol','?')}*", _kb([[_btn("⚙️ Auto Sell", f"sol:autosell:{address}")], [_btn("← Live", "degen:live")]]))


async def handle_quick_buy(query, context, address, amount):
    await query.answer("Buy flow submitted", show_alert=True)


async def handle_demo_buy(query, context, address, amount):
    await query.answer("Demo buy created", show_alert=True)


async def handle_ca_input(update, context, address):
    msg = await update.message.reply_text(f"🔬 Scanning `{address[:8]}...`", parse_mode="Markdown")
    settings = db.get_user_settings(update.effective_chat.id)
    p1 = settings.get("buy_preset_1", 25)
    p2 = settings.get("buy_preset_2", 50)
    p3 = settings.get("buy_preset_3", 100)
    await msg.edit_text(
        f"🔬 *Contract Scan*\n`{address}`",
        parse_mode="Markdown",
        reply_markup=IKM([
            [_btn(f"🟢 ${p1}", f"degen:buy:{address}:{p1}"), _btn(f"🟢 ${p2}", f"degen:buy:{address}:{p2}"), _btn(f"🟢 ${p3}", f"degen:buy:{address}:{p3}")],
            [_btn("🎮 Demo Buy", f"degen:demo_buy:{address}:{p1}")],
            [_btn("❌ Skip", "degen")],
        ]),
    )
