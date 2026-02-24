import datetime
import logging
import os
import sys

import db
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ConversationHandler, MessageHandler, filters

from engine import notification_filter, phase_engine, regime_detector, session_checklist, session_journal
from engine.degen import dev_tracker, exit_planner, narrative_detector
from engine.degen.auto_scanner import run_auto_scanner, run_watchlist_scanner
from engine.hyperliquid.monitor import run_hl_monitor
from engine.polymarket.alert_monitor import run_polymarket_monitor
from engine.polymarket.demo_trading import update_poly_demo_trades
from engine.solana.auto_sell_monitor import run_auto_sell_monitor
from engine.solana.dca_executor import run_dca_executor
from engine.solana.trenches_feed import run_trenches_scanner
from engine.solana.wallet_tracker import run_wallet_tracker
from handlers import alerts, ca_paste_handler, chart_handler, commands, degen_wizard, news_handler, polymarket_handler, solana_handler, wizard, hyperliquid_handler
from handlers.router import master_callback_router
from security.emergency_stop import is_halted
from security.heartbeat import send_heartbeat

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger(__name__)


async def post_init(application):
    log.info("Bot startup checks...")
    try:
        db._ensure_pool()
        log.info("✅ Database connected")
    except Exception as exc:
        log.error("❌ Database unavailable: %s", exc)
    log.info("Trading status: %s", "HALTED" if is_halted() else "Active")


def main():
    for var in ["BOT_TOKEN", "CHAT_ID"]:
        if not os.getenv(var):
            print(f"FATAL: {var} is not set", flush=True)
            sys.exit(1)

    db.init_pool()
    db.setup_db()
    db.ensure_intelligence_tables()

    app = Application.builder().token(os.getenv("BOT_TOKEN")).post_init(post_init).build()

    # Conversations first
    app.add_handler(polymarket_handler.poly_setup_conv, group=0)
    app.add_handler(solana_handler.sol_setup_conv, group=0)
    app.add_handler(hyperliquid_handler.hl_setup_conv, group=0)

    chart_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.PHOTO | filters.Document.IMAGE, chart_handler.chart_received_first)],
        states={chart_handler.CHART_WAITING_LTF: [MessageHandler(filters.PHOTO | filters.Document.IMAGE, chart_handler.chart_received_ltf)]},
        fallbacks=[],
        per_chat=True,
    )
    app.add_handler(chart_conv, group=0)
    app.add_handler(wizard.build_wizard_handler(), group=0)

    # Commands
    app.add_handler(CommandHandler("start", commands.handle_start))
    app.add_handler(CommandHandler("stop", commands.handle_stop))
    app.add_handler(CommandHandler("resume", commands.handle_resume))
    app.add_handler(CommandHandler("security", commands.handle_security))
    app.add_handler(CommandHandler("audit", commands.handle_audit))
    app.add_handler(CommandHandler("keys", commands.handle_keys))
    app.add_handler(CommandHandler("limits", commands.handle_limits))
    app.add_handler(CommandHandler("setup", commands.handle_setup_command))
    app.add_handler(CommandHandler("buy", commands.handle_buy_command))
    app.add_handler(CommandHandler("sell", commands.handle_sell_command))
    app.add_handler(CommandHandler("price", commands.handle_price_command))
    app.add_handler(CommandHandler("pnl", commands.handle_pnl_command))
    app.add_handler(CommandHandler("positions", commands.handle_positions_command))
    app.add_handler(CommandHandler("scan", commands.handle_scan_command))
    app.add_handler(CommandHandler("alert", commands.handle_alert_command))
    app.add_handler(CommandHandler("trenches", commands.handle_trenches_command))
    app.add_handler(CommandHandler("settings", commands.handle_settings_command))

    # CA paste detection
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"), ca_paste_handler.handle_ca_paste), group=0)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, solana_handler.handle_solana_text), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, polymarket_handler.handle_poly_text), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, commands.handle_setup), group=2)

    # One callback handler
    app.add_handler(CallbackQueryHandler(master_callback_router), group=10)

    # Jobs
    app.job_queue.run_repeating(phase_engine.run_phase_engine, interval=300, first=60, name="phase_engine")
    app.job_queue.run_repeating(phase_engine.alert_lifecycle_job, interval=300, first=90, name="alert_lifecycle")
    app.job_queue.run_daily(regime_detector.run_regime_detection, time=datetime.time(hour=5, minute=30, tzinfo=datetime.timezone.utc), name="regime_detection")
    app.job_queue.run_repeating(phase_engine.model_grading_job, interval=86400, first=3600, name="model_grading")
    app.job_queue.run_daily(session_journal.record_session_data, time=datetime.time(hour=7, minute=5, tzinfo=datetime.timezone.utc), name="session_journal")
    app.job_queue.run_daily(session_checklist.run_pre_session_checklist, time=datetime.time(hour=6, minute=30, tzinfo=datetime.timezone.utc), name="pre_session_checklist")
    app.job_queue.run_daily(notification_filter.run_pattern_analysis, time=datetime.time(hour=20, minute=0, tzinfo=datetime.timezone.utc), days=(6,), name="pattern_analysis")
    app.job_queue.run_repeating(phase_engine.expire_old_phases_job, interval=3600, first=390, name="phase_expiry")
    app.job_queue.run_repeating(alerts.run_scanner, interval=300, first=240, name="scanner")
    app.job_queue.run_repeating(alerts.run_pending_checker, interval=30, first=330, name="pending_checker")
    app.job_queue.run_repeating(news_handler.news_briefing_job, interval=600, first=420, name="news_briefing")
    app.job_queue.run_repeating(news_handler.news_signal_job, interval=300, first=150, name="news_signal")
    app.job_queue.run_repeating(run_hl_monitor, interval=300, first=540, name="hl_monitor")
    app.job_queue.run_repeating(run_auto_sell_monitor, interval=60, first=570, name="auto_sell_monitor")
    app.job_queue.run_repeating(run_dca_executor, interval=60, first=600, name="dca_executor")
    app.job_queue.run_repeating(run_wallet_tracker, interval=60, first=630, name="wallet_tracker")
    app.job_queue.run_repeating(run_trenches_scanner, interval=30, first=660, name="trenches_scanner")
    app.job_queue.run_repeating(run_auto_scanner, interval=1800, first=120, name="auto_degen_scanner")
    app.job_queue.run_repeating(run_watchlist_scanner, interval=900, first=270, name="watchlist_scanner")
    app.job_queue.run_repeating(run_polymarket_monitor, interval=900, first=480, name="poly_monitor")
    app.job_queue.run_repeating(update_poly_demo_trades, interval=900, first=510, name="poly_demo_update")
    app.job_queue.run_repeating(dev_tracker.run_dev_wallet_monitor, interval=600, first=210, name="dev_wallet_monitor")
    app.job_queue.run_repeating(narrative_detector.update_narrative_momentum, interval=1800, first=300, name="narrative_momentum")
    app.job_queue.run_repeating(exit_planner.monitor_exit_triggers, interval=300, first=120, name="degen_exit_monitor")
    app.job_queue.run_daily(send_heartbeat, time=datetime.time(8, 0, 0), name="heartbeat")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
