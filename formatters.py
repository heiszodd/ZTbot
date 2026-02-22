from datetime import datetime, timezone, timedelta
from config import VIOLATION_LABELS, WAT
from prices import fmt_price


def _tier_badge(tier): return {"A": "🏆 TIER A", "B": "🥈 TIER B", "C": "🥉 TIER C"}.get(tier, tier)
def _direction_icon(direction): return "🟢 LONG" if direction == "BUY" else "🔴 SHORT"
def _bar(value, max_val=100, width=10):
    f = int((value / max_val) * width) if max_val else 0
    return "█" * max(0, min(width, f)) + "░" * max(0, width - max(0, min(width, f)))


def _wat_now():
    return datetime.now(timezone.utc).astimezone(WAT)


def fmt_home(active_models, live_alerts):
    now_wat = _wat_now().strftime("%H:%M")
    return (
        "📊 *Mission Control Dashboard*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 Current time: {now_wat} WAT\n"
        "🌍 London Open — 08:00 UTC (09:00 WAT)\n"
        "🗽 NY Open — 13:00 UTC (14:00 WAT)\n"
        "🌏 Asia Open — 23:00 UTC (00:00 WAT)\n"
        "🔀 Overlap — 13:00–16:00 UTC (14:00–17:00 WAT)\n"
        f"Active models: `{len(active_models)}`\n"
        f"Recent setups: `{len(live_alerts)}`"
    )


def fmt_models(models):
    return "⚙️ *My Models*\n" + "\n".join([f"• {m['name']} ({m['pair']})" for m in models])


def fmt_model_detail(m, price=None):
    rules = "\n".join([f"• {'🔒' if r.get('mandatory') else '🔓'} {r['name']} +{r['weight']}" for r in m.get('rules', [])])
    badge = "🏆 *MASTER MODEL*\n" if str(m.get("id", "")).startswith("MM_") else ""
    return f"{badge}⚙️ *{m['name']}*\nPair `{m['pair']}` TF `{m['timeframe']}`\nPrice `{fmt_price(price) if price else '-'}`\n{rules}`"


def fmt_alert(setup, model, scored, risk_pct, risk_usd, at_capacity=False, max_concurrent=3, correlation_warning=None, reentry=False, pending_duration=None, pending_checks=None):
    passed, failed = scored.get('passed_rules', []), scored.get('failed_rules', [])
    lines = ["🚨 *Setup Alert*", "━━━━━━━━━━━━━━━━━━━━━━━━", f"📌 *{model['name']}* · `{setup['pair']}`", f"🧭 {_direction_icon(setup.get('direction', 'BUY'))}", f"💹 Entry `{fmt_price(setup.get('entry'))}`", f"🛑 SL `{fmt_price(setup.get('sl'))}` · 🎯 TP `{fmt_price(setup.get('tp'))}`", "", "🧠 *Confluence*"]
    if scored.get('htf_conflict'): lines.insert(2, "⚠️ *HTF Conflict: Score reduced by `-1.5`*")
    for r in passed: lines.append(f"✅ {r['name']} `+{r['weight']}`")
    for r in failed: lines.append(f"❌ {r['name']} `+{r['weight']}`")
    total = len(passed) + len(failed)
    lines.append(f"`{len(passed)}/{total}` rules passed")
    vol_mod = next((m['value'] for m in scored.get('modifiers', []) if 'Volatility' in m['label']), 0)
    htf_mod = next((m['value'] for m in scored.get('modifiers', []) if 'HTF' in m['label']), 0)
    lines.append(f"Volatility: `{vol_mod:+.1f}`")
    lines.append(f"HTF: `{htf_mod:+.1f}`")
    lines.append(f"*Final Score:* `{scored.get('final_score', 0):.2f}`")
    if scored.get('htf_confirmed'): lines.append("✅ HTF Confirmed — 1H and 4H aligned")
    elif scored.get('htf_conflict'): lines.append("❌ HTF Conflict — trading against higher timeframe")
    else: lines.append("⚠️ HTF Partial — only one timeframe aligned")
    if setup.get('false_breakout'): lines.append("⚠️ Possible false breakout detected — confirm close before entering")
    if setup.get('volume_spike'): lines.append(f"📊 Volume spike detected — `{setup.get('volume_spike_x', 0)}x` average — confirms institutional activity")
    if setup.get('daily_bias'): lines.append(f"📅 Daily Bias: {setup.get('daily_bias')}")
    if correlation_warning: lines.append(correlation_warning)
    if at_capacity: lines.append(f"⚠️ Max concurrent trades reached ({max_concurrent}).")
    if reentry: lines.append("♻️ Re-entry zone revisited after prior skip.")
    if pending_duration is not None:
        checks = pending_checks if pending_checks is not None else 0
        lines.append(f"⏳ Watched for {pending_duration} before confirming — {checks} criteria checks passed")
    return "\n".join(lines)


