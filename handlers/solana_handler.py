import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from security.auth import require_auth, require_auth_callback
from security.rate_limiter import check_command_rate
import db
from engine.solana.wallet_reader import get_wallet_summary, get_token_price_usd
from engine.solana.jupiter_quotes import get_swap_quote, format_quote, USDC_MINT
from engine.solana.trade_planner import generate_trade_plan, format_trade_plan
from engine.solana.executor import execute_jupiter_swap, execute_sol_sell
from engine.execution_pipeline import run_execution_pipeline
from utils.formatting import format_price, format_usd


def _is_valid_solana_address(value: str) -> bool:
    if not value or value.startswith("0x") or not (32 <= len(value) <= 44):
        return False
    return bool(re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", value))


async def show_solana_home(query, context):
    wallet = db.get_solana_wallet()
    settings = db.get_user_settings(query.message.chat_id)
    mode = settings.get("sol_mode", "simple")
    mode_label = "⚡ Simple Mode" if mode == "simple" else "🔬 Advanced Mode"
    if not wallet:
        text = (
            "🔑 *Solana Wallet*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "No wallet connected yet.\n\n"
            "To get started, provide your\n"
            "Solana *public key* (wallet address).\n\n"
            "⚡ *Phase 2 Live Execution Ready*\n"
            "Connect wallet to enable live Jupiter swaps."
        )
        buttons = [[InlineKeyboardButton(mode_label, callback_data="solana:toggle_mode")],[InlineKeyboardButton("🔑 Connect Wallet", callback_data="solana:connect")], [InlineKeyboardButton("🏠 Home", callback_data="nav:home")]]
    else:
        summary = await get_wallet_summary(wallet["public_key"])
        short_key = wallet["public_key"][:6] + "..." + wallet["public_key"][-4:]
        text = (
            f"🔑 *Solana Wallet*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Address: `{short_key}`\n\n"
            f"💰 *Balances*\n"
            f"SOL:   {summary['sol_balance']:.4f} SOL ({format_usd(summary['sol_usd'])})\n"
            f"USDC:  {format_usd(summary['usdc_balance'])}\n"
        )
        if summary["other_tokens"]:
            text += "\n*Other Holdings*\n"
            for t in summary["other_tokens"][:5]:
                short_mint = t["mint"][:6] + "..." + t["mint"][-4:]
                text += f"  {short_mint}: ${t['usd_val']:.2f}\n"
        text += (
            f"\n*Total: {format_usd(summary['total_usd'])}*\n\n"
            "⚡ *Phase 2 Live Trading Enabled*\n"
            "Use Quick Buy, Quote, or CA-detected buy actions to execute live swaps."
        )
        buttons = [[InlineKeyboardButton(mode_label, callback_data="solana:toggle_mode")],
            [InlineKeyboardButton("🔄 Refresh Balance", callback_data="solana:refresh")],
            [InlineKeyboardButton("🟢 Quick Buy $25", callback_data="sol:quick_buy:25"), InlineKeyboardButton("🟢 Quick Buy $50", callback_data="sol:quick_buy:50")],
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


async def _setup_default_auto_sell(token_address: str, token_symbol: str, entry_price: float, settings: dict):
    db.upsert_auto_sell_config(
        {
            "token_address": token_address,
            "token_symbol": token_symbol,
            "entry_price": entry_price,
            "stop_loss_pct": settings.get("sol_stop_loss_pct", -20),
            "tp1_pct": settings.get("sol_tp1_pct", 50),
            "tp2_pct": settings.get("sol_tp2_pct", 100),
            "tp3_pct": settings.get("sol_tp3_pct", 200),
            "tp1_sell_pct": 25,
            "tp2_sell_pct": 25,
            "tp3_sell_pct": 50,
            "active": True,
        }
    )


async def handle_sol_execute_buy(query, context, token_address, token_symbol, amount_usd, auto_sell=True):
    quote = await get_swap_quote(input_mint=USDC_MINT, output_mint=token_address, amount_usd=amount_usd, input_price=1.0)
    if "error" in quote:
        await query.answer(f"Quote failed: {quote['error']}", show_alert=True)
        return

    settings = db.get_user_settings(query.message.chat_id)
    threshold = settings.get("instant_buy_threshold", 50)
    instant = settings.get("instant_buy_enabled", True)
    plan = {
        "coin": token_symbol,
        "symbol": token_symbol,
        "side": "Buy",
        "token_address": token_address,
        "input_mint": USDC_MINT,
        "output_mint": token_address,
        "size_usd": amount_usd,
        "entry_price": quote["effective_price"],
        "stop_loss": 0,
        "slippage_bps": quote["slippage_bps"],
        "tokens_out": quote["tokens_out"],
        "raw_quote": quote["raw_quote"],
    }
    result = await run_execution_pipeline("solana", plan, execute_jupiter_swap, query.from_user.id, context, skip_confirm=(instant and amount_usd <= threshold))
    if result.get("pending"):
        await query.message.reply_text(result["message"], parse_mode="Markdown", reply_markup=result["keyboard"])
        return
    if not result.get("success"):
        await query.message.reply_text(f"❌ Buy failed\n{result.get('error','Unknown error')}")
        return
    db.save_sol_position({"token_address": token_address, "token_symbol": token_symbol, "entry_price": plan["entry_price"], "tokens_held": plan["tokens_out"], "cost_basis": amount_usd, "wallet_index": settings.get("active_wallet", 1)})
    if auto_sell:
        await _setup_default_auto_sell(token_address, token_symbol, plan["entry_price"], settings)
    await query.message.reply_text(f"✅ *Bought {token_symbol}*\n[View on Solscan](https://solscan.io/tx/{result['tx_id']})", parse_mode="Markdown")


async def handle_sol_execute_sell(query, context, token_address, token_symbol, sell_pct=100):
    pos = db.get_sol_position(token_address)
    if not pos:
        await query.answer("Position not found", show_alert=True)
        return
    token_price = await get_token_price_usd(token_address)
    tokens_to_sell = float(pos.get("tokens_held") or 0) * sell_pct / 100
    amount_usd = tokens_to_sell * token_price
    quote = await get_swap_quote(input_mint=token_address, output_mint=USDC_MINT, amount_usd=amount_usd, input_price=token_price)
    if "error" in quote:
        await query.answer(f"Quote failed: {quote['error']}", show_alert=True)
        return
    plan = {
        "coin": token_symbol,
        "symbol": token_symbol,
        "side": "Sell",
        "token_address": token_address,
        "input_mint": token_address,
        "output_mint": USDC_MINT,
        "size_usd": amount_usd,
        "entry_price": token_price,
        "stop_loss": 0,
        "sell_pct": sell_pct,
        "tokens_out": quote["tokens_out"],
        "slippage_bps": quote["slippage_bps"],
        "raw_quote": quote["raw_quote"],
    }
    result = await run_execution_pipeline("solana", plan, execute_sol_sell, query.from_user.id, context)
    if result.get("pending"):
        await query.message.reply_text(result["message"], parse_mode="Markdown", reply_markup=result["keyboard"])
        return
    if not result.get("success"):
        await query.message.reply_text(f"❌ Sell failed\n{result.get('error','?')}")
        return
    db.update_sol_position_after_sell(token_address, sell_pct, quote["tokens_out"], token_price)
    await query.message.reply_text(f"✅ *Sold {sell_pct}% {token_symbol}*\n[View on Solscan](https://solscan.io/tx/{result['tx_id']})", parse_mode="Markdown")


@require_auth
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
                    [InlineKeyboardButton("📲 Execute Live Buy", callback_data=f"sol:execute:{token}:{amount}")],
                    [InlineKeyboardButton("💾 Save to Watchlist", callback_data=f"solana:save_watch:{token}")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="solana:cancel")],
                ]
            ),
        )
        context.user_data.pop("solana_state", None)
        return True

    return False


