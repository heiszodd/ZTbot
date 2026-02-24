from __future__ import annotations

import uuid
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from security.auth import require_auth, require_auth_callback
from security.rate_limiter import check_command_rate

import db
from degen.rule_library import RULES_BY_ID
from degen.templates import TEMPLATES
from engine.degen.contract_scanner import format_scan_result, scan_contract
from engine.degen.narrative_detector import format_narrative_dashboard
from engine.degen.auto_scanner import run_auto_scanner
from handlers.degen_journal_handler import show_degen_journal_home
from security.spending_limits import run_all_checks
from telegram.error import BadRequest
from utils.formatting import format_price, format_usd
import re



@require_auth
async def degen_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id if update.effective_chat else 0
    settings = db.get_user_settings(chat_id)
    mode = settings.get("degen_mode", "simple")
    mode_btn = "🔬 Advanced →" if mode == "simple" else "⚡ Simple →"
    if mode == "simple":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ Simple Mode", callback_data="degen:toggle_mode")],
            [InlineKeyboardButton("🔍 Scan Token", callback_data="degen:scan_prompt"), InlineKeyboardButton("📊 Positions", callback_data="degen:positions")],
            [InlineKeyboardButton("💰 Buy", callback_data="degen:scan_prompt"), InlineKeyboardButton("💸 Sell", callback_data="degen:positions")],
            [InlineKeyboardButton("📜 History", callback_data="degen:journal_home"), InlineKeyboardButton("⚙️ Settings", callback_data="degen:settings")],
            [InlineKeyboardButton(mode_btn, callback_data="degen:toggle_mode")],
        ])
    else:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔬 Advanced Mode", callback_data="degen:toggle_mode")],
            [InlineKeyboardButton("🔍 Scanner", callback_data="scanner:run_now"), InlineKeyboardButton("🎯 Auto Scanner", callback_data="degen:scanner_settings")],
            [InlineKeyboardButton("💰 Quick Buy", callback_data="degen:scan_prompt"), InlineKeyboardButton("💸 Quick Sell", callback_data="degen:positions")],
            [InlineKeyboardButton("📋 Limit Orders", callback_data="degen:positions"), InlineKeyboardButton("📈 DCA Orders", callback_data="degen:dca_home")],
            [InlineKeyboardButton("👥 Copy Wallets", callback_data="wallet:dash"), InlineKeyboardButton("🔴 Blacklist", callback_data="degen:blacklist")],
            [InlineKeyboardButton("📊 Positions", callback_data="degen:positions"), InlineKeyboardButton("📜 PnL History", callback_data="degen:journal_home")],
            [InlineKeyboardButton("⚙️ Settings", callback_data="degen:settings"), InlineKeyboardButton(mode_btn, callback_data="degen:toggle_mode")],
        ])
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        msg = await query.message.reply_text("🎰 Degen Zone\n━━━━━━━━━━━━━━━━\n⏳ Loading live data...", reply_markup=kb)
    else:
        msg = await update.message.reply_text("🎰 Degen Zone\n━━━━━━━━━━━━━━━━\n⏳ Loading live data...", reply_markup=kb)
    active = db.get_active_degen_models()
    wallets = db.get_tracked_wallets(active_only=True)
    finds_today = len(db.get_recent_degen_tokens(limit=500))
    alerts_today = len(db.get_recent_wallet_alerts(hours=24))
    txt = __import__("formatters").fmt_degen_home(active, wallets, True, finds_today, alerts_today)
    try:
        await msg.edit_text(txt, reply_markup=kb)
    except BadRequest:
        pass


def degen_dashboard_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Models", callback_data="degen_model:list")],
        [InlineKeyboardButton("➕ New Degen Model", callback_data="degen_model:new")],
    ])


@require_auth_callback
async def start_model_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id if q and q.from_user else 0
    allowed, reason = check_command_rate(uid)
    if not allowed:
        await q.answer(reason, show_alert=True)
        return
    uid = q.from_user.id if q and q.from_user else 0
    allowed, reason = check_command_rate(uid)
    if not allowed:
        await q.answer(reason, show_alert=True)
        return
    await q.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Quick Deploy — use a preset", callback_data="degen_model:quick_pick")],
        [InlineKeyboardButton("🔧 Custom Build — full wizard", callback_data="dgwiz:start")],
    ])
    await q.message.reply_text("➕ Create Degen Model\n━━━━━━━━━━━━━━━━━━━━━━━━\nHow do you want to start?", reply_markup=kb)


def _detail_text(model: dict) -> str:
    rules = model.get("rules", [])
    lines = [f"📌 {model['name']}", f"Status: {model['status']}", f"Chains: {', '.join(model.get('chains', []))}", f"Rules: {len(rules)}", f"Alerts fired: {model.get('alert_count',0)}"]
    for r in rules:
        rd = RULES_BY_ID.get(r.get("id"), {"name": r.get("id")})
        lines.append(f"- {'🔒' if r.get('mandatory') else '○'} {rd['name']} (w={r.get('weight')})")
    stats = db.get_degen_model_stats(model["id"])
    lines.append(f"\nBest find: {stats.get('best_find') or 'N/A'}")
    if stats.get("last_tokens"):
        lines.append("Last tokens: " + ", ".join(stats["last_tokens"]))
    return "\n".join(lines)


