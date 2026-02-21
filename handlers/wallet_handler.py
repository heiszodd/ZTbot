from __future__ import annotations

import re
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

import db
from config import CHAT_ID, ETHERSCAN_KEY, BSCSCAN_KEY, WAT
from degen import wallet_tracker
from handlers import commands

ADD_CHAIN, ADD_ADDRESS, ADD_LABEL, ADD_ALERTS, ADD_MINIMUM, ADD_CONFIRM, COPY_ALLOC = range(70, 77)


def _guard(update: Update) -> bool:
    return update.effective_chat and update.effective_chat.id == CHAT_ID


def _wallets_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👀 Tracked Wallets", callback_data="wallet:list"), InlineKeyboardButton("➕ Add Wallet", callback_data="wallet:add")],
        [InlineKeyboardButton("📋 Recent Activity", callback_data="wallet:activity"), InlineKeyboardButton("📊 Best Calls", callback_data="wallet:calls")],
        [InlineKeyboardButton("🎰 Degen Home", callback_data="nav:degen_home")],
    ])


async def wallets_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        msg = await query.message.reply_text("🐋 Whale Tracker\n━━━━━━━━━━━━━━━━\n⏳ Loading live data...", reply_markup=_wallets_keyboard())
    else:
        msg = await update.message.reply_text("🐋 Whale Tracker\n━━━━━━━━━━━━━━━━\n⏳ Loading live data...", reply_markup=_wallets_keyboard())
    wallets = db.get_tracked_wallets(active_only=False)
    active = [w for w in wallets if w.get("active")]
    alerts = db.get_recent_wallet_alerts(hours=24)
    last = alerts[0]["tx_timestamp"].astimezone(WAT).strftime("%H:%M") if alerts and alerts[0].get("tx_timestamp") else "N/A"
    text = (
        "🐋 Whale Tracker\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Tracking {len(wallets)} wallets   {len(active)} active\n"
        f"Alerts today: {len(alerts)}\n"
        f"Last activity: {last} WAT"
    )
    await msg.edit_text(text, reply_markup=_wallets_keyboard())


async def list_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    wallets = db.get_tracked_wallets(active_only=False)
    rows = []
    for w in wallets:
        label = w.get("label") or f"{w['address'][:6]}...{w['address'][-4:]}"
        rows.append([InlineKeyboardButton(f"{w.get('tier_label','🔍')} {label} — {w['chain']}", callback_data=f"wallet:detail:{w['id']}")])
    rows.append([InlineKeyboardButton("« Back", callback_data="wallet:dash")])
    await q.message.reply_text("Tracked wallets:", reply_markup=InlineKeyboardMarkup(rows))


async def wallet_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, wallet_id: int):
    q = update.callback_query
    await q.answer()
    wallet = db.get_tracked_wallet(wallet_id)
    if not wallet:
        await q.message.reply_text("Wallet not found")
        return
    txs = db.get_wallet_transactions(wallet_id, limit=5)
    icons = {"buy": "🟢", "sell": "🔴", "transfer": "🔁", "unknown": "❔"}
    lines = [
        f"{wallet.get('tier_label','🔍')} {wallet.get('label') or wallet['address'][:6]+'...'+wallet['address'][-4:]}",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📋 {wallet['address']}",
        f"🔗 Chain: {wallet['chain']}",
        f"📅 Wallet age: {wallet.get('wallet_age_days') or 0} days",
        f"📊 Credibility: {wallet.get('credibility') or 'UNKNOWN'}",
        f"💼 Portfolio: {wallet.get('portfolio_size_label') or 'N/A'} (~${float(wallet.get('total_value_usd') or 0):,.0f})",
        f"🎯 Est. win rate: {float(wallet.get('estimated_win_rate') or 0):.1f}%",
        "",
        "📋 Recent Activity (last 5 txs):",
    ]
    for t in txs:
        wt = t["tx_timestamp"].astimezone(WAT).strftime("%H:%M") if t.get("tx_timestamp") else "--:--"
        lines.append(f"  {icons.get(t.get('tx_type'),'❔')} {t.get('token_symbol','?')} ${float(t.get('amount_usd') or 0):,.0f} {wt}")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Full History", callback_data=f"wallet:history:{wallet_id}"), InlineKeyboardButton("⚙️ Alert Settings", callback_data=f"wallet:settings:{wallet_id}")],
        [InlineKeyboardButton("🔕 Pause" if wallet.get("active") else "▶️ Resume", callback_data=f"wallet:pause:{wallet_id}"), InlineKeyboardButton("🗑 Remove", callback_data=f"wallet:remove:{wallet_id}")],
        [InlineKeyboardButton("« Back", callback_data="wallet:list")],
    ])
    await q.message.reply_text("\n".join(lines), reply_markup=kb)


