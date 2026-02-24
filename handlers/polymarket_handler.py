from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import db
from engine.polymarket.market_reader import fetch_markets, fetch_market_by_id
from engine.polymarket.scanner import run_market_scanner, format_scanner_results
from engine.polymarket.sentiment import get_crypto_sentiment, format_sentiment_dashboard
from engine.polymarket.demo_trading import open_poly_demo_trade


async def show_polymarket_home(query, context):
    markets = await fetch_markets(limit=30)
    total = len(markets)
    top_crypto = next((m for m in markets if "btc" in m.get("question", "").lower() or "sol" in m.get("question", "").lower()), None)
    sentiment = await get_crypto_sentiment()
    overall = sentiment.get("btc", {}).get("bias", "neutral") if sentiment else "neutral"
    text = (
        "🎯 *Polymarket*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Active markets: {total}\n"
        f"Top crypto: {(top_crypto or {}).get('question', 'N/A')[:55]}\n"
        f"Crowd bias: {overall.title()}\n"
    )
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔍 Scanner", callback_data="poly:scanner"), InlineKeyboardButton("📊 Watchlist", callback_data="poly:watchlist")],
            [InlineKeyboardButton("🌊 Sentiment", callback_data="poly:sentiment"), InlineKeyboardButton("🎮 Demo Trades", callback_data="poly:demo_trades")],
            [InlineKeyboardButton("🔔 Add Alert", callback_data="poly:add_alert"), InlineKeyboardButton("📅 Resolving Soon", callback_data="poly:resolving")],
            [InlineKeyboardButton("🏠 Home", callback_data="nav:home")],
        ]
    )
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)


async def show_poly_scanner(query, context):
    results = await run_market_scanner()
    text = format_scanner_results(results or {})
    await query.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("➕ Watch High Volume", callback_data="poly:watchcat:high_volume"), InlineKeyboardButton("➕ Watch Uncertain", callback_data="poly:watchcat:uncertain")],
                [InlineKeyboardButton("📲 Live Trade", callback_data="poly:live_top"), InlineKeyboardButton("🎮 Demo Trade", callback_data="poly:demo_top")],
            ]
        ),
    )


async def show_poly_sentiment(query, context):
    sentiment = await get_crypto_sentiment()
    text = format_sentiment_dashboard(sentiment)
    text += "\n\n_Use this to confirm/deny perps bias._"
    await query.message.reply_text(text, parse_mode="Markdown")


async def handle_poly_demo_trade(query, context, market_id: str):
    context.user_data["poly_state"] = "choose_side"
    context.user_data["poly_market_id"] = market_id
    await query.message.reply_text(
        "Which side? Choose YES or NO",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("YES", callback_data="poly:pick:YES"), InlineKeyboardButton("NO", callback_data="poly:pick:NO")]]),
    )


async def handle_poly_live_trade(query, context, market_id: str):
    market = await fetch_market_by_id(market_id)
    question = market.get("question", market_id)
    await query.message.reply_text(
        "📲 Live Trading — Coming in Phase 2\n\n"
        "To trade this market manually now:\n"
        "1. Go to polymarket.com\n"
        f"2. Search: {question[:80]}\n"
        "3. Buy YES/NO with USDC on Polygon\n\n"
        "Phase 2 will execute this automatically.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎮 Demo Trade Instead", callback_data=f"poly:demo:{market_id}")]]),
    )


@require_auth
async def handle_poly_text(update, context):
    state = context.user_data.get("poly_state")
    if not state or not update.message or not update.message.text:
        return False
    if state == "await_custom_size":
        try:
            size = float(update.message.text.strip().replace("$", ""))
        except Exception:
            await update.message.reply_text("Invalid size.")
            return True
        market_id = context.user_data.get("poly_market_id")
        side = context.user_data.get("poly_side", "YES")
        market = await fetch_market_by_id(market_id)
        yes = 0.0
        for t in market.get("tokens", []):
            if str(t.get("outcome", "")).lower() == "yes":
                yes = float(t.get("price", 0) or 0) * 100
        tid = await open_poly_demo_trade(market_id, market.get("question", ""), side, yes, size)
        await update.message.reply_text(f"✅ Demo position opened:\n{side} on {market.get('question','')[:60]}\nEntry: {yes:.0f}% probability\nSize: ${size:.0f}\nP&L updates every 15 minutes.\nID: {tid}")
        context.user_data.pop("poly_state", None)
        return True
    return False


