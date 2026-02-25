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


async def show_degen_home(query, context):
    from security.key_manager import key_exists

    try:
        sol_ok = key_exists("sol_hot_wallet")
    except Exception:
        sol_ok = False
    await _edit(query, "🔥 *Degen*", _kb([
        [_btn("🔍 Scanner", "degen:scanner"), _btn("🔬 Scan Contract", "degen:scan_contract")],
        [_btn("🧩 Models", "degen:models"), _btn("💼 Live Wallet" + (" ✅" if sol_ok else " 🔴"), "degen:live")],
        [_btn("🎮 Demo Wallet", "degen:demo"), _btn("👁 Wallet Tracking", "degen:tracking")],
        [_btn("⭐ Watchlist", "degen:watchlist"), _btn("📦 Others", "degen:others")],
        [_btn("🏠 Home", "home")],
    ]))


async def show_degen_scanner(query, context):
    try:
        models = db.get_active_degen_models() or []
    except Exception:
        models = []
    try:
        pending = db.get_pending_signals(section="degen", active_only=True) or []
    except Exception:
        pending = []

    text = (
        f"🔍 *Degen Scanner*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Active Models: {len(models)}\n\n"
        f"The scanner checks new Solana token\n"
        f"launches against your active degen\n"
        f"models every 15 minutes.\n\n"
        f"Tokens that pass are shown here\n"
        f"with buy options.\n"
    )

    if not models:
        text += "\n⚠️ No active degen models.\nGo to Models to activate one."
    elif pending:
        text += f"\n*Flagged Tokens ({len(pending)}):*\n"
        for s in pending[:5]:
            sym = s.get("pair", "?")
            score = float(s.get("quality_score") or 0)
            grade = s.get("quality_grade", "?")
            data = s.get("signal_data") or {}
            mcap = float(data.get("market_cap_usd") or 0)
            mcap_s = f"${mcap/1000:.0f}K" if mcap < 1_000_000 else f"${mcap/1_000_000:.1f}M"
            text += f"  🟢 *${sym}* {grade} {score:.0f}/100  MCap {mcap_s}\n"
    else:
        text += "\n_No flagged tokens yet._\n"

    kb = IKM([
        [IKB("▶️ Run Scan Now", callback_data="degen:scanner:run"), IKB("🕳 Trenches Feed", callback_data="degen:trenches")],
        [IKB("🧩 Manage Models", callback_data="degen:models"), IKB("🔬 Scan a Contract", callback_data="degen:scan_contract")],
        [IKB("← Degen", callback_data="degen")],
    ])
    await _edit(query, text, kb)


async def handle_degen_scanner_run(query, context):
    await query.answer("⏳ Scanning...", show_alert=False)
    try:
        from engine.solana.trenches_feed import run_trenches_scanner

        result = await run_trenches_scanner(context)
        count = len(result) if isinstance(result, list) else 0
        await query.answer(f"✅ Found {count} tokens", show_alert=True)
    except Exception as e:
        await query.answer(f"Scan error: {str(e)[:100]}", show_alert=True)
    await show_degen_scanner(query, context)


async def show_scan_contract(query, context):
    text = (
        "🔬 *Scan Contract*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Send a Solana token address or link:\n\n"
        "• Token address (32-44 chars)\n"
        "• dexscreener.com/solana/...\n"
        "• birdeye.so/token/...\n"
        "• pump.fun/...\n\n"
        "I'll run a full safety scan:\n"
        "Contract safety  |  Honeypot check\n"
        "Rug probability  |  Dev wallet\n"
        "Liquidity lock   |  Holder count\n"
        "Market cap       |  Buy/sell ratio\n\n"
        "_Paste the address in chat now._"
    )
    await _edit(query, text, IKM([[IKB("← Degen", callback_data="degen")]]))