async def add_wallet_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["in_conversation"] = True
    q = update.callback_query
    await q.answer()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Solana", callback_data="wallet:chain:SOL"), InlineKeyboardButton("Ethereum", callback_data="wallet:chain:ETH")], [InlineKeyboardButton("BSC", callback_data="wallet:chain:BSC"), InlineKeyboardButton("Base", callback_data="wallet:chain:BASE")]])
    await q.message.reply_text("🔗 Which chain is this wallet on?", reply_markup=kb)
    return ADD_CHAIN


async def add_wallet_chain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["new_wallet"] = {"chain": q.data.split(":")[-1], "alert_on_buy": True, "alert_on_sell": True, "alert_min_usd": 100}
    await q.message.reply_text("📋 Paste the wallet address:")
    return ADD_ADDRESS


def _valid_address(address: str, chain: str) -> bool:
    if chain == "SOL":
        return re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", address or "") is not None
    return re.match(r"^0x[a-fA-F0-9]{40}$", address or "") is not None


async def add_wallet_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = (update.message.text or "").strip()
    data = context.user_data.get("new_wallet", {})
    chain = data.get("chain")
    if not _valid_address(address, chain):
        await update.message.reply_text("Invalid address format. Paste again.")
        return ADD_ADDRESS
    if chain in {"ETH", "BASE", "BSC"} and not (ETHERSCAN_KEY or BSCSCAN_KEY):
        await update.message.reply_text("EVM tracking requires an Etherscan/BSCScan API key. Add ETHERSCAN_KEY to your environment variables.")
        context.user_data.pop("in_conversation", None)
    return ConversationHandler.END
    if db.get_tracked_wallet_by_address(address, chain):
        await update.message.reply_text("Already tracking this wallet.")
        context.user_data.pop("in_conversation", None)
    return ConversationHandler.END
    data["address"] = address
    await update.message.reply_text("🔍 Analysing wallet... this takes a few seconds")
    profile = await wallet_tracker.score_whale_reputation(address, chain)
    data.update(profile)
    holdings = profile.get("top_holdings", [])
    lines = [profile.get("summary", "Wallet profile"), "", "Top holdings:"]
    for h in holdings[:5]:
        lines.append(f"• {h.get('symbol')}: ${float(h.get('value_usd') or 0):,.0f}")
    lines.append("\nGive this wallet a nickname (or tap Skip):")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Skip — use address", callback_data="wallet:skip_label")]])
    await update.message.reply_text("\n".join(lines), reply_markup=kb)
    return ADD_LABEL


async def add_wallet_label(update: Update, context: ContextTypes.DEFAULT_TYPE):
    label = (update.message.text or "").strip()
    context.user_data["new_wallet"]["label"] = label
    return await _ask_alert_settings(update, context)


async def add_wallet_skip_label(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["new_wallet"]["label"] = ""
    return await _ask_alert_settings(update, context)


async def _ask_alert_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Buys tokens", callback_data="wallet:toggle_buy"), InlineKeyboardButton("✅ Sells tokens", callback_data="wallet:toggle_sell")],
        [InlineKeyboardButton("Continue", callback_data="wallet:alerts_next")],
    ])
    sender = update.callback_query.message.reply_text if update.callback_query else update.message.reply_text
    await sender("📣 Alert me when this wallet:", reply_markup=kb)
    return ADD_ALERTS


async def add_wallet_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = context.user_data["new_wallet"]
    if q.data == "wallet:toggle_buy":
        data["alert_on_buy"] = not data.get("alert_on_buy", True)
        return await _ask_alert_settings(update, context)
    if q.data == "wallet:toggle_sell":
        data["alert_on_sell"] = not data.get("alert_on_sell", True)
        return await _ask_alert_settings(update, context)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Any", callback_data="wallet:min:0"), InlineKeyboardButton("$50", callback_data="wallet:min:50"), InlineKeyboardButton("$100", callback_data="wallet:min:100")],
        [InlineKeyboardButton("$500", callback_data="wallet:min:500"), InlineKeyboardButton("$1K", callback_data="wallet:min:1000"), InlineKeyboardButton("$5K", callback_data="wallet:min:5000")],
    ])
    await q.message.reply_text("💰 Minimum transaction size to alert on:", reply_markup=kb)
    return ADD_MINIMUM


