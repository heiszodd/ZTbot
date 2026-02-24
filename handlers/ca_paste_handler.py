import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from security.auth import require_auth
from engine.degen.contract_scanner import scan_contract, format_scan_result

ADDR_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
URL_PATTERNS = [
    re.compile(r"dexscreener\.com/solana/([1-9A-HJ-NP-Za-km-z]{32,44})", re.IGNORECASE),
    re.compile(r"birdeye\.so/token/([1-9A-HJ-NP-Za-km-z]{32,44})", re.IGNORECASE),
    re.compile(r"pump\.fun/([1-9A-HJ-NP-Za-km-z]{32,44})", re.IGNORECASE),
]


@require_auth
async def handle_ca_paste(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return False
    text = update.message.text.strip()
    address = text if ADDR_RE.fullmatch(text) else None
    if not address:
        for pattern in URL_PATTERNS:
            match = pattern.search(text)
            if match:
                address = match.group(1)
                break
    if not address:
        return False

    msg = await update.message.reply_text("⏳ Loading...")
    scan = await scan_contract(address, force_refresh=True)
    await msg.edit_text(
        format_scan_result(scan),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🟢 $25", callback_data=f"degen:buy:{address}:25"), InlineKeyboardButton("🟢 $50", callback_data=f"degen:buy:{address}:50")],
            [InlineKeyboardButton("🔍 Full Scan", callback_data=f"degen:scan:{address}"), InlineKeyboardButton("← Back", callback_data="nav:degen_home")],
        ]),
    )
    return True