@require_auth_callback
async def handle_degen_model_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "degen:toggle_mode":
        chat_id = q.message.chat_id
        settings = db.get_user_settings(chat_id)
        nxt = "advanced" if settings.get("degen_mode") == "simple" else "simple"
        db.update_user_settings(chat_id, {"degen_mode": nxt})
        return await degen_home(update, context)
    if data == "degen:settings":
        st = db.get_user_settings(q.message.chat_id)
        text = (f"⚙️ Degen Settings\nInstant Buy: {'ON' if st.get('instant_buy_enabled') else 'OFF'}\n"
                f"Threshold: {format_usd(st.get('instant_buy_threshold'))}\n"
                f"Presets: {format_usd(st.get('buy_preset_1'))}, {format_usd(st.get('buy_preset_2'))}, {format_usd(st.get('buy_preset_3'))}, {format_usd(st.get('buy_preset_4'))}\n"
                f"MEV: {'🛡 ON' if st.get('mev_protection') else '⚠️ OFF'}")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Edit Presets", callback_data="degen:edit_presets")],[InlineKeyboardButton("⚡ Instant Buy", callback_data="degen:toggle_instant")],[InlineKeyboardButton("🛡 MEV", callback_data="degen:toggle_mev")],[InlineKeyboardButton("← Back", callback_data="nav:degen_home")]])
        return await q.message.reply_text(text, reply_markup=kb)
    if data == "degen:toggle_instant":
        st = db.get_user_settings(q.message.chat_id)
        db.update_user_settings(q.message.chat_id, {"instant_buy_enabled": not st.get("instant_buy_enabled", True)})
        return await q.message.reply_text("✅ Instant buy updated.")
    if data == "degen:toggle_mev":
        st = db.get_user_settings(q.message.chat_id)
        db.update_user_settings(q.message.chat_id, {"mev_protection": not st.get("mev_protection", True)})
        return await q.message.reply_text("✅ MEV protection updated.")
    if data == "degen:edit_presets":
        context.user_data["degen_state"] = "await_presets"
        return await q.message.reply_text("Send 4 preset amounts separated by spaces. Example: 25 50 100 250")
    if data.startswith("degen:buy:"):
        _,_,address,amount = data.split(":",3)
        usd = float(amount)
        from handlers.solana_handler import handle_sol_execute_buy
        return await handle_sol_execute_buy(q, context, address, address[:6], usd, auto_sell=True)
    if data == "degen_model:new":
        return await start_model_create(update, context)
    if data == "degen_model:quick_pick":
        rows = [[InlineKeyboardButton(f"{tpl['name']} — Deploy", callback_data=f"degen_model:quick_deploy:{key}")] for key, tpl in TEMPLATES.items() if key in {"safe_hunter", "fresh_launch", "clean_dev", "micro_cap", "moonshot"}]
        await q.message.reply_text("Quick deploy presets:", reply_markup=InlineKeyboardMarkup(rows))
        return
    if data == "degen_model:list":
        models = db.get_all_degen_models()
        rows = [[InlineKeyboardButton(f"{'🟢' if m['status']=='active' else '⚫'} {m['name']} | {','.join(m.get('chains',[]))} | {len(m.get('rules',[]))}r | {m.get('alert_count',0)}a", callback_data=f"degen_model:detail:{m['id']}")] for m in models]
        rows.append([InlineKeyboardButton("🗑 Delete All Degen Models", callback_data="degen_model:delete_all_confirm")])
        rows.append([InlineKeyboardButton("➕ New Degen Model", callback_data="degen_model:new")])
        await q.message.reply_text("Degen models", reply_markup=InlineKeyboardMarkup(rows))
        return

    if data == "degen_model:delete_all_confirm":
        await q.message.reply_text(
            "⚠️ Delete *all* degen models? This cannot be undone.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 Yes, Delete All", callback_data="degen_model:delete_all")],
                [InlineKeyboardButton("Cancel", callback_data="degen_model:list")],
            ]),
        )
        return
    if data == "degen_model:delete_all":
        db.delete_all_degen_models()
        await q.message.reply_text("✅ All degen models deleted.", parse_mode="Markdown")
        await q.message.reply_text("Degen models", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ New Degen Model", callback_data="degen_model:new")]]))
        return

    parts = data.split(":")
    action = parts[1]
    if action == "quick_deploy":
        tpl = TEMPLATES[parts[2]]
        model = {
            "id": str(uuid.uuid4())[:12], "name": tpl["name"], "description": tpl["description"], "status": "inactive", "chains": ["SOL"], "rules": [dict(r, weight=RULES_BY_ID[r['id']]['weight_default'], mandatory=r.get('mandatory', RULES_BY_ID[r['id']]['mandatory_default'])) for r in tpl["rules"]],
            "min_score": 5.0, "max_risk_level": "HIGH", "min_moon_score": 40, "max_risk_score": 60, "min_liquidity": 5000,
            "max_token_age_minutes": 120, "min_token_age_minutes": 2, "require_lp_locked": False, "require_mint_revoked": False, "require_verified": False,
            "block_serial_ruggers": True, "max_dev_rug_count": 0, "max_top1_holder_pct": 20, "min_holder_count": 10,
        }
        db.insert_degen_model(model)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Activate", callback_data=f"degen_model:toggle:{model['id']}"), InlineKeyboardButton("Later", callback_data=f"degen_model:detail:{model['id']}")]])
        await q.message.reply_text(f"✅ {model['name']} deployed!\nActivate now to start scanning?", reply_markup=kb)
        return

    model_id = parts[2]
    model = db.get_degen_model(model_id)
    if not model:
        await q.message.reply_text("Model not found")
        return
    if action == "detail":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏸ Deactivate" if model["status"] == "active" else "✅ Activate", callback_data=f"degen_model:toggle:{model_id}")],
            [InlineKeyboardButton("✏️ Edit Model", callback_data=f"degen_model:edit:{model_id}"), InlineKeyboardButton("📋 Clone", callback_data=f"degen_model:clone:{model_id}")],
            [InlineKeyboardButton("📜 Version History", callback_data=f"degen_model:versions:{model_id}"), InlineKeyboardButton("📊 Rule Performance", callback_data=f"degen_model:rule_perf:{model_id}")],
            [InlineKeyboardButton("🗑 Delete", callback_data=f"degen_model:delete_confirm:{model_id}")], [InlineKeyboardButton("« Back", callback_data="nav:degen_home")]
        ])
        await q.message.reply_text(_detail_text(model), reply_markup=kb)
    elif action == "toggle":
        db.set_degen_model_status(model_id, "inactive" if model["status"] == "active" else "active")
        await q.message.reply_text("Toggled.")
    elif action == "clone":
        new_id = db.clone_degen_model(model_id)
        await q.message.reply_text(f"Cloned as {new_id}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Open", callback_data=f"degen_model:detail:{new_id}")]]))
    elif action == "delete_confirm":
        await q.message.reply_text("Confirm delete?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Delete", callback_data=f"degen_model:delete:{model_id}")]]))
    elif action == "delete":
        db.delete_degen_model(model_id)
        await q.message.reply_text("Deleted.")
    elif action == "versions":
        versions = db.get_degen_model_versions(model_id)
        await q.message.reply_text("\n".join([f"v{v['version']} @ {v['saved_at']}" for v in versions]) or "No versions.")
    elif action == "rule_perf":
        rows = db.get_degen_rule_performance(model_id)
        lines = []
        for r in rows:
            flag = ""
            if r["samples"] >= 10 and r["win_rate"] > 60:
                flag = " 🔥"
            elif r["samples"] >= 10 and r["win_rate"] < 35:
                flag = " ⚠️"
            elif r["samples"] < 10:
                flag = " (Insufficient data)"
            lines.append(f"{r['rule_name']}: pass {r['pass_rate']}% | entry {r['entry_rate']}% | win {r['win_rate']}%{flag}")
        await q.message.reply_text("\n".join(lines) or "No performance data")
    elif action == "edit":
        db.save_degen_model_version(model_id)
        await q.message.reply_text("Edit via wizard currently starts over.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Start Wizard", callback_data="dgwiz:start")]]))

