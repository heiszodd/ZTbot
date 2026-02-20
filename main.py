import logging
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler
)
from config import TOKEN
from handlers import commands, alerts, wizard, stats

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)


def main():
    app = Application.builder().token(TOKEN).build()

    # ── Core commands ─────────────────────────────────
    app.add_handler(CommandHandler("start",      commands.start))
    app.add_handler(CommandHandler("help",       commands.help_cmd))
    app.add_handler(CommandHandler("status",     commands.status))
    app.add_handler(CommandHandler("menu",       commands.menu))

    # ── Model commands ────────────────────────────────
    app.add_handler(CommandHandler("models",     commands.list_models))
    app.add_handler(CommandHandler("activate",   commands.activate_model))
    app.add_handler(CommandHandler("deactivate", commands.deactivate_model))

    # ── Scanning ──────────────────────────────────────
    app.add_handler(CommandHandler("scan",       commands.scan))
    app.add_handler(CommandHandler("alerts",     commands.list_alerts))

    # ── Performance ───────────────────────────────────
    app.add_handler(CommandHandler("stats",      stats.stats_cmd))
    app.add_handler(CommandHandler("discipline", stats.discipline_cmd))
    app.add_handler(CommandHandler("regime",     stats.regime_cmd))

    # ── Model wizard (conversation) ───────────────────
    app.add_handler(wizard.build_wizard_handler())

    # ── Inline button callbacks ───────────────────────
    app.add_handler(CallbackQueryHandler(alerts.handle_alert_response, pattern="^(entered|skipped|watching):"))
    app.add_handler(CallbackQueryHandler(commands.handle_menu_callback, pattern="^menu:"))
    app.add_handler(CallbackQueryHandler(commands.handle_model_callback, pattern="^model:"))

    # ── Scheduler: scanner every 15 min ──────────────
    job_queue = app.job_queue
    job_queue.run_repeating(alerts.run_scanner, interval=900, first=10, name="scanner")

    log.info("Bot started.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
