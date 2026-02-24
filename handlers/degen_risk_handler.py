from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import db


async def show_degen_live_risk(query, context):
    s = db.get_user_settings(query.message.chat_id)
    txt = (
        "💰 Live Wallet Risk Settings\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🛑 Stop Loss: {s.get('live_sl_pct',20)}%\n"
        f"🎯 TP1: +{s.get('live_tp1_pct',50)}% → sell {s.get('live_tp1_sell_pct',25)}%\n"
        f"🎯 TP2: +{s.get('live_tp2_pct',100)}% → sell {s.get('live_tp2_sell_pct',25)}%\n"
        f"🎯 TP3: +{s.get('live_tp3_pct',200)}% → sell {s.get('live_tp3_sell_pct',50)}%\n"
        f"⚡ Trail: {s.get('live_trail_pct',20)}%\n"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("← Live Wallet", callback_data="degen:live")]])
    await query.message.edit_text(txt, reply_markup=kb)


async def show_degen_demo_risk(query, context):
    await query.message.edit_text(
        "💰 Demo Wallet Risk Settings",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Degen", callback_data="degen:home")]]),
    )


async def handle_set_live_sl(query, context):
    await query.answer("Send SL % in chat", show_alert=True)


async def handle_set_live_tp(query, context):
    await query.answer("Send TP % in chat", show_alert=True)


async def handle_set_live_trail(query, context):
    await query.answer("Send trail % in chat", show_alert=True)


async def handle_set_demo_sl(query, context):
    await query.answer("Send demo SL %", show_alert=True)


async def handle_set_demo_tp(query, context):
    await query.answer("Send demo TP %", show_alert=True)


async def handle_set_demo_trail(query, context):
    await query.answer("Send demo trail %", show_alert=True)