from degen.narrative_tracker import detect_narrative, get_cold_narratives, get_hot_narratives


@require_auth
async def degen_stats_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hot = get_hot_narratives(limit=3)
    cold = get_cold_narratives()
    rug = db.get_rug_postmortem_stats() if hasattr(db, "get_rug_postmortem_stats") else {"total": 0, "alerted": 0, "alerted_pct": 0, "avg_minutes": 0, "top_signals": [], "missed": []}
    txt = [
        "📊 Degen Stats",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "🔥 Hot Narratives This Week",
    ]
    for h in hot:
        txt.append(f"• {h['narrative']}: {h['token_count']} tokens | moon {h['avg_moon_score']:.1f}")
    if cold:
        txt.append(f"❄️ Cold: {cold[0]['narrative']} — losing momentum")
    txt.extend([
        "",
        "☠️ Rug Post-Mortems",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Total rugs detected: {rug['total']}",
        f"Rugs we alerted on:  {rug['alerted']} ({rug['alerted_pct']}%)",
        f"Avg time to rug:     {rug['avg_minutes']} minutes",
        f"Most common signals: {', '.join(rug.get('top_signals', [])[:3])}",
        f"Missed signals:      {', '.join(rug.get('missed', [])[:3])}",
    ])
    sender = update.callback_query.message.reply_text if update.callback_query else update.message.reply_text
    if update.callback_query:
        await update.callback_query.answer()
    await sender("\n".join(txt))




