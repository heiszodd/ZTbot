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


async def show_perps_home(query, context):
    from security.key_manager import key_exists

    try:
        hl_ok = key_exists("hl_api_wallet")
    except Exception:
        hl_ok = False
    await _edit(query, "📈 *Perps*", _kb([
        [_btn("🔍 Scanner", "perps:scanner"), _btn("🧩 Models", "perps:models")],
        [_btn("📓 Journal", "perps:journal"), _btn("🔷 Live Account" + (" ✅" if hl_ok else " 🔴"), "perps:live")],
        [_btn("🎮 Demo Account", "perps:demo"), _btn("💰 Risk", "perps:risk")],
        [_btn("⏳ Pending", "perps:pending"), _btn("📦 Others", "perps:others")],
        [_btn("🏠 Home", "home")],
    ]))


async def show_perps_scanner(query, context):
    try:
        models = db.get_all_models() or []
    except Exception:
        models = []
    active = [m for m in models if m.get("active") or str(m.get("status", "")).lower() == "active"]
    try:
        pending = db.get_pending_signals(section="perps", active_only=True) or []
    except Exception:
        pending = []

    text = (
        f"🔍 *Perps Scanner*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Active Models: {len(active)}/{len(models)}\n"
        f"Pending Signals: {len(pending)}\n\n"
        f"Scanner runs every 5 minutes.\n"
        f"Phase 4 signals fire a Telegram alert.\n"
        f"Phase 1-3 appear in Pending.\n"
    )

    if active:
        text += "\n*Scanning:*\n"
        for m in active[:5]:
            text += f"  ✅ {m.get('name','?')} — {m.get('pair','?')} {m.get('timeframe','?')}\n"
        if len(active) > 5:
            text += f"  ...and {len(active)-5} more\n"
    else:
        text += "\n⚠️ No active models. Activate at least one model to start scanning.\n"

    if pending:
        text += "\n*Recent Signals:*\n"
        for s in pending[:3]:
            pair = s.get("pair", "?")
            phase = s.get("phase", "?")
            dirn = s.get("direction", "?")
            e = "🟢" if "bull" in str(dirn).lower() else "🔴"
            text += f"  {e} {pair} Phase {phase} — {dirn}\n"

    kb = IKM([
        [IKB("▶️ Run Now", callback_data="perps:scanner:run"), IKB("⏳ Pending", callback_data="perps:pending")],
        [IKB("🧩 Manage Models", callback_data="perps:models")],
        [IKB("← Perps", callback_data="perps")],
    ])
    await _edit(query, text, kb)


async def handle_perps_scanner_run(query, context):
    await query.answer("⏳ Running scanner...", show_alert=False)
    try:
        try:
            from engine.phase_engine import run_phase_scanner
            await run_phase_scanner(context)
        except Exception:
            from engine.phase_engine import run_phase_engine
            await run_phase_engine(context)
        await query.answer("✅ Scan complete. Check Pending.", show_alert=True)
    except Exception as e:
        await query.answer(f"Scanner error: {str(e)[:100]}", show_alert=True)
    await show_perps_scanner(query, context)


async def _first_model_table_with_data() -> tuple[str | None, list]:
    from psycopg2 import sql

    for table in ("models", "trading_models", "perps_models"):
        try:
            with db.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL("SELECT * FROM {} ORDER BY created_at NULLS LAST, id").format(sql.Identifier(table))
                    )
                    rows = [dict(r) for r in cur.fetchall()]
                    if rows:
                        return table, rows
        except Exception:
            continue
    return None, []


async def _detect_model_table() -> str | None:
    from psycopg2 import sql

    for table in ("models", "trading_models", "perps_models"):
        try:
            with db.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql.SQL("SELECT 1 FROM {} LIMIT 1").format(sql.Identifier(table)))
                    cur.fetchone()
                conn.commit()
            return table
        except Exception:
            continue
    return None


