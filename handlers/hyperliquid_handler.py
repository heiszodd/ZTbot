import logging
from datetime import datetime, timezone

import db
from config import HL_ADDRESS
from engine.hyperliquid.account_reader import (
    fetch_account_summary,
    fetch_funding_summary,
    fetch_positions_with_prices,
)
from engine.hyperliquid.analytics import calculate_hl_performance, format_performance
from engine.hyperliquid.market_data import fetch_all_markets
from engine.hyperliquid.trade_planner import format_hl_trade_plan, generate_hl_trade_plan
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

log = logging.getLogger(__name__)


def _hl_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="hl:home"), InlineKeyboardButton("📊 Positions", callback_data="hl:positions")],
        [InlineKeyboardButton("📋 Open Orders", callback_data="hl:orders"), InlineKeyboardButton("📈 Performance", callback_data="hl:performance")],
        [InlineKeyboardButton("💱 Trade Plans", callback_data="hl:plans"), InlineKeyboardButton("📜 History", callback_data="hl:history")],
        [InlineKeyboardButton("🌊 Funding", callback_data="hl:funding"), InlineKeyboardButton("🏪 Markets", callback_data="hl:markets")],
        [InlineKeyboardButton("🏠 Perps Home", callback_data="nav:perps_home")],
    ])


async def show_hl_home(query, context):
    address = db.get_hl_address() or HL_ADDRESS
    if not address:
        await query.message.reply_text(
            "🔷 *Hyperliquid Dashboard*\n"
            "Connect your Hyperliquid address (public key only — 0x... format)\n\n"
            "⚠️ Phase 1: read-only monitoring.\n"
            "No private keys needed yet.\n"
            "Auto-trading comes in Phase 2.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔑 Connect Address", callback_data="hl:connect")]]),
        )
        return

    summary = await fetch_account_summary(address)
    positions = await fetch_positions_with_prices(address)
    short_addr = f"{address[:6]}...{address[-4:]}"

    lines = [
        "🔷 *Hyperliquid Dashboard*",
        "",
        f"Address: `{short_addr}`",
        f"Account Value: ${summary.get('account_value', 0):,.2f}",
        f"Available: ${summary.get('available', 0):,.2f}",
        f"Margin Used: ${summary.get('total_margin', 0):,.2f} ({summary.get('margin_ratio', 0):.1f}%)",
        f"Unrealized: ${summary.get('total_upnl', 0):+,.2f}",
        "",
        f"Positions ({len(positions)}):",
    ]
    for pos in positions[:6]:
        emoji = "🟢" if pos["side"] == "Long" else "🔴"
        lines.append(
            f"{emoji} {pos['coin']}  {pos['size']}\n"
            f"Entry: ${pos.get('entry_price', 0):,.4f} | Mark: ${pos.get('mark_price', 0):,.4f}\n"
            f"PnL: ${pos.get('live_upnl', 0):+,.2f} ({pos.get('live_upnl_pct', 0):+,.1f}%)"
        )

    await query.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=_hl_home_kb())


async def show_hl_positions(query, context):
    address = db.get_hl_address() or HL_ADDRESS
    positions = await fetch_positions_with_prices(address) if address else []
    plans = db.get_hl_trade_plans(status="pending")
    sl_map = {p.get("coin"): p.get("stop_loss") for p in plans}

    if not positions:
        await query.message.reply_text("📊 No open Hyperliquid positions.", reply_markup=_hl_home_kb())
        return

    lines = ["📊 *Hyperliquid Positions*", "━━━━━━━━━━━━━━━━━━━━━━━━"]
    for pos in positions:
        coin = pos.get("coin")
        funding = pos.get("funding_since_open", 0)
        lines.append(
            f"{'🟢' if pos.get('side') == 'Long' else '🔴'} *{coin}* {pos.get('size')}\n"
            f"Entry: ${pos.get('entry_price',0):,.4f} | Mark: ${pos.get('mark_price',0):,.4f}\n"
            f"SL(plan): {sl_map.get(coin) if sl_map.get(coin) else 'N/A'} | Liq: {pos.get('liq_price') or 'N/A'}\n"
            f"PnL: ${pos.get('live_upnl',0):+,.2f} ({pos.get('live_upnl_pct',0):+,.1f}%)\n"
            f"Funding since open: ${funding:+.4f}"
        )
    await query.message.reply_text("\n\n".join(lines), parse_mode="Markdown", reply_markup=_hl_home_kb())


async def show_hl_performance(query, context):
    address = db.get_hl_address() or HL_ADDRESS
    perf = await calculate_hl_performance(address) if address else {"total_trades": 0}
    await query.message.reply_text(format_performance(perf), parse_mode="Markdown", reply_markup=_hl_home_kb())


async def show_hl_markets(query, context):
    markets = await fetch_all_markets()
    top = sorted(markets, key=lambda m: float(m.get("day_volume", 0) or 0), reverse=True)[:20]
    lines = ["🏪 *Hyperliquid Markets (Top 20 by volume)*", "━━━━━━━━━━━━━━━━━━━━━━━━"]
    rows = []
    for m in top:
        rate = float(m.get("funding_rate", 0) or 0)
        beneficiary = "Shorts receive" if rate > 0 else "Longs receive" if rate < 0 else "Neutral"
        lines.append(f"{m['coin']}: ${m['price']:,.4f} | Funding {rate:+.5f} ({beneficiary})")
        rows.append([InlineKeyboardButton(f"{m['coin']} quote", callback_data=f"hl:quote:{m['coin']}")])
    rows.append([InlineKeyboardButton("🏠 Dashboard", callback_data="hl:home")])
    await query.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))


