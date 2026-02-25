from telegram import InlineKeyboardButton as IKB, InlineKeyboardMarkup as IKM
import db


def _kb(rows):
    return IKM(rows)


def _btn(l, d):
    return IKB(l, callback_data=d)


async def _edit(query, text, kb):
    try:
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def show_predictions_home(query, context):
    from security.key_manager import key_exists

    try:
        poly_ok = key_exists("poly_hot_wallet")
    except Exception:
        poly_ok = False
    await _edit(query, "🎯 *Predictions*", _kb([
        [_btn("🔍 Scanner", "predictions:scanner"), _btn("⭐ Watchlist", "predictions:watchlist")],
        [_btn("💼 Live Predictions" + (" ✅" if poly_ok else " 🔴"), "predictions:live")],
        [_btn("🎮 Demo Predictions", "predictions:demo"), _btn("🧩 Models", "predictions:models")],
        [_btn("📦 Others", "predictions:others")],
        [_btn("🏠 Home", "home")],
    ]))


async def show_predictions_scanner(query, context):
    await _edit(query, "🔍 *Scanning markets...*", _kb([[_btn("← Predictions", "predictions")]]))
    try:
        from engine.polymarket.scanner import run_market_scanner, format_scanner_results
        markets = await run_market_scanner()
        text = format_scanner_results(markets)

        rows = []
        for i, m in enumerate(markets[:5]):
            mid = m.get("condition_id") or m.get("id") or str(i)
            q = (m.get("question") or "?")[:25]
            rows.append([
                _btn(f"📲 {q}", f"poly:detail:{mid}"),
                _btn("⭐ Watch", f"poly:watch:{mid}"),
            ])
        rows.append([_btn("🔄 Rescan", "predictions:scanner")])
        rows.append([_btn("← Predictions", "predictions")])
        await _edit(query, text, _kb(rows))
    except Exception as e:
        await _edit(query, f"🔍 *Prediction Scanner*\n\nError: {e}", _kb([[_btn("🔄 Retry", "predictions:scanner")], [_btn("← Predictions", "predictions")]]))


async def show_predictions_watchlist(query, context):
    items = db.get_poly_watchlist() or []
    lines = "\n".join([f"• {i.get('question','?')[:50]}" for i in items[:5]]) or "Watchlist is empty."
    await _edit(query, f"⭐ *Prediction Watchlist*\n{lines}", _kb([[_btn("← Predictions", "predictions")]]))


async def show_predictions_live(query, context):
    from security.key_manager import key_exists

    try:
        has_poly_wallet = key_exists("poly_hot_wallet")
    except Exception:
        has_poly_wallet = False

    if not has_poly_wallet:
        return await _edit(query, "💼 *Live Predictions — Polymarket*\nConnect wallet to trade.", _kb([[_btn("🔑 Connect Polymarket", "poly:connect")], [_btn("← Predictions", "predictions")]]))
    try:
        positions = db.get_open_poly_live_trades() or []
    except Exception:
        positions = []
    await _edit(query, f"💼 *Live Predictions*\nOpen: {len(positions)}", _kb([
        [_btn("🔄 Refresh", "predictions:live:refresh"), _btn("📊 All", "predictions:live:positions")],
        [_btn("📜 History", "predictions:live:history")],
        [_btn("← Predictions", "predictions")],
    ]))


async def show_predictions_demo(query, context):
    rows = db.get_open_poly_demo_trades() or []
    await _edit(query, f"🎮 *Demo Predictions*\nOpen: {len(rows)}", _kb([[_btn("← Predictions", "predictions")]]))


async def show_predictions_models(query, context):
    try:
        models = db.get_all_prediction_models() or []
    except Exception:
        models = []

    if not models:
        text = (
            "🧩 *Prediction Models*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "No prediction models yet.\n\n"
            "Prediction models define what\n"
            "makes a good YES or NO trade\n"
            "on Polymarket.\n\n"
            "Use a preset to get started."
        )
        kb = IKM([
            [IKB("📚 Use Preset", callback_data="predictions:models:presets")],
            [IKB("➕ Create Custom", callback_data="predictions:models:create")],
            [IKB("← Predictions", callback_data="predictions")],
        ])
        await _edit(query, text, kb)
        return

    active_cnt = sum(1 for m in models if m.get("active"))
    total = len(models)

    text = f"🧩 *Prediction Models*\n━━━━━━━━━━━━━━━━━━━━━━━━\nActive: {active_cnt}/{total}\n\n"
    rows = [[IKB("✅ Activate All", callback_data="predictions:models:all:on"), IKB("⭕ Deactivate All", callback_data="predictions:models:all:off")]]

    for m in models:
        mid = m["id"]
        name = m.get("name", "?")[:22]
        pos = m.get("position_type", "both")
        yes_mn = float(m.get("min_yes_pct", 0))
        yes_mx = float(m.get("max_yes_pct", 100))
        active = m.get("active", False)
        score = float(m.get("min_passing_score", 3))
        status = "✅" if active else "⭕"
        toggle = "Deactivate" if active else "Activate"
        toggle_cb = f"predictions:models:off:{mid}" if active else f"predictions:models:on:{mid}"
        pos_e = "YES" if pos == "YES" else "NO" if pos == "NO" else "YES/NO"
        text += f"{status} *{name}*\n   {pos_e}  YES {yes_mn:.0f}%-{yes_mx:.0f}%  Min score {score:.1f}pts\n"
        rows.append([IKB(f"📋 {name[:18]}", callback_data=f"predictions:models:view:{mid}"), IKB(toggle, callback_data=toggle_cb)])

    rows.append([IKB("➕ Create Model", callback_data="predictions:models:create"), IKB("📚 Presets", callback_data="predictions:models:presets")])
    rows.append([IKB("← Predictions", callback_data="predictions")])
    await _edit(query, text, IKM(rows))


