from telegram import InlineKeyboardButton as IKB, InlineKeyboardMarkup as IKM
import db


def _kb(rows): return IKM(rows)
def _btn(l, d): return IKB(l, callback_data=d)


async def _edit(query, text, kb):
    try:
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def show_predictions_home(query, context):
    from security.key_manager import key_exists
    poly_ok = key_exists("poly_hot_wallet")
    await _edit(query, "🎯 *Predictions*", _kb([
        [_btn("🔍 Scanner", "predictions:scanner"), _btn("⭐ Watchlist", "predictions:watchlist")],
        [_btn("💼 Live Predictions" + (" ✅" if poly_ok else " 🔴"), "predictions:live")],
        [_btn("🎮 Demo Predictions", "predictions:demo"), _btn("🧩 Models", "predictions:models")],
        [_btn("📦 Others", "predictions:others")],
        [_btn("🏠 Home", "home")],
    ]))


async def show_predictions_scanner(query, context):
    await _edit(query, "🔍 *Prediction Scanner*", _kb([[_btn("← Predictions", "predictions")]]))


async def show_predictions_watchlist(query, context):
    items = db.get_poly_watchlist() or []
    lines = "\n".join([f"• {i.get('question','?')[:50]}" for i in items[:5]]) or "Watchlist is empty."
    await _edit(query, f"⭐ *Prediction Watchlist*\n{lines}", _kb([[_btn("← Predictions", "predictions")]]))


async def show_predictions_live(query, context):
    from security.key_manager import key_exists
    if not key_exists("poly_hot_wallet"):
        return await _edit(query, "💼 *Live Predictions — Polymarket*\nConnect wallet to trade.", _kb([[_btn("🔑 Connect Polymarket", "poly:connect")], [_btn("← Predictions", "predictions")]]))
    positions = db.get_open_poly_live_trades() or []
    await _edit(query, f"💼 *Live Predictions*\nOpen: {len(positions)}", _kb([
        [_btn("🔄 Refresh", "predictions:live:refresh"), _btn("📊 All", "predictions:live:positions")],
        [_btn("📜 History", "predictions:live:history")],
        [_btn("← Predictions", "predictions")],
    ]))


async def show_predictions_demo(query, context):
    rows = db.get_open_poly_demo_trades() or []
    await _edit(query, f"🎮 *Demo Predictions*\nOpen: {len(rows)}", _kb([[_btn("← Predictions", "predictions")]]))


async def show_predictions_models(query, context):
    rows = db.get_active_prediction_models() or []
    lines = "\n".join([f"• {m.get('name','model')}" for m in rows[:8]]) or "No models yet."
    await _edit(query, f"🧩 *Prediction Models*\n{lines}", _kb([[_btn("← Predictions", "predictions")]]))


async def show_predictions_others(query, context):
    await _edit(query, "📦 *Predictions — Others*", _kb([[_btn("← Predictions", "predictions")]]))


async def show_live_positions(query, context):
    rows = db.get_open_poly_live_trades() or []
    text, kb_rows = "📊 *All Live Positions*\n", []
    for r in rows:
        mid = r.get("market_id", "")
        text += f"• {r.get('position','?')} {r.get('question','?')[:32]}\n"
        kb_rows.append([_btn("💸 Close", f"poly:close:{mid}")])
    kb_rows.append([_btn("← Live", "predictions:live")])
    await _edit(query, text if rows else "📊 *All Live Positions*\nNo open positions.", _kb(kb_rows))


async def show_live_history(query, context):
    # fallback using demo history if dedicated helper absent
    rows = db.get_poly_demo_trades(status="closed") or []
    text = "📜 *Trade History*\n" + ("\n".join([f"• {r.get('question','?')[:42]}" for r in rows[:10]]) or "No trade history.")
    await _edit(query, text, _kb([[_btn("← Live", "predictions:live")]]))


async def handle_poly_live_trade(query, context, market_id, position, amount):
    from engine.polymarket.executor import execute_poly_trade
    result = await execute_poly_trade({"market_id": market_id, "position": position, "size_usd": amount})
    if result.get("success"):
        db.save_poly_live_trade({"market_id": market_id, "question": market_id, "position": position, "token_id": "", "entry_price": result.get("price", 0.5), "size_usd": amount, "shares": result.get("shares", 0), "order_id": result.get("order_id", ""), "status": "open"})
        await query.answer("✅ Trade executed", show_alert=True)
    else:
        await query.answer(result.get("error", "Failed"), show_alert=True)


async def handle_poly_demo_trade(query, context, market_id):
    db.create_poly_demo_trade({"market_id": market_id, "question": market_id, "position": "YES", "entry_price": 0.5, "size_usd": 25, "shares": 50, "status": "open"})
    await query.answer("🎮 Demo trade opened", show_alert=True)


async def handle_poly_close(query, context, market_id):
    open_trade = db.get_poly_live_trade(market_id)
    if not open_trade:
        return await query.answer("No open position", show_alert=True)
    from engine.polymarket.executor import close_poly_position
    result = await close_poly_position(market_id, open_trade.get("token_id", ""), float(open_trade.get("shares", 0)), open_trade.get("position", "YES"))
    if result.get("success"):
        db.update_poly_live_trade(int(open_trade["id"]), {"status": "closed", "closed_at": __import__('datetime').datetime.utcnow()})
        await query.answer("✅ Position closed", show_alert=True)
    else:
        await query.answer(result.get("error", "Failed"), show_alert=True)