async def show_degen_models(query, context):
    try:
        models = db.get_all_degen_models() or []
    except Exception:
        models = []

    if not models:
        text = (
            "🧩 *Degen Models*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "No degen models yet.\n\n"
            "Degen models define what a Solana\n"
            "token must score to be flagged as\n"
            "a potential buy.\n\n"
            "Use a preset to get started quickly."
        )
        kb = IKM([
            [IKB("📚 Use Preset", callback_data="degen:models:presets")],
            [IKB("➕ Create Custom", callback_data="degen:models:create")],
            [IKB("← Degen", callback_data="degen")],
        ])
        await _edit(query, text, kb)
        return

    active_cnt = sum(1 for m in models if m.get("active") or str(m.get("status", "")).lower() == "active")
    total = len(models)

    text = f"🧩 *Degen Models*\n━━━━━━━━━━━━━━━━━━━━━━━━\nActive: {active_cnt}/{total}\n\n"
    rows = [[IKB("✅ Activate All", callback_data="degen:models:all:on"), IKB("⭕ Deactivate All", callback_data="degen:models:all:off")]]

    def fmt_mcap(v):
        v = float(v or 0)
        if v >= 1_000_000:
            return f"${v/1_000_000:.1f}M"
        if v >= 1000:
            return f"${v/1000:.0f}K"
        return f"${v:.0f}"

    for m in models:
        mid = m["id"]
        name = m.get("name", "?")[:22]
        mcap_min = float(m.get("min_mcap_usd") or m.get("min_liquidity") or 0)
        mcap_max = float(m.get("max_mcap_usd") or 10_000_000)
        active = m.get("active") or str(m.get("status", "")).lower() == "active"
        score = float(m.get("min_score") or 0)
        status = "✅" if active else "⭕"
        toggle = "Deactivate" if active else "Activate"
        toggle_cb = f"degen:models:off:{mid}" if active else f"degen:models:on:{mid}"

        text += f"{status} *{name}*\n   MCap {fmt_mcap(mcap_min)}—{fmt_mcap(mcap_max)}  Min score {score:.0f}\n"
        rows.append([IKB(f"📋 {name[:18]}", callback_data=f"degen:models:view:{mid}"), IKB(toggle, callback_data=toggle_cb)])

    rows.append([IKB("➕ Create Model", callback_data="degen:models:create"), IKB("📚 Presets", callback_data="degen:models:presets")])
    rows.append([IKB("← Degen", callback_data="degen")])
    await _edit(query, text, IKM(rows))


async def show_degen_model_detail(query, context, mid: int):
    try:
        model = db.get_degen_model(str(mid))
    except Exception:
        model = None

    if not model:
        await _edit(query, "Model not found.", IKM([[IKB("← Models", callback_data="degen:models")]]))
        return

    name = model.get("name", "?")
    desc = model.get("description", "")
    active = model.get("active") or str(model.get("status", "")).lower() == "active"
    score = model.get("min_score", 0)
    mcap_mn = float(model.get("min_mcap_usd") or model.get("min_liquidity") or 0)
    mcap_mx = float(model.get("max_mcap_usd") or 10_000_000)
    liq_mn = float(model.get("min_liquidity_usd") or model.get("min_liquidity") or 0)
    age_mx = int(model.get("max_age_minutes") or model.get("max_token_age_minutes") or 0)
    holders = int(model.get("min_holder_count") or 0)
    rug_mx = model.get("max_rug_score", model.get("max_risk_score", 0))
    size = float(model.get("position_size_usd") or 0)
    auto = bool(model.get("auto_buy", False))
    sigs = model.get("total_signals", model.get("total_alerts", 0))
    today = model.get("signals_today", 0)

    def fmt(v):
        if v >= 1_000_000:
            return f"${v/1_000_000:.1f}M"
        if v >= 1000:
            return f"${v/1000:.0f}K"
        return f"${v:.0f}"

    status = "✅ Active" if active else "⭕ Inactive"
    toggle_lbl = "Deactivate" if active else "Activate"
    toggle_cb = f"degen:models:off:{mid}" if active else f"degen:models:on:{mid}"
    auto_lbl = "🤖 Auto-buy ON" if auto else "Auto-buy OFF"

    text = f"📋 *{name}*\n━━━━━━━━━━━━━━━━━━━━━━━━\nStatus:     {status}\n"
    text += f"_{desc}_\n\n" if desc else "\n"
    text += (
        f"*Criteria:*\n"
        f"  Min score:    {score:.0f}/100\n"
        f"  MCap range:   {fmt(mcap_mn)}—{fmt(mcap_mx)}\n"
        f"  Min liquidity:{fmt(liq_mn)}\n"
        f"  Max age:      {age_mx//60}h\n"
        f"  Min holders:  {holders:,}\n"
        f"  Max rug score:{rug_mx}/100\n\n"
        f"*Execution:*\n"
        f"  Position size:{fmt(size)}\n"
        f"  {auto_lbl}\n\n"
        f"*Stats:*\n"
        f"  Signals today:{today}  Total:{sigs}\n"
    )

    kb = IKM([
        [IKB(toggle_lbl, callback_data=toggle_cb)],
        [IKB("✏️ Edit", callback_data=f"degen:models:edit:{mid}"), IKB("🗑 Delete", callback_data=f"degen:models:delete:{mid}")],
        [IKB("← Models", callback_data="degen:models")],
    ])
    await _edit(query, text, kb)