async def show_prediction_model_detail(query, context, mid: int):
    model = None
    try:
        rows = db.get_all_prediction_models() or []
        model = next((m for m in rows if int(m.get("id", -1)) == int(mid)), None)
    except Exception:
        model = None

    if not model:
        await _edit(query, "Model not found.", IKM([[IKB("← Models", callback_data="predictions:models")]]))
        return

    name = model.get("name", "?")
    desc = model.get("description", "")
    active = model.get("active", False)
    pos = model.get("position_type", "both")
    yes_mn = model.get("min_yes_pct", 0)
    yes_mx = model.get("max_yes_pct", 100)
    vol = model.get("min_volume_24h", 0)
    days_mn = model.get("min_days_to_resolve", 1)
    days_mx = model.get("max_days_to_resolve", 30)
    size_mn = model.get("min_size_usd", 10)
    size_mx = model.get("max_size_usd", 100)
    score = float(model.get("min_passing_score", 3) or 3)
    auto = model.get("auto_trade", False)
    sigs = model.get("total_signals", 0)
    wr = model.get("win_rate", 0)

    status = "✅ Active" if active else "⭕ Inactive"
    toggle_lbl = "Deactivate" if active else "Activate"
    toggle_cb = f"predictions:models:off:{mid}" if active else f"predictions:models:on:{mid}"

    def fmt_vol(v):
        v = float(v or 0)
        if v >= 1_000_000:
            return f"${v/1_000_000:.1f}M"
        if v >= 1000:
            return f"${v/1000:.0f}K"
        return f"${v:.0f}"

    pos_desc = {
        "YES": "Buys YES positions only",
        "NO": "Buys NO positions only",
        "both": "Buys YES and NO positions",
    }.get(pos, pos)

    text = f"📋 *{name}*\n━━━━━━━━━━━━━━━━━━━━━━━━\nStatus: {status}\n"
    text += f"_{desc}_\n\n" if desc else "\n"
    text += (
        f"*Strategy:*\n"
        f"  {pos_desc}\n"
        f"  YES range: {yes_mn:.0f}%—{yes_mx:.0f}%\n"
        f"  Min volume: {fmt_vol(vol)}/24h\n"
        f"  Resolves in: {days_mn}—{days_mx} days\n"
        f"  Trade size: ${size_mn}—${size_mx}\n"
        f"  Min score: {score:.1f} confluence points\n\n"
        f"*Stats:*\n"
        f"  Signals: {sigs}  Win rate: {wr:.0f}%\n"
        f"  Auto-trade: {'🤖 ON' if auto else 'OFF'}\n"
    )

    kb = IKM([
        [IKB(toggle_lbl, callback_data=toggle_cb)],
        [IKB("🗑 Delete", callback_data=f"predictions:models:delete:{mid}")],
        [IKB("← Models", callback_data="predictions:models")],
    ])
    await _edit(query, text, kb)


async def show_prediction_model_presets(query, context):
    text = (
        "📚 *Prediction Model Presets*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📉 *Mean Reversion*\n"
        "   Markets near 50% — uncertain\n"
        "   outcome with high volume\n\n"
        "🎯 *Fade the Crowd*\n"
        "   Markets above 80% — buy NO\n"
        "   on overconfident consensus\n\n"
        "⚡ *Momentum Rider*\n"
        "   Rising probability markets\n"
        "   buy YES when trend is up\n\n"
        "🔗 *Crypto Correlation*\n"
        "   Crypto-specific markets\n"
        "   aligned with phase engine"
    )
    kb = IKM([
        [IKB("📉 Mean Reversion", callback_data="predictions:models:preset:mean")],
        [IKB("🎯 Fade the Crowd", callback_data="predictions:models:preset:fade")],
        [IKB("⚡ Momentum Rider", callback_data="predictions:models:preset:momentum")],
        [IKB("🔗 Crypto Correlation", callback_data="predictions:models:preset:crypto")],
        [IKB("← Models", callback_data="predictions:models")],
    ])
    await _edit(query, text, kb)


