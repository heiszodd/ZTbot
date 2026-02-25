"""Slash commands."""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

log = logging.getLogger(__name__)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from security.auth import is_authorised

    uid = update.effective_user.id
    if not is_authorised(uid):
        return

    try:
        from handlers.nav import show_home

        await show_home(update, context)
    except Exception as e:
        log.error("cmd_start nav failed: %s", e)
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("📈 Perps", callback_data="perps"),
                    InlineKeyboardButton("🔥 Degen", callback_data="degen"),
                ],
                [
                    InlineKeyboardButton("🎯 Predictions", callback_data="predictions"),
                    InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
                ],
                [InlineKeyboardButton("❓ Help", callback_data="help")],
            ]
        )
        await update.message.reply_text(
            "🤖 *Trading Bot*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Select a section:",
            parse_mode="Markdown",
            reply_markup=kb,
        )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from security.auth import is_authorised

    if not is_authorised(update.effective_user.id):
        return
    try:
        from security.audit import log_event
        from security.emergency_stop import halt_trading

        uid = update.effective_user.id
        halt_trading("User command /stop")
        log_event("emergency_stop", {"trigger": "/stop"}, user_id=uid, success=True)
        await update.message.reply_text(
            "🛑 *ALL TRADING HALTED*\nNo orders will be placed.\nRun /resume to restart.",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"Stop error: {e}")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from security.auth import is_authorised

    if not is_authorised(update.effective_user.id):
        return
    try:
        from security.emergency_stop import resume_trading

        resume_trading("User command /resume")
        await update.message.reply_text("✅ Trading resumed.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Resume error: {e}")


async def cmd_security(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from security.auth import is_authorised

    if not is_authorised(update.effective_user.id):
        return
    try:
        from handlers.nav import show_security_status

        await show_security_status(update, context)
    except Exception as e:
        await update.message.reply_text(f"Security status error: {e}")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from security.auth import is_authorised

    if not is_authorised(update.effective_user.id):
        return
    try:
        from handlers.nav import show_help

        await show_help(update, context)
    except Exception as e:
        await update.message.reply_text(f"Help error: {e}")
