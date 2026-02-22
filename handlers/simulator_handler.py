from collections import Counter
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import db
import engine
import prices as px
from config import CHAT_ID, SUPPORTED_PAIRS


def _is_authorized(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.id == CHAT_ID)


def _sim_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🧠 Create Model (Wizard)", callback_data="wizard:start")],
            [InlineKeyboardButton("🧪 Test Existing Model", callback_data="sim:test:start")],
            [InlineKeyboardButton("🏠 Back to Perps", callback_data="nav:perps_home")],
        ]
    )


def _tf_series(series_1m: list[float], tf: str) -> list[float]:
    if tf == "1m":
        return series_1m
    step = 5 if tf == "5m" else 15
    return [series_1m[i] for i in range(step - 1, len(series_1m), step)]


def _auto_htf_bias(series: list[float], tf: str) -> str:
    tf_to_min = {"1m": 1, "5m": 5, "15m": 15}
    tf_min = tf_to_min.get(tf, 1)
    bars_4h = max(2, int(240 / tf_min))
    if len(series) <= bars_4h:
        return "Bullish"
    return "Bullish" if series[-1] >= series[-bars_4h - 1] else "Bearish"


def _simulate_detailed(model: dict, prices: list[float], rr_target: float) -> dict:
    wins = losses = unresolved = 0
    no_setup = mandatory_failed = below_tier = 0
    direction_counts = Counter()
    tier_counts = Counter()
    passed_rule_counts = Counter()
    failed_rule_counts = Counter()
    mandatory_failed_counts = Counter()
    final_scores = []

    sl_pct = 0.003
    tp_pct = sl_pct * rr_target

    for i in range(30, len(prices) - 8, 3):
        setup = engine.build_live_setup(model, prices[: i + 1])
        if not setup.get("passed_rule_ids"):
            no_setup += 1
            continue

        scored = engine.score_setup(setup, model)
        if not scored.get("valid", True):
            mandatory_failed += 1
            for r in scored.get("mandatory_failed", []):
                mandatory_failed_counts[r] += 1
            continue
        if not scored.get("tier"):
            below_tier += 1
            continue

        direction = setup.get("direction", "BUY")
        direction_counts[direction] += 1
        tier_counts[scored["tier"]] += 1
        final_scores.append(float(scored.get("final_score") or 0.0))

        for r in scored.get("passed_rules", []):
            passed_rule_counts[r.get("name", "unknown")] += 1
        for r in scored.get("failed_rules", []):
            failed_rule_counts[r.get("name", "unknown")] += 1

        entry = prices[i]
        future = prices[i + 1 : i + 7]
        if direction == "BUY":
            hit_tp = (max(future) - entry) / entry >= tp_pct
            hit_sl = (entry - min(future)) / entry >= sl_pct
        else:
            hit_tp = (entry - min(future)) / entry >= tp_pct
            hit_sl = (max(future) - entry) / entry >= sl_pct

        if hit_tp and not hit_sl:
            wins += 1
        elif hit_sl:
            losses += 1
        else:
            unresolved += 1

    trades = wins + losses
    wr = (wins / trades * 100.0) if trades else 0.0
    expectancy_r = ((wins / trades) * rr_target - (losses / trades)) if trades else 0.0
    min_wr_for_positive = 100.0 / (rr_target + 1.0) * 100.0

    return {
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "unresolved": unresolved,
        "win_rate": wr,
        "expectancy_r": expectancy_r,
        "no_setup": no_setup,
        "mandatory_failed": mandatory_failed,
        "below_tier": below_tier,
        "direction_counts": direction_counts,
        "tier_counts": tier_counts,
        "passed_rule_counts": passed_rule_counts,
        "failed_rule_counts": failed_rule_counts,
        "mandatory_failed_counts": mandatory_failed_counts,
        "avg_final_score": (sum(final_scores) / len(final_scores)) if final_scores else 0.0,
        "min_wr_for_positive": min_wr_for_positive,
    }


def _top_items(counter: Counter, limit: int = 6) -> list[tuple[str, int]]:
    return counter.most_common(limit)


