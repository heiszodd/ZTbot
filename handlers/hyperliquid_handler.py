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
from security.auth import require_auth, require_auth_callback
from security.rate_limiter import check_command_rate
from utils.formatting import format_usd

log = logging.getLogger(__name__)


def _hl_home_kb(mode: str = "simple") -> InlineKeyboardMarkup:
    base = [[InlineKeyboardButton("⚡ Simple Mode" if mode=="simple" else "🔬 Advanced Mode", callback_data="hl:toggle_mode")]]
    rows = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="hl:home"), InlineKeyboardButton("📊 Positions", callback_data="hl:positions")],
        [InlineKeyboardButton("📋 Open Orders", callback_data="hl:orders"), InlineKeyboardButton("📈 Performance", callback_data="hl:performance")],
        [InlineKeyboardButton("💱 Trade Plans", callback_data="hl:plans"), InlineKeyboardButton("📜 History", callback_data="hl:history")],
        [InlineKeyboardButton("🌊 Funding", callback_data="hl:funding"), InlineKeyboardButton("🏪 Markets", callback_data="hl:markets")],
        [InlineKeyboardButton("🏠 Perps Home", callback_data="nav:perps_home")],
    ]
    if mode == "advanced":
        rows.insert(3, [InlineKeyboardButton("📏 Quick Risk", callback_data="hl:risk_sizes")])
    return InlineKeyboardMarkup(base + rows)


async def show_hl_home(query, context):
    settings = db.get_user_settings(query.message.chat_id)
    mode = settings.get("perps_mode", "simple")
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
        "⚡ *Phase 2 Live Trading Enabled*",
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

    await query.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=_hl_home_kb(mode))


async def show_hl_positions(query, context):
    settings = db.get_user_settings(query.message.chat_id)
    mode = settings.get("perps_mode", "simple")
    address = db.get_hl_address() or HL_ADDRESS
    positions = await fetch_positions_with_prices(address) if address else []
    plans = db.get_hl_trade_plans(status="pending")
    sl_map = {p.get("coin"): p.get("stop_loss") for p in plans}

    if not positions:
        await query.message.reply_text("📊 No open Hyperliquid positions.", reply_markup=_hl_home_kb(db.get_user_settings(query.message.chat_id).get("perps_mode","simple")))
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
    kb_rows = []
    for pos in positions[:5]:
        coin = pos.get("coin")
        kb_rows.append([InlineKeyboardButton(f"💸 {coin} 25%", callback_data=f"hl:close:{coin}:25"), InlineKeyboardButton("50%", callback_data=f"hl:close:{coin}:50"), InlineKeyboardButton("All", callback_data=f"hl:close:{coin}:100")])
    kb_rows.extend(_hl_home_kb(db.get_user_settings(query.message.chat_id).get("perps_mode","simple")).inline_keyboard)
    await query.message.reply_text("\n\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb_rows))


async def show_hl_performance(query, context):
    settings = db.get_user_settings(query.message.chat_id)
    mode = settings.get("perps_mode", "simple")
    address = db.get_hl_address() or HL_ADDRESS
    perf = await calculate_hl_performance(address) if address else {"total_trades": 0}
    await query.message.reply_text(format_performance(perf), parse_mode="Markdown", reply_markup=_hl_home_kb(db.get_user_settings(query.message.chat_id).get("perps_mode","simple")))


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
    settings = db.get_user_settings(query.message.chat_id)
    mode = settings.get("perps_mode", "simple")
    address = db.get_hl_address() or HL_ADDRESS
    funding = await fetch_funding_summary(address) if address else {"total": 0, "by_coin": {}}
    lines = ["🌊 *Hyperliquid Funding*", "━━━━━━━━━━━━━━━━━━━━━━━━", f"Total: ${funding.get('total', 0):+,.4f}"]
    for coin, value in funding.get("by_coin", {}).items():
        lines.append(f"{coin}: ${value:+,.4f}")
    lines.append("\nPositive means you received funding.")
    await query.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=_hl_home_kb(mode))


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
        format_hl_trade_plan(plan) + "\n\n⚡ *Phase 2*: confirm to place a real signed order.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📲 Execute Live", callback_data=f"hl:execute:{setup_id}"), InlineKeyboardButton("📋 Save Plan", callback_data=f"hl:save_plan:{setup_id}")],
            [InlineKeyboardButton("🎮 Run as Demo", callback_data=f"hl:demo:{setup_id}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="hl:home")],
        ]),
    )


async def handle_hl_execute_trade(query, context, plan, signal_id=""):
    from engine.execution_pipeline import run_execution_pipeline
    from engine.hyperliquid.executor import place_limit_order

    result = await run_execution_pipeline(
        section="hyperliquid",
        plan=plan,
        executor=place_limit_order,
        user_id=query.from_user.id,
        context=context,
        signal_id=signal_id,
    )

    if result.get("pending"):
        await query.message.reply_text(result["message"], parse_mode="Markdown", reply_markup=result["keyboard"])
        return
    if not result.get("success"):
        await query.answer(result.get("error", "Failed"), show_alert=True)
        return
    tx_id = result.get("tx_id", "")
    await query.message.reply_text(f"✅ *Order Placed*\nOrder ID: `{tx_id}`", parse_mode="Markdown")