@require_auth
async def handle_manual_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if context.user_data.get("degen_state") == "await_presets":
        try:
            a,b,c,d = [float(x) for x in text.split()[:4]]
            db.update_user_settings(update.effective_chat.id, {"buy_preset_1": a, "buy_preset_2": b, "buy_preset_3": c, "buy_preset_4": d})
            context.user_data.pop("degen_state", None)
            await update.message.reply_text("✅ Presets updated.")
            return
        except Exception:
            await update.message.reply_text("❌ Send exactly 4 numbers, e.g. 25 50 100 250")
            return
    parts = text.split()

    address = None
    patterns = [r"dexscreener\.com/solana/([1-9A-HJ-NP-Za-km-z]{32,44})", r"birdeye\.so/token/([1-9A-HJ-NP-Za-km-z]{32,44})", r"pump\.fun/([1-9A-HJ-NP-Za-km-z]{32,44})"]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            address = m.group(1)
            break
    if not address:
        for part in parts:
            if (part.startswith("0x") and len(part) == 42) or (len(part) in range(32, 45) and not part.startswith("0x")):
                address = part
                break

    if not address:
        await update.message.reply_text("Please include a contract address.\nExample: scan 0x1234...abcd")
        return

    force_refresh = text.lower().startswith("scan ")
    msg = await update.message.reply_text(
        "🔍 Scanning contract...\n⏳ Checking GoPlus, DexScreener, honeypot.is..."
    )
    scan = await scan_contract(address, force_refresh=force_refresh)
    result = format_scan_result(scan)

    await msg.edit_text(
        result,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🟢 $25", callback_data=f"degen:buy:{address}:25"),
                    InlineKeyboardButton("🟢 $50", callback_data=f"degen:buy:{address}:50"),
                    InlineKeyboardButton("🟢 $100", callback_data=f"degen:buy:{address}:100"),
                ],
                [
                    InlineKeyboardButton("🟢 $250", callback_data=f"degen:buy:{address}:250"),
                    InlineKeyboardButton("🟢 Custom", callback_data=f"degen:buy_custom:{address}"),
                    InlineKeyboardButton("❌ Skip", callback_data="degen:home"),
                ],
                [InlineKeyboardButton("👁 Watch Dev Wallet", callback_data=f"degen:watch_dev:{address}"), InlineKeyboardButton("🔄 Refresh Scan", callback_data=f"degen:scan:{address}")],
            ]
        ),
    )