async def show_perps_models(query, context):
    _, models = await _first_model_table_with_data()

    if not models:
        text = (
            "🧩 *Perps Models*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "No models yet.\n\n"
            "Create your first model to start\n"
            "scanning for trade setups.\n\n"
            "_Tap Create Model to get started._"
        )
        kb = IKM([
            [IKB("➕ Create Model", callback_data="perps:models:create")],
            [IKB("← Perps", callback_data="perps")],
        ])
        await _edit(query, text, kb)
        return

    active_cnt = sum(1 for m in models if m.get("active", False) or str(m.get("status", "")).lower() == "active")
    total = len(models)

    text = (
        f"🧩 *Perps Models*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Active: {active_cnt}/{total}\n\n"
    )

    rows = [[IKB("✅ Activate All", callback_data="perps:models:all:on"), IKB("⭕ Deactivate All", callback_data="perps:models:all:off")]]

    for m in models:
        mid = m.get("id", 0)
        name = (m.get("name") or "?")[:22]
        pair = m.get("pair", "?")
        tf = m.get("timeframe", "?")
        active = m.get("active", False) or str(m.get("status", "")).lower() == "active"
        grade = m.get("grade") or m.get("quality_grade") or ""
        status = "✅" if active else "⭕"
        toggle = "Deactivate" if active else "Activate"
        toggle_cb = f"perps:models:off:{mid}" if active else f"perps:models:on:{mid}"
        grade_str = f" {grade}" if grade else ""
        text += f"{status} *{name}*{grade_str}\n   {pair} · {tf}\n"
        rows.append([
            IKB(f"📋 {name[:18]}", callback_data=f"perps:models:view:{mid}"),
            IKB(toggle, callback_data=toggle_cb),
        ])

    rows.append([IKB("➕ Create Model", callback_data="perps:models:create"), IKB("📚 Presets", callback_data="perps:models:create")])
    rows.append([IKB("← Perps", callback_data="perps")])
    await _edit(query, text, IKM(rows))


async def show_perps_model_detail(query, context, mid):
    model = None
    try:
        model = db.get_model(mid)
    except Exception:
        model = None

    if not model:
        await _edit(query, "Model not found.", IKM([[IKB("← Models", callback_data="perps:models")]]))
        return

    name = model.get("name", "?")
    pair = model.get("pair", "?")
    tf = model.get("timeframe", "?")
    active = model.get("active") or str(model.get("status", "")).lower() == "active"
    grade = model.get("grade") or model.get("quality_grade") or "?"
    score = model.get("score", model.get("min_score", 0))
    desc = model.get("description", "")
    rules = model.get("rules") or model.get("weighted_rules") or []
    phase1 = model.get("phase1_rules") or []
    phase2 = model.get("phase2_rules") or []
    phase3 = model.get("phase3_rules") or []
    phase4 = model.get("phase4_rules") or []

    status = "✅ Active" if active else "⭕ Inactive"
    toggle_label = "Deactivate" if active else "Activate"
    toggle_cb = f"perps:models:off:{mid}" if active else f"perps:models:on:{mid}"

    text = (
        f"📋 *{name}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Status:    {status}\n"
        f"Pair:      {pair}\n"
        f"Timeframe: {tf}\n"
        f"Grade:     {grade}  Score: {score}\n"
    )

    if desc:
        text += f"\n_{desc}_\n"

    if phase1 or phase2 or phase3 or phase4:
        text += "\n*Phase Rules:*\n"
        if phase1:
            text += f"P1: {_format_rules(phase1)}\n"
        if phase2:
            text += f"P2: {_format_rules(phase2)}\n"
        if phase3:
            text += f"P3: {_format_rules(phase3)}\n"
        if phase4:
            text += f"P4: {_format_rules(phase4)}\n"
    elif rules:
        text += f"\n*Rules ({len(rules)}):*\n"
        for r in rules[:8]:
            if isinstance(r, dict):
                rname = (r.get("name") or r.get("rule_id") or str(r))[:40]
                w = r.get("weight", "")
            else:
                rname = str(r)[:40]
                w = ""
            wstr = f" (w:{w})" if w != "" else ""
            text += f"  • {rname}{wstr}\n"

    total = model.get("total_signals", 0)
    today = model.get("signals_today", 0)
    if total or today:
        text += f"\n*Signals:*\n  Today: {today}  Total: {total}\n"

    rows = [
        [IKB(toggle_label, callback_data=toggle_cb)],
        [IKB("🗑 Delete", callback_data=f"perps:models:delete:{mid}")],
        [IKB("← Models", callback_data="perps:models")],
    ]
    await _edit(query, text, IKM(rows))