async def handle_hl_close_position(query, context, coin, size, is_long, pct=100):
    from engine.execution_pipeline import run_execution_pipeline
    from engine.hyperliquid.executor import close_position
    plan = {"coin": coin, "side": "Close", "size_usd": size * pct / 100, "size_coins": size, "entry_price": 0, "stop_loss": 0}

    async def close_exec(_):
        return await close_position(coin=coin, size=size, is_long=is_long, pct=pct)

    result = await run_execution_pipeline("hyperliquid", plan, close_exec, query.from_user.id, context)
    if result.get("pending"):
        await query.message.reply_text(result["message"], parse_mode="Markdown", reply_markup=result["keyboard"])
    elif result.get("success"):
        await query.answer(f"✅ {pct}% of {coin} closed", show_alert=True)
    else:
        await query.answer(result.get("error", "Close failed"), show_alert=True)


async def handle_hl_cancel_order(query, context, order_id):
    from engine.hyperliquid.executor import cancel_order

    order = db.get_hl_order(order_id)
    coin = order.get("coin", "") if order else ""
    result = await cancel_order(coin, int(order_id))
    if result.get("success"):
        db.update_hl_order_status(order_id, "cancelled")
        await query.answer("✅ Order cancelled", show_alert=True)
    else:
        await query.answer(result.get("error", "Cancel failed"), show_alert=True)


async def handle_hl_set_trail(query, context, coin, trail_pct):
    from engine.hyperliquid.executor import set_trailing_stop

    pos = db.get_hl_position_by_coin(coin)
    if not pos:
        await query.answer("Position not found", show_alert=True)
        return
    result = await set_trailing_stop(coin=coin, size=pos["size"], is_long=pos.get("side") == "Long", trail_pct=trail_pct)
    if result.get("success"):
        db.save_hl_trailing_stop(coin, trail_pct)
        await query.answer(f"✅ Trailing stop {trail_pct}% set", show_alert=True)
    else:
        await query.answer(result.get("error", "Failed"), show_alert=True)


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


@require_auth_callback
async def handle_hl_cb(update, context):
    q = update.callback_query
    uid = q.from_user.id if q and q.from_user else 0
    allowed, reason = check_command_rate(uid)
    if not allowed:
        await q.answer(reason, show_alert=True)
        return
    await q.answer()

    if q.data == "hl:toggle_mode":
        st = db.get_user_settings(q.message.chat_id)
        db.update_user_settings(q.message.chat_id, {"perps_mode": "advanced" if st.get("perps_mode") == "simple" else "simple"})
        return await show_hl_home(q, context)
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
    if q.data.startswith("hl:execute:"):
        setup_id = int(q.data.split(":")[-1])
        setup = db.get_setup_phase_by_id(setup_id)
        if not setup:
            return await q.message.reply_text("Setup not found.")
        signal = {"pair": setup.get("pair"), "direction": setup.get("direction", "Bullish"), "entry_price": setup.get("entry_price"), "stop_loss": setup.get("stop_loss"), "take_profit": setup.get("tp1")}
        plan = await generate_hl_trade_plan(signal)
        return await handle_hl_execute_trade(q, context, plan, str(setup_id))
    if q.data.startswith("hl:quote:"):
        coin = q.data.split(":")[-1]
        signal = {"pair": f"{coin}USDT", "direction": "Bullish", "stop_loss": 1}
        plan = await generate_hl_trade_plan(signal)
        return await q.message.reply_text(format_hl_trade_plan(plan), parse_mode="Markdown")
    if q.data.startswith("hl:close:"):
        _,_,coin,pct = q.data.split(":",3)
        pos = db.get_hl_position_by_coin(coin)
        if not pos:
            return await q.answer("Position not found", show_alert=True)
        return await handle_hl_close_position(q, context, coin, float(pos.get("size") or 0), pos.get("side") == "Long", float(pct))
    if q.data.startswith("hl:cancel:"):
        return await handle_hl_cancel_order(q, context, q.data.split(":", 2)[2])
    if q.data.startswith("hl:trail:"):
        _, _, coin, trail = q.data.split(":", 3)
        return await handle_hl_set_trail(q, context, coin, float(trail))
    if q.data in {"hl:connect", "hl:orders", "hl:plans", "hl:history", "hl:risk_sizes"}:
        return await q.message.reply_text("Phase 1 — execution not yet implemented")

# New-nav compatibility exports
show_perps_live_home = show_hl_home
show_hl_open_orders = show_hl_positions
show_hl_history = show_hl_positions


async def show_hl_trail_setup(query, context, coin: str):
    await query.message.reply_text(
        f"Set trailing stop for {coin}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("2%", callback_data=f"hl:trail:{coin}:2")]]),
    )


async def handle_hl_wallet_setup(query, context):
    await query.message.reply_text("Send Hyperliquid public address.")