def fmt_invalidation(reason, pair, model_name): return f"⚠️ *Setup Invalidated*\n{model_name} {pair}\n{reason}"
def fmt_help(): return "🧭 *Guide*\nUse menu buttons."
def fmt_discipline(score, violations): return f"🛡️ *Discipline* `{score}/100`"
def fmt_alert_log(alerts): return "🔔 *Live Alerts*\n" + "\n".join([f"{a.get('pair')} {a.get('score')}" for a in alerts])
def fmt_status(session, db_ok, active_models, prices_ok):
    now_wat = _wat_now().strftime("%H:%M")
    return f"⚡ *System Status*\n🕐 Current time: {now_wat} WAT\n📅 Session: {session}\nDB {'OK' if db_ok else 'ERR'}"
def fmt_backtest(model, result, days): return f"🧪 *Backtest* {model['name']} {days}d"


def fmt_stats_overview(row):
    total = row.get('total') or 0
    wins = row.get('wins') or 0
    wr = round((wins / total) * 100, 1) if total else 0
    return f"📈 *30-Day Performance*\nTrades `{total}`\nWin rate `{wr}%` [{_bar(wr)}]\nTotal R `{row.get('total_r') or 0}`"


def fmt_stats_tiers(tiers): return "📊 *By Tier*"
def fmt_stats_sessions(sessions): return "🌍 *By Session*"
def fmt_stats(row, tiers, sessions, *args, **kwargs): return "\n\n".join([fmt_stats_overview(row), fmt_stats_tiers(tiers), fmt_stats_sessions(sessions)])


def fmt_rolling_10(trades):
    if not trades: return "📈 *Rolling 10*\nNo closed trades yet."
    blocks = ''.join('▓' if t.get('result') == 'TP' else '░' for t in trades)
    wins = sum(1 for t in trades if t.get('result') == 'TP')
    total = len(trades)
    wr = round((wins / total) * 100, 1) if total else 0
    total_r = round(sum(float(t.get('rr') or 0) for t in trades), 2)
    first = sum(float(t.get('rr') or 0) for t in trades[:5])
    last = sum(float(t.get('rr') or 0) for t in trades[5:])
    trend = '📈 Improving' if last > first else '📉 Declining' if last < first else '➡️ Flat'
    return f"📈 *Rolling 10*\n{blocks}\nWin rate: `{wr}%` · Total R: `{total_r}` · {trend}"


def fmt_heatmap(hourly_data):
    rows = {int(x['hour']): x for x in hourly_data}
    scored = []
    for h in range(24):
        d = rows.get(h, {"wins": 0, "total": 0, "total_r": 0})
        t = int(d.get('total') or 0)
        wr = round((int(d.get('wins') or 0) / t) * 100, 1) if t else 0
        r = float(d.get('total_r') or 0)
        scored.append((h, wr, r))
    top = {x[0] for x in sorted(scored, key=lambda x: x[2], reverse=True)[:3]}
    bot = {x[0] for x in sorted(scored, key=lambda x: x[2])[:3]}
    out = ["🕐 *Time-of-Day Heatmap*", "━━━━━━━━━━━━━━━━━━━━━━━━"]
    for h, wr, r in scored:
        icon = '🔥' if h in top else '❄️' if h in bot else '•'
        out.append(f"`{h:02d}` {icon} WR `{wr}%` | R `{r:+.2f}`")
    return "\n".join(out)


def fmt_landing() -> str:
    return (
        "👋 Welcome to ZTbot\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Your personal trading intelligence system.\n\n"
        "Choose your section:"
    )