def _format_rules(rules: list) -> str:
    if not rules:
        return "none"
    names = []
    for r in rules[:4]:
        if isinstance(r, dict):
            n = (r.get("name") or r.get("rule_id") or "?")
            names.append(n[:20])
        else:
            names.append(str(r)[:20])
    suffix = f" +{len(rules)-4} more" if len(rules) > 4 else ""
    return ", ".join(names) + suffix


async def handle_perps_model_toggle(query, context, mid: int, on: bool):
    from psycopg2 import sql

    toggled = False
    for table in ("models", "trading_models", "perps_models"):
        try:
            with db.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL("UPDATE {} SET active=%s, status=%s WHERE id=%s RETURNING id").format(sql.Identifier(table)),
                        (bool(on), "active" if on else "inactive", int(mid)),
                    )
                    row = cur.fetchone()
                conn.commit()
            if row:
                toggled = True
                break
        except Exception:
            continue

    label = "activated" if on else "deactivated"
    if toggled:
        await query.answer(f"✅ Model {label}", show_alert=False)
    else:
        await query.answer("Toggle failed — check logs", show_alert=True)
    await show_perps_models(query, context)


async def handle_perps_models_all(query, context, on: bool):
    from psycopg2 import sql

    updated = False
    for table in ("models", "trading_models", "perps_models"):
        try:
            with db.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL("UPDATE {} SET active=%s, status=%s WHERE id <> %s RETURNING id").format(sql.Identifier(table)),
                        (bool(on), "active" if on else "inactive", 0),
                    )
                    rows = cur.fetchall()
                conn.commit()
            if rows is not None:
                updated = True
                break
        except Exception:
            continue

    label = "activated" if on else "deactivated"
    if updated:
        await query.answer(f"All models {label}", show_alert=False)
    else:
        await query.answer("Update failed", show_alert=True)
    await show_perps_models(query, context)


async def handle_perps_model_delete(query, context, mid: int):
    from psycopg2 import sql

    deleted = False
    for table in ("models", "trading_models", "perps_models"):
        try:
            with db.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql.SQL("DELETE FROM {} WHERE id=%s RETURNING id").format(sql.Identifier(table)), (int(mid),))
                    row = cur.fetchone()
                conn.commit()
            if row:
                deleted = True
                break
        except Exception:
            continue

    await query.answer("Model deleted" if deleted else "Delete failed", show_alert=False)
    await show_perps_models(query, context)


async def show_perps_master_model(query, context):
    text = (
        "🏆 *Master Model*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "The master model aggregates signals\n"
        "across all active models.\n\n"
        "A signal must pass at least 2 active\n"
        "models to reach Phase 4 alert.\n\n"
        "_Configure individual models to\n"
        "tune master model sensitivity._"
    )
    kb = IKM([
        [IKB("🧩 Manage Models", callback_data="perps:models")],
        [IKB("← Perps", callback_data="perps")],
    ])
    await _edit(query, text, kb)


async def show_perps_model_create(query, context):
    text = (
        "➕ *Create Perps Model*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Select a pre-built model preset to\n"
        "add instantly, or create a custom\n"
        "model with the wizard.\n\n"
        "Each model scans for specific ICT\n"
        "setups on a pair + timeframe.\n\n"
        "_Tap a preset to get started:_"
    )
    kb = IKM([
        [IKB("📚 BTC 4H Trend", callback_data="perps:models:preset:btc4h")],
        [IKB("📚 BTC 1H Scalp", callback_data="perps:models:preset:btc1h")],
        [IKB("📚 ETH 1H Scalp", callback_data="perps:models:preset:eth1h")],
        [IKB("📚 SOL 1H Momentum", callback_data="perps:models:preset:sol1h")],
        [IKB("📚 SOL 15m Sniper", callback_data="perps:models:preset:sol15m")],
        [IKB("← Models", callback_data="perps:models")],
    ])
    await _edit(query, text, kb)


