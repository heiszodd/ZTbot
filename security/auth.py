import functools
import logging
import os

from telegram import Update
from telegram.ext import ContextTypes

log = logging.getLogger(__name__)


def _parse_allowed_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            log.warning("Invalid user ID in ALLOWED_USER_IDS: %s", part)
    return ids


def _get_allowed_ids() -> set[int]:
    ids = _parse_allowed_ids(os.getenv("ALLOWED_USER_IDS", ""))

    # Safety fallback: if ALLOWED_USER_IDS isn't configured,
    # still allow configured CHAT_ID owner account.
    if not ids:
        try:
            from config import CHAT_ID

            ids.add(int(CHAT_ID))
            log.warning(
                "ALLOWED_USER_IDS empty; falling back to CHAT_ID=%s for owner access.",
                CHAT_ID,
            )
        except Exception as exc:
            log.critical("Auth fallback failed (CHAT_ID unavailable): %s", exc)

    if not ids:
        log.critical("No allowed users resolved; bot will reject all users.")

    return ids


ALLOWED_USER_IDS = _get_allowed_ids()


def is_authorised(user_id: int) -> bool:
    return user_id in ALLOWED_USER_IDS


async def check_auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False

    if is_authorised(user.id):
        return True

    log.warning(
        "UNAUTHORISED ACCESS ATTEMPT: user_id=%s username=@%s name=%s",
        user.id,
        user.username,
        user.full_name,
    )

    try:
        import db

        db.log_audit(
            action="unauthorised_access",
            details={
                "user_id": user.id,
                "username": user.username,
                "name": user.full_name,
            },
            user_id=user.id,
            success=False,
            error="User not in whitelist",
        )
    except Exception:
        pass

    if update.message:
        await update.message.reply_text(
            "⛔ Access denied.\n"
            f"Your user ID: `{user.id}`\n"
            "Ask admin to add it to ALLOWED_USER_IDS.",
            parse_mode="Markdown",
        )
    return False


def require_auth(func):
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not await check_auth(update, context):
            return
        return await func(update, context, *args, **kwargs)

    return wrapper


def require_auth_callback(func):
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        query = update.callback_query
        user = query.from_user if query else None
        uid = user.id if user else 0
        if not is_authorised(uid):
            log.warning("UNAUTHORISED CALLBACK: user_id=%s data=%s", uid, query.data if query else "?")
            if query:
                await query.answer(f"Unauthorised. Your ID: {uid}", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)

    return wrapper
