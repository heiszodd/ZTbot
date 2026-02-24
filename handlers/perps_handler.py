from telegram import InlineKeyboardButton as IKB, InlineKeyboardMarkup as IKM
import db


def _kb(rows): return IKM(rows)
def _btn(l, d): return IKB(l, callback_data=d)


async def _edit(query, text, kb):
    try:
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def show_perps_home(query, context):
    from security.key_manager import key_exists
    hl_ok = key_exists("hl_api_wallet")
    await _edit(query, "📈 *Perps*", _kb([
        [_btn("🔍 Scanner", "perps:scanner"), _btn("🧩 Models", "perps:models")],
        [_btn("📓 Journal", "perps:journal"), _btn("🔷 Live Account" + (" ✅" if hl_ok else " 🔴"), "perps:live")],
        [_btn("🎮 Demo Account", "perps:demo"), _btn("💰 Risk", "perps:risk")],
        [_btn("⏳ Pending", "perps:pending"), _btn("📦 Others", "perps:others")],
        [_btn("🏠 Home", "home")],
    ]))


async def show_perps_scanner(query, context):
    await _edit(query, "🔍 *Perps Scanner*", _kb([[_btn("⏳ Pending", "perps:pending")], [_btn("← Perps", "perps")]]))


async def show_perps_models(query, context):
    models = db.get_all_models()[:10]
    lines = "\n".join([f"• {m.get('name','?')}" for m in models]) or "No models yet."
    await _edit(query, f"🧩 *Perps Models*\n{lines}", _kb([[_btn("← Perps", "perps")]]))


async def show_perps_journal(query, context):
    entries = db.get_journal_entries(limit=5) or []
    lines = "\n".join([f"• {e.get('title','Untitled')}" for e in entries]) or "No journal entries yet."
    await _edit(query, f"📓 *Journal*\n{lines}", _kb([[_btn("← Perps", "perps")]]))


async def show_perps_live(query, context):
    from security.key_manager import key_exists
    if not key_exists("hl_api_wallet"):
        await _edit(query, "🔷 *Live Account — Hyperliquid*\nConnect wallet to trade.", _kb([[_btn("🔑 Connect Hyperliquid", "hl:connect")], [_btn("← Perps", "perps")]]))
        return
    address = db.get_hl_address() or ""
    positions = db.get_hl_positions(address) if address else []
    await _edit(query, f"🔷 *Hyperliquid*\nPositions: {len(positions)}", _kb([
        [_btn("🔄 Refresh", "hl:refresh"), _btn("📊 Positions", "hl:positions")],
        [_btn("📋 Orders", "hl:orders"), _btn("📈 Performance", "hl:performance")],
        [_btn("📜 History", "hl:history"), _btn("🌊 Funding", "hl:funding")],
        [_btn("🏪 Markets", "hl:markets")],
        [_btn("← Perps", "perps")],
    ]))


async def show_perps_demo(query, context):
    stats = db.get_demo_stats("hyperliquid") or {}
    await _edit(query, f"🎮 *Demo Account*\nBalance: ${stats.get('balance',10000):,.2f}", _kb([[_btn("← Perps", "perps")]]))


async def show_perps_risk(query, context):
    s = db.get_risk_settings() or {}
    await _edit(query, f"💰 *Risk*\nMax risk/trade: {s.get('max_risk_pct',1)}%", _kb([[_btn("← Perps", "perps")]]))


async def show_perps_pending(query, context):
    signals = db.get_pending_signals(section="perps", active_only=True) or []
    rows, text = [], "⏳ *Pending Signals*\n"
    for s in signals[:8]:
        sid = s.get("id", 0)
        text += f"• {s.get('pair','?')} P{s.get('phase','?')}\n"
        rows.append([_btn("📋 Plan", f"pending:plan:{sid}"), _btn("❌", f"pending:dismiss:{sid}")])
    rows.append([_btn("← Perps", "perps")])
    await _edit(query, text if signals else "⏳ *Pending Signals*\nNo pending signals.", _kb(rows))


async def show_perps_others(query, context):
    await _edit(query, "📦 *Perps — Others*", _kb([[_btn("← Perps", "perps")]]))


async def show_hl_positions(query, context):
    address = db.get_hl_address() or ""
    positions = db.get_hl_positions(address) if address else []
    rows, text = [], "📊 *Open Positions*\n"
    for p in positions:
        coin = p.get("coin", "?")
        text += f"• {coin}\n"
        rows.append([_btn("25%", f"hl:close:{coin}:25"), _btn("50%", f"hl:close:{coin}:50"), _btn("100%", f"hl:close:{coin}:100")])
    rows.append([_btn("← Live", "perps:live")])
    await _edit(query, text if positions else "📊 *Positions*\nNo open positions.", _kb(rows))


async def show_hl_orders(query, context):
    await _edit(query, "📋 *Open Orders*", _kb([[_btn("← Live", "perps:live")]]))


async def show_hl_performance(query, context):
    await _edit(query, "📈 *Performance*", _kb([[_btn("← Live", "perps:live")]]))


async def show_hl_history(query, context):
    await _edit(query, "📜 *Trade History*", _kb([[_btn("← Live", "perps:live")]]))


async def show_hl_funding(query, context):
    await _edit(query, "🌊 *Funding*", _kb([[_btn("← Live", "perps:live")]]))


async def show_hl_markets(query, context):
    await _edit(query, "🏪 *Markets*", _kb([[_btn("← Live", "perps:live")]]))


async def handle_hl_cancel(query, context, order_id):
    order = db.get_hl_order(order_id)
    if not order:
        await query.answer("Order not found", show_alert=True)
    else:
        from engine.hyperliquid.executor import cancel_order
        r = await cancel_order(order.get("coin", ""), int(order_id))
        await query.answer("✅ Order cancelled" if r.get("success") else r.get("error", "Failed"), show_alert=True)
    await show_hl_orders(query, context)


async def handle_hl_close(query, context, coin, pct):
    pos = db.get_hl_position_by_coin(coin)
    if not pos:
        await query.answer("Position not found", show_alert=True)
        return
    from engine.hyperliquid.executor import close_position
    r = await close_position(coin=coin, size=float(pos.get("size") or 0), is_long=(pos.get("side") == "Long"), pct=pct)
    await query.answer("✅ Closed" if r.get("success") else r.get("error", "Failed"), show_alert=True)
    await show_hl_positions(query, context)


async def handle_hl_live_trade(query, context, signal_id):
    await query.message.reply_text(f"Trade confirmation flow for signal {signal_id}.")


async def handle_hl_demo_trade(query, context, signal_id):
    await query.message.reply_text(f"Demo trade opened for signal {signal_id}.")


async def show_pending_plan(query, context, signal_id):
    signals = db.get_pending_signals(section="perps", active_only=True)
    signal = next((s for s in signals if int(s.get("id", 0)) == int(signal_id)), None)
    if not signal:
        await _edit(query, "Signal not found.", _kb([[_btn("← Pending", "perps:pending")]]))
        return
    sid = signal.get("id", signal_id)
    await _edit(query, f"📋 *Signal Plan*\nPair: {signal.get('pair','?')}", _kb([
        [_btn("📲 Live Trade", f"hl:live:{sid}"), _btn("🎮 Demo", f"hl:demo:{sid}")],
        [_btn("❌ Dismiss", f"pending:dismiss:{sid}")],
        [_btn("← Pending", "perps:pending")],
    ]))
