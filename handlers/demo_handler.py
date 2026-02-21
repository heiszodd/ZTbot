from __future__ import annotations

import json
import time
import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import db
import prices


def _section_title(section: str) -> str:
    return "PERPS" if section == "perps" else "DEGEN"


def _dashboard_kb(section: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 Open Trades", callback_data=f"demo:{section}:open"), InlineKeyboardButton("📋 Trade History", callback_data=f"demo:{section}:history")],
        [InlineKeyboardButton("💰 Deposit More", callback_data=f"demo:{section}:deposit"), InlineKeyboardButton("🔄 Reset Account", callback_data=f"demo:{section}:reset")],
        [InlineKeyboardButton("📊 Full Stats", callback_data=f"demo:{section}:stats"), InlineKeyboardButton("🏆 Best Trades", callback_data=f"demo:{section}:best")],
        [InlineKeyboardButton(f"« Back to {_section_title(section)}", callback_data=f"nav:{'perps_home' if section=='perps' else 'degen_home'}")],
    ])


def _setup_kb(section: str):
    vals = [1000, 5000, 10000, 25000, 50000, 100000]
    rows = [[InlineKeyboardButton(f"${vals[i]:,}", callback_data=f"demo:{section}:setup:{vals[i]}"), InlineKeyboardButton(f"${vals[i+1]:,}", callback_data=f"demo:{section}:setup:{vals[i+1]}")] for i in range(0, len(vals), 2)]
    rows.append([InlineKeyboardButton("✏️ Custom amount", callback_data=f"demo:{section}:setup:custom")])
    return InlineKeyboardMarkup(rows)


async def _render_dashboard(sender, section: str):
    st = db.get_demo_stats(section)
    open_trades = db.get_open_demo_trades(section)
    lines = [
        f"🎮 Demo Trading — {_section_title(section)}",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💰 Balance:        ${st.get('balance',0):,.2f}",
        f"📈 Total PnL:      ${st.get('total_pnl',0):,.2f} ({st.get('total_pnl_pct',0):.2f}%)",
        f"🏆 Peak Balance:   ${st.get('peak_balance',0):,.2f}",
        f"📉 Lowest:         ${st.get('lowest_balance',0):,.2f}",
        "",
        "📊 Performance",
        f"   Trades:   {st.get('total_trades',0)}  (W {st.get('winning_trades',0)} | L {st.get('losing_trades',0)})",
        f"   Win Rate: {st.get('win_rate',0):.1f}%",
        "",
        f"📌 Open Positions ({len(open_trades)}):",
    ]
    for t in open_trades[:6]:
        lines.append(f"• 🎮 {t.get('pair') or t.get('token_symbol')} {t.get('direction')} [PAPER] {t.get('current_pnl_pct',0):+.2f}%")
    lines.append("\n_Virtual funds only — not real money_")
    await sender("\n".join(lines), reply_markup=_dashboard_kb(section), parse_mode="Markdown")


async def demo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Choose demo section", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Perps", callback_data="demo:perps:home"), InlineKeyboardButton("Degen", callback_data="demo:degen:home")]]))


async def demo_perps_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    acct = db.get_demo_account("perps")
    if not acct:
        return await update.message.reply_text("🎮 Demo Trading — PERPS\n━━━━━━━━━━━━━━━━━━━━━━━━\nPaper trade with virtual funds.\nHow much virtual capital to start with?", reply_markup=_setup_kb("perps"))
    await _render_dashboard(update.message.reply_text, "perps")


async def demo_degen_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    acct = db.get_demo_account("degen")
    if not acct:
        return await update.message.reply_text("🎮 Demo Trading — DEGEN\n━━━━━━━━━━━━━━━━━━━━━━━━\nPaper trade with virtual funds.\nHow much virtual capital to start with?", reply_markup=_setup_kb("degen"))
    await _render_dashboard(update.message.reply_text, "degen")


async def open_demo_from_signal(context: ContextTypes.DEFAULT_TYPE, section: str, trade: dict):
    acct = db.get_demo_account(section)
    if not acct:
        return False, "You don't have a demo account yet. Set one up first."
    tid = db.open_demo_trade({**trade, "section": section})
    return True, f"🎮 DEMO — Demo trade opened! ID: #{tid}"


