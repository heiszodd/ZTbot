async def route_callback(update, context) -> None:
    import logging

    log = logging.getLogger(__name__)
    query = update.callback_query
    if not query:
        return

    data = (query.data or "").strip().lower()
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
    data = aliases.get(data, data)

    from security.auth import is_authorised

    uid = query.from_user.id
    if not is_authorised(uid):
        await query.answer()
        return

    try:
        from security.rate_limiter import check_command_rate

        ok, reason = check_command_rate(uid)
        if not ok:
            await query.answer(reason, show_alert=True)
            return
    except Exception as e:
        log.error("rate limiter error: %s", e)

    await query.answer()

    async def _edit(text: str, kb=None):
        try:
            await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            try:
                await query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
            except Exception as e:
                log.error("edit/reply failed: %s", e)

    def _kb(rows):
        from telegram import InlineKeyboardMarkup

        return InlineKeyboardMarkup(rows)

    def _btn(label: str, cb: str):
        from telegram import InlineKeyboardButton

        return InlineKeyboardButton(label, callback_data=cb)

    if data == "home":
        try:
            from handlers.nav import show_home

            await show_home(update, context)
        except Exception as e:
            log.error("home: %s", e)
            await _edit(f"❌ Error loading home: {e}")

    elif data.startswith("perps") or data.startswith("hl:") or data.startswith("pending:"):
        try:
            from handlers import perps_handler as p

            if data == "perps":
                await p.show_perps_home(query, context)
            elif data == "perps:scanner":
                await p.show_perps_scanner(query, context)
            elif data == "perps:models":
                await p.show_perps_models(query, context)
            elif data == "perps:journal":
                await p.show_perps_journal(query, context)
            elif data in {"perps:live", "hl:refresh"}:
                await p.show_perps_live(query, context)
            elif data == "perps:demo":
                await p.show_perps_demo(query, context)
            elif data == "perps:risk":
                await p.show_perps_risk(query, context)
            elif data == "perps:pending":
                await p.show_perps_pending(query, context)
            elif data == "perps:others":
                await p.show_perps_others(query, context)
            elif data == "hl:positions":
                await p.show_hl_positions(query, context)
            elif data == "hl:orders":
                await p.show_hl_orders(query, context)
            elif data == "hl:performance":
                await p.show_hl_performance(query, context)
            elif data == "hl:history":
                await p.show_hl_history(query, context)
            elif data == "hl:funding":
                await p.show_hl_funding(query, context)
            elif data == "hl:markets":
                await p.show_hl_markets(query, context)
            elif data.startswith("hl:cancel:"):
                await p.handle_hl_cancel(query, context, data.split(":")[-1])
            elif data.startswith("hl:close:"):
                parts = data.split(":")
                await p.handle_hl_close(query, context, parts[2], float(parts[3]))
            elif data.startswith("hl:live:"):
                await p.handle_hl_live_trade(query, context, data.split(":")[-1])
            elif data.startswith("hl:demo:"):
                await p.handle_hl_demo_trade(query, context, data.split(":")[-1])
            elif data.startswith("pending:dismiss:"):
                import db

                db.dismiss_pending_signal(int(data.split(":")[-1]))
                await p.show_perps_pending(query, context)
            elif data.startswith("pending:plan:"):
                await p.show_pending_plan(query, context, int(data.split(":")[-1]))
            else:
                log.warning("Unhandled perps callback: %s", data)
                await _edit("Unknown Perps action.", _kb([[_btn("← Perps", "perps")]]))
        except Exception as e:
            log.error("perps/hl/pending route error: %s", e)
            await _edit(f"Error: {e}", _kb([[_btn("← Home", "home")]]))

    elif data.startswith("degen") or data.startswith("sol:"):
        try:
            from handlers import degen_handler as d

            if data == "degen":
                await d.show_degen_home(query, context)
            elif data == "degen:scanner":
                await d.show_degen_scanner(query, context)
            elif data == "degen:scan_contract":
                await d.show_scan_contract(query, context)
            elif data == "degen:models":
                await d.show_degen_models(query, context)
            elif data in {"degen:live", "degen:live:refresh"}:
                await d.show_degen_live(query, context)
            elif data == "degen:demo":
                await d.show_degen_demo(query, context)
            elif data == "degen:tracking":
                await d.show_wallet_tracking(query, context)
            elif data == "degen:watchlist":
                await d.show_degen_watchlist(query, context)
            elif data == "degen:others":
                await d.show_degen_others(query, context)
            elif data == "degen:live:buy":
                await d.show_buy_screen(query, context)
            elif data == "degen:live:sell":
                await d.show_sell_screen(query, context)
            elif data == "degen:live:risk":
                await d.show_live_risk(query, context)
            elif data == "degen:demo:risk":
                await d.show_demo_risk(query, context)
            elif data.startswith("degen:live:risk:"):
                await d.handle_live_risk_action(query, context, data.split(":", 3)[-1])
            elif data.startswith("degen:demo:risk:"):
                await d.handle_demo_risk_action(query, context, data.split(":", 3)[-1])
            elif data.startswith("degen:buy:"):
                parts = data.split(":")
                await d.handle_quick_buy(query, context, parts[2], float(parts[3]))
            elif data.startswith("degen:demo_buy:"):
                parts = data.split(":")
                await d.handle_demo_buy(query, context, parts[2], float(parts[3]))
            elif data.startswith("sol:autosell:"):
                await d.show_autosell_config(query, context, data.split(":", 2)[-1])
            elif data.startswith("sol:position:"):
                await d.show_position_detail(query, context, data.split(":", 2)[-1])
            else:
                log.warning("Unhandled degen callback: %s", data)
                await _edit("Unknown Degen action.", _kb([[_btn("← Degen", "degen")]]))
        except Exception as e:
            log.error("degen/sol route error: %s", e)
            await _edit(f"Error: {e}", _kb([[_btn("← Home", "home")]]))

    elif data.startswith("predictions") or data.startswith("poly:"):
        try:
            from handlers import predictions_handler as ph

            if data == "predictions":
                await ph.show_predictions_home(query, context)
            elif data == "predictions:scanner":
                await ph.show_predictions_scanner(query, context)
            elif data == "predictions:watchlist":
                await ph.show_predictions_watchlist(query, context)
            elif data in {"predictions:live", "predictions:live:refresh"}:
                await ph.show_predictions_live(query, context)
            elif data == "predictions:demo":
                await ph.show_predictions_demo(query, context)
            elif data == "predictions:models":
                await ph.show_predictions_models(query, context)
            elif data == "predictions:others":
                await ph.show_predictions_others(query, context)
            elif data == "predictions:live:positions":
                await ph.show_live_positions(query, context)
            elif data == "predictions:live:history":
                await ph.show_live_history(query, context)
            elif data.startswith("poly:trade:"):
                parts = data.split(":")
                await ph.handle_poly_live_trade(query, context, parts[2], parts[3], float(parts[4]))
            elif data.startswith("poly:demo:"):
                await ph.handle_poly_demo_trade(query, context, data.split(":", 2)[-1])
            elif data.startswith("poly:close:"):
                await ph.handle_poly_close(query, context, data.split(":", 2)[-1])
            else:
                log.warning("Unhandled predictions callback: %s", data)
                await _edit("Unknown Predictions action.", _kb([[_btn("← Predictions", "predictions")]]))
        except Exception as e:
            log.error("predictions/poly route error: %s", e)
            await _edit(f"Error: {e}", _kb([[_btn("← Home", "home")]]))

    elif data.startswith("settings"):
        try:
            if data == "settings":
                from handlers.settings_handler import show_settings

                await show_settings(query, context)
            elif data == "settings:wallets":
                from handlers.settings_handler import show_wallet_status

                await show_wallet_status(query, context)
            elif data == "settings:limits":
                from handlers.settings_handler import show_limits

                await show_limits(query, context)
            elif data == "settings:security":
                from handlers.nav import show_security_status

                await show_security_status(update, context)
            else:
                log.warning("Unhandled settings callback: %s", data)
                await _edit("Unknown Settings action.", _kb([[_btn("← Settings", "settings")]]))
        except Exception as e:
            log.error("settings route error: %s", e)
            await _edit(f"Error: {e}", _kb([[_btn("← Home", "home")]]))

    elif data == "help" or data.startswith("help:"):
        try:
            from handlers.nav import show_help, show_help_topic

            if data == "help":
                await show_help(update, context)
            else:
                await show_help_topic(query, context, data.split(":", 1)[-1])
        except Exception as e:
            log.error("help route error: %s", e)
            await _edit(f"Help error: {e}", _kb([[_btn("← Home", "home")]]))

    elif data.startswith("confirm:execute:"):
        try:
            from security.confirmation import execute_confirmation

            confirm_id = data.split(":")[3] if len(data.split(":")) > 3 else ""
            await query.message.edit_text("⏳ Executing...", reply_markup=None)
            success, result = await execute_confirmation(confirm_id)
            await query.message.edit_text(
                f"✅ *Executed*\n`{result.get('tx_id', '')}`"
                if success and isinstance(result, dict)
                else f"❌ *Failed*\n{result}",
                parse_mode="Markdown",
            )
        except Exception as e:
            await _edit(f"❌ Error: {e}")

    elif data.startswith("confirm:cancel:"):
        try:
            from security.confirmation import cancel_confirmation

            confirm_id = data.split(":")[3] if len(data.split(":")) > 3 else ""
            cancel_confirmation(confirm_id)
            await query.message.edit_text("❌ Trade cancelled.", reply_markup=None)
        except Exception as e:
            await _edit(f"❌ Cancel error: {e}")

    else:
        log.warning("Unhandled callback from user %s: '%s'", uid, data)


async def route_text_message(update, context) -> None:
    import re

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
