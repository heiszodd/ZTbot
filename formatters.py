from config import VIOLATION_LABELS, TIER_RISK


# ── Symbols ───────────────────────────────────────────
BULL = "🟢"
BEAR = "🔴"
WARN = "⚠️"
INFO = "ℹ️"
TICK = "✅"
CROSS = "❌"
DOT  = "•"


def _tier_line(tier, risk_pct):
    icons = {"A": "🏆", "B": "🥈", "C": "🥉"}
    return f"{icons.get(tier,'?')} Tier {tier} — {risk_pct}% risk"


def _score_line(raw, modifier_total, final, threshold):
    mod = f" {'+' if modifier_total>=0 else ''}{modifier_total:.1f}" if modifier_total != 0 else ""
    return f"{raw:.1f}{mod} = {final} (min {threshold})"


def _rules_block(model_rules, scored):
    passed_ids = {r["id"] for r in scored["passed_rules"]}
    lines = []
    for rule in model_rules:
        icon = TICK if rule["id"] in passed_ids else CROSS
        tag  = " [REQ]" if rule.get("mandatory") else ""
        lines.append(f"  {icon} {rule['name']}{tag}  +{rule['weight']}")
    return "\n".join(lines)


def _modifier_block(modifiers):
    if not modifiers:
        return "  none"
    lines = []
    for m in modifiers:
        sign = "+" if m["value"] >= 0 else ""
        lines.append(f"  {sign}{m['value']:+.1f}  {m['label']}")
    return "\n".join(lines)


# ── Alert messages ────────────────────────────────────
def fmt_alert(setup, model, scored):
    tier     = scored["tier"]
    tier_str = _tier_line(tier, scored["risk_pct"])
    c_warn   = f"\n{WARN} LOW CONVICTION — size 0.5% max\n" if tier == "C" else ""
    dir_icon = BULL if setup.get("direction") == "BUY" else BEAR

    modifiers = _modifier_block(scored["modifiers"])
    rules     = _rules_block(model["rules"], scored)

    return (
        f"{'━'*26}\n"
        f"🚨 SETUP ALERT\n"
        f"{'━'*26}\n"
        f"Model:    {model['name']}\n"
        f"Pair:     {setup['pair']}  {model['timeframe']}\n"
        f"Session:  {scored['session']}\n"
        f"Dir:      {dir_icon} {setup.get('direction','')}\n"
        f"{'━'*26}\n"
        f"{tier_str}{c_warn}\n"
        f"Score:    {_score_line(scored['raw_score'], scored['modifier_total'], scored['final_score'], model.get('tier_c', 5.5))}\n"
        f"Vol:      {scored['vol_label']}\n"
        f"HTF:      {scored['htf_label']}\n"
        f"{'━'*26}\n"
        f"Rules:\n{rules}\n"
        f"{'━'*26}\n"
        f"Modifiers:\n{modifiers}\n"
        f"{'━'*26}\n"
        f"SL:  {setup.get('sl')}\n"
        f"TP:  {setup.get('tp')}\n"
        f"RR:  1:{setup.get('rr')}\n"
        f"{'━'*26}\n"
        f"Did you take this trade?"
    )


def fmt_invalidation(reason, pair, model_name):
    return (
        f"{WARN} SETUP INVALIDATED\n"
        f"{'─'*22}\n"
        f"Model:  {model_name}\n"
        f"Pair:   {pair}\n"
        f"Reason: {reason}"
    )


# ── Command responses ─────────────────────────────────
def fmt_start():
    return (
        "📡 Trading Intelligence Bot\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "Scoring pipeline:\n"
        "  ① Mandatory gate  (Sweep · OB · Session)\n"
        "  ② News blackout   (≤30 min → block)\n"
        "  ③ Raw score       (rule weights)\n"
        "  ④ Flat modifiers  (ATR vol · HTF)\n"
        "  ⑤ Tier A/B/C     (risk sizing)\n"
        "\n"
        "Sessions (UTC):\n"
        "  Asia     23:00 – 08:00\n"
        "  London   08:00 – 16:00\n"
        "  Overlap  12:00 – 16:00\n"
        "  NY       13:00 – 21:00\n"
        "\n"
        "/help — all commands\n"
        "/menu — quick access"
    )


def fmt_help():
    return (
        "📖 Commands\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "Models\n"
        "  /models        — list all models\n"
        "  /create_model  — build a new model\n"
        "  /activate  ID  — activate a model\n"
        "  /deactivate ID — deactivate\n"
        "\n"
        "Scanning\n"
        "  /scan PAIR     — manual scan (e.g. /scan EURUSD)\n"
        "  /alerts        — recent alert log\n"
        "\n"
        "Performance\n"
        "  /stats         — 30-day P&L summary\n"
        "  /discipline    — violation log + score\n"
        "  /regime        — session/regime breakdown\n"
        "\n"
        "System\n"
        "  /status        — health check\n"
        "  /menu          — quick button menu\n"
        "  /help          — this list"
    )


def fmt_status(session, db_ok, active_models):
    db_icon = TICK if db_ok else CROSS
    return (
        f"🟢 System Status\n"
        f"{'─'*22}\n"
        f"Session:        {session}\n"
        f"DB:             {db_icon}\n"
        f"Active models:  {active_models}\n"
        f"Mandatory gate: {TICK}\n"
        f"News blackout:  {TICK} 30 min\n"
        f"HTF check:      {TICK} 1H + 4H\n"
        f"Scanner:        {TICK} every 15 min"
    )