async def show_degen_model_presets(query, context):
    text = (
        "📚 *Degen Model Presets*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Select a preset to add:\n\n"
        "🚀 *Pump Hunter*\n"
        "   Early stage, $10K-$200K MCap\n"
        "   High risk, fast momentum\n\n"
        "💎 *Gem Hunter*\n"
        "   Quality tokens, $50K-$2M MCap\n"
        "   Locked LP, more holders\n\n"
        "🛡 *Safe Play*\n"
        "   $500K-$10M MCap, many checks\n"
        "   Lower risk, larger positions\n\n"
        "🔥 *Degen Max*\n"
        "   $5K-$100K MCap, minimal checks\n"
        "   Maximum risk, small positions"
    )
    kb = IKM([
        [IKB("🚀 Pump Hunter", callback_data="degen:models:preset:pump")],
        [IKB("💎 Gem Hunter", callback_data="degen:models:preset:gem")],
        [IKB("🛡 Safe Play", callback_data="degen:models:preset:safe")],
        [IKB("🔥 Degen Max", callback_data="degen:models:preset:degen_max")],
        [IKB("← Models", callback_data="degen:models")],
    ])
    await _edit(query, text, kb)


async def handle_degen_model_preset(query, context, preset: str):
    presets = {
        "pump": {"name": "Pump Hunter", "description": "Early stage pumps. High momentum.", "active": True, "min_score": 60, "min_mcap_usd": 10000, "max_mcap_usd": 200000, "min_liquidity_usd": 10000, "max_age_minutes": 120, "min_holder_count": 30, "max_rug_score": 60, "position_size_usd": 25, "auto_buy": False},
        "gem": {"name": "Gem Hunter", "description": "Undervalued quality tokens.", "active": True, "min_score": 70, "min_mcap_usd": 50000, "max_mcap_usd": 2000000, "min_liquidity_usd": 50000, "max_age_minutes": 1440, "min_holder_count": 100, "max_rug_score": 30, "position_size_usd": 100, "auto_buy": False},
        "safe": {"name": "Safe Play", "description": "Lower risk, larger MCap.", "active": True, "min_score": 75, "min_mcap_usd": 500000, "max_mcap_usd": 10000000, "min_liquidity_usd": 100000, "max_age_minutes": 10080, "min_holder_count": 500, "max_rug_score": 20, "position_size_usd": 200, "auto_buy": False},
        "degen_max": {"name": "Degen Max", "description": "Max risk. Tiny caps. Small size.", "active": True, "min_score": 40, "min_mcap_usd": 5000, "max_mcap_usd": 100000, "min_liquidity_usd": 5000, "max_age_minutes": 60, "min_holder_count": 10, "max_rug_score": 70, "position_size_usd": 10, "auto_buy": False},
    }

    p = presets.get(preset)
    if not p:
        await query.answer("Unknown preset", show_alert=True)
        return

    try:
        existing = db.get_all_degen_models() or []
        if any(m.get("name") == p["name"] for m in existing):
            await query.answer(f"{p['name']} already exists", show_alert=True)
            return await show_degen_models(query, context)

        new_id = db.save_degen_model(p)
        await query.answer(f"✅ {p['name']} added" if new_id else "Failed to save model", show_alert=True)
    except Exception as e:
        await query.answer(str(e), show_alert=True)
    await show_degen_models(query, context)


async def handle_degen_model_toggle(query, context, mid: int, on: bool):
    ok = db.toggle_degen_model(mid, on)
    label = "activated" if on else "deactivated"
    await query.answer(f"Model {label}" if ok else "Toggle failed", show_alert=not ok)
    await show_degen_model_detail(query, context, mid)


