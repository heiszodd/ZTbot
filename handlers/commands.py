"""Slash commands."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from security.auth import require_auth

log = logging.getLogger(__name__)


@require_auth
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from handlers.nav import show_home

    await show_home(update, context)


@require_auth
async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from security.audit import log_event
    from security.emergency_stop import halt_trading

    uid = update.effective_user.id
    halt_trading("User command /stop")
    log_event("emergency_stop", {"trigger": "/stop"}, user_id=uid, success=True)
    await update.message.reply_text("🛑 *ALL TRADING HALTED*\nNo orders will be placed.\nRun /resume to restart.", parse_mode="Markdown")


@require_auth
async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from security.emergency_stop import resume_trading

    resume_trading("User command /resume")
    await update.message.reply_text("✅ Trading resumed.", parse_mode="Markdown")


@require_auth
async def cmd_security(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from handlers.nav import show_security_status

    await show_security_status(update, context)


@require_auth
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from handlers.nav import show_help

    await show_help(update, context)
