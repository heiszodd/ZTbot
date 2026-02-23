import datetime
import json
import logging
import os
import sys
import time
from pathlib import Path

import db
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, filters
)

import prices as px
from config import SCANNER_INTERVAL, WAT
from handlers import commands, alerts, wizard, stats, scheduler, news_handler, degen_handler, degen_wizard, wallet_handler, demo_handler, ca_handler, chart_handler, simulator_handler, risk_handler
from engine import phase_engine, session_journal, regime_detector, notification_filter, session_checklist
from degen import wallet_tracker
from engine import run_backtest
from engine.degen import dev_tracker, exit_planner, narrative_detector
from engine.degen.auto_scanner import run_auto_scanner, run_watchlist_scanner

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

DASHBOARD_STATE_FILE = Path(".cache/dashboard_state.json")
DASHBOARD_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
BACKTEST_SUMMARY_FILE = Path("backtest_summary.json")


MODEL_DESCRIPTIONS = {
    "FVG Basic": "Fair value gap continuation model with basic displacement filters.",
    "Sweep Reversal": "Liquidity sweep + market structure reversal confirmation.",
    "OB Confluence": "Order-block reaction aligned with session and directional bias.",
    "FVG + OB Filter": "FVG entries gated by nearby OB confluence zones.",
    "Breaker Block": "Breaker-block continuation model after failed OBs.",
}


# NOTE: Dashboard globals are intentionally simple and JSON-serializable.
bot_status = {
    "started_at": time.time(),
    "status": "Running",
    "last_activity": None,
    "active_models": [],
    "last_warning": None,
}
recent_trades = []
open_positions = []
last_backtest = {}
system_health = {
    "api_calls_today": 0,
    "warnings": "No proxy issues",
}


def _wat_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).astimezone(WAT)


def _wat_now_str() -> str:
    return _wat_now().strftime("%Y-%m-%d %H:%M:%S WAT")


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
        bot_status["last_warning"] = f"DB: {exc}"
        return default