def fmt_perps_home(active_models: list, recent_setups: list, session: str, time_wat: str, pending_setups: list | None = None) -> str:
    pending_setups = pending_setups or []
    lines = [
        "📈 Perps Trading",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🕐 {time_wat} WAT   📡 {session}",
        "",
        f"⚙️ Active Models ({len(active_models)})",
    ]
    if active_models:
        for m in active_models[:5]:
            lines.append(f"• {m.get('name')} — {m.get('pair')} {m.get('timeframe')}")
    else:
        lines.append("No active models — tap Models to create one")

    lines.extend(["", f"⏳ *Pending Setups* ({len(pending_setups)})"])
    if not pending_setups:
        lines.append("No setups building right now")
    else:
        for p in pending_setups[:5]:
            pct = float(p.get('score_pct') or 0)
            bar = _bar(min(100, pct), 100, 10)
            lines.append(f"• {p.get('pair')} {p.get('timeframe')} [{bar}] {pct:.0f}%")

    lines.append("")
    lines.append(f"🚨 Recent Setups ({len(recent_setups)} in last 2h)")
    if recent_setups:
        for a in recent_setups[:3]:
            lines.append(f"• {a.get('pair')} {a.get('tier')} {a.get('direction')} {a.get('alerted_at')}")
    else:
        lines.append("No setups in the last 2 hours")
    return "\n".join(lines)


def fmt_degen_home(active_models: list, tracked_wallets: list, scanner_active: bool, finds_today: int, alerts_today: int) -> str:
    lines = [
        "🎰 Degen Zone",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "⚠️ High risk — only use what you can lose",
        "",
        f"📡 Scanner: {'🟢 Active' if scanner_active else '⚫ Inactive'}",
        f"⚙️ Active Degen Models ({len(active_models)})",
    ]
    if active_models:
        for m in active_models[:3]:
            lines.append(f"• {m.get('name')}")
    else:
        lines.append("No models active — tap Models to create one")
    lines.extend(["", f"🐋 Tracking {len(tracked_wallets)} Wallets"])
    if tracked_wallets:
        for w in tracked_wallets[:3]:
            label = w.get('label') or f"{w.get('address','')[:6]}...{w.get('address','')[-4:]}"
            lines.append(f"• {w.get('tier_label','🔍')} {label}")
    else:
        lines.append("No wallets tracked — tap Wallets to add one")
    lines.extend(["", f"🆕 New Finds Today: {finds_today} tokens scanned", f"🚨 Alerts Today: {alerts_today} degen alerts sent"])
    return "\n".join(lines)


def fmt_pending_setup(setup: dict, classification: dict, score_result: dict) -> str:
    score_pct = float(classification.get("score_pct", 0) or 0)
    filled = round(max(0, min(100, score_pct)) / 10)
    bar = "█" * filled + "░" * (10 - filled)
    passed = classification.get("passed_rules", []) or []
    failed = classification.get("failed_rules", []) or []
    mandatory_failed = classification.get("mandatory_failed", []) or []
    closest = classification.get("closest_rules", []) or []
    trend = setup.get("trend", "➡️ Score unchanged")
    levels = setup.get("levels", {})

    lines = [
        "⏳ *PENDING SETUP*",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"⚙️ Model:  {setup.get('model_name', '-')}",
        f"🪙 Pair:   {setup.get('pair', '-')}   {setup.get('timeframe', '-')}",
        f"📊 Bias:   {'📈 Bullish' if (setup.get('direction') or '').upper() == 'BUY' else '📉 Bearish'}",
        f"⏰ First seen: {setup.get('first_seen_label', '-')}",
        f"🔄 Last check: {setup.get('last_check_label', '-')}  (check #{setup.get('check_count', 1)})",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "📊 *Score Progress*",
        f"   [{bar}] {score_pct:.0f}% of threshold",
        f"   Score:     {score_result.get('score', score_result.get('final_score', 0)):.2f} / {setup.get('min_score_threshold', 0):.2f}",
        f"   Missing:   {classification.get('missing_score', 0):.2f} more points needed",
        f"   Rules:     {classification.get('rules_passed_count', len(passed))}/{classification.get('rules_total_count', len(passed)+len(failed))} passing",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"✅ *Criteria Met* ({len(passed)})",
    ]
    for r in passed:
        lines.append(f"   ✅ {r.get('name')}   +{r.get('weight', 0)}pts")

    lines.extend(["", "━━━━━━━━━━━━━━━━━━━━━━━━", f"❌ *Criteria Missing* ({len(failed)})"])
    for r in failed:
        lines.append(f"   ❌ {r.get('name')}   ({r.get('weight', 0)}pts missing)")

    if mandatory_failed:
        lines.extend(["", "🔒 *Required Rules Not Met*"])
        for r in mandatory_failed:
            nm = r.get('name') if isinstance(r, dict) else r
            lines.append(f"   🔒 {nm} — REQUIRED — setup cannot complete without this")

    lines.extend(["", "━━━━━━━━━━━━━━━━━━━━━━━━", "👀 *Watch For*", "These rules would complete the setup:"])
    for r in closest[:3]:
        lines.append(f"   ⚡ {r.get('name')}   +{r.get('weight', 0)}pts  needs to flip to pass")

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "💹 *Current Levels*",
        f"   Price:  ${levels.get('price', setup.get('entry_price', 0))}",
        f"   Entry:  ${setup.get('entry_price', levels.get('entry', 0))}",
        f"   SL:     ${setup.get('sl', 0)}",
        f"   TP1:    ${setup.get('tp1', 0)}",
        f"   TP2:    ${setup.get('tp2', 0)}",
        f"   TP3:    ${setup.get('tp3', 0)}",
        "",
        trend,
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "⏳ Monitoring... updates every 30s",
    ])
    return "\n".join(lines)
