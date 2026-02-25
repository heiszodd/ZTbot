import logging
import os
from functools import wraps

from telegram import Update
from telegram.ext import ContextTypes

log = logging.getLogger(__name__)


def _get_allowed_ids() -> set[int]:
    raw = os.getenv("ALLOWED_USER_IDS", "")
    if not raw:
        log.warning("ALLOWED_USER_IDS not set — all users allowed (dev mode)")
        return set()

    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
        elif part:
            log.warning("Invalid user ID in ALLOWED_USER_IDS: %s", part)
    return ids


ALLOWED_USER_IDS = _get_allowed_ids()


def is_authorised(user_id: int) -> bool:
    if not ALLOWED_USER_IDS:
        return True
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

    if update.message:
        await update.message.reply_text(
            "⛔ Access denied.\n"
            f"Your user ID: `{user.id}`\n"
            "Ask admin to add it to ALLOWED_USER_IDS.",
            parse_mode="Markdown",
        )
    return False


def require_auth(fn):
    @wraps(fn)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
        uid = update.effective_user.id
        if not is_authorised(uid):
            log.warning("Unauthorised: %s", uid)
            return
        return await fn(update, context, *a, **kw)

    return wrapper


def require_auth_callback(fn):
    @wraps(fn)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
        query = update.callback_query
        if not query:
            return
        uid = query.from_user.id
        if not is_authorised(uid):
            log.warning("Unauthorised callback: %s", uid)
            await query.answer()
            return
        return await fn(update, context, *a, **kw)

    return wrapper