async def show_hl_funding(query, context):
    address = db.get_hl_address() or HL_ADDRESS
    funding = await fetch_funding_summary(address) if address else {"total": 0, "by_coin": {}}
    lines = ["🌊 *Hyperliquid Funding*", "━━━━━━━━━━━━━━━━━━━━━━━━", f"Total: ${funding.get('total', 0):+,.4f}"]
    for coin, value in funding.get("by_coin", {}).items():
        lines.append(f"{coin}: ${value:+,.4f}")
    lines.append("\nPositive means you received funding.")
    await query.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=_hl_home_kb())


async def handle_hl_live_plan(query, context):
    parts = query.data.split(":")
    setup_id = int(parts[-1])
    setup = db.get_setup_phase_by_id(setup_id)
    if not setup:
        await query.message.reply_text("Could not find saved signal for this alert.")
        return
    signal = {
        "pair": setup.get("pair"),
        "direction": setup.get("direction", "Bullish"),
        "entry_price": setup.get("entry_price"),
        "stop_loss": setup.get("stop_loss"),
        "take_profit": setup.get("tp1"),
        "quality_grade": "C",
        "quality_score": 0,
    }
    plan = await generate_hl_trade_plan(signal)
    await query.message.reply_text(
        format_hl_trade_plan(plan),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Save Plan", callback_data=f"hl:save_plan:{setup_id}"), InlineKeyboardButton("🎮 Run as Demo", callback_data=f"hl:demo:{setup_id}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="hl:home")],
        ]),
    )


async def handle_hl_demo(query, context):
    parts = query.data.split(":")
    setup_id = int(parts[-1])
    setup = db.get_setup_phase_by_id(setup_id)
    if not setup:
        await query.message.reply_text("Setup not found for HL demo trade.")
        return

    signal = {
        "pair": setup.get("pair"),
        "direction": setup.get("direction", "Bullish"),
        "entry_price": setup.get("entry_price"),
        "stop_loss": setup.get("stop_loss"),
        "take_profit": setup.get("tp1"),
        "position_size": 100,
        "risk_amount": 5,
    }
    plan = await generate_hl_trade_plan(signal)
    if not plan.get("success"):
        await query.message.reply_text(format_hl_trade_plan(plan), parse_mode="Markdown")
        return

    side = "BUY" if plan["side"] == "Long" else "SELL"
    trade_id = db.open_demo_trade(
        {
            "section": "perps",
            "pair": f"{plan['coin']}USDT",
            "token_symbol": plan["coin"],
            "direction": side,
            "entry_price": plan["entry_price"],
            "sl": plan["stop_loss"],
            "tp1": plan["tp1"],
            "tp2": plan["tp2"],
            "tp3": plan["tp3"],
            "position_size_usd": plan["size_usd"],
            "risk_amount_usd": max(plan["risk_amount"], 1),
            "risk_pct": 0.5,
            "model_id": setup.get("model_id"),
            "model_name": "HL Demo",
            "tier": "A",
            "score": setup.get("score") or 0,
            "source": "hl_demo",
            "notes": "Hyperliquid Phase 1 demo open",
        }
    )
    await query.message.reply_text(
        f"🎮 HL demo trade opened (#{trade_id})\n"
        f"{plan['coin']} {plan['side']} | Entry ${plan['entry_price']:,.4f}\n"
        "Phase 1 — execution not yet implemented for real orders."
    )


async def handle_hl_cb(update, context):
    q = update.callback_query
    await q.answer()

    if q.data == "hl:home":
        return await show_hl_home(q, context)
    if q.data == "hl:positions":
        return await show_hl_positions(q, context)
    if q.data == "hl:performance":
        return await show_hl_performance(q, context)
    if q.data == "hl:markets":
        return await show_hl_markets(q, context)
    if q.data == "hl:funding":
        return await show_hl_funding(q, context)
    if q.data.startswith("hl:live_plan:"):
        return await handle_hl_live_plan(q, context)
    if q.data.startswith("hl:demo:"):
        return await handle_hl_demo(q, context)
    if q.data.startswith("hl:save_plan:"):
        setup_id = int(q.data.split(":")[-1])
        setup = db.get_setup_phase_by_id(setup_id)
        if not setup:
            return await q.message.reply_text("Setup not found.")
        saved_id = db.save_hl_trade_plan(
            {
                "address": db.get_hl_address() or HL_ADDRESS,
                "coin": setup.get("pair", "").replace("USDT", ""),
                "side": "Long" if "bull" in str(setup.get("direction", "")).lower() else "Short",
                "entry_price": setup.get("entry_price"),
                "stop_loss": setup.get("stop_loss"),
                "take_profit_1": setup.get("tp1"),
                "take_profit_2": setup.get("tp2"),
                "take_profit_3": setup.get("tp3"),
                "size_usd": 100,
                "leverage": 5,
                "source": "phase_engine",
                "signal_id": setup_id,
                "status": "pending",
                "notes": f"Saved {datetime.now(timezone.utc).isoformat()}",
            }
        )
        return await q.message.reply_text(f"✅ HL plan saved as #{saved_id}.")
    if q.data.startswith("hl:quote:"):
        coin = q.data.split(":")[-1]
        signal = {"pair": f"{coin}USDT", "direction": "Bullish", "stop_loss": 1}
        plan = await generate_hl_trade_plan(signal)
        return await q.message.reply_text(format_hl_trade_plan(plan), parse_mode="Markdown")
    if q.data in {"hl:connect", "hl:orders", "hl:plans", "hl:history"}:
        return await q.message.reply_text("Phase 1 — execution not yet implemented")