async def handle_perps_model_preset(query, context, preset: str):
    from psycopg2 import sql
    import json

    presets = {
        "btc4h": {
            "name": "BTC 4H Trend", "pair": "BTCUSDT", "timeframe": "4h", "active": True,
            "description": "BTC trend following on 4H. Looks for structure, OB, FVG confluence.",
            "phase1_rules": [{"rule_id": "rule_htf_bullish", "weight": 1}, {"rule_id": "rule_bos_bullish", "weight": 1}],
            "phase2_rules": [{"rule_id": "rule_fvg_bullish", "weight": 1}, {"rule_id": "rule_bullish_ob_present", "weight": 1}],
            "phase3_rules": [{"rule_id": "rule_ote_zone", "weight": 1}],
            "phase4_rules": [{"rule_id": "rule_candle_confirmation", "weight": 1}],
            "min_quality_score": 60,
        },
        "btc1h": {
            "name": "BTC 1H Scalp", "pair": "BTCUSDT", "timeframe": "1h", "active": True,
            "description": "BTC scalp on 1H. Session overlaps, FVG entries.",
            "phase1_rules": [{"rule_id": "rule_htf_bullish", "weight": 1}],
            "phase2_rules": [{"rule_id": "rule_fvg_bullish", "weight": 1}, {"rule_id": "rule_liquidity_sweep", "weight": 1}],
            "phase3_rules": [{"rule_id": "rule_session_overlap", "weight": 1}],
            "phase4_rules": [{"rule_id": "rule_candle_confirmation", "weight": 1}],
            "min_quality_score": 55,
        },
        "eth1h": {
            "name": "ETH 1H Scalp", "pair": "ETHUSDT", "timeframe": "1h", "active": True,
            "description": "ETH scalp on 1H. Session-based entries.",
            "phase1_rules": [{"rule_id": "rule_htf_bullish", "weight": 1}],
            "phase2_rules": [{"rule_id": "rule_fvg_bullish", "weight": 1}],
            "phase3_rules": [{"rule_id": "rule_session_overlap", "weight": 1}],
            "phase4_rules": [{"rule_id": "rule_candle_confirmation", "weight": 1}],
            "min_quality_score": 55,
        },
        "sol1h": {
            "name": "SOL 1H Momentum", "pair": "SOLUSDT", "timeframe": "1h", "active": True,
            "description": "SOL momentum on 1H. High volatility entries.",
            "phase1_rules": [{"rule_id": "rule_bos_bullish", "weight": 1}],
            "phase2_rules": [{"rule_id": "rule_fvg_bullish", "weight": 1}],
            "phase3_rules": [{"rule_id": "rule_ote_zone", "weight": 1}],
            "phase4_rules": [{"rule_id": "rule_candle_confirmation", "weight": 1}],
            "min_quality_score": 55,
        },
        "sol15m": {
            "name": "SOL 15m Sniper", "pair": "SOLUSDT", "timeframe": "15m", "active": True,
            "description": "SOL aggressive scalp on 15m. Quick entries on displacement.",
            "phase1_rules": [{"rule_id": "rule_bos_bullish", "weight": 1}],
            "phase2_rules": [{"rule_id": "rule_liquidity_sweep", "weight": 1}],
            "phase3_rules": [{"rule_id": "rule_fvg_bullish", "weight": 1}, {"rule_id": "rule_displacement", "weight": 1}],
            "phase4_rules": [{"rule_id": "rule_candle_confirmation", "weight": 1}],
            "min_quality_score": 50,
        },
    }

    p = presets.get(preset)
    if not p:
        await query.answer("Unknown preset", show_alert=True)
        return

    saved = False
    for table in ("models", "trading_models", "perps_models"):
        try:
            with db.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL(
                            """
                            INSERT INTO {} (
                                name, pair, timeframe, active, status,
                                description, phase1_rules, phase2_rules,
                                phase3_rules, phase4_rules, min_quality_score
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s)
                            RETURNING id
                            """
                        ).format(sql.Identifier(table)),
                        (
                            p["name"], p["pair"], p["timeframe"], bool(p["active"]), "active",
                            p["description"], json.dumps(p["phase1_rules"]), json.dumps(p["phase2_rules"]),
                            json.dumps(p["phase3_rules"]), json.dumps(p["phase4_rules"]), p["min_quality_score"],
                        ),
                    )
                    row = cur.fetchone()
                conn.commit()
            if row:
                saved = True
                break
        except Exception:
            continue

    if saved:
        await query.answer(f"✅ {p['name']} added", show_alert=True)
    else:
        await query.answer("Failed to save — check table name", show_alert=True)
    await show_perps_models(query, context)