def _fmt_age(minutes: int) -> str:
    m = int(minutes or 0)
    if m < 60:
        return f"{m} min"
    if m < 1440:
        return f"{m/60:.1f} hours"
    return f"{m/1440:.1f} days"


def fmt_ca_report(token_data, risk, moon, dev, curve, auth, nlp, net) -> str:
    if token_data.get("not_found"):
        return (
            "⚠️ Token not found on any DEX\n"
            "This token may be:\n"
            "• Too new to have a pair created yet\n"
            "• Not yet listed on any DEX\n"
            "• An invalid contract address\n"
            "• A scam with no liquidity\n\n"
            "RugCheck data shown if available."
        )
    name = token_data.get("name") or "Unknown"
    symbol = token_data.get("symbol") or "?"
    addr = token_data.get("address") or "N/A"
    chain = token_data.get("chain") or token_data.get("chain_guess") or "unknown"
    curve_line = ""
    if curve.get("is_pumpfun"):
        bars = "█" * int((curve.get("curve_pct", 0) / 10)) + "░" * (10 - int(curve.get("curve_pct", 0) / 10))
        curve_line = f"\n🌱 Pump.fun bonding curve: [{bars}] {curve.get('curve_pct',0):.1f}%"
    flags = risk.get("risk_flags") or []
    green = moon.get("bull_factors") or []
    exits = moon.get("smart_exits") or {}
    links = [f"[DexScreener]({token_data.get('url')})" if token_data.get("url") else None, f"[RugCheck](https://rugcheck.xyz/tokens/{addr})"]
    if token_data.get("pump_url"):
        links.append(f"[Pump.fun]({token_data.get('pump_url')})")
    if token_data.get("twitter"):
        links.append(f"[Twitter]({token_data.get('twitter')})")
    if token_data.get("telegram"):
        links.append(f"[Telegram]({token_data.get('telegram')})")
    links = " | ".join([x for x in links if x])
    return (
        f"[{risk.get('risk_level','RISK')}] CA REPORT\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 *{name}* ({symbol})\n"
        f"📋 `{addr}`\n"
        f"🔗 Chain: {chain}   DEX: {token_data.get('dex') or 'Not listed'}\n"
        f"⏱ Age: {_fmt_age(token_data.get('token_age_minutes') or 0)}{curve_line}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💰 *Market Data*\n"
        f"   Price:        {fmt_price(token_data.get('price_usd') or 0)}\n"
        f"   Market Cap:   ${float(token_data.get('mcap') or 0):,.0f}\n"
        f"   Liquidity:    ${float(token_data.get('liquidity_usd') or 0):,.0f}\n"
        f"   FDV:          ${float(token_data.get('fdv') or 0):,.0f}\n"
        f"   Volume 1h:    ${float(token_data.get('volume_1h') or 0):,.0f}\n"
        f"   1h Change:    {float(token_data.get('price_change_1h') or 0):+.2f}%\n"
        f"   24h Change:   {float(token_data.get('price_change_24h') or 0):+.2f}%\n"
        f"   Buys/Sells:   {int(token_data.get('buys_1h') or 0)}/{int(token_data.get('sells_1h') or 0)} last hour\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👥 *Holders*\n"
        f"   Count:         {int(token_data.get('holder_count') or 0)}\n"
        f"   Top holder:    {float(token_data.get('top1_holder_pct') or 0):.2f}%\n"
        f"   Top 5 total:   {float(token_data.get('top5_holders_pct') or 0):.2f}%\n"
        "\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔐 *Contract Safety*\n"
        f"   Mint revoked:    {'✅ Yes' if token_data.get('mint_revoked') else '❌ NO — devs can print'}\n"
        f"   Freeze revoked:  {'✅ Yes' if token_data.get('freeze_revoked') else '❌ NO — devs can freeze'}\n"
        f"   LP locked:       {float(token_data.get('lp_locked_pct') or 0):.1f}%\n"
        f"   LP burned:       {'✅ Yes' if token_data.get('lp_burned') else '❌ No'}\n"
        f"   Verified:        {'✅ Yes' if token_data.get('verified') else '❌ No'}\n"
        f"   Honeypot:        {'💀 DETECTED' if token_data.get('is_honeypot') else '✅ Safe'}\n"
        f"   RugCheck score:  {int(token_data.get('rugcheck_score') or 0)}/1000\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👨‍💻 *Developer*\n"
        f"   Wallet:      `{(token_data.get('dev_wallet') or 'N/A')[:8]}...`\n"
        f"   Age:         {int(token_data.get('dev_wallet_age_days') or 0)} days\n"
        f"   Reputation:  {dev.get('reputation_label')}\n"
        f"   Supply held: {dev.get('supply_held_pct',0):.2f}%\n"
        f"   Past rugs:   {dev.get('past_rugs',0)}\n"
        f"   Network:     {net.get('network_label')}\n\n"
        "📝 *Description Analysis*\n"
        f"   Quality:   {nlp.get('description_quality')}\n"
        f"   {', '.join(nlp.get('red_flags') or ['No text red flags'])}\n\n"
        "📊 *Volume Authenticity*\n"
        f"   {auth.get('authenticity_label') or auth.get('label') or 'N/A'}\n\n"
        f"⚠️ *Risk Factors* ({len(flags)} triggered)\n"
        f"{' ; '.join(flags) if flags else 'None'}\n\n"
        f"✅ *Green Flags* ({len(green)} found)\n"
        f"{' ; '.join(green) if green else 'None'}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎯 *Scores*\n"
        f"   🛡️ Risk Score:  {risk.get('risk_score')}/100   {risk.get('risk_level')}\n"
        f"   🚀 Moon Score:  {moon.get('moon_score')}/100   {moon.get('label')}\n"
        f"   📊 Confluence:  {(moon.get('confluence') or {}).get('contributing_categories',0)}/6 categories\n\n"
        "💡 *Verdict*\n"
        "   High-volatility degen setup. Size carefully and respect exits.\n"
        "   Allocation recommendation: keep risk small and predefined.\n\n"
        "🎯 *If entering:*\n"
        f"   Entry:   {fmt_price(token_data.get('price_usd') or 0)}\n"
        f"   SL:      {fmt_price(exits.get('sl') or 0)}\n"
        f"   TP1:     {fmt_price(exits.get('tp1') or 0)}\n"
        f"   TP2:     {fmt_price(exits.get('tp2') or 0)}\n"
        f"   TP3:     {fmt_price(exits.get('tp3') or 0)}\n"
        f"   ⏰ Time stop: exit if no move in {int(exits.get('time_stop_minutes') or 30)} minutes\n\n"
        f"🔗 {links}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ DEGEN — high risk only"
    )


