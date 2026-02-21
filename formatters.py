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
    return f"⚙️ *{m['name']}*\nPair `{m['pair']}` TF `{m['timeframe']}`\nPrice `{fmt_price(price) if price else '-'}`\n{rules}`"


def fmt_alert(setup, model, scored, risk_pct, risk_usd, at_capacity=False, max_concurrent=3, correlation_warning=None, reentry=False):
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


def fmt_perps_home(active_models: list, recent_setups: list, session: str, time_wat: str) -> str:
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
