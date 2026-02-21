import datetime
import json
import logging
import os
import sys
import time
from pathlib import Path

import db
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler
)

import prices as px
from config import TOKEN, SCANNER_INTERVAL, CRYPTO_PAIRS
from handlers import commands, alerts, wizard, stats, scheduler
from engine import run_backtest

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

DASHBOARD_STATE_FILE = Path(".cache/dashboard_state.json")
DASHBOARD_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


MODEL_DESCRIPTIONS = {
    "FVG Basic": "Fair value gap continuation model with basic displacement filters.",
    "Sweep Reversal": "Liquidity sweep + market structure reversal confirmation.",
    "OB Confluence": "Order-block reaction aligned with session and directional bias.",
    "FVG + OB Filter": "FVG entries gated by nearby OB confluence zones.",
    "Breaker Block": "Breaker-block continuation model after failed OBs.",
}


BOT_STATE = {
    "started_at": time.time(),
    "status": "Running",
    "active_strategy": "Auto Scanner",
    "last_run_time": None,
    "last_warning": None,
    "last_price_refresh_ts": 0.0,
}

PRICE_REFRESH_COOLDOWN_SEC = 12


def _utc_now_str() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _fmt_datetime(dt_value) -> str:
    if not dt_value:
        return "N/A"
    if isinstance(dt_value, str):
        return dt_value
    if hasattr(dt_value, "strftime"):
        return dt_value.strftime("%Y-%m-%d %H:%M")
    return str(dt_value)


def _fmt_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins, sec = divmod(rem, 60)
    if days:
        return f"{days}d {hours:02}:{mins:02}:{sec:02}"
    return f"{hours:02}:{mins:02}:{sec:02}"


