import logging
import sys
import db
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters
)
from config import TOKEN, SCANNER_INTERVAL
from handlers import commands, alerts, wizard, stats
from engine import run_backtest

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)


def main():
    # Ensure DB tables exist on startup
    try:
        db.setup_db()
        log.info("DB ready")
    except Exception as e:
        log.error(f"DB setup failed: {e}")

    app = Application.builder().token(TOKEN).build()

    # ── Core navigation ───────────────────────────────
    app.add_handler(CommandHandler("start",       commands.start))
    app.add_handler(CommandHandler("home",        commands.start))
    app.add_handler(CommandHandler("scan",        commands.scan))
    app.add_handler(CommandHandler("guide",       commands.guide))
    app.add_handler(CommandHandler("stats",       stats.stats_cmd))
    app.add_handler(CommandHandler("discipline",  stats.discipline_cmd))
    app.add_handler(CommandHandler("result",      stats.result_cmd))
    app.add_handler(CommandHandler("create_model",wizard.wiz_start))
    app.add_handler(CommandHandler("backtest",    commands.backtest))

    # ── Model wizard (ConversationHandler — must be first) ──
    app.add_handler(wizard.build_wizard_handler())

    # ── Callback routers ──────────────────────────────
    app.add_handler(CallbackQueryHandler(commands.handle_nav,       pattern="^nav:"))
    app.add_handler(CallbackQueryHandler(commands.handle_model_cb,  pattern="^model:"))
    app.add_handler(CallbackQueryHandler(commands.handle_scan_cb,   pattern="^scan:"))
    app.add_handler(CallbackQueryHandler(commands.handle_backtest_cb, pattern="^backtest:"))
    app.add_handler(CallbackQueryHandler(alerts.handle_alert_response, pattern="^alert:"))

    # ── Scanner job ───────────────────────────────────
    app.job_queue.run_repeating(
        alerts.run_scanner,
        interval=SCANNER_INTERVAL,
        first=15,
        name="scanner"
    )

    log.info("🤖 Bot started — polling")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].lower() in {"backtest", "--backtest", "-b"}:
        run_backtest()
    else:
        main()