async def handle_demo_risk_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payload = context.user_data.get("demo_alert_trade")
    if not payload:
        return

    raw = (update.message.text or "").strip().replace("$", "").replace(",", "")
    try:
        risk_amount = float(raw)
    except Exception:
        await update.message.reply_text("Enter a valid USD amount (e.g. 25).")
        return

    if risk_amount <= 0:
        await update.message.reply_text("Risk amount must be greater than 0.")
        return

    balance = float(payload.get("balance") or 0)
    risk_amount = min(risk_amount, balance)
    entry = float(payload.get("entry_price") or 0)
    sl = float(payload.get("sl") or 0)
    tp = float(payload.get("tp") or 0)
    direction = str(payload.get("direction") or "BUY").upper()

    if entry <= 0 or sl <= 0:
        context.user_data.pop("demo_alert_trade", None)
        context.user_data.pop("in_conversation", None)
        await update.message.reply_text("Could not open demo trade: invalid alert entry/SL values.")
        return

    sl_distance_pct = abs((entry - sl) / entry)
    position = (risk_amount / sl_distance_pct) if sl_distance_pct > 0 else risk_amount
    tp1 = tp if tp > 0 else (entry * (1.01 if direction in {"BUY", "LONG"} else 0.99))
    tp2 = entry + (tp1 - entry) * 1.5
    tp3 = entry + (tp1 - entry) * 2.0

    ok, msg = await open_demo_from_signal(context, "perps", {
        "pair": payload.get("pair"),
        "direction": payload.get("direction"),
        "entry_price": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "position_size_usd": max(0, position),
        "risk_amount_usd": risk_amount,
        "risk_pct": (risk_amount / balance * 100) if balance else 0,
        "model_id": payload.get("model_id"),
        "model_name": payload.get("model_name"),
        "tier": payload.get("tier"),
        "score": payload.get("score"),
        "source": "alert_demo_entry",
        "notes": "Demo entry from alert with user-defined risk",
    })
    context.user_data.pop("demo_alert_trade", None)
    context.user_data.pop("in_conversation", None)
    await update.message.reply_text(msg)


async def handle_demo_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    parts = q.data.split(":")
    section, action = parts[1], parts[2]
    if action == "home":
        acct = db.get_demo_account(section)
        if not acct:
            return await q.message.reply_text(f"🎮 Demo Trading — {_section_title(section)}\n━━━━━━━━━━━━━━━━━━━━━━━━\nPaper trade with virtual funds.\nHow much virtual capital to start with?", reply_markup=_setup_kb(section))
        return await _render_dashboard(q.message.reply_text, section)
    if action == "setup":
        if parts[3] == "custom":
            context.user_data["demo_custom_section"] = section
            return await q.message.reply_text("Enter custom demo amount (100 - 10000000):")
        amount = float(parts[3])
        db.create_demo_account(section, amount)
        return await q.message.reply_text(f"✅ Demo account created!\n💰 Starting balance: ${amount:,.2f}\n📈 Let's start paper trading.")
    if action == "deposit":
        db.deposit_demo_funds(section, 1000)
        return await q.message.reply_text("🎮 DEMO — Deposited $1,000 [PAPER].")
    if action == "reset":
        db.reset_demo_account(section)
        return await q.message.reply_text("🎮 DEMO — Account reset completed.")
    if action == "open":
        trades = db.get_open_demo_trades(section)
        if not trades:
            return await q.message.reply_text("No open demo trades.")
        lines = [f"🎮 Open Demo Trades — {_section_title(section)}", "━━━━━━━━━━━━━━━━━━━━━━━━"]
        for t in trades:
            lines.append(f"#{t['id']} {t.get('pair') or t.get('token_symbol')} {t.get('direction')} entry {t.get('entry_price')} now {t.get('current_price')} [PAPER] {t.get('current_pnl_pct',0):+.2f}%")
        return await q.message.reply_text("\n".join(lines))
    if action == "history":
        rows = db.get_demo_trade_history(section)
        lines = ["🎮 Demo Trade History", "━━━━━━━━━━━━━━━━━━━━━━━━"]
        for r in rows[:20]:
            lines.append(f"🎮 #{r['id']} {r.get('pair') or r.get('token_symbol')} {r.get('result') or 'OPEN'} [PAPER] {r.get('final_pnl_pct') or r.get('current_pnl_pct') or 0:+.2f}%")
        return await q.message.reply_text("\n".join(lines))
    if action in {"stats", "best"}:
        return await _render_dashboard(q.message.reply_text, section)


async def _fetch_dex_price(address: str) -> float:
    if not address:
        return 0.0
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            r = await client.get(f"https://api.dexscreener.com/latest/dex/tokens/{address}")
            pairs = (r.json() or {}).get("pairs") or []
            if not pairs:
                return 0.0
            best = max(pairs, key=lambda p: float(((p or {}).get("liquidity") or {}).get("usd") or 0))
            return float(best.get("priceUsd") or 0)
    except Exception:
        return 0.0