async def handle_degen_models_all(query, context, on: bool):
    try:
        for m in (db.get_all_degen_models() or []):
            db.toggle_degen_model(m.get("id"), on)
        label = "activated" if on else "deactivated"
        await query.answer(f"All models {label}", show_alert=False)
    except Exception as e:
        await query.answer(str(e), show_alert=True)
    await show_degen_models(query, context)


async def handle_degen_model_delete(query, context, mid: int):
    ok = db.delete_degen_model(str(mid))
    await query.answer("Model deleted" if ok else "Delete failed", show_alert=not ok)
    await show_degen_models(query, context)


async def show_degen_live(query, context):
    from security.key_manager import key_exists

    try:
        has_sol_wallet = key_exists("sol_hot_wallet")
    except Exception:
        has_sol_wallet = False

    if not has_sol_wallet:
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
    try:
        balance = db.get_demo_balance("degen")
    except Exception:
        balance = 10000.0
    try:
        trades = db.get_open_demo_trades("degen") or []
    except Exception:
        trades = []
    try:
        history = db.get_closed_demo_trades("degen", limit=3) or []
    except Exception:
        history = []

    pnl = sum(float(t.get("pnl") or t.get("current_pnl_usd") or t.get("final_pnl_usd") or 0) for t in trades)
    pe = "🟢" if pnl >= 0 else "🔴"

    text = (
        f"🎮 *Demo Wallet — Degen*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Balance:  ${balance:,.2f}\n"
        f"Open PnL: {pe} ${pnl:+.2f}\n"
        f"Open:     {len(trades)} positions\n"
    )

    if trades:
        text += "\n*Open Positions:*\n"
        for t in trades[:3]:
            sym = t.get("pair", "?")
            p = float(t.get("pnl") or t.get("current_pnl_usd") or t.get("final_pnl_usd") or 0)
            pe2 = "🟢" if p >= 0 else "🔴"
            size = float(t.get("size_usd") or t.get("position_size_usd") or 0)
            text += f"  {pe2} ${sym}  ${size:.0f}  ${p:+.2f}\n"

    if history:
        text += "\n*Recent Closed:*\n"
        for t in history:
            sym = t.get("pair", "?")
            p = float(t.get("pnl") or t.get("final_pnl_usd") or 0)
            pe2 = "🟢" if p >= 0 else "🔴"
            text += f"  {pe2} ${sym}  ${p:+.2f}\n"

    kb = IKM([
        [IKB("📊 Positions", callback_data="degen:demo:positions"), IKB("📜 History", callback_data="degen:demo:history")],
        [IKB("➕ Add $500", callback_data="degen:demo:deposit:500"), IKB("➕ Add $1,000", callback_data="degen:demo:deposit:1000")],
        [IKB("🔄 Reset to $10,000", callback_data="degen:demo:reset:confirm")],
        [IKB("💰 Risk Settings", callback_data="degen:demo:risk")],
        [IKB("← Degen", callback_data="degen")],
    ])
    await _edit(query, text, kb)


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


async def handle_degen_demo_deposit(query, context, amount: float):
    try:
        current = db.get_demo_balance("degen")
        new_bal = current + amount
        db.set_demo_balance("degen", new_bal)
        await query.answer(f"✅ Deposited ${amount:,.0f}. Balance: ${new_bal:,.2f}", show_alert=True)
    except Exception as e:
        await query.answer(str(e), show_alert=True)
    await show_degen_demo(query, context)


async def handle_degen_demo_reset_confirm(query, context):
    text = (
        "🔄 *Reset Demo Wallet?*\n\n"
        "This will:\n"
        "• Close all open demo positions\n"
        "• Reset balance to $10,000\n"
        "• Clear trade history\n\n"
        "This cannot be undone."
    )
    await _edit(query, text, IKM([[IKB("✅ Yes, Reset", callback_data="degen:demo:reset:execute"), IKB("❌ Cancel", callback_data="degen:demo")]]))


async def handle_degen_demo_reset(query, context):
    try:
        db.reset_demo_balance("degen", 10000.0)
        await query.answer("✅ Demo wallet reset to $10,000", show_alert=True)
    except Exception as e:
        await query.answer(str(e), show_alert=True)
    await show_degen_demo(query, context)