def fmt_models(models):
    if not models:
        return (
            "No models yet.\n"
            "Use /create_model to build one."
        )
    icon = {True: "🟢", False: "⚪"}
    lines = ["⚙️ Models\n" + "─"*22]
    for m in models:
        active = m["status"] == "active"
        mandatory_count = sum(1 for r in m["rules"] if r.get("mandatory"))
        lines.append(
            f"{icon[active]} {m['name']}\n"
            f"   {m['pair']} · {m['timeframe']} · {m['session']}\n"
            f"   Rules: {len(m['rules'])} ({mandatory_count} mandatory)\n"
            f"   Tiers: A≥{m['tier_a']} B≥{m['tier_b']} C≥{m['tier_c']}\n"
            f"   ID: {m['id']}"
        )
    return "\n\n".join(lines)


def fmt_model_detail(m):
    lines = [
        f"⚙️ {m['name']}\n" + "─"*22,
        f"Pair:      {m['pair']}",
        f"Timeframe: {m['timeframe']}",
        f"Session:   {m['session']}",
        f"Bias:      {m['bias']}",
        f"Status:    {m['status']}",
        f"Tiers:     A≥{m['tier_a']} (2%)  B≥{m['tier_b']} (1%)  C≥{m['tier_c']} (0.5%)",
        "",
        "Rules:",
    ]
    for r in m["rules"]:
        tag  = " [MANDATORY]" if r.get("mandatory") else ""
        lines.append(f"  {DOT} {r['name']}{tag}  +{r['weight']}")
    return "\n".join(lines)


def fmt_stats(row, tiers, sessions):
    if not row or not row["total"]:
        return "No trades logged in the last 30 days."

    total = row["total"] or 0
    wins  = row["wins"]  or 0
    wr    = round((wins / total) * 100, 1) if total else 0

    lines = [
        "📊 30-Day Performance\n" + "─"*22,
        f"Trades:     {total}",
        f"Win rate:   {wr}%",
        f"Total R:    {row['total_r']}R",
        f"Avg R:      {row['avg_rr']}R",
        "",
        "By Tier:",
    ]
    for t in tiers:
        tr = t["total"] or 0
        tw = t["wins"]  or 0
        twr = round((tw/tr)*100,1) if tr else 0
        lines.append(f"  Tier {t['tier']}  {twr}%  ({tr} trades)  {t['total_r']}R")

    lines += ["", "By Session:"]
    for s in sessions:
        sr = s["total"] or 0
        sw = s["wins"]  or 0
        swr = round((sw/sr)*100,1) if sr else 0
        lines.append(f"  {s['session']:<10} {swr}%  ({sr} trades)")

    return "\n".join(lines)


def fmt_discipline(score, violations):
    bar_filled = int(score / 10)
    bar = "█" * bar_filled + "░" * (10 - bar_filled)
    state = "Excellent" if score >= 90 else "Good" if score >= 75 else "Fair" if score >= 60 else "Poor"

    lines = [
        "🛡️ Discipline Report\n" + "─"*22,
        f"Score:  {score}/100  [{bar}]  {state}",
        "",
        "Scoring rules:",
        f"  {TICK} Clean trade      +{2}",
        f"  {WARN} Minor (V2,V5)    −5",
        f"  {CROSS} Major (V1,V3,V4) −10",
    ]

    if violations:
        lines += ["", f"Recent violations ({len(violations)}):"]
        for v in violations[:10]:
            major = v["violation"] in ("V1","V3","V4")
            tag   = "MAJOR" if major else "MINOR"
            lines.append(
                f"  {CROSS if major else WARN} {v['violation']} [{tag}]  {v['pair']}\n"
                f"      {VIOLATION_LABELS.get(v['violation'], '')}\n"
                f"      {v['logged_at'].strftime('%Y-%m-%d %H:%M')}"
            )
    else:
        lines += ["", f"{TICK} No violations in the last 30 days."]

    lines += [
        "",
        "All violation types:",
    ]
    for code, label in VIOLATION_LABELS.items():
        major = code in ("V1","V3","V4")
        pen   = "−10 MAJOR" if major else "−5 MINOR"
        lines.append(f"  {code}  {label}  [{pen}]")

    return "\n".join(lines)


def fmt_scan_result(pair, scored, model):
    if not scored["valid"]:
        return (
            f"🔍 Scan: {pair}\n"
            f"{'─'*22}\n"
            f"{CROSS} Invalidated\n"
            f"Reason: {scored['invalid_reason']}"
        )
    if not scored["tier"]:
        return (
            f"🔍 Scan: {pair}\n"
            f"{'─'*22}\n"
            f"Score: {scored['final_score']} — below Tier C ({model.get('tier_c',5.5)})\n"
            f"No alert."
        )
    return (
        f"🔍 Scan: {pair}\n"
        f"{'─'*22}\n"
        f"{TICK} Score: {scored['final_score']} → Tier {scored['tier']}\n"
        f"Risk: {scored['risk_pct']}%\n"
        f"Alert queued."
    )


def fmt_alert_log(alerts):
    if not alerts:
        return "No alerts in the last 24 hours."
    lines = ["📋 Recent Alerts\n" + "─"*22]
    for a in alerts:
        valid_str = f"Tier {a['tier']}" if a["valid"] and a["tier"] else "INVALIDATED"
        lines.append(
            f"{TICK if a['valid'] else CROSS} {a['pair']}  {valid_str}"
            f"  score={a['score']}\n"
            f"   {a['alerted_at'].strftime('%H:%M')}  {a.get('reason','') or ''}"
        )
    return "\n\n".join(lines)