def _fmt_simulation_report(
    model: dict,
    pair: str,
    days: int,
    chart_tf: str,
    rr_target: float,
    bias_mode: str,
    resolved_bias: str,
    data_points: int,
    stats: dict,
) -> str:
    top_pass = _top_items(stats["passed_rule_counts"], 5)
    top_fail = _top_items(stats["failed_rule_counts"], 5)
    top_mand_fail = _top_items(stats["mandatory_failed_counts"], 3)

    lines = [
        "🧪 *PRO SIMULATOR REPORT*",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Model: `{model['id']}`",
        f"Name: {model['name']}",
        f"Pair: `{pair}`   Days: `{days}`   Chart: `{chart_tf}`",
        f"R:R Target: `{rr_target:.1f}R`",
        f"HTF Bias Mode: `{bias_mode}`   Applied Bias: `{resolved_bias}`",
        f"Data Points Used: `{data_points}`",
        "",
        "📐 *Engine Detail*",
        "1) Setup generated every 3 bars using model rules.",
        "2) Mandatory rules must pass; otherwise setup is rejected.",
        "3) Tier gate must pass (`tier_c` minimum).",
        "4) Trade simulation uses SL `0.3%` and TP = `0.3% × RR`.",
        "5) If both TP and SL are touched in window, SL bias remains conservative.",
        "",
        "📊 *Results*",
        f"Trades: `{stats['trades']}` | Wins: `{stats['wins']}` | Losses: `{stats['losses']}` | Unresolved: `{stats['unresolved']}`",
        f"Win Rate: `{stats['win_rate']:.2f}%`",
        f"Expectancy: `{stats['expectancy_r']:+.3f}R/trade`",
        f"Minimum WR needed for positive expectancy at {rr_target:.1f}R: `{stats['min_wr_for_positive']:.2f}%`",
        "",
        "🧰 *Pipeline Diagnostics*",
        f"No setup generated: `{stats['no_setup']}` windows",
        f"Mandatory gate failed: `{stats['mandatory_failed']}` windows",
        f"Below tier threshold: `{stats['below_tier']}` windows",
        f"Average final score (qualified only): `{stats['avg_final_score']:.2f}`",
        f"Direction count: `BUY={stats['direction_counts'].get('BUY',0)}` / `SELL={stats['direction_counts'].get('SELL',0)}`",
        f"Tier count: `A={stats['tier_counts'].get('A',0)}` `B={stats['tier_counts'].get('B',0)}` `C={stats['tier_counts'].get('C',0)}`",
        "",
        "✅ *Most Passed Rules*",
    ]
    lines.extend([f"• {name} — `{count}`" for name, count in top_pass] or ["• None"])
    lines.append("")
    lines.append("❌ *Most Failed Rules*")
    lines.extend([f"• {name} — `{count}`" for name, count in top_fail] or ["• None"])
    if top_mand_fail:
        lines.append("")
        lines.append("🔒 *Top Mandatory Failures*")
        lines.extend([f"• {name} — `{count}`" for name, count in top_mand_fail])

    lines.append("")
    if stats["expectancy_r"] > 0 and stats["win_rate"] < 50:
        lines.append("✅ This configuration satisfies `<50% WR` with positive expectancy.")
    else:
        lines.append("⚠️ This configuration does not currently achieve positive expectancy under the selected RR/bias settings.")
    return "\n".join(lines)


async def simulator_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    await update.message.reply_text(
        "🧪 *Pro Simulator*\nCreate models with the wizard, then run button-driven explainable tests.",
        parse_mode="Markdown",
        reply_markup=_sim_home_kb(),
    )


async def show_simulator_home(reply):
    await reply(
        "🧪 *Pro Simulator*\nCreate and test models with full explainability.",
        parse_mode="Markdown",
        reply_markup=_sim_home_kb(),
    )