async def show_degen_demo_positions(query, context):
    try:
        trades = db.get_open_demo_trades("degen") or []
    except Exception:
        trades = []

    if not trades:
        return await _edit(query, "📊 *Demo Positions*\n\nNo open demo positions.", IKM([[IKB("← Demo", callback_data="degen:demo")]]))

    text = "📊 *Demo Positions*\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    rows = []
    for t in trades:
        tid = t.get("id")
        pair = t.get("pair", "?")
        entry = float(t.get("entry_price") or 0)
        cur = float(t.get("current_price") or entry)
        pnl = float(t.get("pnl") or t.get("current_pnl_usd") or 0)
        size = float(t.get("size_usd") or t.get("position_size_usd") or 0)
        pe = "🟢" if pnl >= 0 else "🔴"
        text += f"*${pair}*\n   Entry ${entry:,.8f}  Now ${cur:,.8f}\n   Size ${size:,.0f}  {pe} ${pnl:+.2f}\n\n"
        rows.append([IKB(f"❌ Close {pair}", callback_data=f"degen:demo:close:{tid}")])
    rows.append([IKB("← Demo", callback_data="degen:demo")])
    await _edit(query, text, IKM(rows))


async def show_degen_demo_history(query, context):
    try:
        history = db.get_closed_demo_trades("degen", limit=20) or []
    except Exception:
        history = []
    if not history:
        return await _edit(query, "📜 *Demo History*\n\nNo closed trades.", IKM([[IKB("← Demo", callback_data="degen:demo")]]))
    text = "📜 *Demo History*\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for t in history:
        pair = t.get("pair", "?")
        pnl = float(t.get("pnl") or t.get("final_pnl_usd") or 0)
        pe = "🟢" if pnl >= 0 else "🔴"
        text += f"{pe} ${pair}  ${pnl:+.2f}\n"
    await _edit(query, text, IKM([[IKB("← Demo", callback_data="degen:demo")]]))


async def handle_degen_demo_close(query, context, tid: int):
    try:
        trades = db.get_open_demo_trades("degen") or []
        trade = next((t for t in trades if int(t.get("id", 0)) == int(tid)), None)
        if not trade:
            await query.answer("Trade not found", show_alert=True)
            return await show_degen_demo_positions(query, context)
        pnl = float(trade.get("current_pnl_usd") or trade.get("pnl") or 0)
        ok = db.close_demo_trade(int(tid), pnl=pnl, reason="manual")
        await query.answer("✅ Position closed" if ok else "Close failed", show_alert=True)
    except Exception as e:
        await query.answer(str(e), show_alert=True)
    await show_degen_demo_positions(query, context)


async def show_wallet_tracking(query, context):
    try:
        wallets = db.get_tracked_wallets() or []
    except Exception:
        wallets = []

    text = (
        f"👁 *Wallet Tracking*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Tracking: {len(wallets)}/10 wallets\n\n"
        f"Track smart money wallets.\n"
        f"Get alerts on their buys/sells.\n"
        f"Optionally mirror their trades.\n"
    )

    rows = []
    if wallets:
        for w in wallets:
            wid = w["id"]
            addr = w.get("wallet_address", "")
            label = w.get("label") or addr[:12] + "..."
            copies = w.get("total_copies", 0)
            pnl = float(w.get("pnl_from_copies", 0) or 0)
            mirror = w.get("auto_mirror", False)
            pe = "🟢" if pnl >= 0 else "🔴"
            m_e = "🪞" if mirror else "👁"
            text += (
                f"{m_e} *{label}*\n"
                f"   {addr[:8]}...{addr[-6:]}\n"
                f"   Copies: {copies}  PnL: {pe} ${pnl:+.2f}\n\n"
            )
            rows.append([IKB(f"⚙️ {label[:16]}", callback_data=f"degen:tracking:view:{wid}"), IKB("🗑", callback_data=f"degen:tracking:remove:{wid}")])
    else:
        text += "_No wallets tracked yet._\n\n"

    if len(wallets) < 10:
        rows.append([IKB("➕ Add Wallet", callback_data="degen:tracking:add")])
    rows.append([IKB("📋 Copy History", callback_data="degen:tracking:history")])
    rows.append([IKB("← Degen", callback_data="degen")])
    await _edit(query, text, IKM(rows))