@require_auth_callback
async def handle_solana_cb(update, context):
    q = update.callback_query
    uid = q.from_user.id if q and q.from_user else 0
    allowed, reason = check_command_rate(uid)
    if not allowed:
        await q.answer(reason, show_alert=True)
        return
    await q.answer()
    data = q.data
    if data.startswith("sol:"):
        data = "solana:" + data[len("sol:"):]
    if data == "solana:toggle_mode":
        st = db.get_user_settings(q.message.chat_id)
        db.update_user_settings(q.message.chat_id, {"sol_mode": "advanced" if st.get("sol_mode") == "simple" else "simple"})
        return await show_solana_home(q, context)
    if data in {"solana:home", "solana:refresh"}:
        return await show_solana_home(q, context)
    if data == "solana:connect":
        return await handle_solana_connect(q, context)
    if data == "solana:quote":
        return await handle_get_quote(q, context)
    if data.startswith("solana:execute:"):
        _, _, token, amount = data.split(":", 3)
        return await handle_sol_execute_buy(q, context, token, token[:6], float(amount), auto_sell=True)
    if data.startswith("solana:sell:"):
        _, _, token, pct = data.split(":", 3)
        return await handle_sol_execute_sell(q, context, token, token[:6], float(pct))
    if data.startswith("solana:quick_buy:"):
        _, _, amount = data.split(":", 2)
        await q.message.reply_text(
            "Paste token address to execute quick buy amount:\n"
            f"${float(amount):.0f}\n\n"
            "Then tap quote -> execute live."
        )
        return
    if data == "solana:cancel":
        context.user_data.pop("solana_state", None)
        await q.message.reply_text("❌ Cancelled.")
        return
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

# New-nav compatibility exports
show_degen_live_home = show_solana_home


async def show_degen_buy_screen(query, context):
    await query.message.reply_text("Paste token address to buy.")


async def show_degen_sell_screen(query, context):
    await query.message.reply_text("Open positions shown below.")


async def show_quick_buy_screen(query, context, address: str):
    await query.message.reply_text(
        f"Quick buy {address}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("$50", callback_data=f"degen:live:{address}")]]),
    )


async def show_autosell_config(query, context, address: str):
    await query.message.reply_text(f"Auto-sell config for {address}")


async def show_sol_position_detail(query, context, address: str):
    await query.message.reply_text(f"Position detail for {address}")


async def handle_sol_wallet_setup(query, context):
    await handle_solana_connect(query, context)