async def show_perps_journal(query, context):
    entries = db.get_journal_entries(limit=5) or []
    lines = "\n".join([f"• {e.get('title','Untitled')}" for e in entries]) or "No journal entries yet."
    await _edit(query, f"📓 *Journal*\n{lines}", _kb([[_btn("← Perps", "perps")]]))


async def show_perps_live(query, context):
    from security.key_manager import key_exists

    try:
        has_hl_wallet = key_exists("hl_api_wallet")
    except Exception:
        has_hl_wallet = False

    if not has_hl_wallet:
        await _edit(query, "🔷 *Live Account — Hyperliquid*\nConnect wallet to trade.", _kb([[_btn("🔑 Connect Hyperliquid", "hl:connect")], [_btn("← Perps", "perps")]]))
        return
    try:
        address = db.get_hl_address() or ""
    except Exception:
        address = ""

    try:
        positions = db.get_hl_positions(address) if address else []
    except Exception:
        positions = []
    await _edit(query, f"🔷 *Hyperliquid*\nPositions: {len(positions)}", _kb([
        [_btn("🔄 Refresh", "hl:refresh"), _btn("📊 Positions", "hl:positions")],
        [_btn("📋 Orders", "hl:orders"), _btn("📈 Performance", "hl:performance")],
        [_btn("📜 History", "hl:history"), _btn("🌊 Funding", "hl:funding")],
        [_btn("🏪 Markets", "hl:markets")],
        [_btn("← Perps", "perps")],
    ]))


async def show_perps_demo(query, context):
    try:
        balance = db.get_demo_balance("perps")
    except Exception:
        balance = 10000.0
    try:
        trades = db.get_open_demo_trades("perps") or []
    except Exception:
        trades = []
    try:
        history = db.get_closed_demo_trades("perps", limit=3) or []
    except Exception:
        history = []

    pnl = sum(float(t.get("pnl") or t.get("current_pnl_usd") or t.get("final_pnl_usd") or 0) for t in trades)
    pe = "🟢" if pnl >= 0 else "🔴"

    text = (
        f"🎮 *Demo Account — Perps*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Balance:  ${balance:,.2f}\n"
        f"Open PnL: {pe} ${pnl:+.2f}\n"
        f"Open:     {len(trades)} trades\n"
    )

    if trades:
        text += "\n*Open Trades:*\n"
        for t in trades[:3]:
            dirn = t.get("direction", "?")
            pair = t.get("pair", "?")
            p = float(t.get("pnl") or t.get("current_pnl_usd") or t.get("final_pnl_usd") or 0)
            pe2 = "🟢" if p >= 0 else "🔴"
            text += f"  {pe2} {dirn} {pair}  ${p:+.2f}\n"

    if history:
        text += "\n*Recent Closed:*\n"
        for t in history:
            dirn = t.get("direction", "?")
            pair = t.get("pair", "?")
            p = float(t.get("pnl") or t.get("final_pnl_usd") or 0)
            pe2 = "🟢" if p >= 0 else "🔴"
            text += f"  {pe2} {dirn} {pair}  ${p:+.2f}\n"

    kb = IKM([
        [IKB("📊 All Positions", callback_data="perps:demo:positions"), IKB("📜 History", callback_data="perps:demo:history")],
        [IKB("➕ Deposit $1,000", callback_data="perps:demo:deposit:1000"), IKB("➕ Deposit $5,000", callback_data="perps:demo:deposit:5000")],
        [IKB("🔄 Reset to $10,000", callback_data="perps:demo:reset:confirm")],
        [IKB("← Perps", callback_data="perps")],
    ])
    await _edit(query, text, kb)