@require_auth_callback
async def handle_degen_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "degen:toggle_mode":
        chat_id = q.message.chat_id
        settings = db.get_user_settings(chat_id)
        nxt = "advanced" if settings.get("degen_mode") == "simple" else "simple"
        db.update_user_settings(chat_id, {"degen_mode": nxt})
        return await degen_home(update, context)
    if data == "degen:settings":
        st = db.get_user_settings(q.message.chat_id)
        text = (f"⚙️ Degen Settings\nInstant Buy: {'ON' if st.get('instant_buy_enabled') else 'OFF'}\n"
                f"Threshold: {format_usd(st.get('instant_buy_threshold'))}\n"
                f"Presets: {format_usd(st.get('buy_preset_1'))}, {format_usd(st.get('buy_preset_2'))}, {format_usd(st.get('buy_preset_3'))}, {format_usd(st.get('buy_preset_4'))}\n"
                f"MEV: {'🛡 ON' if st.get('mev_protection') else '⚠️ OFF'}")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Edit Presets", callback_data="degen:edit_presets")],[InlineKeyboardButton("⚡ Instant Buy", callback_data="degen:toggle_instant")],[InlineKeyboardButton("🛡 MEV", callback_data="degen:toggle_mev")],[InlineKeyboardButton("← Back", callback_data="nav:degen_home")]])
        return await q.message.reply_text(text, reply_markup=kb)
    if data == "degen:toggle_instant":
        st = db.get_user_settings(q.message.chat_id)
        db.update_user_settings(q.message.chat_id, {"instant_buy_enabled": not st.get("instant_buy_enabled", True)})
        return await q.message.reply_text("✅ Instant buy updated.")
    if data == "degen:toggle_mev":
        st = db.get_user_settings(q.message.chat_id)
        db.update_user_settings(q.message.chat_id, {"mev_protection": not st.get("mev_protection", True)})
        return await q.message.reply_text("✅ MEV protection updated.")
    if data == "degen:edit_presets":
        context.user_data["degen_state"] = "await_presets"
        return await q.message.reply_text("Send 4 preset amounts separated by spaces. Example: 25 50 100 250")
    if data.startswith("degen:buy:"):
        _,_,address,amount = data.split(":",3)
        usd = float(amount)
        ok, failures = run_all_checks("solana", usd, f"sol:{address}")
        if not ok:
            return await q.message.reply_text("❌ " + "\n".join(failures))
        st = db.get_user_settings(q.message.chat_id)
        instant = st.get("instant_buy_enabled", True) and usd <= float(st.get("instant_buy_threshold") or 50)
        if instant:
            return await q.message.reply_text(f"✅ Bought `{address[:6]}...` for {format_usd(usd)} (queued)", parse_mode="Markdown")
        return await q.message.reply_text(f"Confirm buy {format_usd(usd)} for `{address[:6]}...`", parse_mode="Markdown")
    if data == "degen:stats":
        return await degen_stats_screen(update, context)
    if data == "degen:scan_prompt":
        return await q.message.reply_text("Send a contract address or type: scan 0x...")
    if data == "degen:exit_plan":
        from engine.degen.exit_planner import format_exit_plan
        return await q.message.reply_text(format_exit_plan(0.0001, 100), parse_mode="Markdown")
    if data == "degen:narratives":
        narratives = {n["narrative"]: {"count": n.get("mention_count",0), "velocity": n.get("velocity",0), "trend": n.get("trend","stable"), "tokens": n.get("tokens", []) or []} for n in db.get_all_narratives()}
        return await q.message.reply_text(format_narrative_dashboard(narratives), parse_mode="Markdown")
    if data == "degen:journal_home":
        return await show_degen_journal_home(q, context)
    if data == "degen:scanner_settings":
        return await show_scanner_settings(q, context)
    if data == "degen:watchlist":
        return await show_watchlist(q, context)
    if data.startswith("degen:scan:"):
        address = data.split(":", 2)[2]
        scan = await scan_contract(address, force_refresh=True)
        return await q.message.reply_text(format_scan_result(scan), parse_mode="Markdown")
    if data.startswith("degen:watch_dev:"):
        address = data.split(":", 2)[2]
        scan = db.get_contract_scan(address, "eth") or {}
        wallet = scan.get("dev_wallet")
        if wallet:
            db.save_dev_wallet({"contract_address": address, "chain": scan.get("chain", "eth"), "wallet_address": wallet, "label": "deployer", "watching": True})
            return await q.message.reply_text(f"👁 Now watching dev wallet `{wallet[:6]}...{wallet[-4:]}`", parse_mode="Markdown")
        return await q.message.reply_text("No dev wallet detected in latest scan.")
    if data.startswith("degen:unwatch:"):
        _, _, wallet, contract = data.split(":", 3)
        db.update_dev_wallet(wallet, contract, {"watching": False})
        return await q.message.reply_text("🛑 Dev wallet watch disabled.")
    if data == "degen:portfolio_risk":
        open_degen = db.get_open_demo_trades("degen") if hasattr(db, "get_open_demo_trades") else []
        open_copy = [r for r in db.get_wallet_copy_trades(limit=200) if r.get("result") is None] if hasattr(db, "get_wallet_copy_trades") else []
        total = len(open_degen) + len(open_copy)
        chain_counts = {}
        narrative_counts = {}
        for t in open_degen:
            chain = t.get("chain", "SOL")
            chain_counts[chain] = chain_counts.get(chain, 0) + 1
            n = detect_narrative(t.get("token_symbol", ""), t.get("notes", ""))
            narrative_counts[n] = narrative_counts.get(n, 0) + 1
        lines = ["📊 Degen Portfolio Risk", "━━━━━━━━━━━━━━━━━━━━━━━━", f"Open Positions: {total}", "", "🔗 Chain Concentration:"]
        for k, v in chain_counts.items():
            pct = (v / total * 100) if total else 0
            lines.append(f"  {k}: {v} positions ({pct:.1f}%)")
        lines.append("\n🎭 Narrative Concentration:")
        for k, v in narrative_counts.items():
            pct = (v / total * 100) if total else 0
            warn = " — ⚠️ concentrated" if pct > 50 else ""
            lines.append(f"  {k}: {v} positions{warn}")
        await q.message.reply_text("\n".join(lines))
        return
    if data == "degen:compare":
        rows = db.get_recent_degen_tokens(limit=20)
        if len(rows) < 2:
            return await q.message.reply_text("Need at least 2 tokens to compare.")
        context.user_data["compare_candidates"] = rows
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"{t.get('symbol')}", callback_data=f"degen:compare:a:{t.get('address')}")] for t in rows[:10]])
        return await q.message.reply_text("Select first token to compare:", reply_markup=kb)
    if data.startswith("degen_journal:"):
        if data == "degen_journal:all":
            entries = db.get_degen_journal_entries(limit=20)
            lines = ["🎲 *All Degen Plays*", "━━━━━━━━━━━━━━━━━━━━━━━━"]
            for e in entries[:20]:
                out = e.get("outcome") or "OPEN"
                lines.append(f"• {e.get('token_symbol','?')} — {out} — ${float(e.get('pnl_usd',0) or 0):+.2f}")
            await q.message.reply_text("\n".join(lines), parse_mode="Markdown")
            return
        if data == "degen_journal:by_narrative":
            entries = db.get_degen_journal_entries(limit=200)
            bucket = {}
            for e in entries:
                n = e.get("narrative") or "Other"
                bucket[n] = bucket.get(n, 0) + 1
            txt = "📊 *Journal by Narrative*\n" + "\n".join([f"• {k}: {v}" for k, v in sorted(bucket.items(), key=lambda x: x[1], reverse=True)])
            await q.message.reply_text(txt, parse_mode="Markdown")
            return
        if data == "degen_journal:best":
            entries = db.get_degen_journal_entries(limit=200)
            closed = [e for e in entries if e.get("final_multiplier")]
            best = sorted(closed, key=lambda e: float(e.get("final_multiplier", 1) or 1), reverse=True)[:10]
            txt = "🏆 *Best Plays*\n" + "\n".join([f"• {e.get('token_symbol','?')}: {float(e.get('final_multiplier',1) or 1):.1f}x" for e in best])
            await q.message.reply_text(txt, parse_mode="Markdown")
            return

    if data.startswith("degen:compare:a:"):
        a = data.split(":")[-1]
        context.user_data["compare_a"] = a
        rows = [t for t in context.user_data.get("compare_candidates", []) if t.get("address") != a]
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"{t.get('symbol')}", callback_data=f"degen:compare:b:{t.get('address')}")] for t in rows[:10]])
        return await q.message.reply_text("Select second token:", reply_markup=kb)
    if data.startswith("degen:sold:"):
        _, _, journal_id, target = data.split(":", 3)
        journal = next((x for x in db.get_degen_journal_entries(limit=500) if int(x.get("id")) == int(journal_id)), None)
        if journal:
            entry = float(journal.get("entry_price") or 0)
            peak = float(journal.get("peak_price") or entry or 0)
            final_multiplier = (peak / entry) if entry > 0 else float(target)
            pnl = (float(journal.get("position_size_usd") or 0) * max(final_multiplier - 1, 0))
            db.update_degen_journal(int(journal_id), {"exit_time": __import__("datetime").datetime.utcnow().isoformat(), "final_multiplier": final_multiplier, "pnl_usd": pnl, "outcome": "closed", "followed_exit_plan": True})
        return await q.message.reply_text("✅ Journal updated with sale.")
    if data.startswith("degen:hold:"):
        return await q.message.reply_text("⏭ Holding. Reminder logged.")

    if data.startswith("degen:live:"):
        address = data.split(":", 2)[2]
        scan = db.get_latest_auto_scan(address) or db.get_contract_scan(address, "solana") or {}
        symbol = scan.get("token_symbol") or scan.get("symbol") or "TOKEN"
        from engine.solana.trade_planner import generate_trade_plan, format_trade_plan
        plan = await generate_trade_plan(address, symbol, "buy", 50.0, scan)
        text = format_trade_plan(plan) + "\n\n_Phase 1 — manual execution only._"
        return await q.message.reply_text(text, parse_mode="Markdown")
    if data.startswith("degen:demo:"):
        address = data.split(":", 2)[2]
        scan = db.get_latest_auto_scan(address) or db.get_contract_scan(address, "solana") or {}
        symbol = scan.get("token_symbol") or scan.get("symbol") or "TOKEN"
        price = float(scan.get("price_usd") or 0.000001)
        tid = db.open_demo_trade({
            "section": "degen",
            "pair": "",
            "token_symbol": symbol,
            "direction": "BUY",
            "entry_price": price,
            "sl": price * 0.75,
            "tp1": price * 1.5,
            "tp2": price * 3,
            "tp3": price * 10,
            "position_size_usd": 10,
            "risk_amount_usd": 10,
            "risk_pct": 1.0,
            "model_id": "degen_demo",
            "model_name": "Degen Demo",
            "tier": "C",
            "score": float(scan.get("probability_score") or 0),
            "source": "degen_demo_button",
            "notes": f"{address}",
        })
        return await q.message.reply_text(f"🎮 Demo trade opened for {symbol} (#{tid})")
    if data.startswith("degen:compare:b:"):
        b = data.split(":")[-1]
        a = context.user_data.get("compare_a")
        rows = context.user_data.get("compare_candidates", [])
        ta = next((x for x in rows if x.get("address") == a), {})
        tb = next((x for x in rows if x.get("address") == b), {})
        verdict = ta.get("symbol") if float(ta.get("moon_score",0)) - float(ta.get("risk_score",100)) > float(tb.get("moon_score",0)) - float(tb.get("risk_score",100)) else tb.get("symbol")
        msg = (
            "⚖️ Token Comparison\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"             {ta.get('symbol')}    {tb.get('symbol')}\n"
            f"Chain:       {ta.get('chain')}      {tb.get('chain')}\n"
            f"Market Cap:  ${float(ta.get('mcap',0)):,.0f}      ${float(tb.get('mcap',0)):,.0f}\n"
            f"Liquidity:   ${float(ta.get('liquidity_usd',0)):,.0f}      ${float(tb.get('liquidity_usd',0)):,.0f}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ Risk:     {int(ta.get('risk_score',0))}/100      {int(tb.get('risk_score',0))}/100\n"
            f"🚀 Moon:     {int(ta.get('moon_score',0))}/100      {int(tb.get('moon_score',0))}/100\n\n"
            f"VERDICT: {verdict} scores better overall."
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ Ape {ta.get('symbol')}", callback_data=f"wallet:watch:{ta.get('address')}"), InlineKeyboardButton(f"✅ Ape {tb.get('symbol')}", callback_data=f"wallet:watch:{tb.get('address')}")], [InlineKeyboardButton("👀 Watch Both", callback_data="wallet:dismiss"), InlineKeyboardButton("❌ Skip Both", callback_data="wallet:dismiss")]])
        return await q.message.reply_text(msg, reply_markup=kb)


log = logging.getLogger(__name__)


@require_auth_callback
async def handle_scan_action(query, context) -> None:
    """Handles whitelist, ignore, ape-in, and full-scan callbacks."""
    data = query.data
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    address = parts[2] if len(parts) > 2 else ""

    if action == "whitelist":
        await handle_whitelist(query, context, address)
    elif action == "ignore":
        await handle_ignore(query, context, address)
    elif action == "ape":
        await handle_ape_in(query, context, address)
    elif action == "full":
        await handle_full_scan(query, context, address)


async def handle_whitelist(query, context, address: str) -> None:
    scan_result = db.get_latest_auto_scan(address)
    symbol = scan_result.get("token_symbol", "?") if scan_result else "?"

    db.add_to_watchlist({
        "contract_address": address,
        "chain": scan_result.get("chain", "solana") if scan_result else "solana",
        "token_symbol": scan_result.get("token_symbol", "") if scan_result else "",
        "token_name": scan_result.get("token_name", "") if scan_result else "",
        "last_score": scan_result.get("probability_score", 0) if scan_result else 0,
        "added_by": "user_whitelist",
    })
    db.update_auto_scan_action(address, "whitelist")

    try:
        await query.message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ Whitelisted — watching {symbol}", callback_data="noop")]])
        )
    except Exception as exc:
        log.error("Whitelist edit markup failed: %s", exc)

    try:
        await query.answer(f"✅ {symbol} added to watchlist. Will alert on score changes.", show_alert=False)
    except Exception as exc:
        log.error("Whitelist query answer failed: %s", exc)