async def add_wallet_minimum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    val = float(q.data.split(":")[-1])
    data = context.user_data["new_wallet"]
    data["alert_min_usd"] = val
    summary = (
        f"{data.get('tier_label')} {data.get('label') or data['address'][:6]+'...'+data['address'][-4:]}\n"
        f"Chain: {data['chain']}\n"
        f"Buy alerts: {'Yes' if data.get('alert_on_buy') else 'No'}\n"
        f"Sell alerts: {'Yes' if data.get('alert_on_sell') else 'No'}\n"
        f"Min tx: ${val:,.0f}"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Start Tracking", callback_data="wallet:confirm"), InlineKeyboardButton("❌ Cancel", callback_data="wallet:cancel")]])
    await q.message.reply_text(summary, reply_markup=kb)
    return ADD_CONFIRM


async def add_wallet_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "wallet:cancel":
        await q.message.reply_text("Cancelled.", reply_markup=commands.degen_keyboard())
        context.user_data.pop("in_conversation", None)
    return ConversationHandler.END
    data = context.user_data.get("new_wallet", {})
    wallet_id = db.add_tracked_wallet(data)
    txs = await wallet_tracker.get_recent_transactions(data["address"], data["chain"], limit=1)
    if txs:
        db.update_wallet_last_tx(wallet_id, txs[0]["tx_hash"])
    await q.message.reply_text("✅ Wallet added to tracker.", reply_markup=commands.degen_keyboard())
    context.user_data.pop("in_conversation", None)
    return ConversationHandler.END


async def handle_wallet_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not _guard(update):
        return
    data = q.data
    if data == "wallet:dash":
        return await wallets_dashboard(update, context)
    if data == "wallet:list":
        return await list_wallets(update, context)
    if data.startswith("wallet:detail:"):
        return await wallet_detail(update, context, int(data.split(":")[-1]))
    if data.startswith("wallet:pause:"):
        wid = int(data.split(":")[-1])
        w = db.get_tracked_wallet(wid)
        db.set_wallet_active(wid, not bool(w.get("active")))
        return await wallet_detail(update, context, wid)
    if data.startswith("wallet:remove:"):
        db.delete_tracked_wallet(int(data.split(":")[-1]))
        return await wallets_dashboard(update, context)
    if data.startswith("wallet:history:"):
        wid = int(data.split(":")[-1])
        txs = db.get_wallet_transactions(wid, limit=20)
        lines = ["Recent wallet activity:"]
        for t in txs:
            wt = t["tx_timestamp"].astimezone(WAT).strftime("%H:%M") if t.get("tx_timestamp") else "--:--"
            lines.append(f"• {t.get('tx_type')} {t.get('token_symbol')} ${float(t.get('amount_usd') or 0):,.0f} {wt}")
        return await q.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data=f"wallet:detail:{wid}")]]))
    if data == "wallet:activity":
        msg = await q.message.reply_text("🆕 Latest Finds\n━━━━━━━━━━━━━━━━\n⏳ Loading live data...")
        alerts = db.get_recent_wallet_alerts(hours=72)
        lines = ["Recent activity (20):"]
        for a in alerts[:20]:
            wt = a["tx_timestamp"].astimezone(WAT).strftime("%H:%M") if a.get("tx_timestamp") else "--:--"
            lines.append(f"• {a.get('label') or a.get('wallet_address','')[:6]} {a.get('tx_type')} {a.get('token_symbol')} ${float(a.get('amount_usd') or 0):,.0f} {wt}")
        return await q.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="wallet:dash")]]))
    if data == "wallet:calls":
        calls = db.get_best_wallet_calls(limit=20)
        lines = ["Best whale calls we've seen:"]
        for c in calls:
            lines.append(f"• {c.get('wallet_label')} {c.get('token_symbol')} entry {c.get('entry_price')} max gain {c.get('pnl_x')}x")
        return await q.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="wallet:dash")]]))
    if data.startswith("wallet:demo_copy:"):
        from handlers import demo_handler
        tx_hash = data.split(":")[-1]
        item = context.application.bot_data.get(f"wallet_tx:{tx_hash}")
        if not item:
            return await q.message.reply_text("Trade context expired.")
        acct = db.get_demo_account("degen")
        if not acct:
            return await q.message.reply_text("You don't have a demo account yet. Set one up first.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎮 Setup Demo", callback_data="demo:degen:home")]]))
        tx = item["tx"]
        entry = float(tx.get("price_per_token") or 0)
        risk_amount = float(acct.get("balance") or 0) * 0.0025
        ok, msg = await demo_handler.open_demo_from_signal(context, "degen", {"token_symbol": tx.get("token_symbol"), "direction": "BUY", "entry_price": entry, "sl": entry * 0.85, "tp1": entry * 2, "tp2": entry * 5, "tp3": entry * 10, "position_size_usd": risk_amount * 10, "risk_amount_usd": risk_amount, "risk_pct": 0.25, "model_id": "wallet_copy", "model_name": "Whale Copy", "tier": "C", "score": 0, "source": "whale_copy", "notes": tx.get("token_address")})
        return await q.message.reply_text(msg)
    if data.startswith("wallet:copy:"):
        tx_hash = data.split(":")[-1]
        item = context.application.bot_data.get(f"wallet_tx:{tx_hash}")
        if not item:
            return await q.message.reply_text("Trade context expired.")
        tx = item["tx"]
        context.user_data["copy_trade"] = item
        entry = float(tx.get("price_per_token") or 0)
        sl, tp1, tp2, tp3 = entry * 0.85, entry * 2, entry * 5, entry * 10
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("0.1%", callback_data="wallet:alloc:0.1"), InlineKeyboardButton("0.25%", callback_data="wallet:alloc:0.25"), InlineKeyboardButton("0.5%", callback_data="wallet:alloc:0.5")], [InlineKeyboardButton("1%", callback_data="wallet:alloc:1"), InlineKeyboardButton("✏️ Manual", callback_data="wallet:alloc:manual")]])
        await q.message.reply_text(f"Entry ${entry:.8f}\nSL ${sl:.8f}\nTP1 ${tp1:.8f}\nTP2 ${tp2:.8f}\nTP3 ${tp3:.8f}\n\n💰 How much to allocate?", reply_markup=kb)
        return COPY_ALLOC
    if data.startswith("wallet:alloc:"):
        pct = data.split(":")[-1]
        if pct == "manual":
            await q.message.reply_text("Send allocation percentage, e.g. 0.3")
            return COPY_ALLOC
        return await _finalize_copy_trade(update, context, float(pct))