async def handle_perps_demo_deposit(query, context, amount: float):
    try:
        current = db.get_demo_balance("perps")
        new_bal = current + amount
        db.set_demo_balance("perps", new_bal)
        await query.answer(f"✅ Deposited ${amount:,.0f}. Balance: ${new_bal:,.2f}", show_alert=True)
    except Exception as e:
        await query.answer(str(e), show_alert=True)
    await show_perps_demo(query, context)


async def handle_perps_demo_reset_confirm(query, context):
    text = (
        "🔄 *Reset Demo Account?*\n\n"
        "This will:\n"
        "• Close all open demo trades\n"
        "• Reset balance to $10,000\n"
        "• Clear trade history\n\n"
        "This cannot be undone."
    )
    kb = IKM([[IKB("✅ Yes, Reset", callback_data="perps:demo:reset:execute"), IKB("❌ Cancel", callback_data="perps:demo")]])
    await _edit(query, text, kb)


async def handle_perps_demo_reset(query, context):
    try:
        db.reset_demo_balance("perps", 10000.0)
        await query.answer("✅ Demo account reset to $10,000", show_alert=True)
    except Exception as e:
        await query.answer(str(e), show_alert=True)
    await show_perps_demo(query, context)


async def show_perps_demo_positions(query, context):
    try:
        trades = db.get_open_demo_trades("perps") or []
    except Exception:
        trades = []

    if not trades:
        text = (
            "📊 *Demo Positions*\n\n"
            "No open demo trades.\n\n"
            "Signals at Phase 4 will show\n"
            "a [🎮 Demo] button to open one."
        )
        kb = IKM([[IKB("← Demo", callback_data="perps:demo")]])
        await _edit(query, text, kb)
        return

    text = "📊 *Demo Positions*\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    rows = []
    for t in trades:
        tid = t.get("id")
        pair = t.get("pair", "?")
        dirn = t.get("direction", "?")
        entry = float(t.get("entry_price") or 0)
        cur = float(t.get("current_price") or entry or 0)
        pnl = float(t.get("pnl") or t.get("current_pnl_usd") or t.get("final_pnl_usd") or 0)
        size = float(t.get("size_usd") or t.get("position_size_usd") or 0)
        pe = "🟢" if pnl >= 0 else "🔴"
        dirn_e = "📈" if "bull" in str(dirn).lower() or str(dirn).lower() in {"long", "buy"} else "📉"
        text += (
            f"{dirn_e} *{dirn} {pair}*\n"
            f"   Entry ${entry:,.4f}  Now ${cur:,.4f}\n"
            f"   Size ${size:,.0f}  {pe} PnL ${pnl:+.2f}\n\n"
        )
        rows.append([IKB(f"❌ Close {pair}", callback_data=f"perps:demo:close:{tid}")])
    rows.append([IKB("← Demo", callback_data="perps:demo")])
    await _edit(query, text, IKM(rows))


async def show_perps_demo_history(query, context):
    try:
        history = db.get_closed_demo_trades("perps", limit=20) or []
    except Exception:
        history = []
    if not history:
        await _edit(query, "📜 *Demo History*\n\nNo closed demo trades.", IKM([[IKB("← Demo", callback_data="perps:demo")]]))
        return
    text = "📜 *Demo History*\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for t in history:
        pair = t.get("pair", "?")
        dirn = t.get("direction", "?")
        pnl = float(t.get("pnl") or t.get("final_pnl_usd") or 0)
        pe = "🟢" if pnl >= 0 else "🔴"
        text += f"{pe} {dirn} {pair}  ${pnl:+.2f}\n"
    await _edit(query, text, IKM([[IKB("← Demo", callback_data="perps:demo")]]))