@require_auth_callback
async def handle_polymarket_cb(update, context):
    q = update.callback_query
    uid = q.from_user.id if q and q.from_user else 0
    allowed, reason = check_command_rate(uid)
    if not allowed:
        await q.answer(reason, show_alert=True)
        return
    await q.answer()
    data = q.data
    if data in {"poly:home", "nav:polymarket_home"}:
        return await show_polymarket_home(q, context)
    if data == "poly:scanner":
        return await show_poly_scanner(q, context)
    if data == "poly:sentiment":
        return await show_poly_sentiment(q, context)
    if data.startswith("poly:live:"):
        return await handle_poly_live_trade(q, context, data.split(":", 2)[2])
    if data.startswith("poly:demo:"):
        return await handle_poly_demo_trade(q, context, data.split(":", 2)[2])
    if data.startswith("poly:pick:"):
        side = data.split(":", 2)[2]
        context.user_data["poly_side"] = side
        context.user_data["poly_state"] = "await_custom_size"
        return await q.message.reply_text(
            "Size? (default $10)",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("$5", callback_data="poly:size:5"), InlineKeyboardButton("$10", callback_data="poly:size:10"), InlineKeyboardButton("$25", callback_data="poly:size:25"), InlineKeyboardButton("$50", callback_data="poly:size:50")]]),
        )
    if data.startswith("poly:size:"):
        size = float(data.split(":", 2)[2])
        market_id = context.user_data.get("poly_market_id")
        side = context.user_data.get("poly_side", "YES")
        market = await fetch_market_by_id(market_id)
        yes = 0.0
        for t in market.get("tokens", []):
            if str(t.get("outcome", "")).lower() == "yes":
                yes = float(t.get("price", 0) or 0) * 100
        tid = await open_poly_demo_trade(market_id, market.get("question", ""), side, yes, size)
        context.user_data.pop("poly_state", None)
        return await q.message.reply_text(f"✅ Demo position opened:\n{side} on {market.get('question','')[:60]}\nEntry: {yes:.0f}% probability\nSize: ${size:.0f}\nP&L updates every 15 minutes.\nID: {tid}")
    if data.startswith("poly:watchcat:"):
        cat = data.split(":", 2)[2]
        results = await run_market_scanner()
        items = (results or {}).get(cat, [])[:3]
        for m in items:
            db.add_poly_watchlist({"market_id": m["market_id"], "question": m["question"], "alert_yes_above": 60, "alert_yes_below": 40})
        return await q.message.reply_text(f"✅ Added {len(items)} market(s) to watchlist from {cat}.")
    if data.startswith("poly:remove:"):
        db.remove_poly_watchlist(data.split(":", 2)[2])
        return await q.message.reply_text("🗑 Removed market alert.")
    if data == "poly:watchlist":
        rows = db.get_poly_watchlist()
        if not rows:
            return await q.message.reply_text("📊 Polymarket watchlist is empty.")
        txt = "📊 *Polymarket Watchlist*\n━━━━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join([f"• {r.get('question','?')[:65]}" for r in rows[:20]])
        return await q.message.reply_text(txt, parse_mode="Markdown")
    if data == "poly:demo_trades":
        rows = db.get_poly_demo_trades()
        if not rows:
            return await q.message.reply_text("🎮 No Polymarket demo trades yet.")
        txt = "🎮 *Polymarket Demo Trades*\n━━━━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join([f"#{r['id']} {r['position']} {r.get('question','')[:45]} — {r['status']} {float(r.get('pnl_usd') or 0):+.2f}$" for r in rows[:20]])
        return await q.message.reply_text(txt, parse_mode="Markdown")
