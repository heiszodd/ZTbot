from telegram import InlineKeyboardButton, InlineKeyboardMarkup


async def show_journal_home(query, context):
    await query.message.reply_text(
        "📓 Journal Home",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Perps", callback_data="perps:home")]]),
    )
