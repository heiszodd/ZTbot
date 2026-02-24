import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

from security.auth import require_auth_callback

log = logging.getLogger(__name__)


def _normalize_callback_data(raw: str) -> str:
    data = (raw or "").strip().lower()
    if not data:
        return ""

    aliases = {
        "start": "home",
        "main": "home",
        "menu": "home",
        "dashboard": "home",
        "home:perps": "perps",
        "home:degen": "degen",
        "home:predictions": "predictions",
        "home:settings": "settings",
        "menu:perps": "perps",
        "menu:degen": "degen",
        "menu:predictions": "predictions",
        "menu:settings": "settings",
        "nav:perps": "perps",
        "nav:degen": "degen",
        "nav:predictions": "predictions",
        "nav:settings": "settings",
    }
    return aliases.get(data, data)


@require_auth_callback
async def route_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = _normalize_callback_data(query.data)

    from security.rate_limiter import check_command_rate

    ok, reason = check_command_rate(query.from_user.id)
    if not ok:
        await query.answer(reason, show_alert=True)
        return
    await query.answer()

    if data == "home":
        from handlers.nav import show_home
        return await show_home(update, context)

    if data.startswith("perps") or data.startswith("hl:") or data.startswith("pending:"):
        from handlers import perps_handler as p
        if data == "perps": return await p.show_perps_home(query, context)
        if data == "perps:scanner": return await p.show_perps_scanner(query, context)
        if data == "perps:models": return await p.show_perps_models(query, context)
        if data == "perps:journal": return await p.show_perps_journal(query, context)
        if data == "perps:live" or data == "hl:refresh": return await p.show_perps_live(query, context)
        if data == "perps:demo": return await p.show_perps_demo(query, context)
        if data == "perps:risk": return await p.show_perps_risk(query, context)
        if data == "perps:pending": return await p.show_perps_pending(query, context)
        if data == "perps:others": return await p.show_perps_others(query, context)
        if data == "hl:positions": return await p.show_hl_positions(query, context)
        if data == "hl:orders": return await p.show_hl_orders(query, context)
        if data == "hl:performance": return await p.show_hl_performance(query, context)
        if data == "hl:history": return await p.show_hl_history(query, context)
        if data == "hl:funding": return await p.show_hl_funding(query, context)
        if data == "hl:markets": return await p.show_hl_markets(query, context)
        if data.startswith("hl:cancel:"): return await p.handle_hl_cancel(query, context, data.split(":")[-1])
        if data.startswith("hl:close:"):
            parts = data.split(":")
            return await p.handle_hl_close(query, context, parts[2], float(parts[3]))
        if data.startswith("hl:live:"): return await p.handle_hl_live_trade(query, context, data.split(":")[-1])
        if data.startswith("hl:demo:"): return await p.handle_hl_demo_trade(query, context, data.split(":")[-1])
        if data.startswith("pending:dismiss:"):
            import db
            db.dismiss_pending_signal(int(data.split(":")[-1]))
            return await p.show_perps_pending(query, context)
        if data.startswith("pending:plan:"): return await p.show_pending_plan(query, context, int(data.split(":")[-1]))

    if data.startswith("degen") or data.startswith("sol:"):
        from handlers import degen_handler as d
        if data == "degen": return await d.show_degen_home(query, context)
        if data == "degen:scanner": return await d.show_degen_scanner(query, context)
        if data == "degen:scan_contract": return await d.show_scan_contract(query, context)
        if data == "degen:models": return await d.show_degen_models(query, context)
        if data in {"degen:live", "degen:live:refresh"}: return await d.show_degen_live(query, context)
        if data == "degen:demo": return await d.show_degen_demo(query, context)
        if data == "degen:tracking": return await d.show_wallet_tracking(query, context)
        if data == "degen:watchlist": return await d.show_degen_watchlist(query, context)
        if data == "degen:others": return await d.show_degen_others(query, context)
        if data == "degen:live:buy": return await d.show_buy_screen(query, context)
        if data == "degen:live:sell": return await d.show_sell_screen(query, context)
        if data == "degen:live:risk": return await d.show_live_risk(query, context)
        if data == "degen:demo:risk": return await d.show_demo_risk(query, context)
        if data.startswith("degen:live:risk:"): return await d.handle_live_risk_action(query, context, data.split(":", 3)[-1])
        if data.startswith("degen:demo:risk:"): return await d.handle_demo_risk_action(query, context, data.split(":", 3)[-1])
        if data.startswith("degen:buy:"):
            parts = data.split(":")
            return await d.handle_quick_buy(query, context, parts[2], float(parts[3]))
        if data.startswith("degen:demo_buy:"):
            parts = data.split(":")
            return await d.handle_demo_buy(query, context, parts[2], float(parts[3]))
        if data.startswith("sol:autosell:"): return await d.show_autosell_config(query, context, data.split(":", 2)[-1])
        if data.startswith("sol:position:"): return await d.show_position_detail(query, context, data.split(":", 2)[-1])

    if data.startswith("predictions") or data.startswith("poly:"):
        from handlers import predictions_handler as ph
        if data == "predictions": return await ph.show_predictions_home(query, context)
        if data == "predictions:scanner": return await ph.show_predictions_scanner(query, context)
        if data == "predictions:watchlist": return await ph.show_predictions_watchlist(query, context)
        if data in {"predictions:live", "predictions:live:refresh"}: return await ph.show_predictions_live(query, context)
        if data == "predictions:demo": return await ph.show_predictions_demo(query, context)
        if data == "predictions:models": return await ph.show_predictions_models(query, context)
        if data == "predictions:others": return await ph.show_predictions_others(query, context)
        if data == "predictions:live:positions": return await ph.show_live_positions(query, context)
        if data == "predictions:live:history": return await ph.show_live_history(query, context)
        if data.startswith("poly:trade:"):
            parts = data.split(":")
            return await ph.handle_poly_live_trade(query, context, parts[2], parts[3], float(parts[4]))
        if data.startswith("poly:demo:"): return await ph.handle_poly_demo_trade(query, context, data.split(":", 2)[-1])
        if data.startswith("poly:close:"): return await ph.handle_poly_close(query, context, data.split(":", 2)[-1])

    if data.startswith("settings"):
        from handlers.settings_handler import show_limits, show_settings, show_wallet_status
        if data == "settings": return await show_settings(query, context)
        if data == "settings:wallets": return await show_wallet_status(query, context)
        if data == "settings:limits": return await show_limits(query, context)
        if data == "settings:security":
            from handlers.nav import show_security_status
            return await show_security_status(update, context)

    if data == "help" or data.startswith("help:"):
        from handlers.nav import show_help, show_help_topic
        if data == "help": return await show_help(update, context)
        return await show_help_topic(query, context, data.split(":", 1)[-1])

    if data.startswith("confirm:execute:"):
        from security.confirmation import execute_confirmation
        confirm_id = data.split(":")[3] if len(data.split(":")) > 3 else ""
        await query.message.edit_text("⏳ Executing...", reply_markup=None)
        success, result = await execute_confirmation(confirm_id)
        return await query.message.edit_text(f"✅ *Executed*\n`{result.get('tx_id','')}`" if success and isinstance(result, dict) else f"❌ *Failed*\n{result}", parse_mode="Markdown")

    if data.startswith("confirm:cancel:"):
        from security.confirmation import cancel_confirmation
        confirm_id = data.split(":")[3] if len(data.split(":")) > 3 else ""
        cancel_confirmation(confirm_id)
        return await query.message.edit_text("❌ Trade cancelled.", reply_markup=None)

    log.warning("Unhandled callback: %s", data)
    from handlers.nav import show_home

    await show_home(update, context)


async def route_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from security.auth import is_authorised
    if not is_authorised(update.effective_user.id):
        return

    text = (update.message.text or "").strip()
    sol_pattern = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
    link_pattern = re.compile(r"(?:dexscreener\.com/solana/|birdeye\.so/token/|pump\.fun/)([1-9A-HJ-NP-Za-km-z]{32,44})")

    address = text if sol_pattern.match(text) else None
    if not address:
        m = link_pattern.search(text)
        if m:
            address = m.group(1)

    if address:
        from handlers.degen_handler import handle_ca_input
        await handle_ca_input(update, context, address)