async def handle_perps_demo_close(query, context, tid: int):
    try:
        trades = db.get_open_demo_trades("perps") or []
        trade = next((t for t in trades if int(t.get("id", 0)) == int(tid)), None)
        if not trade:
            await query.answer("Trade not found", show_alert=True)
            return await show_perps_demo_positions(query, context)
        pnl = float(trade.get("current_pnl_usd") or trade.get("pnl") or 0)
        ok = db.close_demo_trade(int(tid), pnl=pnl, reason="manual")
        await query.answer("✅ Trade closed" if ok else "Close failed", show_alert=True)
    except Exception as e:
        await query.answer(str(e), show_alert=True)
    await show_perps_demo_positions(query, context)


async def show_perps_risk(query, context):
    try:
        s = db.get_risk_settings("perps") or {}
    except Exception:
        s = {}

    text = (
        f"💰 *Risk Settings — Perps*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Max Risk per Trade:  {s.get('max_risk_pct',1)}%\n"
        f"Daily Loss Limit:    ${s.get('daily_loss_limit',200):,.0f}\n"
        f"Max Open Positions:  {s.get('max_positions',5)}\n"
        f"Max Leverage:        {s.get('max_leverage',10)}x\n"
        f"Max Daily Trades:    {s.get('max_daily_trades',10)}\n\n"
        f"_Tap a setting to change it._"
    )

    kb = IKM([
        [IKB("📊 Max Risk %", callback_data="perps:risk:edit:max_risk_pct"), IKB("🛑 Daily Limit", callback_data="perps:risk:edit:daily_loss_limit")],
        [IKB("📈 Max Positions", callback_data="perps:risk:edit:max_positions"), IKB("⚡ Max Leverage", callback_data="perps:risk:edit:max_leverage")],
        [IKB("🔄 Reset Defaults", callback_data="perps:risk:reset")],
        [IKB("← Perps", callback_data="perps")],
    ])
    await _edit(query, text, kb)


async def show_perps_risk_edit(query, context, field: str):
    labels = {
        "max_risk_pct": ("Max Risk per Trade (%)", ["0.5", "1", "1.5", "2", "3", "5"], "perps:risk:set:max_risk_pct:"),
        "daily_loss_limit": ("Daily Loss Limit ($)", ["100", "200", "500", "1000", "2000"], "perps:risk:set:daily_loss_limit:"),
        "max_positions": ("Max Open Positions", ["1", "2", "3", "5", "10"], "perps:risk:set:max_positions:"),
        "max_leverage": ("Max Leverage", ["2", "3", "5", "10", "20", "50"], "perps:risk:set:max_leverage:"),
    }
    if field not in labels:
        await show_perps_risk(query, context)
        return

    label, options, cb_prefix = labels[field]
    text = f"✏️ *{label}*\n\nSelect a value:"
    opt_rows, row = [], []
    for opt in options:
        row.append(IKB(opt, callback_data=cb_prefix + opt))
        if len(row) == 3:
            opt_rows.append(row)
            row = []
    if row:
        opt_rows.append(row)
    opt_rows.append([IKB("← Risk", callback_data="perps:risk")])
    await _edit(query, text, IKM(opt_rows))


async def handle_perps_risk_set(query, context, field: str, value: str):
    try:
        val = float(value) if "." in value else int(value)
        s = db.get_risk_settings("perps") or {}
        s[field] = val
        db.save_risk_settings("perps", s)
        await query.answer(f"✅ {field} set to {value}", show_alert=False)
    except Exception as e:
        await query.answer(str(e), show_alert=True)
    await show_perps_risk(query, context)


async def handle_perps_risk_reset(query, context):
    try:
        db.save_risk_settings("perps", {
            "max_risk_pct": 1,
            "daily_loss_limit": 200,
            "max_positions": 5,
            "max_leverage": 10,
            "max_daily_trades": 10,
        })
        await query.answer("✅ Risk settings reset to defaults", show_alert=False)
    except Exception as e:
        await query.answer(str(e), show_alert=True)
    await show_perps_risk(query, context)


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
    try:
        address = db.get_hl_address() or ""
    except Exception:
        address = ""

    try:
        positions = db.get_hl_positions(address) if address else []
    except Exception:
        positions = []
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
