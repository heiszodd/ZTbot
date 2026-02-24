import asyncio
import time
import logging
import uuid
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

log = logging.getLogger(__name__)
CONFIRMATION_TIMEOUT = 60
_pending: dict = {}

def create_confirmation(plan: dict, callback: callable) -> str:
    confirm_id = str(uuid.uuid4())[:12]
    _pending[confirm_id] = {"plan": plan, "created_at": time.time(), "callback": callback, "used": False}
    asyncio.get_event_loop().call_later(CONFIRMATION_TIMEOUT, lambda: _expire_confirmation(confirm_id))
    log.info(f"Confirmation created: {confirm_id}")
    return confirm_id

def _expire_confirmation(confirm_id: str) -> None:
    entry = _pending.get(confirm_id)
    if entry and not entry["used"]:
        del _pending[confirm_id]
        log.info(f"Confirmation expired: {confirm_id}")

async def execute_confirmation(confirm_id: str) -> tuple[bool, str]:
    entry = _pending.get(confirm_id)
    if not entry:
        return False, "Confirmation expired or not found. Generate a new trade plan."
    if entry["used"]:
        return False, "This confirmation was already used. Cannot replay a trade confirmation."
    age = time.time() - entry["created_at"]
    if age > CONFIRMATION_TIMEOUT:
        del _pending[confirm_id]
        return False, f"Confirmation timed out after {CONFIRMATION_TIMEOUT}s. Generate a new trade plan."
    entry["used"] = True
    try:
        result = await entry["callback"](entry["plan"])
        del _pending[confirm_id]
        log.info(f"Confirmation executed: {confirm_id}")
        return True, result
    except Exception as e:
        log.error(f"Confirmation execution failed {confirm_id}: {e}")
        del _pending[confirm_id]
        return False, f"Execution failed: {e}"

def cancel_confirmation(confirm_id: str) -> bool:
    if confirm_id in _pending:
        del _pending[confirm_id]
        log.info(f"Confirmation cancelled: {confirm_id}")
        return True
    return False

def build_confirmation_keyboard(confirm_id: str, section: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm — Execute Trade", callback_data=f"confirm:execute:{section}:{confirm_id}")],[InlineKeyboardButton(f"❌ Cancel  (auto-cancels in {CONFIRMATION_TIMEOUT}s)", callback_data=f"confirm:cancel:{section}:{confirm_id}")]])

def build_confirmation_message(plan: dict, section: str, confirm_id: str) -> str:
    return (
        f"⚠️ *TRADE CONFIRMATION REQUIRED*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Section:  {section.upper()}\n"
        f"Action:   {plan.get('side','?')} {plan.get('coin', plan.get('symbol','?'))}\n"
        f"Size:     ${plan.get('size_usd',0):,.2f}\n"
        f"Entry:    ${plan.get('entry_price',0):,.4f}\n"
        f"Stop:     ${plan.get('stop_loss',0):,.4f}\n"
        f"Risk:     ${plan.get('risk_amount',0):,.2f}\n\n"
        f"⏰ *Expires in {CONFIRMATION_TIMEOUT} seconds*\n"
        f"Ref: `{confirm_id}`\n\n"
        f"_Tap Confirm to execute. This cannot be undone._"
    )
