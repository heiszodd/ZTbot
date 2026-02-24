import os
import logging
import functools
from telegram import Update
from telegram.ext import ContextTypes

log = logging.getLogger(__name__)


def _get_allowed_ids() -> set:
    raw = os.getenv("ALLOWED_USER_IDS", "")
    ids = set()
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                ids.add(int(part))
            except ValueError:
                log.warning(f"Invalid user ID in ALLOWED_USER_IDS: {part}")
    if not ids:
        log.critical("ALLOWED_USER_IDS is empty! Bot will reject ALL users. Set this in Railway env vars.")
    return ids


ALLOWED_USER_IDS = _get_allowed_ids()


def is_authorised(user_id: int) -> bool:
    return user_id in ALLOWED_USER_IDS


async def check_auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False
    if not is_authorised(user.id):
        log.warning(
            f"UNAUTHORISED ACCESS ATTEMPT: user_id={user.id} username=@{user.username} name={user.full_name}"
        )
        try:
            import db
            db.log_audit(action="unauthorised_access", details={"user_id": user.id, "username": user.username, "name": user.full_name}, user_id=user.id, success=False, error="User not in whitelist")
        except Exception:
            pass
        return False
    return True


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
            log.warning(f"UNAUTHORISED CALLBACK: user_id={uid} data={query.data if query else '?'}")
            if query:
                await query.answer("Unauthorised.", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper
