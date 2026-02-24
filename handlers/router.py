import logging

from telegram import Update
from telegram.ext import ContextTypes

from security.auth import require_auth_callback
from security.rate_limiter import check_command_rate

log = logging.getLogger(__name__)


@require_auth_callback
async def master_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    raw_data = query.data or ""
    data = raw_data

    legacy_aliases = {
        "nav:perps_home": "perps:home",
        "nav:degen_home": "degen:home",
        "nav:degen_models": "degen:models",
        "nav:polymarket_home": "predictions:home",
        "nav:solana_home": "degen:live",
        "nav:scan": "perps:scanner",
        "nav:models": "perps:models",
        "nav:journal": "perps:journal",
        "nav:pending": "perps:pending",
        "nav:risk": "perps:risk",
        "nav:notif_filter": "settings:notifications",
        "nav:status": "settings:home",
        "nav:guide": "help:home",
    }

    legacy_aliases = {
        "nav:perps_home": "perps:home",
        "nav:degen_home": "degen:home",
        "nav:degen_models": "degen:models",
        "nav:polymarket_home": "predictions:home",
        "nav:solana_home": "degen:live",
        "nav:scan": "perps:scanner",
        "nav:models": "perps:models",
        "nav:journal": "perps:journal",
        "nav:pending": "perps:pending",
        "nav:risk": "perps:risk",
        "nav:notif_filter": "settings:notifications",
        "nav:status": "settings:home",
        "nav:guide": "help:home",
    }
    data = legacy_aliases.get(data, data)

    uid = query.from_user.id
    allowed, reason = check_command_rate(uid)
    if not allowed:
        await query.answer(reason, show_alert=True)
        return

    await query.answer()

    if raw_data.startswith("nav:") and raw_data != "nav:home":
        from handlers.commands import handle_nav
        await handle_nav(update, context)
        return

    data = legacy_aliases.get(data, data)

    if data == "nav:home":
    if data.startswith("nav:") and data != "nav:home" and data not in legacy_aliases:
        from handlers.commands import handle_nav
        await handle_nav(update, context)
    elif data == "nav:home":
        from handlers.commands import show_home
        await show_home(update, context)
    elif data == "perps:home":
        from handlers.nav_handler import show_perps_home
        await show_perps_home(query, context)
    elif data == "perps:scanner":
        from handlers.nav_handler import show_perps_scanner
        await show_perps_scanner(query, context)
    elif data == "perps:models":
        from handlers.nav_handler import show_perps_models
        await show_perps_models(query, context)
    elif data == "perps:journal":
        from handlers.journal_handler import show_journal_home
        await show_journal_home(query, context)
    elif data == "perps:live":
        from handlers.hyperliquid_handler import show_perps_live_home
        await show_perps_live_home(query, context)
    elif data == "perps:demo":
        from handlers.nav_handler import show_perps_demo
        await show_perps_demo(query, context)
    elif data == "perps:risk":
        from handlers.risk_handler import show_risk_settings
        await show_risk_settings(query, context)
    elif data == "perps:pending":
        from handlers.nav_handler import show_perps_pending
        await show_perps_pending(query, context)
    elif data == "perps:others":
        from handlers.nav_handler import show_perps_others
        await show_perps_others(query, context)
    elif data == "degen:home":
        from handlers.nav_handler import show_degen_home
        await show_degen_home(query, context)
    elif data == "degen:scanner":
        from handlers.degen_handler import show_degen_scanner
        await show_degen_scanner(query, context)
    elif data == "degen:scan_contract":
        from handlers.degen_handler import show_scan_contract
        await show_scan_contract(query, context)
    elif data == "degen:models":
        from handlers.degen_model_handler import show_degen_models_home
        await show_degen_models_home(query, context)
    elif data == "degen:live":
        from handlers.solana_handler import show_degen_live_home
        await show_degen_live_home(query, context)
    elif data == "degen:demo":
        from handlers.degen_handler import show_degen_demo_home
        await show_degen_demo_home(query, context)
    elif data == "degen:wallet_tracking":
        from handlers.degen_handler import show_wallet_tracking
        await show_wallet_tracking(query, context)
    elif data == "degen:watchlist":
        from handlers.degen_handler import show_degen_watchlist
        await show_degen_watchlist(query, context)
    elif data == "degen:others":
        from handlers.nav_handler import show_degen_others
        await show_degen_others(query, context)
    elif data == "predictions:home":
        from handlers.nav_handler import show_predictions_home
        await show_predictions_home(query, context)
    elif data == "predictions:scanner":
        from handlers.polymarket_handler import show_poly_scanner
        await show_poly_scanner(query, context)
    elif data == "predictions:watchlist":
        from handlers.polymarket_handler import show_poly_watchlist
        await show_poly_watchlist(query, context)
    elif data == "predictions:live":
        from handlers.polymarket_handler import show_predictions_live_home
        await show_predictions_live_home(query, context)
    elif data == "predictions:demo":
        from handlers.polymarket_handler import show_poly_demo_home
        await show_poly_demo_home(query, context)
    elif data == "predictions:models":
        from handlers.predictions_model_handler import show_predictions_models_home
        await show_predictions_models_home(query, context)
    elif data == "predictions:others":
        from handlers.nav_handler import show_predictions_others
        await show_predictions_others(query, context)
    elif data == "settings:home":
        from handlers.nav_handler import show_settings_home
        await show_settings_home(query, context)
    elif data == "settings:notifications":
        from handlers.risk_handler import show_notification_filter
        await show_notification_filter(query)
    elif data == "settings:wallets":
        from handlers.nav_handler import show_wallet_settings
        await show_wallet_settings(query, context)
    elif data == "settings:security":
        from handlers.commands import handle_security
        await handle_security(update, context)
    elif data == "help:home":
        from handlers.nav_handler import show_help_home
        await show_help_home(query, context)
    elif data.startswith("help:"):
        from handlers.nav_handler import show_help_topic
        await show_help_topic(query, context, data.split(":", 1)[1])
    elif data.startswith("confirm:"):
        from handlers.commands import handle_confirmation_callback
        await handle_confirmation_callback(update, context)
    elif data.startswith("wizard:"):
        from handlers.wizard import handle_wizard_cb
        await handle_wizard_cb(update, context)
    elif data.startswith("chart:"):
        from handlers.chart_handler import handle_chart_cb
        await handle_chart_cb(update, context)
    elif data.startswith("hl:"):
        from handlers.hyperliquid_handler import handle_hl_cb
        await handle_hl_cb(update, context)
    elif data.startswith("sol:") or data.startswith("solana:"):
        from handlers.solana_handler import handle_solana_cb
        await handle_solana_cb(update, context)
    elif data.startswith("poly:"):
        from handlers.polymarket_handler import handle_polymarket_cb
        await handle_polymarket_cb(update, context)
    elif data.startswith("degen:") or data.startswith("scanner:"):
        from handlers.degen_handler import handle_degen_cb, handle_scanner_settings_action
        if data.startswith("scanner:"):
            await handle_scanner_settings_action(update, context)
        else:
            await handle_degen_cb(update, context)
    elif data.startswith("risk:"):
        from handlers.risk_handler import handle_risk_cb
        await handle_risk_cb(update, context)
    elif data.startswith("filter:"):
        from handlers.risk_handler import handle_risk_cb
        await handle_risk_cb(update, context)
    elif data.startswith("pending:"):
        from handlers.alerts import handle_pending_cb
        await handle_pending_cb(update, context)
    else:
        log.warning("Unhandled callback: %s", data)
        await query.answer("This button is not yet active.", show_alert=False)
