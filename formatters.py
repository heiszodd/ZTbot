from datetime import datetime, timezone
from config import VIOLATION_LABELS, TIER_RISK
from prices import fmt_price


def _tier_badge(tier):
    return {"A": "🏆 TIER A", "B": "🥈 TIER B", "C": "🥉 TIER C"}.get(tier, tier)

def _tier_risk(tier):
    return {"A": "2.0%", "B": "1.0%", "C": "0.5%"}.get(tier, "—")

def _direction_icon(direction):
    return "🟢 LONG" if direction == "BUY" else "🔴 SHORT"

def _status_icon(status):
    return "🟢 Active" if status == "active" else "⚫ Inactive"

def _bar(value, max_val=100, width=10):
    filled = int((value / max_val) * width)
    return "█" * filled + "░" * (width - filled)

def _time_ago(dt):
    if not dt: return ""
    diff = datetime.now(timezone.utc) - dt.replace(tzinfo=timezone.utc)
    s = int(diff.total_seconds())
    if s < 60: return f"{s}s ago"
    if s < 3600: return f"{s//60}m ago"
    return f"{s//3600}h ago"


# ── Welcome / Home ────────────────────────────────────
def fmt_welcome(active_count: int, alert_count: int) -> str:
    return (
        "📡  *Trading Intelligence Bot*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🟢  Active models:  *{active_count}*\n"
        f"🔔  Alerts today:   *{alert_count}*\n\n"
        "Scoring pipeline:\n"
        "  ① Mandatory gate  —  Sweep · OB · Session\n"
        "  ② News blackout   —  30 min window\n"
        "  ③ Raw score       —  rule weights\n"
        "  ④ Modifiers       —  ATR vol · HTF\n"
        "  ⑤ Tier A/B/C      —  auto risk sizing\n\n"
        "Choose an option below 👇"
    )


# ── Dashboard ─────────────────────────────────────────
def fmt_dashboard(active_models: list, live_alerts: list) -> str:
    updated_at = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    lines = [
        "📊  *Mission Control Dashboard*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"_Updated: {updated_at}_",
        "",
    ]

    # Active models
    lines.append(f"⚙️  *Active Models*  ({len(active_models)})")
    if active_models:
        for m in active_models:
            lines.append(f"  🟢  {m['name']}  —  {m['pair']} {m['timeframe']}")
    else:
        lines.append("  No active models. Create one below.")
    lines.append("")

    # Valid setups today
    lines.append(f"🔔  *Valid Setups Today*  ({len(live_alerts)})")
    if live_alerts:
        for a in live_alerts[:5]:
            tier = _tier_badge(a.get("tier", ""))
            lines.append(
                f"  {tier}  {a['pair']}  {_direction_icon(a.get('direction','BUY'))}\n"
                f"    Entry {fmt_price(a['entry'] or 0)}  ·  Score {a['score']}"
            )
    else:
        lines.append("  No valid setups in the last 12 hours.")

    lines += ["", "🧭  *Suggested Next Step*", "  1) Open Models", "  2) Activate one model", "  3) Run Manual Scan"]
    return "\n".join(lines)