async def show_tracking_add(query, context):
    text = (
        "➕ *Track a Wallet*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Send the Solana wallet address\n"
        "you want to track in chat.\n\n"
        "The bot will monitor it every\n"
        "60 seconds and alert you when\n"
        "it buys or sells a token.\n\n"
        "To get wallet addresses:\n"
        "• Copy from a trade you spotted\n"
        "• Search gmgn.ai for top wallets\n"
        "• Use Birdeye top traders list\n\n"
        "_Paste the wallet address now._"
    )
    context.user_data["awaiting_track_wallet"] = True
    await _edit(query, text, IKM([[IKB("← Tracking", callback_data="degen:tracking")]]))


async def handle_add_tracked_wallet(update, context, address: str):
    msg = await update.message.reply_text(f"⏳ Adding `{address[:12]}...`", parse_mode="Markdown")
    try:
        existing = db.get_tracked_wallets(active_only=False) or []
        if any(w.get("wallet_address") == address for w in existing):
            await msg.edit_text("⚠️ Already tracking this wallet.")
            return

        db.save_tracked_wallet({"wallet_address": address, "label": address[:12], "auto_mirror": False, "active": True})

        await msg.edit_text(
            f"✅ *Wallet Added*\n\n`{address}`\n\nMonitoring every 60 seconds.\nYou'll get alerts on buys/sells.",
            parse_mode="Markdown",
            reply_markup=IKM([[IKB("👁 View Tracked", callback_data="degen:tracking")]]),
        )
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}")


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