async def copy_alloc_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        pct = float((update.message.text or "0").strip())
    except Exception:
        await update.message.reply_text("Invalid number.")
        return COPY_ALLOC
    return await _finalize_copy_trade(update, context, pct)


async def _finalize_copy_trade(update: Update, context: ContextTypes.DEFAULT_TYPE, pct: float):
    item = context.user_data.get("copy_trade")
    if not item:
        target = update.callback_query.message.reply_text if update.callback_query else update.message.reply_text
        await target("Trade context expired.")
        context.user_data.pop("in_conversation", None)
    return ConversationHandler.END
    tx = item["tx"]
    entry = float(tx.get("price_per_token") or 0)
    trade_id = db.log_copy_trade({
        "wallet_tx_id": item["wallet_tx_id"], "token_address": tx.get("token_address"), "token_symbol": tx.get("token_symbol"), "entry_price": entry,
        "entry_usd": tx.get("amount_usd", 0) * pct / 100.0, "tp1": entry * 2, "tp2": entry * 5, "tp3": entry * 10, "sl": entry * 0.85,
    })
    db.log_degen_copy_trade(tx.get("token_symbol"), trade_id)
    db.log_trade({"pair": tx.get("token_symbol", "COPY"), "model_id": "wallet_copy", "tier": "C", "direction": "BUY", "entry_price": entry, "sl": entry * 0.85, "tp": entry * 2, "rr": 2.0, "session": "Degen", "score": 0, "risk_pct": pct, "violation": None, "source": "copy_trade"})
    target = update.callback_query.message.reply_text if update.callback_query else update.message.reply_text
    await target("✅ Copy trade logged to wallet_copy_trades, degen_trades, and trade_log.\n📸 Don't forget to share screenshot reminder.")
    context.user_data.pop("in_conversation", None)
    return ConversationHandler.END


def build_add_wallet_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(add_wallet_start, pattern=r"^wallet:add$")],
        states={
            ADD_CHAIN: [CallbackQueryHandler(add_wallet_chain, pattern=r"^wallet:chain:")],
            ADD_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_wallet_address)],
            ADD_LABEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_wallet_label), CallbackQueryHandler(add_wallet_skip_label, pattern=r"^wallet:skip_label$")],
            ADD_ALERTS: [CallbackQueryHandler(add_wallet_alerts, pattern=r"^wallet:(toggle_buy|toggle_sell|alerts_next)$")],
            ADD_MINIMUM: [CallbackQueryHandler(add_wallet_minimum, pattern=r"^wallet:min:")],
            ADD_CONFIRM: [CallbackQueryHandler(add_wallet_confirm, pattern=r"^wallet:(confirm|cancel)$")],
            COPY_ALLOC: [CallbackQueryHandler(handle_wallet_cb, pattern=r"^wallet:alloc:"), MessageHandler(filters.TEXT & ~filters.COMMAND, copy_alloc_manual)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        allow_reentry=True,
    )
