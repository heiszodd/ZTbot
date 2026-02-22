from __future__ import annotations

import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import db
from degen.rule_library import RULES_BY_ID
from degen.templates import TEMPLATES




async def degen_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = __import__("handlers.commands", fromlist=["degen_keyboard"]).degen_keyboard()
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
    scanner_active = True
    txt = __import__("formatters").fmt_degen_home(active, wallets, scanner_active, finds_today, alerts_today)
    await msg.edit_text(txt, reply_markup=kb)


def degen_dashboard_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Models", callback_data="degen_model:list")],
        [InlineKeyboardButton("➕ New Degen Model", callback_data="degen_model:new")],
    ])


async def start_model_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
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


async def handle_degen_model_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
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


async def handle_degen_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "degen:stats":
        return await degen_stats_screen(update, context)
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
    if data.startswith("degen:compare:a:"):
        a = data.split(":")[-1]
        context.user_data["compare_a"] = a
        rows = [t for t in context.user_data.get("compare_candidates", []) if t.get("address") != a]
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"{t.get('symbol')}", callback_data=f"degen:compare:b:{t.get('address')}")] for t in rows[:10]])
        return await q.message.reply_text("Select second token:", reply_markup=kb)
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
