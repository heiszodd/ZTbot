import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

async def send_heartbeat(context) -> None:
    from config import CHAT_ID, HL_ADDRESS
    from security.emergency_stop import is_halted
    from security.spending_limits import get_daily_summary
    try:
        halted = is_halted()
        status_emoji = "🔴 HALTED" if halted else "🟢 Active"
        spend = get_daily_summary()
        hl_value = 0.0
        if HL_ADDRESS and not halted:
            try:
                from engine.hyperliquid.account_reader import fetch_account_summary
                summary = await fetch_account_summary(HL_ADDRESS)
                hl_value = summary.get("account_value", 0)
            except Exception:
                pass
        now = datetime.now(timezone.utc)
        text = f"💓 *Bot Heartbeat*\n━━━━━━━━━━━━━━━━━━━━━━━━\n{now.strftime('%Y-%m-%d %H:%M')} UTC\nStatus: {status_emoji}\n\n💰 *Account*\nHL Value: ${hl_value:,.2f}\n\n📊 *Today's Spend*\n"
        for section, data in spend.items():
            text += f"  {section.title()}: ${data['spent']:.2f} / ${data['limit']:.0f} ({data['trades']} trades)\n"
        try:
            import db
            recent_events = db.get_recent_audit(hours=24, limit=5)
            security_events = [e for e in recent_events if "security" in e.get("action", "")]
            if security_events:
                text += f"\n⚠️ *Security Events (24h): {len(security_events)}*\n"
                for ev in security_events[:3]:
                    text += f"  {ev['action']}: {ev.get('error', '')}\n"
        except Exception:
            pass
        text += "\n_If you did not receive this message something is wrong._"
        await context.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")
    except Exception as e:
        log.error(f"Heartbeat send failed: {e}")
