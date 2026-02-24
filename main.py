"""main.py — Bot entry point.
Registers handlers in strict order.
No business logic here.
"""

import logging
from datetime import time as dt_time

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from config import TOKEN as TELEGRAM_BOT_TOKEN
from handlers.commands import cmd_help, cmd_resume, cmd_security, cmd_start, cmd_stop
from handlers.router import route_callback, route_text_message
from handlers.wallet_setup import hl_setup_conv, poly_setup_conv, sol_setup_conv

from engine.phase_engine import run_phase_engine
from engine.hyperliquid.monitor import run_hl_monitor
from engine.solana.auto_sell_monitor import run_auto_sell_monitor
from engine.polymarket.alert_monitor import run_polymarket_monitor

logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)


async def post_init(app):
    """Startup checks."""
    log.info("Bot starting up...")
    try:
        from security.encryption import _get_fernet

        _get_fernet()
        log.info("✅ Encryption key valid")
    except Exception as e:
        log.critical("❌ Encryption: %s", e)

    from security.auth import ALLOWED_USER_IDS

    if ALLOWED_USER_IDS:
        log.info("✅ Auth: %s user(s)", len(ALLOWED_USER_IDS))
    else:
        log.critical("❌ ALLOWED_USER_IDS empty")

    from security.emergency_stop import is_halted

    halted = is_halted()
    log.info("%s Trading: %s", "⏸" if halted else "✅", "HALTED" if halted else "Active")

    import db

    db.log_audit({"action": "bot_started", "details": {}, "success": True})


def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    app.add_handler(hl_setup_conv)
    app.add_handler(sol_setup_conv)
    app.add_handler(poly_setup_conv)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("security", cmd_security))
    app.add_handler(CommandHandler("help", cmd_help))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, route_text_message))
    app.add_handler(CallbackQueryHandler(route_callback))

    jq = app.job_queue
    jq.run_repeating(run_phase_engine, interval=300, first=60, name="phase_scanner")
    jq.run_repeating(run_hl_monitor, interval=300, first=90, name="hl_monitor")
    jq.run_repeating(run_auto_sell_monitor, interval=60, first=120, name="auto_sell")
    jq.run_repeating(run_polymarket_monitor, interval=900, first=150, name="poly_monitor")

    from security.heartbeat import send_heartbeat

    jq.run_daily(send_heartbeat, time=dt_time(8, 0, 0), name="heartbeat")

    log.info("Starting polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
