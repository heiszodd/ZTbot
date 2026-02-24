from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import db


async def show_degen_models_home(query, context):
    models = db.get_active_degen_models()
    text = (
        "🧩 Degen Models\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Active Models: {len(models)}\n"
        "Tokens Evaluated Today: 0\n"
        "Signals Generated: 0\n"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Create Model", callback_data="degen_model:create"), InlineKeyboardButton("🏆 Master Model", callback_data="degen_model:master")],
        [InlineKeyboardButton("📊 Model Stats", callback_data="degen_model:stats"), InlineKeyboardButton("📚 Presets", callback_data="degen_model:presets")],
        [InlineKeyboardButton("← Degen", callback_data="degen:home")],
    ])
    await query.message.edit_text(text, reply_markup=kb)