def _safe_db_call(func, default, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        BOT_STATE["last_warning"] = f"DB: {exc}"
        return default


def _load_dashboard_state() -> dict:
    if not DASHBOARD_STATE_FILE.exists():
        return {
            "recent_trades": [],
            "backtest_summary": {},
            "model_detection_counts": {},
            "price_snapshot": {},
            "last_dashboard_opened": _utc_now_str(),
        }
    try:
        return json.loads(DASHBOARD_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {
            "recent_trades": [],
            "backtest_summary": {},
            "model_detection_counts": {},
            "price_snapshot": {},
            "last_dashboard_opened": _utc_now_str(),
        }


def _save_dashboard_state(state: dict) -> None:
    state["last_dashboard_opened"] = _utc_now_str()
    DASHBOARD_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _compute_performance(recent_trades: list[dict]) -> dict:
    closed = [t for t in recent_trades if t.get("result")]
    total = len(closed)
    wins = sum(1 for t in closed if str(t.get("result", "")).upper() in {"TP", "WIN"})
    losses = sum(1 for t in closed if str(t.get("result", "")).upper() in {"SL", "LOSS"})
    breakeven = sum(1 for t in closed if str(t.get("result", "")).upper() in {"BE", "BREAKEVEN"})

    rr_values = [float(t.get("rr", 0.0) or 0.0) for t in closed]
    pos_rr = [x for x in rr_values if x > 0]
    neg_rr = [abs(x) for x in rr_values if x < 0]

    winrate = (wins / total * 100) if total else 0.0
    avg_rr = (sum(rr_values) / total) if total else 0.0
    profit_factor = (sum(pos_rr) / sum(neg_rr)) if neg_rr else (float("inf") if pos_rr else 0.0)
    net_pnl_pct = sum(rr_values)

    max_win_streak = max_loss_streak = 0
    cur_win = cur_loss = 0
    for trade in reversed(closed):
        result = str(trade.get("result", "")).upper()
        if result in {"TP", "WIN"}:
            cur_win += 1
            cur_loss = 0
        elif result in {"SL", "LOSS"}:
            cur_loss += 1
            cur_win = 0
        else:
            cur_win = cur_loss = 0
        max_win_streak = max(max_win_streak, cur_win)
        max_loss_streak = max(max_loss_streak, cur_loss)

    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "winrate": winrate,
        "avg_rr": avg_rr,
        "profit_factor": profit_factor,
        "net_pnl_pct": net_pnl_pct,
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
    }


def _clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _render_section(title: str) -> None:
    print(f"\n{'=' * 20} {title} {'=' * 20}")


def _render_dashboard(state: dict) -> None:
    _clear_screen()
    now = time.time()
    uptime = _fmt_duration(now - BOT_STATE["started_at"])

    open_trades = _safe_db_call(db.get_open_trades, [], limit=10)
    all_models = _safe_db_call(db.get_all_models, [])

    recent_closed = _safe_db_call(db.get_recent_alerts, [], hours=168, limit=10)
    trade_log = state.get("recent_trades") or recent_closed or []
    perf = _compute_performance(trade_log)

    print("🚀 ZTbot Command Dashboard (Low-API Mode)")
    print("-" * 64)
    print(f"🕒 { _utc_now_str() }")

    _render_section("Bot / Engine Status")
    print(f"Status            : {BOT_STATE['status']}")
    print(f"Active Strategy   : {BOT_STATE['active_strategy']}")
    print(f"Last Run Time     : {BOT_STATE['last_run_time'] or 'N/A'}")
    print(f"Uptime            : {uptime}")

    _render_section("Performance Overview")
    pf = "∞" if perf["profit_factor"] == float("inf") else f"{perf['profit_factor']:.2f}"
    print(f"Total Trades      : {perf['total']} (W {perf['wins']} | L {perf['losses']} | BE {perf['breakeven']})")
    print(f"Winrate           : {perf['winrate']:.2f}%")
    print(f"Average RR        : {perf['avg_rr']:.2f}")
    print(f"Profit Factor     : {pf}")
    print(f"Net PnL % (R~%)   : {perf['net_pnl_pct']:.2f}%")
    print(f"Streaks           : Max Win {perf['max_win_streak']} | Max Loss {perf['max_loss_streak']}")

    _render_section("Open Trades / Positions")
    if not open_trades:
        print("No open trades.")
    else:
        for t in open_trades[:8]:
            status = t.get("result") or "OPEN"
            print(
                f"• {t.get('pair','N/A'):<8} | Entry {px.fmt_price(float(t.get('entry_price', 0) or 0)):<12} "
                f"| Time {_fmt_datetime(t.get('logged_at')):<16} | Status {status:<6} | Model {t.get('model_id','N/A')}"
            )

    _render_section("Recent Activity")
    if not trade_log:
        print("No recent trades or setups in cache yet.")
    else:
        for t in trade_log[:8]:
            rr = float(t.get("rr", 0.0) or 0.0)
            result = t.get("result") or t.get("status") or "N/A"
            print(
                f"• {_fmt_datetime(t.get('logged_at') or t.get('alerted_at') or t.get('day')):<16} "
                f"| {t.get('pair','N/A'):<8} | {t.get('model_id') or t.get('model_name') or 'N/A':<16} "
                f"| {result:<10} | RR {rr:.2f}"
            )

    _render_section("Active Models / Strategies")
    if not all_models:
        fallback_models = [
            {"name": "FVG Basic", "status": "active"},
            {"name": "Sweep Reversal", "status": "active"},
            {"name": "OB Confluence", "status": "inactive"},
        ]
        all_models = fallback_models
    model_counts = state.get("model_detection_counts", {})
    for model in all_models[:10]:
        name = model.get("name", "Unknown")
        status = model.get("status", "inactive")
        desc = MODEL_DESCRIPTIONS.get(name, "Custom strategy model.")
        detections = model_counts.get(name, 0)
        print(f"• {name:<18} | {status:<8} | detections:{detections:<4} | {desc}")

    _render_section("Backtest Summary (latest cached)")
    bt = state.get("backtest_summary") or {}
    if not bt:
        print("No backtest summary cached yet. Run one via quick action #1.")
    else:
        print(f"Pair/TF/Range     : {bt.get('pair','N/A')} {bt.get('timeframe','N/A')} {bt.get('range','N/A')}")
        print(f"Setups/W/L        : {bt.get('total_setups',0)} / {bt.get('wins',0)} / {bt.get('losses',0)}")
        print(f"Winrate / Avg RR  : {bt.get('winrate',0):.2f}% / {bt.get('avg_rr',0):.2f}")
        print(f"Most Win/Loss Day : {bt.get('best_day','N/A')} / {bt.get('worst_day','N/A')}")

    _render_section("System Health / Alerts")
    health = px.get_api_health()
    last_call = health.get("last_api_call_ts")
    last_call_fmt = _fmt_datetime(datetime.datetime.fromtimestamp(last_call, tz=datetime.timezone.utc)) if last_call else "Never"
    print(f"API Calls (session): {health.get('api_call_count', 0)}")
    print(f"Last API fetch     : {last_call_fmt}")
    print(f"Cache status       : {health.get('cache_files', 0)} files @ {health.get('cache_dir')}")
    print(f"Last API error     : {health.get('last_api_error') or BOT_STATE.get('last_warning') or 'None'}")

    _render_section("Quick Actions")
    print("1) Run Backtest")
    print("2) Refresh specific pair price (one-shot)")
    print("3) Toggle model on/off")
    print("4) View recent logs (trade + alert snapshots)")
    print("5) Refresh watched pairs (top 3) once")
    print("6) Pause/Resume bot state")
    print("0) Exit dashboard")


def _refresh_specific_pair_price(state: dict) -> None:
    now = time.time()
    if now - BOT_STATE["last_price_refresh_ts"] < PRICE_REFRESH_COOLDOWN_SEC:
        wait_for = int(PRICE_REFRESH_COOLDOWN_SEC - (now - BOT_STATE["last_price_refresh_ts"]))
        print(f"Please wait {wait_for}s before another manual price refresh (API cooldown).")
        input("Press Enter to continue...")
        return

    pair = input("Pair (e.g., BTCUSDT): ").strip().upper()
    if not pair:
        return
    fetched = px.fetch_prices([pair])
    BOT_STATE["last_price_refresh_ts"] = now
    if not fetched:
        print("No price data available.")
    else:
        value = fetched.get(pair)
        state.setdefault("price_snapshot", {})[pair] = {
            "price": value,
            "refreshed_at": _utc_now_str(),
        }
        print(f"{pair} => {px.fmt_price(value)}")
    input("Press Enter to continue...")


def _refresh_watched_pairs(state: dict) -> None:
    now = time.time()
    if now - BOT_STATE["last_price_refresh_ts"] < PRICE_REFRESH_COOLDOWN_SEC:
        wait_for = int(PRICE_REFRESH_COOLDOWN_SEC - (now - BOT_STATE["last_price_refresh_ts"]))
        print(f"Please wait {wait_for}s before another manual price refresh (API cooldown).")
        input("Press Enter to continue...")
        return

    watched = CRYPTO_PAIRS[:3]
    print(f"Refreshing watched pairs once: {', '.join(watched)}")
    fetched = px.fetch_prices(watched)
    BOT_STATE["last_price_refresh_ts"] = now
    if not fetched:
        print("No watched pair prices returned.")
    else:
        snap = state.setdefault("price_snapshot", {})
        for pair in watched:
            price = fetched.get(pair)
            if price is None:
                continue
            previous_vol_proxy = (snap.get(pair) or {}).get("approx_volume_proxy")
            snap[pair] = {
                "price": price,
                "approx_volume_proxy": previous_vol_proxy,
                "refreshed_at": _utc_now_str(),
            }
            vol_text = f"{previous_vol_proxy:.2f}" if isinstance(previous_vol_proxy, (int, float)) else "N/A"
            print(f"• {pair:<8} | close {px.fmt_price(price):<12} | vol-proxy {vol_text}")
    input("Press Enter to continue...")


def _toggle_model() -> None:
    models = _safe_db_call(db.get_all_models, [])
    if not models:
        print("No DB models found.")
        input("Press Enter to continue...")
        return
    for idx, model in enumerate(models, start=1):
        print(f"{idx}) {model.get('name')} [{model.get('status')}] id={model.get('id')}")
    choice = input("Select model #: ").strip()
    if not choice.isdigit() or int(choice) < 1 or int(choice) > len(models):
        return
    picked = models[int(choice) - 1]
    new_status = "inactive" if picked.get("status") == "active" else "active"
    _safe_db_call(db.set_model_status, None, picked.get("id"), new_status)
    print(f"Model {picked.get('name')} => {new_status}")
    input("Press Enter to continue...")


def _show_recent_logs(state: dict) -> None:
    alerts_log = _safe_db_call(db.get_recent_alerts, [], hours=72, limit=10)
    open_trades = _safe_db_call(db.get_open_trades, [], limit=10)
    print("\nRecent alerts:")
    for a in alerts_log[:10]:
        print(f"• {_fmt_datetime(a.get('alerted_at'))} | {a.get('pair')} | {a.get('model_name')} | tier {a.get('tier')} | valid {a.get('valid')}")
    print("\nOpen trades:")
    for t in open_trades[:10]:
        print(f"• {_fmt_datetime(t.get('logged_at'))} | {t.get('pair')} | {t.get('model_id')} | entry {t.get('entry_price')}")
    state["recent_trades"] = alerts_log
    input("Press Enter to continue...")


def show_dashboard() -> None:
    """Interactive CLI dashboard prioritizing bot health and performance over live price polling."""
    state = _load_dashboard_state()
    while True:
        _render_dashboard(state)
        choice = input("\nChoose action: ").strip()
        BOT_STATE["last_run_time"] = _utc_now_str()

        if choice == "1":
            print("Launching interactive backtest...")
            summary = run_backtest()
            if summary:
                state["backtest_summary"] = summary
            input("Backtest finished. Press Enter to continue...")
        elif choice == "2":
            _refresh_specific_pair_price(state)
        elif choice == "3":
            _toggle_model()
        elif choice == "4":
            _show_recent_logs(state)
        elif choice == "5":
            _refresh_watched_pairs(state)
        elif choice == "6":
            BOT_STATE["status"] = "Paused" if BOT_STATE["status"] == "Running" else "Running"
        elif choice == "0":
            _save_dashboard_state(state)
            print("Exiting dashboard.")
            return
        else:
            print("Unknown choice.")
            time.sleep(0.6)

        _save_dashboard_state(state)


def main():
    # Ensure DB tables exist on startup
    try:
        db.setup_db()
        log.info("DB ready")
    except Exception as e:
        log.error(f"DB setup failed: {e}")

    app = Application.builder().token(TOKEN).build()

    # ── Core navigation ───────────────────────────────
    app.add_handler(CommandHandler("start",       commands.start))
    app.add_handler(CommandHandler("home",        commands.start))
    app.add_handler(CommandHandler("scan",        commands.scan))
    app.add_handler(CommandHandler("guide",       commands.guide))
    app.add_handler(CommandHandler("stats",       stats.stats_cmd))
    app.add_handler(CommandHandler("discipline",  stats.discipline_cmd))
    app.add_handler(CommandHandler("result",      stats.result_cmd))
    app.add_handler(CommandHandler("create_model",wizard.wiz_start))
    app.add_handler(CommandHandler("backtest",    commands.backtest))

    # ── Model wizard (ConversationHandler — must be first) ──
    app.add_handler(wizard.build_wizard_handler())

    # ── Callback routers ──────────────────────────────
    app.add_handler(CallbackQueryHandler(commands.handle_nav,       pattern="^nav:"))
    app.add_handler(CallbackQueryHandler(commands.handle_model_cb,  pattern="^model:"))
    app.add_handler(CallbackQueryHandler(commands.handle_scan_cb,   pattern="^scan:"))
    app.add_handler(CallbackQueryHandler(commands.handle_backtest_cb, pattern="^backtest:"))
    app.add_handler(CallbackQueryHandler(alerts.handle_alert_response, pattern="^alert:"))

    # ── Scanner job ───────────────────────────────────
    app.job_queue.run_repeating(
        alerts.run_scanner,
        interval=SCANNER_INTERVAL,
        first=15,
        name="scanner"
    )

    app.job_queue.run_daily(
        scheduler.send_morning_briefing,
        time=datetime.time(hour=7, minute=0, tzinfo=datetime.timezone.utc),
        name="morning_briefing",
    )
    app.job_queue.run_daily(
        scheduler.send_session_open,
        time=datetime.time(hour=8, minute=0, tzinfo=datetime.timezone.utc),
        name="london_open",
    )
    app.job_queue.run_daily(
        scheduler.send_session_open,
        time=datetime.time(hour=13, minute=0, tzinfo=datetime.timezone.utc),
        name="ny_open",
    )
    app.job_queue.run_daily(
        scheduler.send_weekly_review_prompt,
        time=datetime.time(hour=17, minute=0, tzinfo=datetime.timezone.utc),
        days=(6,),
        name="weekly_review",
    )
    app.job_queue.run_monthly(
        scheduler.send_monthly_report,
        when=datetime.time(hour=0, minute=5, tzinfo=datetime.timezone.utc),
        day=1,
        name="monthly_report",
    )

    log.info("🤖 Bot started — polling")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].lower() in {"backtest", "--backtest", "-b"}:
        run_backtest()
    elif len(sys.argv) > 1 and sys.argv[1].lower() in {"dashboard", "--dashboard", "-d"}:
        show_dashboard()
    else:
        main()