def fmt_chart_analysis_single(result: dict) -> str:
    if not result.get("chart_detected"):
        reason = result.get("reason", result.get("error", "Unknown error"))
        return f"❌ *Chart not detected*\n{reason}\n\nPlease send a clear candlestick chart screenshot."

    bias = result.get("bias", {})
    setup = result.get("setup", {})
    structure = result.get("market_structure", {})
    trend = result.get("trend", {})
    liq = result.get("liquidity", {})
    ctx = result.get("current_price_context", {})

    action_emoji = {
        "buy": "📈", "sell": "📉", "wait": "⏳", "avoid": "🚫"
    }.get(result.get("action", "wait"), "⏳")

    bias_emoji = "📈" if bias.get("direction") == "bullish" else "📉" if bias.get("direction") == "bearish" else "➡️"
    confidence_emoji = "🟢" if bias.get("confidence") == "high" else "🟡" if bias.get("confidence") == "medium" else "🔴"

    confluence = int(result.get("confluence_score", 0) or 0)
    confluence = max(0, min(10, confluence))
    confluence_bar = "█" * confluence + "░" * (10 - confluence)

    lines = [
        f"📊 *CHART ANALYSIS*",
        f"━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    if result.get("pair_estimate") and result["pair_estimate"] != "unknown":
        lines.append(f"🪙 *{result['pair_estimate']}*   ⏱ {result.get('timeframe_estimate', 'Unknown TF')}")
    else:
        lines.append(f"⏱ Timeframe: {result.get('timeframe_estimate', 'Unknown')}")

    lines += [
        f"",
        f"━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📈 *Trend*",
        f"   Direction:  {trend.get('direction','').capitalize()}",
        f"   Strength:   {trend.get('strength','').capitalize()}",
        f"   {trend.get('description','')}",
        f"",
        f"🏗️ *Market Structure*",
        f"   Type:       {structure.get('type','').replace('_',' ').capitalize()}",
    ]

    if structure.get("structure_break"):
        lines.append(f"   ⚡ Structure Break: {structure.get('structure_break_direction','').capitalize()}")

    lines.append(f"   {structure.get('description','')}")

    key_levels = result.get("key_levels", [])
    if key_levels:
        lines += [f"", f"🎯 *Key Levels*"]
        for level in key_levels[:5]:
            icon = "🔴" if level.get("type") == "resistance" else "🟢" if level.get("type") == "support" else "🔵"
            lines.append(f"   {icon} {level.get('type','').replace('_',' ').capitalize()}: {level.get('price','')}  ({level.get('strength','')})")
            if level.get("description"):
                lines.append(f"      _{level['description']}_")

    obs = result.get("order_blocks", [])
    if obs:
        lines += [f"", f"📦 *Order Blocks*"]
        for ob in obs[:3]:
            icon = "🟢" if ob.get("direction") == "bullish" else "🔴"
            respected = "✅ Respected" if ob.get("respected") else "❓ Untested"
            lines.append(f"   {icon} {ob.get('direction','').capitalize()} OB — {ob.get('price_zone','')}  {respected}")

    fvgs = result.get("fair_value_gaps", [])
    if fvgs:
        lines += [f"", f"⚡ *Fair Value Gaps*"]
        for fvg in fvgs[:3]:
            icon = "🟢" if fvg.get("direction") == "bullish" else "🔴"
            filled = "✅ Filled" if fvg.get("filled") else "⬜ Open"
            lines.append(f"   {icon} {fvg.get('direction','').capitalize()} FVG — {fvg.get('price_zone','')}  {filled}")

    if liq:
        lines += [
            f"",
            f"💧 *Liquidity*",
            f"   Buy side:   {liq.get('buy_side','')}",
            f"   Sell side:  {liq.get('sell_side','')}",
        ]
        if liq.get("recent_sweep"):
            lines.append(f"   ⚡ Recent sweep: {liq.get('sweep_direction','').capitalize()} side swept")

    lines += [
        f"",
        f"📍 *Price Context*",
        f"   Zone:       {ctx.get('in_premium_or_discount','').capitalize()}",
        f"   Near level: {'Yes' if ctx.get('near_key_level') else 'No'}",
    ]
    if ctx.get("key_level_description"):
        lines.append(f"   {ctx['key_level_description']}")

    lines += [
        f"",
        f"━━━━━━━━━━━━━━━━━━━━━━━━",
        f"{bias_emoji} *Bias*",
        f"   Direction:   {bias.get('direction','').capitalize()}",
        f"   Confidence:  {confidence_emoji} {bias.get('confidence','').capitalize()}",
        f"   {bias.get('reasoning','')}",
    ]

    if setup.get("setup_present"):
        lines += [
            f"",
            f"━━━━━━━━━━━━━━━━━━━━━━━━",
            f"🎯 *Setup Detected*",
            f"   Type:       {setup.get('setup_type','')}",
            f"   Entry zone: {setup.get('entry_zone','')}",
            f"   Condition:  {setup.get('entry_condition','')}",
            f"",
            f"💹 *Levels*",
            f"   SL:   {setup.get('stop_loss','')}",
            f"   TP1:  {setup.get('take_profit_1','')}",
            f"   TP2:  {setup.get('take_profit_2','')}",
            f"   TP3:  {setup.get('take_profit_3','')}",
            f"   RR:   {setup.get('risk_reward','')}",
            f"",
            f"❌ Invalidation: {setup.get('invalidation','')}",
        ]
    else:
        lines += [
            f"",
            f"⏳ *No complete setup detected*",
            f"   Wait for: {setup.get('entry_condition', 'Clearer price action')}",
        ]

    confluence_factors = result.get("confluence_factors", [])
    lines += [
        f"",
        f"━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 *Confluence: {confluence}/10*",
        f"[{confluence_bar}]",
    ]
    for factor in confluence_factors:
        lines.append(f"   ✅ {factor}")

    warnings = result.get("warnings", [])
    if warnings:
        lines += [f"", f"⚠️ *Warnings*"]
        for w in warnings:
            lines.append(f"   ⚠️ {w}")

    lines += [
        f"",
        f"━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💡 *Summary*",
        f"{result.get('summary','')}",
        f"",
        f"━━━━━━━━━━━━━━━━━━━━━━━━",
        f"{action_emoji} *Action: {result.get('action','wait').upper()}*",
    ]

    return "\n".join(lines)


def fmt_chart_analysis_mtf(result: dict) -> str:
    if not result.get("htf") or not result.get("ltf"):
        return "❌ *MTF analysis failed* — could not read both charts."

    htf = result["htf"]
    ltf = result["ltf"]
    alignment = result.get("alignment", {})
    setup = result.get("setup", {})

    align_emoji = {
        "perfect": "🟢", "good": "🟡", "partial": "🟡", "conflicting": "🔴"
    }.get(alignment.get("alignment_quality", "partial"), "🟡")

    action_emoji = {
        "buy": "📈", "sell": "📉", "wait": "⏳", "avoid": "🚫"
    }.get(result.get("action", "wait"), "⏳")

    urgency_emoji = {
        "immediate": "🚨", "prepare": "⚡", "watch": "👀", "ignore": "😴"
    }.get(result.get("urgency", "watch"), "👀")

    quality_emoji = {
        "A+": "🌕", "A": "⭐", "B": "👍", "C": "👎", "wait": "⏳"
    }.get(setup.get("setup_quality", "wait"), "⏳")

    confluence = int(result.get("confluence_score", 0) or 0)
    confluence = max(0, min(10, confluence))
    confluence_bar = "█" * confluence + "░" * (10 - confluence)

    lines = [
        f"📐 *MULTI-TIMEFRAME ANALYSIS*",
        f"━━━━━━━━━━━━━━━━━━━━━━━━",
        f"",
        f"🔭 *HTF — {htf.get('timeframe_estimate','Higher TF')}*",
        f"   Trend:      {'📈' if htf.get('trend_direction')=='bullish' else '📉'} {htf.get('trend_direction','').capitalize()}  ({htf.get('trend_strength','')})",
        f"   Structure:  {htf.get('market_structure','').replace('_',' ').capitalize()}",
        f"   Bias:       {'📈' if htf.get('bias')=='bullish' else '📉'} {htf.get('bias','').capitalize()}",
        f"   Zone:       {htf.get('premium_discount','').capitalize()}",
        f"   {htf.get('bias_reasoning','')}",
    ]

    htf_levels = htf.get("key_levels", [])
    if htf_levels:
        lines.append(f"")
        lines.append(f"   📌 Key HTF Levels:")
        for level in htf_levels[:4]:
            icon = "🔴" if level.get("type") == "resistance" else "🟢" if level.get("type") == "support" else "🔵"
            lines.append(f"   {icon} {level.get('type','').replace('_',' ').capitalize()}: {level.get('price','')}  ({level.get('strength','')})")

    lines += [
        f"",
        f"━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🔬 *LTF — {ltf.get('timeframe_estimate','Lower TF')}*",
        f"   Trend:      {'📈' if ltf.get('trend_direction')=='bullish' else '📉'} {ltf.get('trend_direction','').capitalize()}",
        f"   Structure:  {ltf.get('market_structure','').replace('_',' ').capitalize()}",
    ]

    if ltf.get("structure_break"):
        lines.append(f"   ⚡ Structure Break: {ltf.get('structure_break_direction','').capitalize()}")

    ltf_obs = ltf.get("order_blocks", [])
    if ltf_obs:
        lines.append(f"")
        lines.append(f"   📦 LTF Order Blocks:")
        for ob in ltf_obs[:3]:
            icon = "🟢" if ob.get("direction") == "bullish" else "🔴"
            respected = "✅" if ob.get("respected") else "❓"
            lines.append(f"   {icon} {ob.get('direction','').capitalize()} OB — {ob.get('price_zone','')} {respected}")

    ltf_fvgs = ltf.get("fair_value_gaps", [])
    if ltf_fvgs:
        lines.append(f"")
        lines.append(f"   ⚡ LTF Fair Value Gaps:")
        for fvg in ltf_fvgs[:3]:
            icon = "🟢" if fvg.get("direction") == "bullish" else "🔴"
            filled = "✅ Filled" if fvg.get("filled") else "⬜ Open"
            lines.append(f"   {icon} {fvg.get('direction','').capitalize()} FVG — {fvg.get('price_zone','')} {filled}")

    if ltf.get("current_pattern"):
        lines.append(f"")
        lines.append(f"   🕯️ Current Pattern: {ltf['current_pattern']}")
    if ltf.get("entry_trigger"):
        lines.append(f"   ⚡ Entry Trigger: {ltf['entry_trigger']}")

    lines += [
        f"",
        f"━━━━━━━━━━━━━━━━━━━━━━━━",
        f"{align_emoji} *HTF/LTF Alignment: {alignment.get('alignment_quality','').capitalize()}*",
        f"{'✅ Aligned' if alignment.get('htf_ltf_aligned') else '❌ Not Aligned'}",
        f"{alignment.get('alignment_description','')}",
    ]

    lines += [
        f"",
        f"━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🎯 *Setup: {quality_emoji} {setup.get('setup_quality','N/A')}*",
    ]

    if setup.get("setup_present"):
        dir_emoji = "📈" if setup.get("direction") == "long" else "📉"
        lines += [
            f"   {dir_emoji} {setup.get('setup_type','')}",
            f"   Direction:  {setup.get('direction','').upper()}",
            f"   Entry zone: {setup.get('entry_zone','')}",
            f"   Condition:  {setup.get('entry_condition','')}",
            f"",
            f"💹 *Levels*",
            f"   SL:   {setup.get('stop_loss','')}",
            f"   Why:  {setup.get('stop_loss_reasoning','')}",
            f"   TP1:  {setup.get('take_profit_1','')}",
            f"   TP2:  {setup.get('take_profit_2','')}",
            f"   TP3:  {setup.get('take_profit_3','')}",
            f"   RR:   {setup.get('risk_reward','')}",
            f"",
            f"✅ Ideal entry: {setup.get('ideal_entry_description','')}",
            f"❌ Invalidation: {setup.get('invalidation','')}",
        ]
    else:
        lines.append(f"   ⏳ No complete setup — {setup.get('entry_condition','Wait for confirmation')}")

    factors = result.get("confluence_factors", [])
    missing = result.get("missing_confluence", [])
    lines += [
        f"",
        f"━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 *Confluence: {confluence}/10*",
        f"[{confluence_bar}]",
    ]
    for factor in factors:
        lines.append(f"   ✅ {factor}")
    if missing:
        lines.append(f"")
        lines.append(f"   *Missing:*")
        for m in missing[:3]:
            lines.append(f"   ❌ {m}")

    warnings = result.get("warnings", [])
    if warnings:
        lines += [f"", f"⚠️ *Warnings*"]
        for w in warnings:
            lines.append(f"   ⚠️ {w}")

    lines += [
        f"",
        f"━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🔭 HTF: {result.get('htf_summary','')}",
        f"",
        f"🔬 LTF: {result.get('ltf_summary','')}",
        f"",
        f"💡 {result.get('overall_summary','')}",
        f"",
        f"━━━━━━━━━━━━━━━━━━━━━━━━",
        f"{action_emoji} *Action: {result.get('action','wait').upper()}*   {urgency_emoji} {result.get('urgency','watch').capitalize()}",
    ]

    return "\n".join(lines)