def _load_dashboard_state() -> dict:
    if not DASHBOARD_STATE_FILE.exists():
        return {
            "bot_status": bot_status,
            "recent_trades": [],
            "open_positions": [],
            "backtest_summary": {},
            "model_detection_counts": {},
            "system_health": system_health,
            "last_dashboard_opened": _wat_now_str(),
        }
    try:
        return json.loads(DASHBOARD_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {
            "bot_status": bot_status,
            "recent_trades": [],
            "open_positions": [],
            "backtest_summary": {},
            "model_detection_counts": {},
            "system_health": system_health,
            "last_dashboard_opened": _wat_now_str(),
        }


def _save_dashboard_state(state: dict) -> None:
    state["last_dashboard_opened"] = _wat_now_str()
    DASHBOARD_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    BACKTEST_SUMMARY_FILE.write_text(json.dumps(state.get("backtest_summary", {}), indent=2), encoding="utf-8")


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


def clear_screen() -> None:
    # RAILWAY FIX: avoid os.system('clear') because TERM may be unavailable.
    # Move cursor to home + clear full screen using ANSI escapes.
    print("\033[H\033[J", end="")


def _keep_alive_loop(heartbeat_seconds: int = 1800) -> None:
    """
    Keep the primary process alive for Railway/background environments.
    """
    while True:
        # RAILWAY FIX: low CPU sleep + optional proof-of-life heartbeat.
        time.sleep(heartbeat_seconds)
        # Uncomment this line if you want a heartbeat every 30 minutes in Railway logs.
        # print(f"Heartbeat WAT: {_wat_now_str()}")


# Backward-compatible alias for any internal calls/tests still using the old name.
_clear_screen = clear_screen


def _render_section(title: str) -> None:
    print(f"\n{'=' * 20} {title} {'=' * 20}")


def _render_dashboard(state: dict) -> None:
    clear_screen()
    now = time.time()
    status = state.get("bot_status", bot_status)
    uptime = _fmt_duration(now - float(status.get("started_at", now)))

    open_trades = _safe_db_call(db.get_open_trades, [], limit=10)
    all_models = _safe_db_call(db.get_all_models, [])

    recent_closed = _safe_db_call(db.get_recent_alerts, [], hours=168, limit=10)
    trade_log = state.get("recent_trades") or recent_closed or []
    perf = _compute_performance(trade_log)

    print("🚀 ZTbot Interactive Dashboard (No default live prices)")
    print("-" * 64)
    print(f"🕒 {_wat_now_str()}")

    _render_section("🤖 Bot Status")
    active_model_names = status.get("active_models") or [m.get("name") for m in all_models if m.get("status") == "active"]
    active_txt = ", ".join(active_model_names) if active_model_names else "None"
    started_wat = datetime.datetime.fromtimestamp(float(status.get("started_at", now)), tz=datetime.timezone.utc).astimezone(WAT).strftime("%I:%M %p WAT")
    print(f"Status            : {status.get('status', 'Running')}")
    print(f"Active model(s)   : {active_txt}")
    print(f"Last activity     : {status.get('last_activity') or 'N/A'}")
    print(f"Uptime            : {uptime} (Running since {started_wat})")

    _render_section("📈 Performance Overview")
    pf = "∞" if perf["profit_factor"] == float("inf") else f"{perf['profit_factor']:.2f}"
    print(f"Total Trades      : {perf['total']} (W {perf['wins']} | L {perf['losses']} | BE {perf['breakeven']})")
    print(f"Winrate           : {perf['winrate']:.2f}%")
    print(f"Average RR        : {perf['avg_rr']:.2f}")
    print(f"Profit Factor     : {pf}")
    print(f"Net PnL % (R~%)   : {perf['net_pnl_pct']:.2f}%")
    print(f"Streaks           : Max Win {perf['max_win_streak']} | Max Loss {perf['max_loss_streak']}")

    _render_section("📌 Open Positions")
    if not open_trades:
        print("No open positions.")
    else:
        for t in open_trades[:8]:
            position_status = "pending" if str(t.get("status", "")).lower() == "pending" else "open"
            print(
                f"• {t.get('pair','N/A'):<8} | Entry Time {_fmt_datetime(t.get('logged_at')):<16} "
                f"| Model {t.get('model_id','N/A'):<12} | Status {position_status}"
            )

    _render_section("🕘 Recent Activity")
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

    _render_section("🧠 Active Models")
    if not all_models:
        fallback_models = [
            {"name": "FVG Basic", "status": "active"},
            {"name": "Sweep Reversal", "status": "active"},
            {"name": "OB Confluence", "status": "inactive"},
        ]
        all_models = fallback_models
    model_counts = state.get("model_detection_counts", {})
    for idx, model in enumerate(all_models[:10], start=1):
        name = model.get("name", "Unknown")
        model_status = model.get("status", "inactive")
        detections = model_counts.get(name, 0)
        print(f"{idx}. {name:<18} - {model_status.title():<8} | last setups: {detections}")

    _render_section("🧪 Backtest Summary")
    bt = state.get("backtest_summary") or {}
    if not bt:
        print("No backtest summary cached yet. Run one via quick action #1.")
    else:
        print(f"Pair/TF/Range     : {bt.get('pair','N/A')} {bt.get('timeframe','N/A')} {bt.get('range','N/A')}")
        print(f"Setups/W/L        : {bt.get('total_setups',0)} / {bt.get('wins',0)} / {bt.get('losses',0)}")
        print(f"Winrate / Avg RR  : {bt.get('winrate',0):.2f}% / {bt.get('avg_rr',0):.2f}")
        print(f"Most Win Session  : {bt.get('best_day','N/A')} ({bt.get('wins', 0)} wins tracked)")
        print(f"Most Loss Session : {bt.get('worst_day','N/A')} ({bt.get('losses', 0)} losses tracked)")

    _render_section("🛡️ System Health")
    health = px.get_api_health()
    system = state.get("system_health", system_health)
    cache_marker = "Yes" if health.get("cache_files", 0) else "No"
    cache_update = "Never"
    cache_files = sorted(Path(health.get("cache_dir", ".")).glob("*.json"))
    if cache_files:
        cache_update = datetime.datetime.fromtimestamp(cache_files[-1].stat().st_mtime, tz=datetime.timezone.utc).astimezone(WAT).strftime("%Y-%m-%d %H:%M WAT")
    last_call = health.get("last_api_call_ts")
    last_call_fmt = _fmt_datetime(datetime.datetime.fromtimestamp(last_call, tz=datetime.timezone.utc).astimezone(WAT)) if last_call else "Never"
    print(f"Cache status       : BTCUSDT cached: {cache_marker}, last update: {cache_update}")
    print(f"API calls today    : {system.get('api_calls_today', health.get('api_call_count', 0))}")
    print(f"Last API fetch     : {last_call_fmt}")
    print(f"Errors/Warnings    : {health.get('last_api_error') or status.get('last_warning') or system.get('warnings')}")

    _render_section("📋 Menu Options")
    print("1) Run Backtest")
    print("2) Price Check (disabled in dashboard mode)")
    print("3) Toggle Model")
    print("4) View Logs")
    print("5) Exit")


def _refresh_specific_pair_price(state: dict) -> None:
    _ = state
    print("Live price checks are disabled in dashboard mode.")
    print("Use the dedicated Prices screen in Telegram for on-demand quotes.")
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
    print("\nLast log lines from bot.log:\n")
    log_file = Path("bot.log")
    if not log_file.exists():
        print("bot.log not found yet.")
        input("Press Enter to continue...")
        return
    lines = log_file.read_text(encoding="utf-8").splitlines()
    for line in lines[-20:]:
        print(line)

    alerts_log = _safe_db_call(db.get_recent_alerts, [], hours=72, limit=10)
    state["recent_trades"] = alerts_log[:10]
    input("Press Enter to continue...")


def show_dashboard() -> None:
    """
    Interactive CLI dashboard.

    IMPORTANT: This dashboard does NOT fetch or display live prices by default.
    The only permitted live price call is explicit menu option #2.
    """
    state = _load_dashboard_state()
    state.setdefault("bot_status", bot_status)
    state.setdefault("system_health", system_health)

    interactive = sys.stdin.isatty()

    # Optional one-off startup action for non-interactive deploy environments.
    run_backtest_on_boot = os.getenv("RUN_BACKTEST", "").strip().lower() == "true"
    if run_backtest_on_boot:
        print("RUN_BACKTEST=true detected: running one startup backtest...")
        log.info("RUN_BACKTEST=true -> executing one startup backtest")
        summary = run_backtest()
        if summary:
            state["backtest_summary"] = summary
            log.info("Startup backtest summary updated: %s", summary)
        _save_dashboard_state(state)

    if interactive:
        while True:
            print("Refreshing dashboard...")
            state["system_health"]["api_calls_today"] = int(px.get_api_health().get("api_call_count", 0))
            state["bot_status"]["last_activity"] = _wat_now_str()
            _render_dashboard(state)
            choice = input("\nChoose action: ").strip()

            if choice == "1":
                print("Checking cache before backtest fetch...")
                print("Skipping fetch — using cache when available (engine uses use_cache=True).")
                log.info("Backtest requested from dashboard")
                summary = run_backtest()
                if summary:
                    state["backtest_summary"] = summary
                    state["recent_trades"] = state.get("recent_trades", [])
                    log.info("Backtest summary updated: %s", summary)
                input("Backtest finished. Press Enter to continue...")
            elif choice == "2":
                _refresh_specific_pair_price(state)
            elif choice == "3":
                _toggle_model()
            elif choice == "4":
                _show_recent_logs(state)
            elif choice == "5":
                _save_dashboard_state(state)
                print("Exiting dashboard.")
                return
            else:
                print("Unknown choice.")
                time.sleep(0.6)

            _save_dashboard_state(state)
    else:
        # RAILWAY FIX: print dashboard once in non-interactive mode (no log spam loop).
        state["system_health"]["api_calls_today"] = int(px.get_api_health().get("api_call_count", 0))
        state["bot_status"]["last_activity"] = _wat_now_str()
        _render_dashboard(state)
        print("Interactive actions disabled (stdin is not a TTY).")
        _save_dashboard_state(state)


async def keepalive_job(context):
    try:
        with db.get_conn():
            pass
        log.debug("Keepalive ping OK")
    except Exception as e:
        log.warning(f"Keepalive failed: {e}")


async def post_init(application):
    import config

    log.info("━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("Bot starting up...")

    gemini = config.init_gemini()
    if gemini:
        log.info("✅ Gemini: connected")
    else:
        log.warning("⚠️ Gemini: NOT available - chart analysis disabled")

    log.info("📊 Binance: market data ✅ ready (no key needed for OHLCV)")

    if config.CRYPTOPANIC_TOKEN:
        log.info("✅ CryptoPanic: token loaded")
    else:
        log.info("ℹ️ CryptoPanic: not set (optional)")

    try:
        db._ensure_pool()
        log.info("✅ Database: connected")
    except Exception as e:
        log.error(f"❌ Database: {e}")

    log.info("━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("Bot ready.")


def main():
    for var in ["BOT_TOKEN", "CHAT_ID"]:
        if not os.getenv(var):
            print(f"FATAL: {var} is not set", flush=True)
            sys.exit(1)
    if not (os.getenv("DB_URL") or os.getenv("DATABASE_URL")):
        print("FATAL: DB_URL or DATABASE_URL is not set", flush=True)
        sys.exit(1)

    print("ZTbot main.py starting", flush=True)

    try:
        db.init_pool()
        db.setup_db()
        db.ensure_intelligence_tables()
        log.info("DB ready")
    except Exception as e:
        log.error(f"DB setup failed: {e}")
        raise

    app = (
        Application.builder()
        .token(os.getenv("BOT_TOKEN"))
        .post_init(post_init)
        .build()
    )

    # ── Core navigation ───────────────────────────────
    app.add_handler(CommandHandler("start",       commands.start))
    app.add_handler(CommandHandler("home",        commands.start))
    app.add_handler(CommandHandler("perps",       commands.perps_home))
    app.add_handler(CommandHandler("degen",       degen_handler.degen_home))
    app.add_handler(CommandHandler("demo",        demo_handler.demo_cmd))
    app.add_handler(CommandHandler("demo_perps",  demo_handler.demo_perps_cmd))
    app.add_handler(CommandHandler("demo_degen",  demo_handler.demo_degen_cmd))
    app.add_handler(CommandHandler("scan",        commands.scan))
    app.add_handler(CommandHandler("guide",       commands.guide))
    app.add_handler(CommandHandler("stats",       stats.stats_cmd))
    app.add_handler(CommandHandler("discipline",  stats.discipline_cmd))
    app.add_handler(CommandHandler("result",      stats.result_cmd))
    app.add_handler(CommandHandler("create_model", wizard.start_wizard))
    app.add_handler(CommandHandler("backtest",    commands.backtest))
    app.add_handler(CommandHandler("create_degen_model", degen_wizard.start_wizard))
    app.add_handler(CommandHandler("journal",     commands.journal_cmd))
    app.add_handler(CommandHandler("news",        news_handler.news_cmd))
    app.add_handler(CommandHandler("charttest",   chart_handler.chart_api_test_cmd))
    app.add_handler(CommandHandler("simulator",   simulator_handler.simulator_cmd))

    # ── Conversations (must be before generic callback routers) ──
    chart_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.PHOTO | filters.Document.IMAGE, chart_handler.chart_received_first)],
        states={
            chart_handler.CHART_WAITING_LTF: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, chart_handler.chart_received_ltf),
            ],
        },
        fallbacks=[CallbackQueryHandler(chart_handler.handle_chart_cancel, pattern="^chart:cancel$")],
        per_message=False,
        per_chat=True,
        allow_reentry=False,
    )
    app.add_handler(chart_conv, group=0)

    app.add_handler(wizard.build_wizard_handler(), group=0)
    app.add_handler(CallbackQueryHandler(degen_wizard.start_wizard, pattern="^dgwiz:start$"), group=0)

    # Degen wizard callbacks
    app.add_handler(CallbackQueryHandler(degen_wizard.handle_degen_wizard_cb, pattern="^dgwiz:"), group=0)
    # Perps wizard callbacks
    app.add_handler(CallbackQueryHandler(wizard.handle_wizard_cb, pattern="^wizard:"), group=0)

    app.add_handler(commands.build_goal_handler())
    app.add_handler(commands.build_budget_handler())

    # ── Callback routers ──────────────────────────────
    app.add_handler(CallbackQueryHandler(commands.handle_nav, pattern="^nav:"), group=0)
    app.add_handler(CallbackQueryHandler(simulator_handler.handle_sim_cb, pattern="^sim:"), group=0)
    app.add_handler(CallbackQueryHandler(commands.handle_model_cb, pattern="^model:"), group=0)
    app.add_handler(CallbackQueryHandler(chart_handler.handle_chart_cb, pattern="^chart:"), group=0)
    app.add_handler(CallbackQueryHandler(alerts.handle_pending_cb, pattern="^pending:"), group=0)
    app.add_handler(CallbackQueryHandler(demo_handler.handle_demo_cb, pattern="^demo:"), group=0)
    app.add_handler(CallbackQueryHandler(ca_handler.handle_ca_cb, pattern="^ca:"), group=0)
    app.add_handler(CallbackQueryHandler(degen_handler.handle_scan_action, pattern=r"^scan:(whitelist|ignore|ape|full):"), group=0)
    app.add_handler(CallbackQueryHandler(commands.handle_scan_cb, pattern="^scan:"))
    app.add_handler(CallbackQueryHandler(commands.handle_backtest_cb, pattern="^backtest:"))
    app.add_handler(CallbackQueryHandler(alerts.handle_alert_response, pattern="^alert:"))
    app.add_handler(CallbackQueryHandler(stats.handle_journal_cb, pattern="^journal:"))
    app.add_handler(CallbackQueryHandler(news_handler.handle_news_cb, pattern="^news:"))
    app.add_handler(CallbackQueryHandler(degen_handler.handle_degen_model_cb, pattern="^degen_model:"))
    app.add_handler(CallbackQueryHandler(wallet_handler.handle_wallet_cb, pattern="^wallet:"))
    app.add_handler(CallbackQueryHandler(degen_handler.handle_scanner_settings_action, pattern="^scanner:"), group=0)
    app.add_handler(CallbackQueryHandler(degen_handler.handle_degen_cb, pattern="^degen_journal:"))
    app.add_handler(CallbackQueryHandler(degen_handler.handle_degen_cb, pattern="^degen:"))
    app.add_handler(CallbackQueryHandler(risk_handler.handle_risk_cb, pattern="^(risk:|nav:risk|nav:checklist|nav:notif_filter|filter:toggle:|filter:override:|nav:regime)"), group=0)
    app.add_handler(wallet_handler.build_add_wallet_handler())
    app.add_handler(MessageHandler(filters.Regex(r"^(?i:scan\s+).+"), degen_handler.handle_manual_scan), group=0)
    app.add_handler(MessageHandler(filters.Regex(r"^(0x[a-fA-F0-9]{40}|[1-9A-HJ-NP-Za-km-z]{32,44})$"), degen_handler.handle_manual_scan), group=0)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, degen_wizard.handle_degen_name), group=0)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, demo_handler.handle_demo_risk_input))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ca_handler.handle_ca_message), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, risk_handler.handle_risk_text), group=0)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, stats.handle_journal_text))

    # ── Scanner job ───────────────────────────────────
    app.job_queue.run_repeating(phase_engine.run_phase_engine, interval=300, first=60, name="phase_engine")
    app.job_queue.run_repeating(phase_engine.alert_lifecycle_job, interval=300, first=90, name="alert_lifecycle")
    app.job_queue.run_daily(regime_detector.run_regime_detection, time=datetime.time(hour=5, minute=30, tzinfo=datetime.timezone.utc), name="regime_detection")
    app.job_queue.run_repeating(phase_engine.model_grading_job, interval=86400, first=3600, name="model_grading")
    app.job_queue.run_daily(session_journal.record_session_data, time=datetime.time(hour=7, minute=5, tzinfo=datetime.timezone.utc), name="session_journal")
    app.job_queue.run_daily(session_checklist.run_pre_session_checklist, time=datetime.time(hour=6, minute=30, tzinfo=datetime.timezone.utc), name="pre_session_checklist")
    app.job_queue.run_daily(notification_filter.run_pattern_analysis, time=datetime.time(hour=20, minute=0, tzinfo=datetime.timezone.utc), days=(6,), name="pattern_analysis")
    app.job_queue.run_repeating(phase_engine.expire_old_phases_job, interval=3600, first=390, name="phase_expiry")
    app.job_queue.run_repeating(alerts.run_scanner, interval=300, first=240, name="scanner")
    app.job_queue.run_repeating(alerts.run_pending_checker, interval=30, first=330, name="pending_checker")

    app.job_queue.run_repeating(news_handler.news_briefing_job, interval=600, first=420, name="news_briefing")
    app.job_queue.run_repeating(news_handler.news_signal_job, interval=300, first=150, name="news_signal")
    app.job_queue.run_repeating(wallet_tracker.wallet_monitor_job, interval=120, first=450, name="wallet_monitor")
    app.job_queue.run_repeating(demo_handler.demo_monitor_job, interval=30, first=360, name="demo_monitor")
    app.job_queue.run_repeating(ca_handler.ca_monitor_job, interval=120, first=180, name="ca_monitor")

    app.job_queue.run_repeating(run_auto_scanner, interval=1800, first=120, name="auto_degen_scanner")
    app.job_queue.run_repeating(run_watchlist_scanner, interval=900, first=270, name="watchlist_scanner")

    app.job_queue.run_repeating(dev_tracker.run_dev_wallet_monitor, interval=600, first=210, name="dev_wallet_monitor")
    app.job_queue.run_repeating(narrative_detector.update_narrative_momentum, interval=1800, first=300, name="narrative_momentum")
    app.job_queue.run_repeating(exit_planner.monitor_exit_triggers, interval=300, first=120, name="degen_exit_monitor")

    log.info("🤖 Bot started — polling")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("FATAL: Bot crashed — full traceback below", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
