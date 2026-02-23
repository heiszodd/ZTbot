from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import db


def auto_create_degen_journal(scan: dict, early: dict, vel: dict, position: dict, narrative: str) -> int:
    return db.create_degen_journal(
        {
            "contract_address": scan["contract_address"],
            "chain": scan["chain"],
            "token_symbol": scan.get("token_symbol", "?"),
            "token_name": scan.get("token_name", "Unknown"),
            "narrative": narrative,
            "entry_price": scan.get("price_usd", 0),
            "entry_mcap": scan.get("market_cap", 0),
            "entry_liquidity": scan.get("liquidity_usd", 0),
            "entry_holders": scan.get("holder_count", 0),
            "entry_age_hours": early.get("age_hours", 0),
            "entry_rug_grade": scan.get("rug_grade", "?"),
            "position_size_usd": position.get("final_size", 0),
            "early_score": early.get("early_score", 0),
            "social_velocity": vel.get("velocity", 0),
            "rug_score": scan.get("rug_score", 0),
        }
    )


async def show_degen_journal_home(query, context):
    entries = db.get_degen_journal_entries(limit=50)
    closed = [e for e in entries if e.get("outcome")]
    open_entries = [e for e in entries if not e.get("outcome")]

    total_pnl = sum(float(e.get("pnl_usd", 0) or 0) for e in closed)
    wins = sum(1 for e in closed if float(e.get("pnl_usd", 0) or 0) > 0)
    losses = len(closed) - wins
    win_rate = wins / len(closed) if closed else 0

    avg_mult = sum(float(e.get("final_multiplier", 1) or 1) for e in closed) / max(len(closed), 1)
    best = max(closed, key=lambda e: float(e.get("final_multiplier", 1) or 1), default=None)

    text = (
        f"🎲 *Degen Journal*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Total plays:  {len(entries)}\n"
        f"Open:         {len(open_entries)}\n"
        f"Closed:       {len(closed)}\n\n"
    )

    if closed:
        text += (
            f"Win rate:    {win_rate:.0%}\n"
            f"Total P&L:   ${total_pnl:+,.2f}\n"
            f"Avg mult:    {avg_mult:.1f}x\n"
            f"Losses:      {losses}\n"
        )
        if best:
            text += f"Best play:   {best.get('token_symbol', '?')} {float(best.get('final_multiplier', 1) or 1):.1f}x\n"

    if open_entries:
        text += "\n*Open Positions*\n"
        for entry in open_entries[:3]:
            text += f"🎲 {entry.get('token_symbol', '?')} — ${float(entry.get('position_size_usd', 0) or 0):.0f}\n"

    buttons = [
        [InlineKeyboardButton("📋 All Plays", callback_data="degen_journal:all")],
        [InlineKeyboardButton("📊 By Narrative", callback_data="degen_journal:by_narrative")],
        [InlineKeyboardButton("🏆 Best Plays", callback_data="degen_journal:best")],
        [InlineKeyboardButton("🏠 Degen Home", callback_data="nav:degen_home")],
    ]

    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
