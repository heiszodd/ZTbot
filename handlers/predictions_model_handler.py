from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import db


async def show_predictions_models_home(query, context):
    models = db.get_active_prediction_models()
    text = (
        "🧩 Prediction Models\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Active Models: {len(models)}\n"
        "Markets Scanned Today: 0\n"
        "Signals Generated: 0\n"
        "Win Rate (resolved): 0%"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Create Model", callback_data="pred_model:create"), InlineKeyboardButton("🏆 Master Model", callback_data="pred_model:master")],
        [InlineKeyboardButton("📊 Model Stats", callback_data="pred_model:stats"), InlineKeyboardButton("📚 Presets", callback_data="pred_model:presets")],
        [InlineKeyboardButton("← Predictions", callback_data="predictions:home")],
    ])
    await query.message.edit_text(text, reply_markup=kb)