async def demo_monitor_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id or context.application.bot_data.get("chat_id")
    for section in ("perps", "degen"):
        for t in db.get_open_demo_trades(section):
            pair = t.get("pair") or t.get("token_symbol")
            source = str(t.get("source") or "")
            if source == "ca_report":
                note = json.loads(t.get("notes") or "{}")
                price = await _fetch_dex_price(note.get("address")) or float(t.get("current_price") or 0)
            else:
                price = prices.get_price(t.get("pair")) if section == "perps" and t.get("pair") else float(t.get("current_price") or 0)
            if not price:
                continue
            db.update_demo_trade_pnl(t["id"], price)
            tr = db.get_demo_trade_by_id(t["id"]) or t
            direction = (tr.get("direction") or "LONG").upper()
            hit_sl = (price <= tr.get("sl", 0)) if direction in {"LONG", "BUY"} else (price >= tr.get("sl", 10**18))
            hit_tp1 = (price >= tr.get("tp1", 10**18)) if direction in {"LONG", "BUY"} else (price <= tr.get("tp1", 0))
            hit_tp2 = (price >= tr.get("tp2", 10**18)) if direction in {"LONG", "BUY"} else (price <= tr.get("tp2", 0))
            hit_tp3 = (price >= tr.get("tp3", 10**18)) if direction in {"LONG", "BUY"} else (price <= tr.get("tp3", 0))
            if hit_sl:
                closed = db.close_demo_trade(tr["id"], price, "SL")
                msg = (
                    f"🛑 *Stop Loss Hit — {tr.get('token_symbol')}*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎮 Demo Position #{tr['id']} closed\n"
                    f"📉 SL at {prices.fmt_price(tr.get('sl') or 0)}\n"
                    f"💸 Loss: ${closed.get('final_pnl_usd',0):+.2f}\n"
                    f"💰 New Demo Balance: ${closed.get('balance',0):,.2f}"
                )
                await context.application.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
                continue
            if source == "ca_report" and (hit_tp1 or hit_tp2 or hit_tp3):
                lvl = "TP3" if hit_tp3 else "TP2" if hit_tp2 else "TP1"
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("💸 Sell All Now", callback_data=f"ca:sell_confirm:{tr['id']}"), InlineKeyboardButton("💸 Sell 50%", callback_data=f"ca:sell50:{tr['id']}")], [InlineKeyboardButton("🚀 Keep Riding", callback_data=f"ca:ride:{tr['id']}"), InlineKeyboardButton("📊 View Report", callback_data=f"ca:position:{tr['id']}")]])
                msg = (
                    f"🎯 *TP Level Hit — {tr.get('token_symbol')}*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎮 Demo Position #{tr['id']}\n"
                    f"📈 {lvl} reached at {prices.fmt_price(price)}\n"
                    f"💰 Current PnL: ${float(tr.get('current_pnl_usd') or 0):+.2f} ({float(tr.get('current_x') or 1):.2f}x)\n\n"
                    "Take profit or keep riding?"
                )
                await context.application.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown", reply_markup=kb)
            if hit_tp3 and source != "ca_report":
                closed = db.close_demo_trade(tr["id"], price, "TP3")
                await context.application.bot.send_message(chat_id=chat_id, text=f"🎮 DEMO — Demo Trade Closed — TP3\n{pair}\nPnL: [PAPER] ${closed.get('final_pnl_usd',0):+.2f}")
            if source == "ca_report":
                opened = tr.get("opened_at")
                if opened:
                    mins = (time.time() - opened.timestamp()) / 60
                    if mins > int(tr.get("time_stop_minutes") or 30) and abs(float(tr.get("current_pnl_pct") or 0)) < 2:
                        kb = InlineKeyboardMarkup([[InlineKeyboardButton("💸 Exit Now", callback_data=f"ca:sell:{tr['id']}"), InlineKeyboardButton("⏳ Give More Time", callback_data=f"ca:time_extend:{tr['id']}")]])
                        msg = (
                            f"⏰ *Time Stop — {tr.get('token_symbol')}*\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"🎮 No significant move after {int(tr.get('time_stop_minutes') or 30)} minutes\n"
                            f"📊 Current PnL: ${float(tr.get('current_pnl_usd') or 0):+.2f}"
                        )
                        await context.application.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown", reply_markup=kb)