async def handle_ignore(query, context, address: str) -> None:
    scan_result = db.get_latest_auto_scan(address)
    symbol = scan_result.get("token_symbol", "?") if scan_result else "?"

    db.add_to_ignored({
        "contract_address": address,
        "token_symbol": symbol,
        "ignored_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        "reason": "user_ignored",
    })
    db.update_auto_scan_action(address, "ignore")
    db.update_watchlist_item(address, {"status": "ignored"})

    try:
        await query.message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Ignored for 24h", callback_data="noop")]])
        )
    except Exception as exc:
        log.error("Ignore edit markup failed: %s", exc)

    try:
        await query.answer(f"{symbol} ignored for 24 hours.", show_alert=False)
    except Exception as exc:
        log.error("Ignore query answer failed: %s", exc)


async def handle_ape_in(query, context, address: str) -> None:
    from engine.degen.early_entry import calculate_early_score
    from engine.degen.contract_scanner import calculate_degen_position

    scan_result = db.get_latest_auto_scan(address)
    symbol = scan_result.get("token_symbol", "?") if scan_result else "?"
    db.update_auto_scan_action(address, "ape_in")

    chain = scan_result.get("chain", "solana") if scan_result else "solana"
    scan = await scan_contract(address, chain)
    early = calculate_early_score(scan)

    degen_settings = db.get_degen_risk_settings()
    position = calculate_degen_position(
        account_size=degen_settings["account_size"],
        max_position_pct=degen_settings["max_position_pct"],
        rug_score=scan.get("rug_score", 0),
        early_score=early.get("early_score", 0),
    )

    price = scan.get("price_usd", 0) or 0
    sl = price * 0.75
    tp1 = price * 1.5
    size = position["final_size"]

    journal_id = db.create_degen_journal({
        "contract_address": address,
        "chain": chain,
        "token_symbol": symbol,
        "token_name": scan.get("token_name", "Unknown"),
        "entry_price": price,
        "entry_mcap": scan.get("market_cap", 0),
        "entry_liquidity": scan.get("liquidity_usd", 0),
        "entry_holders": scan.get("holder_count", 0),
        "entry_age_hours": early.get("age_hours", 0),
        "entry_rug_grade": scan.get("rug_grade", "?"),
        "position_size_usd": size,
        "early_score": early.get("early_score", 0),
        "rug_score": scan.get("rug_score", 0),
        "entry_time": datetime.utcnow().isoformat(),
    })

    try:
        await query.message.reply_text(
            f"📲 *Aping In — {symbol}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Position size: *${size:.2f}*\n"
            f"Entry price:   ${price:.8f}\n"
            f"Stop loss:     ${sl:.8f} (-25%)\n"
            f"TP1:           ${tp1:.8f} (1.5x)\n\n"
            f"Journal entry #{journal_id} created.\n"
            f"Exit reminders will fire automatically\n"
            f"at 2x, 5x, 10x, and 20x.\n\n"
            f"_Good luck. Respect the exits._",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📓 View Journal Entry", callback_data=f"degen_journal:view:{journal_id}"),
                InlineKeyboardButton("❌ Cancel Entry", callback_data=f"degen_journal:cancel:{journal_id}"),
            ]]),
        )
    except Exception as exc:
        log.error("Ape-in reply failed: %s", exc)

    try:
        await query.answer(f"Journal entry created for {symbol}", show_alert=False)
    except Exception as exc:
        log.error("Ape-in query answer failed: %s", exc)