async def handle_prediction_model_preset(query, context, preset: str):
    presets = {
        "mean": {
            "name": "Mean Reversion",
            "description": "Uncertain markets near 50%.",
            "active": True,
            "position_type": "both",
            "min_yes_pct": 40,
            "max_yes_pct": 60,
            "min_volume_24h": 50000,
            "min_days_to_resolve": 1,
            "max_days_to_resolve": 14,
            "min_size_usd": 10,
            "max_size_usd": 50,
            "min_passing_score": 1.8,
            "weighted_checks": [
                {"check": "CHoCH", "tf": "1h", "weight": 1.0},
                {"check": "LiquiditySweep", "tf": "15m", "weight": 1.0},
                {"check": "FVG", "tf": "5m", "weight": 1.0},
            ],
        },
        "fade": {
            "name": "Fade the Crowd",
            "description": "Buy NO on overpriced consensus.",
            "active": True,
            "position_type": "NO",
            "min_yes_pct": 75,
            "max_yes_pct": 95,
            "min_volume_24h": 100000,
            "min_days_to_resolve": 1,
            "max_days_to_resolve": 7,
            "min_size_usd": 10,
            "max_size_usd": 100,
            "min_passing_score": 2.2,
            "weighted_checks": [
                {"check": "LiquiditySweep", "tf": "15m", "weight": 1.5},
                {"check": "CHoCH", "tf": "15m", "weight": 1.0},
                {"check": "FVG", "tf": "5m", "weight": 1.0},
            ],
        },
        "momentum": {
            "name": "Momentum Rider",
            "description": "Buy YES on rising probability.",
            "active": True,
            "position_type": "YES",
            "min_yes_pct": 20,
            "max_yes_pct": 55,
            "min_volume_24h": 75000,
            "min_days_to_resolve": 1,
            "max_days_to_resolve": 7,
            "min_size_usd": 25,
            "max_size_usd": 100,
            "min_passing_score": 2.3,
            "weighted_checks": [
                {"check": "BOS", "tf": "4h", "weight": 1.5},
                {"check": "FVG", "tf": "15m", "weight": 1.0},
                {"check": "FVG", "tf": "5m", "weight": 1.0},
            ],
        },
        "crypto": {
            "name": "Crypto Correlation",
            "description": "Crypto markets aligned with perps phase engine signals.",
            "active": True,
            "position_type": "both",
            "min_yes_pct": 30,
            "max_yes_pct": 70,
            "min_volume_24h": 25000,
            "min_days_to_resolve": 1,
            "max_days_to_resolve": 30,
            "min_size_usd": 10,
            "max_size_usd": 75,
            "min_passing_score": 2.0,
            "weighted_checks": [
                {"check": "BOS", "tf": "4h", "weight": 1.0},
                {"check": "MSS", "tf": "1h", "weight": 1.0},
                {"check": "FVG", "tf": "15m", "weight": 1.0},
            ],
        },
    }

    p = presets.get(preset)
    if not p:
        await query.answer("Unknown preset", show_alert=True)
        return

    try:
        existing = db.get_all_prediction_models() or []
        if any(m.get("name") == p["name"] for m in existing):
            await query.answer(f"{p['name']} already exists", show_alert=True)
            await show_predictions_models(query, context)
            return

        new_id = db.save_prediction_model(p)
        await query.answer(f"✅ {p['name']} added" if new_id else "Failed to save model", show_alert=True)
    except Exception as e:
        await query.answer(str(e), show_alert=True)
    await show_predictions_models(query, context)


async def handle_prediction_model_toggle(query, context, mid: int, on: bool):
    ok = db.toggle_prediction_model(mid, on)
    label = "activated" if on else "deactivated"
    if ok:
        await query.answer(label, show_alert=False)
    else:
        await query.answer("Toggle failed", show_alert=True)
    await show_prediction_model_detail(query, context, mid)


async def handle_prediction_models_all(query, context, on: bool):
    try:
        for m in (db.get_all_prediction_models() or []):
            db.toggle_prediction_model(int(m.get("id")), on)
        label = "activated" if on else "deactivated"
        await query.answer(f"All {label}", show_alert=False)
    except Exception as e:
        await query.answer(str(e), show_alert=True)
    await show_predictions_models(query, context)


async def handle_prediction_model_delete(query, context, mid: int):
    try:
        db.delete_prediction_model(mid)
        await query.answer("Model deleted", show_alert=False)
    except Exception as e:
        await query.answer(str(e), show_alert=True)
    await show_predictions_models(query, context)


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
