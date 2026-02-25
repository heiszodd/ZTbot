import logging


async def route_callback(update, context) -> None:
    query = update.callback_query
    if not query:
        return

    data = query.data or ""

    try:
        await query.answer()
    except Exception:
        pass

    try:
        from security.auth import is_authorised
        if not is_authorised(query.from_user.id):
            return
    except Exception:
        pass

    try:
        await _route(query, data, update, context)
    except Exception as e:
        logging.getLogger(__name__).error("Router crash on '%s': %s", data, e, exc_info=True)
        try:
            from telegram import InlineKeyboardMarkup, InlineKeyboardButton
            await query.message.edit_text(
                f"❌ *Error*\n\n`{str(e)[:300]}`\n\nTap Home to continue.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="home")]]),
            )
        except Exception:
            pass


async def _route(query, data, update, context):
    log = logging.getLogger(__name__)

    data = (data or "").strip().lower()
    aliases = {
        "start": "home", "main": "home", "menu": "home", "dashboard": "home",
        "home:perps": "perps", "home:degen": "degen", "home:predictions": "predictions", "home:settings": "settings",
        "menu:perps": "perps", "menu:degen": "degen", "menu:predictions": "predictions", "menu:settings": "settings",
        "nav:perps": "perps", "nav:degen": "degen", "nav:predictions": "predictions", "nav:settings": "settings",
    }
    data = aliases.get(data, data)
    uid = query.from_user.id

    try:
        from security.rate_limiter import check_command_rate
        ok, reason = check_command_rate(query.from_user.id)
        if not ok:
            await query.answer(reason, show_alert=True)
            return
    except Exception as e:
        log.error("rate limiter error: %s", e)

    from telegram import InlineKeyboardMarkup as IKM, InlineKeyboardButton as IKB

    def _kb(rows):
        return IKM(rows)

    def _btn(label: str, cb: str):
        return IKB(label, callback_data=cb)

    async def _edit(text: str, kb=None):
        try:
            await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            try:
                await query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
            except Exception as e:
                log.error("edit/reply failed: %s", e)

    if data == "home":
        try:
            from handlers.nav import show_home
            await show_home(update, context)
        except Exception as e:
            await _edit(f"❌ Error loading home: {e}", _kb([[_btn("← Home", "home")]]))

    elif data.startswith("perps") or data.startswith("hl:") or data.startswith("pending:"):
        from handlers import perps_handler as p
        try:
            if data == "perps":
                await p.show_perps_home(query, context)
            elif data == "perps:scanner":
                await p.show_perps_scanner(query, context)
            elif data == "perps:scanner:run":
                await p.handle_perps_scanner_run(query, context)
            elif data == "perps:models":
                await p.show_perps_models(query, context)
            elif data == "perps:models:create":
                await _edit("Model creation flow coming soon.", _kb([[_btn("← Models", "perps:models")]]))
            elif data.startswith("perps:models:view:"):
                await p.show_perps_model_detail(query, context, data.split(":", 3)[-1])
            elif data.startswith("perps:models:on:"):
                await p.handle_perps_model_toggle(query, context, data.split(":", 3)[-1], True)
            elif data.startswith("perps:models:off:"):
                await p.handle_perps_model_toggle(query, context, data.split(":", 3)[-1], False)
            elif data == "perps:models:all:on":
                await p.handle_perps_models_all(query, context, True)
            elif data == "perps:models:all:off":
                await p.handle_perps_models_all(query, context, False)
            elif data.startswith("perps:models:delete:"):
                await p.handle_perps_model_delete(query, context, data.split(":", 3)[-1])
            elif data == "perps:models:master":
                await p.show_perps_master_model(query, context)
            elif data == "perps:models:master:seed":
                await p.handle_perps_master_model_seed(query, context)
            elif data == "perps:models:master:activate":
                await p.handle_perps_master_model_activate(query, context)
            elif data == "perps:journal":
                await p.show_perps_journal(query, context)
            elif data in {"perps:live", "hl:refresh"}:
                await p.show_perps_live(query, context)
            elif data == "perps:demo":
                await p.show_perps_demo(query, context)
            elif data.startswith("perps:demo:deposit:"):
                await p.handle_perps_demo_deposit(query, context, float(data.split(":")[-1]))
            elif data == "perps:demo:reset:confirm":
                await p.handle_perps_demo_reset_confirm(query, context)
            elif data == "perps:demo:reset:execute":
                await p.handle_perps_demo_reset(query, context)
            elif data == "perps:demo:positions":
                await p.show_perps_demo_positions(query, context)
            elif data == "perps:demo:history":
                await p.show_perps_demo_history(query, context)
            elif data.startswith("perps:demo:close:"):
                await p.handle_perps_demo_close(query, context, int(data.split(":")[-1]))
            elif data == "perps:risk":
                await p.show_perps_risk(query, context)
            elif data.startswith("perps:risk:edit:"):
                await p.show_perps_risk_edit(query, context, data.split(":", 3)[-1])
            elif data.startswith("perps:risk:set:"):
                parts = data.split(":")
                await p.handle_perps_risk_set(query, context, parts[3], parts[4])
            elif data == "perps:risk:reset":
                await p.handle_perps_risk_reset(query, context)
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
                await _edit("Unknown Perps action.", _kb([[_btn("← Perps", "perps")]]))
        except Exception as e:
            await _edit(f"Error: {e}", _kb([[_btn("← Home", "home")]]))

    elif data.startswith("degen") or data.startswith("sol:"):
        from handlers import degen_handler as d
        try:
            if data == "degen":
                await d.show_degen_home(query, context)
            elif data == "degen:scanner":
                await d.show_degen_scanner(query, context)
            elif data == "degen:trenches":
                await _edit("Trenches feed is available in scanner jobs.", _kb([[_btn("← Scanner", "degen:scanner")]]))
            elif data == "degen:scanner:run":
                await d.handle_degen_scanner_run(query, context)
            elif data == "degen:scan_contract":
                await d.show_scan_contract(query, context)
            elif data == "degen:models":
                await d.show_degen_models(query, context)
            elif data == "degen:models:create":
                await _edit("Custom model creation flow coming soon.", _kb([[_btn("← Models", "degen:models")]]))
            elif data.startswith("degen:models:edit:"):
                await _edit("Model edit flow coming soon.", _kb([[_btn("← Models", "degen:models")]]))
            elif data.startswith("degen:models:view:"):
                await d.show_degen_model_detail(query, context, int(data.split(":")[-1]))
            elif data.startswith("degen:models:on:"):
                await d.handle_degen_model_toggle(query, context, int(data.split(":")[-1]), True)
            elif data.startswith("degen:models:off:"):
                await d.handle_degen_model_toggle(query, context, int(data.split(":")[-1]), False)
            elif data == "degen:models:all:on":
                await d.handle_degen_models_all(query, context, True)
            elif data == "degen:models:all:off":
                await d.handle_degen_models_all(query, context, False)
            elif data == "degen:models:presets":
                await d.show_degen_model_presets(query, context)
            elif data.startswith("degen:models:preset:"):
                await d.handle_degen_model_preset(query, context, data.split(":")[-1])
            elif data.startswith("degen:models:delete:"):
                await d.handle_degen_model_delete(query, context, int(data.split(":")[-1]))
            elif data in {"degen:live", "degen:live:refresh"}:
                await d.show_degen_live(query, context)
            elif data == "degen:demo":
                await d.show_degen_demo(query, context)
            elif data.startswith("degen:demo:deposit:"):
                await d.handle_degen_demo_deposit(query, context, float(data.split(":")[-1]))
            elif data == "degen:demo:reset:confirm":
                await d.handle_degen_demo_reset_confirm(query, context)
            elif data == "degen:demo:reset:execute":
                await d.handle_degen_demo_reset(query, context)
            elif data == "degen:demo:positions":
                await d.show_degen_demo_positions(query, context)
            elif data == "degen:demo:history":
                await d.show_degen_demo_history(query, context)
            elif data.startswith("degen:demo:close:"):
                await d.handle_degen_demo_close(query, context, int(data.split(":")[-1]))
            elif data == "degen:tracking":
                await d.show_wallet_tracking(query, context)
            elif data == "degen:tracking:add":
                await d.show_tracking_add(query, context)
            elif data == "degen:tracking:history":
                await _edit("Copy history coming soon.", _kb([[_btn("← Tracking", "degen:tracking")]]))
            elif data.startswith("degen:tracking:view:"):
                await _edit("Wallet detail view coming soon.", _kb([[_btn("← Tracking", "degen:tracking")]]))
            elif data.startswith("degen:tracking:remove:"):
                import db
                try:
                    db.delete_tracked_wallet(int(data.split(":")[-1]))
                    await query.answer("Wallet removed", show_alert=False)
                except Exception as e:
                    await query.answer(str(e), show_alert=True)
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
            elif data.startswith("degen:watchlist:add:"):
                await query.answer("Added to watchlist", show_alert=False)
            elif data.startswith("degen:blacklist:add:"):
                await query.answer("Added to blacklist", show_alert=False)
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
                await _edit("Unknown Degen action.", _kb([[_btn("← Degen", "degen")]]))
        except Exception as e:
            await _edit(f"Error: {e}", _kb([[_btn("← Home", "home")]]))

    elif data.startswith("predictions") or data.startswith("poly:"):
        from handlers import predictions_handler as ph
        try:
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
            elif data == "predictions:models:create":
                await _edit("Custom prediction model creation coming soon.", _kb([[_btn("← Models", "predictions:models")]]))
            elif data.startswith("predictions:models:view:"):
                await ph.show_prediction_model_detail(query, context, int(data.split(":")[-1]))
            elif data.startswith("predictions:models:on:"):
                await ph.handle_prediction_model_toggle(query, context, int(data.split(":")[-1]), True)
            elif data.startswith("predictions:models:off:"):
                await ph.handle_prediction_model_toggle(query, context, int(data.split(":")[-1]), False)
            elif data == "predictions:models:all:on":
                await ph.handle_prediction_models_all(query, context, True)
            elif data == "predictions:models:all:off":
                await ph.handle_prediction_models_all(query, context, False)
            elif data == "predictions:models:presets":
                await ph.show_prediction_model_presets(query, context)
            elif data.startswith("predictions:models:preset:"):
                await ph.handle_prediction_model_preset(query, context, data.split(":")[-1])
            elif data.startswith("predictions:models:delete:"):
                await ph.handle_prediction_model_delete(query, context, int(data.split(":")[-1]))
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
                await _edit("Unknown Predictions action.", _kb([[_btn("← Predictions", "predictions")]]))
        except Exception as e:
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
                await _edit("Unknown Settings action.", _kb([[_btn("← Settings", "settings")]]))
        except Exception as e:
            await _edit(f"Error: {e}", _kb([[_btn("← Home", "home")]]))

    elif data == "help" or data.startswith("help:"):
        try:
            from handlers.nav import show_help, show_help_topic
            if data == "help":
                await show_help(update, context)
            else:
                await show_help_topic(query, context, data.split(":", 1)[-1])
        except Exception as e:
            await _edit(f"Help error: {e}", _kb([[_btn("← Home", "home")]]))

    elif data.startswith("confirm:execute:"):
        try:
            from security.confirmation import execute_confirmation
            confirm_id = data.split(":")[3] if len(data.split(":")) > 3 else ""
            await query.message.edit_text("⏳ Executing...", reply_markup=None)
            success, result = await execute_confirmation(confirm_id)
            await query.message.edit_text(
                f"✅ *Executed*\n`{result.get('tx_id', '')}`" if success and isinstance(result, dict) else f"❌ *Failed*\n{result}",
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

    if context.user_data.get("awaiting_track_wallet"):
        context.user_data.pop("awaiting_track_wallet", None)
        sol_re = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')
        text_input = (update.message.text or "").strip()
        if sol_re.match(text_input):
            from handlers.degen_handler import handle_add_tracked_wallet
            await handle_add_tracked_wallet(update, context, text_input)
        else:
            await update.message.reply_text("❌ That doesn't look like a Solana wallet address.\nPlease paste a 32-44 character base58 address.")
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
