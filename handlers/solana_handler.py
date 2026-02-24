import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import db
from engine.solana.wallet_reader import get_wallet_summary, get_token_price_usd
from engine.solana.jupiter_quotes import get_swap_quote, format_quote, USDC_MINT
from engine.solana.trade_planner import generate_trade_plan, format_trade_plan


def _is_valid_solana_address(value: str) -> bool:
    if not value or value.startswith("0x") or not (32 <= len(value) <= 44):
        return False
    return bool(re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", value))


async def show_solana_home(query, context):
    wallet = db.get_solana_wallet()
    if not wallet:
        text = (
            "🔑 *Solana Wallet*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "No wallet connected yet.\n\n"
            "To get started, provide your\n"
            "Solana *public key* (wallet address).\n\n"
            "⚠️ _Phase 1: read-only monitoring._\n"
            "_No private keys needed yet._\n"
            "_Auto-trading comes in Phase 2._"
        )
        buttons = [[InlineKeyboardButton("🔑 Connect Wallet", callback_data="solana:connect")], [InlineKeyboardButton("🏠 Home", callback_data="nav:home")]]
    else:
        summary = await get_wallet_summary(wallet["public_key"])
        short_key = wallet["public_key"][:6] + "..." + wallet["public_key"][-4:]
        text = (
            f"🔑 *Solana Wallet*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Address: `{short_key}`\n\n"
            f"💰 *Balances*\n"
            f"SOL:   {summary['sol_balance']:.4f} SOL (${summary['sol_usd']:.2f})\n"
            f"USDC:  ${summary['usdc_balance']:.2f}\n"
        )
        if summary["other_tokens"]:
            text += "\n*Other Holdings*\n"
            for t in summary["other_tokens"][:5]:
                short_mint = t["mint"][:6] + "..." + t["mint"][-4:]
                text += f"  {short_mint}: ${t['usd_val']:.2f}\n"
        text += f"\n*Total: ${summary['total_usd']:.2f}*\n"
        buttons = [
            [InlineKeyboardButton("🔄 Refresh Balance", callback_data="solana:refresh")],
            [InlineKeyboardButton("📋 Trade Plans", callback_data="solana:plans"), InlineKeyboardButton("👁 Watchlist", callback_data="solana:watchlist")],
            [InlineKeyboardButton("💱 Get Quote", callback_data="solana:quote")],
            [InlineKeyboardButton("🏠 Home", callback_data="nav:home")],
        ]
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))


async def handle_solana_connect(query, context):
    context.user_data["solana_state"] = "await_connect"
    await query.message.reply_text(
        "🔑 Send your Solana wallet address\n"
        "(public key only — starts with a letter,\n"
        "32-44 characters)\n\n"
        "⚠️ Never send your private key or\n"
        "seed phrase to anyone or any bot."
    )


async def handle_get_quote(query, context):
    context.user_data["solana_state"] = "await_quote"
    await query.message.reply_text(
        "Enter token address or symbol and amount. Example:\n"
        "BonkMint123... 50\n"
        "(address then USD amount)"
    )


async def handle_solana_text(update, context):
    state = context.user_data.get("solana_state")
    if not update.message or not update.message.text:
        return False
    text = update.message.text.strip()

    if not state and _is_valid_solana_address(text):
        db.save_solana_wallet({"public_key": text, "label": "main"})
        summary = await get_wallet_summary(text)
        await update.message.reply_text(
            f"✅ Wallet connected\nSOL: {summary['sol_balance']:.4f}\nUSDC: ${summary['usdc_balance']:.2f}\nTotal: ${summary['total_usd']:.2f}"
        )
        return True
    if not state:
        return False

    if state == "await_connect":
        if not _is_valid_solana_address(text):
            await update.message.reply_text("❌ Invalid Solana public key format. Try again.")
            return True
        db.save_solana_wallet({"public_key": text, "label": "main"})
        summary = await get_wallet_summary(text)
        await update.message.reply_text(
            f"✅ Wallet connected\nSOL: {summary['sol_balance']:.4f}\nUSDC: ${summary['usdc_balance']:.2f}\nTotal: ${summary['total_usd']:.2f}"
        )
        context.user_data.pop("solana_state", None)
        return True

    if state == "await_quote":
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text("❌ Format: <token_address> <usd_amount>")
            return True
        token = parts[0]
        try:
            amount = float(parts[1])
        except Exception:
            await update.message.reply_text("❌ Invalid amount.")
            return True

        quote = await get_swap_quote(USDC_MINT, token, amount, 1.0, 100)
        context.user_data["solana_last_quote"] = {"token": token, "amount": amount, "quote": quote}
        await update.message.reply_text(
            format_quote(quote, token[:6], action="BUY"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("📲 Execute Manually", callback_data=f"solana:execute:{token}:{amount}")],
                    [InlineKeyboardButton("💾 Save to Watchlist", callback_data=f"solana:save_watch:{token}")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="solana:cancel")],
                ]
            ),
        )
        context.user_data.pop("solana_state", None)
        return True

    return False


async def handle_solana_cb(update, context):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data in {"solana:home", "solana:refresh"}:
        return await show_solana_home(q, context)
    if data == "solana:connect":
        return await handle_solana_connect(q, context)
    if data == "solana:quote":
        return await handle_get_quote(q, context)
    if data.startswith("solana:execute:"):
        _, _, token, amount = data.split(":", 3)
        plan = await generate_trade_plan(token, token[:6], "buy", float(amount), db.get_latest_auto_scan(token) or {})
        if plan.get("success"):
            db.save_solana_trade_plan(
                {
                    "token_address": token,
                    "token_symbol": token[:6],
                    "action": "buy",
                    "amount_usd": float(amount),
                    "entry_price": await get_token_price_usd(token),
                    "slippage_pct": plan.get("slippage_bps", 100) / 100,
                    "priority_fee": (plan.get("fees") or {}).get("medium", 5000),
                    "jupiter_quote": plan.get("quote", {}),
                    "dex_route": (plan.get("quote") or {}).get("route", ""),
                    "status": "pending",
                }
            )
        return await q.message.reply_text(format_trade_plan(plan), parse_mode="Markdown")
    if data.startswith("solana:save_watch:"):
        token = data.split(":", 2)[2]
        db.add_solana_watchlist({"token_address": token, "token_symbol": token[:6], "status": "watching"})
        return await q.message.reply_text("✅ Added to Solana watchlist.")
    if data == "solana:watchlist":
        rows = db.get_solana_watchlist()
        if not rows:
            return await q.message.reply_text("👁 Solana watchlist is empty.")
        lines = ["👁 *Solana Watchlist*", "━━━━━━━━━━━━━━━━━━━━━━━━"]
        for r in rows[:20]:
            lines.append(f"• {r.get('token_symbol') or r['token_address'][:8]} — {r['status']}")
        return await q.message.reply_text("\n".join(lines), parse_mode="Markdown")
    if data == "solana:plans":
        plans = db.get_solana_trade_plans()
        if not plans:
            return await q.message.reply_text("📋 No trade plans yet.")
        lines = ["📋 *Solana Trade Plans*", "━━━━━━━━━━━━━━━━━━━━━━━━"]
        for p in plans[:10]:
            lines.append(f"• {p.get('action','?').upper()} {p.get('token_symbol','?')} ${float(p.get('amount_usd') or 0):.2f} — {p.get('status')}")
        return await q.message.reply_text("\n".join(lines), parse_mode="Markdown")