async def handle_full_scan(query, context, address: str) -> None:
    try:
        scan = await scan_contract(address, force_refresh=True)
        await query.message.reply_text(format_scan_result(scan), parse_mode="Markdown")
    except Exception as exc:
        log.error("Full scan failed for %s: %s", address, exc)
        try:
            await query.answer("Full scan failed. Try again.", show_alert=True)
        except Exception:
            pass


async def show_scanner_settings(query, context) -> None:
    settings = db.get_scanner_settings()
    text = (
        f"⚙️ *Auto Scanner Settings*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Status:        {'✅ Active' if settings['enabled'] else '⏸ Paused'}\n"
        f"Interval:      {settings['interval_minutes']}min\n"
        f"Min liquidity: ${settings['min_liquidity']:,.0f}\n"
        f"Max liquidity: ${settings['max_liquidity']:,.0f}\n"
        f"Min vol (1h):  ${settings['min_volume_1h']:,.0f}\n"
        f"Max age:       {settings['max_age_hours']}h\n"
        f"Min score:     {settings['min_probability_score']}/100\n"
        f"Min safety:    {settings['min_rug_grade']} grade\n"
        f"Mint revoked:  {'Required ✅' if settings['require_mint_revoked'] else 'Optional'}\n"
        f"LP locked:     {'Required ✅' if settings['require_lp_locked'] else 'Optional'}\n"
    )

    buttons = [
        [InlineKeyboardButton(f"{'⏸ Pause' if settings['enabled'] else '▶️ Enable'} Scanner", callback_data="scanner:toggle")],
        [InlineKeyboardButton(f"💧 Min Liq: ${settings['min_liquidity']:,.0f}", callback_data="scanner:set:min_liquidity")],
        [InlineKeyboardButton(f"📊 Min Score: {settings['min_probability_score']}", callback_data="scanner:cycle:min_score")],
        [InlineKeyboardButton(f"⏱ Max Age: {settings['max_age_hours']}h", callback_data="scanner:cycle:max_age")],
        [InlineKeyboardButton(f"🛡 Min Grade: {settings['min_rug_grade']}", callback_data="scanner:cycle:min_grade")],
        [InlineKeyboardButton(f"🔒 Require Mint Revoked: {'Yes' if settings['require_mint_revoked'] else 'No'}", callback_data="scanner:toggle:mint_revoked")],
        [InlineKeyboardButton(f"🔒 Require LP Lock: {'Yes' if settings['require_lp_locked'] else 'No'}", callback_data="scanner:toggle:lp_locked")],
        [InlineKeyboardButton("▶️ Run Scan Now", callback_data="scanner:run_now")],
        [InlineKeyboardButton("📋 View Watchlist", callback_data="scanner:watchlist")],
        [InlineKeyboardButton("🏠 Degen Home", callback_data="nav:degen_home")],
    ]

    try:
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as exc:
        log.error("show_scanner_settings failed: %s", exc)