def _models_kb(models: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                f"{'🟢' if m.get('status') == 'active' else '⚫'} {m.get('id')} — {m.get('name', '')[:32]}",
                callback_data=f"sim:test:model:{m['id']}",
            )
        ]
        for m in models
    ]
    rows.append([InlineKeyboardButton("« Back", callback_data="nav:simulator")])
    return InlineKeyboardMarkup(rows)


async def _send_model_picker(message):
    models = db.get_all_models()
    if not models:
        await message.reply_text("No models found. Create one first.", reply_markup=_sim_home_kb())
        return
    await message.reply_text("Pick a model to simulate:", reply_markup=_models_kb(models))


async def handle_sim_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    parts = q.data.split(":")
    if len(parts) < 3:
        await q.message.reply_text("Simulator callback malformed.")
        return

    action = parts[2]

    if action == "save_variant":
        last_run = context.user_data.get("sim_last_run")
        if not last_run:
            await q.message.reply_text("No simulator run to save yet. Run a test first.")
            return
        base_model = db.get_model(last_run["base_model_id"])
        if not base_model:
            await q.message.reply_text("Base model not found anymore.")
            return

        new_id = f"SIM_{uuid.uuid4().hex[:8].upper()}"
        sim_tag = (
            f"SIM {last_run['pair']} {last_run['days']}d "
            f"{last_run['chart_tf']} {last_run['resolved_bias']} {last_run['rr_target']:.1f}R"
        )
        new_name = f"{base_model['name']} [{sim_tag}]"
        if len(new_name) > 100:
            new_name = new_name[:97] + "..."

        variant = dict(base_model)
        variant.update(
            {
                "id": new_id,
                "name": new_name,
                "status": "inactive",
                "pair": last_run["pair"],
                "timeframe": last_run["chart_tf"],
                "bias": last_run["resolved_bias"],
                "rr_target": float(last_run["rr_target"]),
                "min_score": float(base_model.get("tier_c") or base_model.get("min_score") or 0),
            }
        )
        try:
            db.save_model(variant)
            await q.message.reply_text(
                f"✅ Saved new variant\nID: `{new_id}`\nName: {new_name}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("⚙️ Open Models", callback_data="nav:models")],
                        [InlineKeyboardButton("🔁 Run Another Test", callback_data="sim:test:start")],
                    ]
                ),
            )
        except Exception as exc:
            await q.message.reply_text(f"❌ Failed to save variant: `{str(exc)[:180]}`", parse_mode="Markdown")
        return

    if action == "start":
        await _send_model_picker(q.message)
        return

    if action == "model" and len(parts) > 3:
        model_id = parts[3]
        rows = [[InlineKeyboardButton(p, callback_data=f"sim:test:pair:{model_id}:{p}")] for p in SUPPORTED_PAIRS]
        rows.append([InlineKeyboardButton("« Back", callback_data="sim:test:start")])
        await q.message.reply_text(f"Model `{model_id}` selected. Pick pair:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
        return

    if action == "pair" and len(parts) > 4:
        model_id, pair = parts[3], parts[4]
        rows = [
            [
                InlineKeyboardButton("7d", callback_data=f"sim:test:days:{model_id}:{pair}:7"),
                InlineKeyboardButton("14d", callback_data=f"sim:test:days:{model_id}:{pair}:14"),
                InlineKeyboardButton("30d", callback_data=f"sim:test:days:{model_id}:{pair}:30"),
            ],
            [InlineKeyboardButton("« Back", callback_data=f"sim:test:model:{model_id}")],
        ]
        await q.message.reply_text("Pick test range:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if action == "days" and len(parts) > 5:
        model_id, pair, days = parts[3], parts[4], parts[5]
        rows = [
            [
                InlineKeyboardButton("1m", callback_data=f"sim:test:tf:{model_id}:{pair}:{days}:1m"),
                InlineKeyboardButton("5m", callback_data=f"sim:test:tf:{model_id}:{pair}:{days}:5m"),
                InlineKeyboardButton("15m", callback_data=f"sim:test:tf:{model_id}:{pair}:{days}:15m"),
            ],
            [InlineKeyboardButton("« Back", callback_data=f"sim:test:pair:{model_id}:{pair}")],
        ]
        await q.message.reply_text("Pick chart basis for simulation:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if action == "tf" and len(parts) > 6:
        model_id, pair, days, tf = parts[3], parts[4], parts[5], parts[6]
        rows = [
            [
                InlineKeyboardButton("2R", callback_data=f"sim:test:rr:{model_id}:{pair}:{days}:{tf}:2"),
                InlineKeyboardButton("3R", callback_data=f"sim:test:rr:{model_id}:{pair}:{days}:{tf}:3"),
                InlineKeyboardButton("4R", callback_data=f"sim:test:rr:{model_id}:{pair}:{days}:{tf}:4"),
            ],
            [InlineKeyboardButton("« Back", callback_data=f"sim:test:days:{model_id}:{pair}:{days}")],
        ]
        await q.message.reply_text("Pick RR target:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if action == "rr" and len(parts) > 7:
        model_id, pair, days, tf, rr = parts[3], parts[4], parts[5], parts[6], parts[7]
        rows = [
            [InlineKeyboardButton("Auto HTF Bias", callback_data=f"sim:test:bias:{model_id}:{pair}:{days}:{tf}:{rr}:auto")],
            [
                InlineKeyboardButton("Bullish", callback_data=f"sim:test:bias:{model_id}:{pair}:{days}:{tf}:{rr}:bullish"),
                InlineKeyboardButton("Bearish", callback_data=f"sim:test:bias:{model_id}:{pair}:{days}:{tf}:{rr}:bearish"),
                InlineKeyboardButton("Both", callback_data=f"sim:test:bias:{model_id}:{pair}:{days}:{tf}:{rr}:both"),
            ],
            [InlineKeyboardButton("« Back", callback_data=f"sim:test:tf:{model_id}:{pair}:{days}:{tf}")],
        ]
        await q.message.reply_text("Pick HTF bias mode:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if action == "bias" and len(parts) > 8:
        model_id, pair, days, tf, rr_raw, bias_mode = parts[3], parts[4], parts[5], parts[6], parts[7], parts[8]
        model = db.get_model(model_id)
        if not model:
            await q.message.reply_text("Model not found.")
            return

        days_i = int(days)
        rr_target = float(rr_raw)
        await q.message.reply_text("Running pro simulation... this can take a few seconds.")

        series_1m = px.get_recent_series(pair, days=days_i, interval="1m")
        if len(series_1m) < 60:
            await q.message.reply_text("Not enough price data returned for this configuration.")
            return
        series = _tf_series(series_1m, tf)
        resolved_bias = _auto_htf_bias(series, tf)
        if bias_mode in {"bullish", "bearish", "both"}:
            resolved_bias = {"bullish": "Bullish", "bearish": "Bearish", "both": "Both"}[bias_mode]

        run_model = dict(model)
        run_model["pair"] = pair
        run_model["bias"] = resolved_bias
        run_model["rr_target"] = rr_target

        stats = _simulate_detailed(run_model, series, rr_target=rr_target)
        context.user_data["sim_last_run"] = {
            "base_model_id": model_id,
            "pair": pair,
            "days": days_i,
            "chart_tf": tf,
            "rr_target": rr_target,
            "resolved_bias": resolved_bias,
        }
        report = _fmt_simulation_report(
            model=run_model,
            pair=pair,
            days=days_i,
            chart_tf=tf,
            rr_target=rr_target,
            bias_mode=bias_mode,
            resolved_bias=resolved_bias,
            data_points=len(series),
            stats=stats,
        )
        await q.message.reply_text(
            report,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("💾 Save as New Variant", callback_data="sim:test:save_variant")],
                    [InlineKeyboardButton("🔁 Test Again", callback_data="sim:test:start")],
                    [InlineKeyboardButton("🧠 Create New Model", callback_data="wizard:start")],
                    [InlineKeyboardButton("🏠 Back to Perps", callback_data="nav:perps_home")],
                ]
            ),
        )
        return

    await q.message.reply_text("Unknown simulator action.")