# ── Models list ───────────────────────────────────────
def fmt_models_list(models: list) -> str:
    if not models:
        return (
            "⚙️  *My Models*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "You haven't created any models yet.\n\n"
            "Tap *➕ New Model* to launch the guided wizard."
        )
    lines = [
        "⚙️  *My Models*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    for m in models:
        mandatory = sum(1 for r in m["rules"] if r.get("mandatory"))
        optional  = len(m["rules"]) - mandatory
        lines.append(
            f"{'🟢' if m['status']=='active' else '⚫'}  *{m['name']}*\n"
            f"   {m['pair']} · {m['timeframe']} · {m['session']} · {m['bias']}\n"
            f"   {mandatory} mandatory · {optional} optional rules\n"
            f"   Tiers: A≥{m['tier_a']} · B≥{m['tier_b']} · C≥{m['tier_c']}"
        )
    return "\n\n".join(lines)


# ── Single model detail ───────────────────────────────
def fmt_model_detail(m: dict, price=None) -> str:
    rules_str = "\n".join(
        f"  {'🔒' if r.get('mandatory') else '🔓'}  {r['name']}  +{r['weight']}"
        for r in m["rules"]
    )
    max_score = round(sum(r["weight"] for r in m["rules"]) + 1.0, 1)
    return (
        f"⚙️  *{m['name']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Status:     {_status_icon(m['status'])}\n"
        f"Pair:       {m['pair']}\n"
        f"Timeframe:  {m['timeframe']}\n"
        f"Session:    {m['session']}\n"
        f"Bias:       {'📈' if m['bias']=='Bullish' else '📉'}  {m['bias']}\n"
        f"Price:      {fmt_price(price) if price is not None else '—'}\n\n"
        f"📋  *Rules*\n{rules_str}\n\n"
        f"🏆  *Tiers*\n"
        f"  Tier A  ≥{m['tier_a']}   →  2.0% risk\n"
        f"  Tier B  ≥{m['tier_b']}   →  1.0% risk\n"
        f"  Tier C  ≥{m['tier_c']}   →  0.5% risk\n\n"
        f"Max possible score:  {max_score}"
    )


# ── Alert message ─────────────────────────────────────
def fmt_alert(
    setup: dict,
    model: dict,
    scored: dict,
    risk_pct: float,
    risk_usd: float,
    at_capacity: bool = False,
    max_concurrent: int = 3,
    correlation_warning: str | None = None,
    reentry: bool = False,
) -> str:
    tier = scored["tier"]
    rules_str = "\n".join(
        f"  {'✅' if r['id'] in {x['id'] for x in scored['passed_rules']} else '❌'}  "
        f"{r['name']}{'  🔒' if r.get('mandatory') else ''}  +{r['weight']}"
        for r in model["rules"]
    )
    confluence = setup.get("confluence_count", len(scored.get("passed_rules") or []))
    low_conf_warn = "\n⚠️ Low confluence (<3 rules passing)." if confluence < 3 else ""
    reentry_line = "\n✅ Re-entry: price returned to previously skipped setup zone." if reentry else ""
    corr_line = f"\n{correlation_warning}" if correlation_warning else ""
    capacity_line = f"\n⚠️ Concurrent trade capacity reached ({max_concurrent})." if at_capacity else ""

    return (
        f"🚨 *SETUP ALERT*\n"
        f"{model['name']} | {setup['pair']} | {model['timeframe']}\n"
        f"{_direction_icon(setup.get('direction','BUY'))}\n\n"
        f"Entry: {fmt_price(setup.get('entry', 0))}\n"
        f"SL: {fmt_price(setup.get('sl', 0))}\n"
        f"TP: {fmt_price(setup.get('tp', 0))}\n"
        f"TP1 (1:1): {fmt_price(setup.get('tp1', 0))}\n"
        f"TP2 (1:2): {fmt_price(setup.get('tp2', 0))}\n"
        f"TP3 (1:3): {fmt_price(setup.get('tp3', 0))}\n"
        f"RR: 1:{setup.get('rr', 2)}\n"
        f"Tier: {tier}\n"
        f"Risk: {risk_pct:.2f}% (${risk_usd:.2f})\n"
        f"Session: {scored['session']}\n"
        f"Confluence: {confluence} rules{low_conf_warn}\n"
        f"Score: {scored['final_score']} (raw {scored['raw_score']:.1f}, mod {scored['modifier_total']:+.1f})"
        f"{corr_line}{capacity_line}{reentry_line}\n\n"
        f"📋 *Rules*\n{rules_str}\n\n"
        "Data only. Not financial advice."
    )


# ── Invalidation ──────────────────────────────────────
def fmt_invalidation(reason: str, pair: str, model_name: str) -> str:
    return (
        f"⚠️  *Setup Invalidated*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Model:  {model_name}\n"
        f"Pair:   {pair}\n"
        f"Reason: {reason}"
    )


# ── Live prices ───────────────────────────────────────
def fmt_prices(prices: dict) -> str:
    if not prices:
        return "❌  Could not fetch prices from Binance right now — please retry shortly."
    lines = [
        "💰  *Live Crypto Prices*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    for pair, price in prices.items():
        lines.append(f"  {pair:<12}  {fmt_price(price)}")
    lines += ["", f"_Updated: {datetime.now(timezone.utc).strftime('%H:%M UTC')}_"]
    return "\n".join(lines)


# ── Stats ─────────────────────────────────────────────
def fmt_stats_overview(row: dict) -> str:
    total = row.get("total") or 0
    wins  = row.get("wins")  or 0
    wr    = round((wins / total) * 100, 1) if total else 0
    bar   = _bar(wr)
    return (
        f"📈  *30-Day Performance*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Trades:    {total}\n"
        f"Win rate:  {wr}%  [{bar}]\n"
        f"Total R:   {row.get('total_r') or 0}R\n"
        f"Avg R:     {row.get('avg_rr') or 0}R"
    )


def fmt_stats_tiers(tiers: list) -> str:
    if not tiers:
        return "📊  *By Tier*\n\nNo trades logged yet."
    lines = ["📊  *Performance by Tier*", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━", ""]
    for t in tiers:
        tr  = t["total"] or 0
        tw  = t["wins"]  or 0
        twr = round((tw/tr)*100, 1) if tr else 0
        lines.append(
            f"{_tier_badge(t['tier'])}   {_tier_risk(t['tier'])}\n"
            f"  {twr}%  win rate  ·  {tr} trades  ·  {t['total_r']}R"
        )
    return "\n\n".join(lines)


def fmt_stats_sessions(sessions: list) -> str:
    if not sessions:
        return "🌍  *By Session*\n\nNo trades logged yet."
    lines = ["🌍  *Performance by Session*", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━", ""]
    for s in sessions:
        sr  = s["total"] or 0
        sw  = s["wins"]  or 0
        swr = round((sw/sr)*100, 1) if sr else 0
        bar = _bar(swr)
        lines.append(f"  {s['session']:<10}  {swr}%  [{bar}]  ({sr}t)")
    return "\n".join(lines)


# ── Discipline ────────────────────────────────────────
def fmt_discipline(score: int, violations: list) -> str:
    bar   = _bar(score)
    state = ("🟢 Excellent" if score >= 90 else "🟡 Good" if score >= 75
             else "🟠 Fair" if score >= 60 else "🔴 Poor")
    lines = [
        "🛡️  *Discipline Report*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"Score:  *{score}/100*  [{bar}]  {state}",
        "",
        "📋  *Scoring Rules*",
        "  ✅  Clean trade          +2",
        "  ⚠️   Minor violation (V2,V5)  −5",
        "  ❌  Major violation (V1,V3,V4)  −10",
        "",
    ]
    if violations:
        lines.append(f"🚨  *Recent Violations* ({len(violations)})")
        for v in violations[:8]:
            major = v["violation"] in ("V1","V3","V4")
            icon  = "❌" if major else "⚠️"
            lines.append(
                f"\n  {icon}  *{v['violation']}*  [{v['pair']}]\n"
                f"  {VIOLATION_LABELS.get(v['violation'], '')}\n"
                f"  _{v['logged_at'].strftime('%Y-%m-%d %H:%M')}_"
            )
    else:
        lines.append("✅  No violations in the last 30 days. Keep it up!")

    lines += [
        "",
        "📖  *All Violation Types*",
    ]
    for code, label in VIOLATION_LABELS.items():
        major = code in ("V1","V3","V4")
        pen   = "−10 MAJOR" if major else "−5 MINOR"
        lines.append(f"  {code}  {label}  [{pen}]")
    return "\n".join(lines)


# ── Alerts log ────────────────────────────────────────
def fmt_alerts_log(alerts: list) -> str:
    if not alerts:
        return (
            "🔔  *Live Alerts*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "No alerts in the last 24 hours."
        )
    lines = [
        "🔔  *Live Alerts*  (last 24h)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    for a in alerts:
        if a["valid"] and a["tier"]:
            lines.append(
                f"  {_tier_badge(a['tier'])}  {a['pair']}\n"
                f"  Entry {fmt_price(a['entry'] or 0)}  ·  Score {a['score']}\n"
                f"  _{_time_ago(a['alerted_at'])}_"
            )
        else:
            lines.append(
                f"  ⚫  {a['pair']}  INVALIDATED\n"
                f"  {a.get('reason','')}\n"
                f"  _{_time_ago(a['alerted_at'])}_"
            )
    return "\n\n".join(lines)


# ── Wizard steps ──────────────────────────────────────
def fmt_wiz_step(step: int, total: int, title: str, body: str) -> str:
    progress = "●" * step + "○" * (total - step)
    return (
        f"⚙️  *Model Wizard*  —  Step {step}/{total}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"_{progress}_\n\n"
        f"*{title}*\n\n"
        f"{body}"
    )


def fmt_wiz_rule_added(rules: list, max_score: float, warns: list) -> str:
    rules_str = "\n".join(
        f"  {'🔒' if r['mandatory'] else '🔓'}  {r['name']}  +{r['weight']}"
        for r in rules
    )
    warn_str = ("\n\n" + "\n".join(f"⚠️  {w}" for w in warns)) if warns else ""
    return (
        f"✅  Rule added!\n\n"
        f"📋  *Rules so far ({len(rules)}):*\n"
        f"{rules_str}\n\n"
        f"Max possible score:  *{max_score}*"
        f"{warn_str}\n\n"
        f"Add another rule or tap ✅ Done."
    )


def fmt_wiz_review(d: dict, max_score: float, tier_reach: list) -> str:
    rules_str = "\n".join(
        f"  {'🔒' if r['mandatory'] else '🔓'}  {r['name']}  +{r['weight']}"
        for r in d["rules"]
    )
    tiers_str = "\n".join(tier_reach)
    return (
        f"📋  *Review Your Model*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Name:       {d['name']}\n"
        f"Pair:       {d['pair']}\n"
        f"Timeframe:  {d['timeframe']}\n"
        f"Session:    {d['session']}\n"
        f"Bias:       {d['bias']}\n\n"
        f"📋  *Rules ({len(d['rules'])})*\n{rules_str}\n\n"
        f"🏆  *Tiers*\n{tiers_str}\n\n"
        f"Max score:  *{max_score}*\n\n"
        f"Confirm to save this model."
    )


def fmt_help() -> str:
    return (
        "🧭  *Step-by-Step App Guide*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*Step 1 — Create your model*\n"
        "• Tap *➕ New Model*\n"
        "• Follow the wizard prompts\n"
        "• Add mandatory + optional rules\n\n"
        "*Step 2 — Activate it*\n"
        "• Open *⚙️ Models*\n"
        "• Select your model\n"
        "• Tap *✅ Activate*\n\n"
        "*Step 3 — Backtest your model*\n"
        "• Run `/backtest <model_id> [days]`\n"
        "• Review win rate and average R\n\n"
        "*Step 4 — Scan market now*\n"
        "• Tap *🔍 Manual Scan*\n"
        "• Pick a pair to force a scan\n\n"
        "*Step 5 — Manage alerts*\n"
        "• Use Entered / Skipped / Watching\n"
        "• Track outcomes with `/result <id> TP|SL`\n\n"
        "*Step 6 — Improve performance*\n"
        "• Review *📊 Stats*\n"
        "• Audit behavior in *🛡️ Discipline*\n\n"
        "Need a reset? Tap *🏠 Dashboard* anytime."
    )



# ── Backward-compatible aliases used by handlers ─────
def fmt_home(active_models: list, live_alerts: list) -> str:
    return fmt_dashboard(active_models, live_alerts)


def fmt_models(models: list) -> str:
    return fmt_models_list(models)




def fmt_performance_advanced(summary: dict, expectancy_leader: dict | None, underperforming: list, consecutive_losses: int) -> str:
    total = int(summary.get("total") or 0)
    wins = int(summary.get("wins") or 0)
    win_rate = round((wins / total) * 100, 2) if total else 0.0
    avg_win = float(summary.get("avg_win_r") or 0.0)
    avg_loss = float(summary.get("avg_loss_r") or 0.0)
    loss_rate = 100 - win_rate
    expectancy = round((win_rate / 100 * avg_win) - (loss_rate / 100 * avg_loss), 3)

    leader_line = "n/a"
    if expectancy_leader:
        leader_line = f"{expectancy_leader.get('pair','n/a')} · {expectancy_leader.get('session','n/a')} · {expectancy_leader.get('model_id','n/a')} ({expectancy_leader.get('expectancy',0)}R)"

    under = "None"
    if underperforming:
        under = ", ".join(f"{x['bucket']} ({x['trades']} trades, {x['expectancy']}R)" for x in underperforming)

    return "\n".join([
        "📊 *Advanced Performance*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"Win rate: {win_rate}%",
        f"Total R: {summary.get('total_r') or 0}R",
        f"Average R: {summary.get('avg_r') or 0}R",
        f"Expectancy: {expectancy}R",
        f"Max drawdown: {summary.get('max_drawdown_r') or 0}R",
        f"Consecutive losses: {consecutive_losses}",
        "",
        f"Top model/session/pair expectancy: {leader_line}",
        f"Underperforming models (20+ trades, neg expectancy): {under}",
    ])


def fmt_stats(row: dict, tiers: list, sessions: list, summary: dict | None = None, expectancy_leader: dict | None = None, underperforming: list | None = None, consecutive_losses: int = 0) -> str:
    chunks = [fmt_stats_overview(row), fmt_stats_tiers(tiers), fmt_stats_sessions(sessions)]
    if summary is not None:
        chunks.append(fmt_performance_advanced(summary, expectancy_leader, underperforming or [], consecutive_losses))
    return "\n\n".join(chunks)


def fmt_alert_log(alerts: list) -> str:
    return fmt_alerts_log(alerts)


def fmt_status(session: str, db_ok: bool, active_models: int, prices_ok: bool) -> str:
    return (
        "⚡ *System Status*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Session:      `{session}`\n"
        f"Database:     {'✅ OK' if db_ok else '❌ Error'}\n"
        f"Price feed:   {'✅ OK' if prices_ok else '❌ Error'}\n"
        f"Active models:`{active_models}`"
    )



def fmt_backtest(model: dict, result: dict, days: int) -> str:
    return (
        f"🧪 *Backtest Result*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Model: *{model['name']}* (`{model['id']}`)\n"
        f"Pair: `{model['pair']}` · Window: `{days}d`\n\n"
        f"Trades: *{result['trades']}*\n"
        f"Wins/Losses: *{result['wins']}* / *{result['losses']}*\n"
        f"Win Rate: *{result['win_rate']}%*\n"
        f"Avg R: *{result['avg_rr']}R*"
    )