async def show_watchlist(query, context) -> None:
    rows = db.get_active_watchlist()
    if not rows:
        text = "📋 *Watchlist*\n━━━━━━━━━━━━━━━━━━━━━━━━\nNo active watchlist tokens yet."
    else:
        lines = ["📋 *Watchlist*", "━━━━━━━━━━━━━━━━━━━━━━━━"]
        for item in rows[:20]:
            lines.append(
                f"• {item.get('token_symbol','?')} — score {float(item.get('last_score',0) or 0):.0f}\n"
                f"  `{item.get('contract_address','')}`"
            )
        text = "\n".join(lines)

    try:
        await query.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Scanner Settings", callback_data="degen:scanner_settings")]]),
        )
    except Exception as exc:
        log.error("show_watchlist failed: %s", exc)


@require_auth_callback
async def handle_scanner_settings_action(query, context) -> None:
    settings = db.get_scanner_settings()
    data = query.data

    if data == "scanner:toggle":
        db.update_scanner_settings({"enabled": not settings.get("enabled", True)})
    elif data == "scanner:cycle:min_score":
        values = [40, 45, 50, 55, 60, 65, 70]
        cur = int(settings.get("min_probability_score", 55))
        nxt = values[(values.index(cur) + 1) % len(values)] if cur in values else 55
        db.update_scanner_settings({"min_probability_score": nxt})
    elif data == "scanner:cycle:max_age":
        values = [6, 12, 24, 48, 72]
        cur = int(settings.get("max_age_hours", 72))
        nxt = values[(values.index(cur) + 1) % len(values)] if cur in values else 72
        db.update_scanner_settings({"max_age_hours": nxt})
    elif data == "scanner:cycle:min_grade":
        values = ["F", "D", "C", "B", "A"]
        cur = str(settings.get("min_rug_grade", "C"))
        nxt = values[(values.index(cur) + 1) % len(values)] if cur in values else "C"
        db.update_scanner_settings({"min_rug_grade": nxt})
    elif data == "scanner:toggle:mint_revoked":
        db.update_scanner_settings({"require_mint_revoked": not settings.get("require_mint_revoked", True)})
    elif data == "scanner:toggle:lp_locked":
        db.update_scanner_settings({"require_lp_locked": not settings.get("require_lp_locked", True)})
    elif data == "scanner:set:min_liquidity":
        values = [25000, 50000, 75000, 100000]
        cur = int(float(settings.get("min_liquidity", 50000) or 50000))
        nxt = values[(values.index(cur) + 1) % len(values)] if cur in values else 50000
        db.update_scanner_settings({"min_liquidity": nxt})
    elif data == "scanner:run_now":
        await query.answer("Running scan now...", show_alert=False)
        asyncio.create_task(run_auto_scanner(context))
    elif data == "scanner:watchlist":
        await show_watchlist(query, context)
        return

    await show_scanner_settings(query, context)