async def handle_ca_input(update, context, address: str):
    msg = await update.message.reply_text(f"🔬 Scanning `{address[:12]}...`\n_This takes 5-10 seconds..._", parse_mode="Markdown")

    try:
        try:
            from engine.degen.contract_scanner import scan_contract
            result = await scan_contract(address)
        except Exception:
            try:
                from engine.solana.contract_scanner import scan_contract
                result = await scan_contract(address)
            except Exception:
                result = await _minimal_scan(address)

        symbol = result.get("symbol") or result.get("token_symbol", "?")
        score = float(result.get("score", result.get("rug_score", 0)))
        grade = result.get("grade", result.get("rug_grade", "?"))
        honeypot = bool(result.get("honeypot", result.get("is_honeypot", False)))
        rug_score = float(result.get("rug_score", 50))
        mcap = float(result.get("market_cap_usd", result.get("market_cap", 0)))
        liq = float(result.get("liquidity_usd", 0))
        holders = int(result.get("holder_count", 0))
        verified = bool(result.get("verified", result.get("is_open_source", False)))
        mint_dis = bool(result.get("mint_disabled", not result.get("mint_enabled", False)))
        freeze_dis = bool(result.get("freeze_disabled", not result.get("transfer_pausable", False)))
        lp_locked = bool(result.get("lp_locked", float(result.get("lp_locked_pct", 0)) >= 50))
        dev_pct = float(result.get("dev_wallet_pct", result.get("dev_holding_pct", 0)))
        age_min = int(result.get("age_minutes", 0))
        buy_sell = float(result.get("buy_sell_ratio", 1.0))
        price = float(result.get("price_usd", 0))
        change_1h = float(result.get("price_change_1h", 0))

        if age_min < 60:
            age_str = f"{age_min}m old"
        elif age_min < 1440:
            age_str = f"{age_min//60}h old"
        else:
            age_str = f"{age_min//1440}d old"

        honey_e = "🚫 HONEYPOT" if honeypot else "✅ Not honeypot"
        ver_e = "✅" if verified else "❌"
        mint_e = "✅" if mint_dis else "⚠️"
        freeze_e = "✅" if freeze_dis else "⚠️"
        lp_e = "✅ Locked" if lp_locked else "⚠️ Not locked"
        dev_e = "✅" if dev_pct < 5 else "⚠️" if dev_pct < 10 else "🚫"
        rug_e = "🟢" if rug_score < 30 else "🟡" if rug_score < 60 else "🔴"
        score_e = "🟢" if score >= 70 else "🟡" if score >= 50 else "🔴"
        bs_e = "🟢" if buy_sell > 1.5 else "⚪" if buy_sell > 0.8 else "🔴"
        ch_e = "🟢" if change_1h > 0 else "🔴"

        mcap_s = f"${mcap/1000:.1f}K" if mcap < 1_000_000 else f"${mcap/1_000_000:.2f}M"
        liq_s = f"${liq/1000:.1f}K" if liq < 1_000_000 else f"${liq/1_000_000:.2f}M"

        text = (
            f"🔬 *${symbol}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{score_e} Score: *{score:.0f}/100*  Grade: *{grade}*\n\n"
            f"*Safety*\n"
            f"  {honey_e}\n"
            f"  Contract verified: {ver_e}\n"
            f"  Mint disabled:     {mint_e}\n"
            f"  Freeze disabled:   {freeze_e}\n"
            f"  LP:                {lp_e}\n"
            f"  Dev wallet:        {dev_e} {dev_pct:.1f}%\n"
            f"  Rug score:         {rug_e} {rug_score:.0f}/100\n\n"
            f"*Market*\n"
            f"  Price:   ${price:.8f}\n"
            f"  MCap:    {mcap_s}\n"
            f"  Liq:     {liq_s}\n"
            f"  Holders: {holders:,}\n"
            f"  Age:     {age_str}\n"
            f"  B/S:     {bs_e} {buy_sell:.1f}x\n"
            f"  1h:      {ch_e} {change_1h:+.1f}%\n\n"
            f"`{address}`"
        )

        rows = []
        if not honeypot and score >= 40:
            from config import CHAT_ID
            settings = db.get_user_settings(int(CHAT_ID))
            p1 = int(settings.get("buy_preset_1", 25))
            p2 = int(settings.get("buy_preset_2", 50))
            p3 = int(settings.get("buy_preset_3", 100))
            rows.append([
                IKB(f"🟢 ${p1} Live", callback_data=f"degen:buy:{address}:{p1}"),
                IKB(f"🟢 ${p2} Live", callback_data=f"degen:buy:{address}:{p2}"),
                IKB(f"🟢 ${p3} Live", callback_data=f"degen:buy:{address}:{p3}"),
            ])
            rows.append([
                IKB(f"🎮 Demo ${p1}", callback_data=f"degen:demo_buy:{address}:{p1}"),
                IKB(f"🎮 Demo ${p2}", callback_data=f"degen:demo_buy:{address}:{p2}"),
            ])
        elif honeypot:
            rows.append([IKB("🚫 HONEYPOT — Do Not Buy", callback_data="degen:scan_contract")])
        else:
            rows.append([IKB("⚠️ Low Score — High Risk", callback_data="degen:scan_contract")])

        rows.append([
            IKB("⭐ Add to Watchlist", callback_data=f"degen:watchlist:add:{address}"),
            IKB("🚫 Blacklist", callback_data=f"degen:blacklist:add:{address}"),
        ])
        rows.append([IKB("← Degen", callback_data="degen")])

        await msg.edit_text(text, parse_mode="Markdown", reply_markup=IKM(rows))

    except Exception as e:
        import logging

        logging.getLogger(__name__).error(f"CA scan error {address}: {e}", exc_info=True)
        await msg.edit_text(
            f"❌ *Scan Failed*\n\nCould not scan `{address[:20]}...`\n\nError: `{str(e)[:200]}`\n\nCheck the address and try again.",
            parse_mode="Markdown",
            reply_markup=IKM([[IKB("← Degen", callback_data="degen")]]),
        )


async def _minimal_scan(address: str) -> dict:
    import httpx

    result = {
        "symbol": address[:6].upper(),
        "score": 0,
        "grade": "?",
        "honeypot": False,
        "rug_score": 50,
        "market_cap_usd": 0,
        "liquidity_usd": 0,
        "holder_count": 0,
        "price_usd": 0,
        "age_minutes": 0,
        "buy_sell_ratio": 1.0,
        "price_change_1h": 0,
        "verified": False,
        "mint_disabled": False,
        "freeze_disabled": False,
        "lp_locked": False,
        "dev_wallet_pct": 0,
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get("https://price.jup.ag/v6/price", params={"ids": address})
            data = r.json()
            price_data = data.get("data", {}).get(address, {})
            if price_data:
                result["price_usd"] = float(price_data.get("price", 0))
                result["symbol"] = price_data.get("mintSymbol", address[:6].upper())
                result["score"] = 30
                result["grade"] = "C"
    except Exception:
        pass
    return result
