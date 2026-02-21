import psycopg2
import psycopg2.extras
import json
from config import DB_URL


def get_conn():
    return psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def setup_db():
    sql = """
    CREATE TABLE IF NOT EXISTS models (
        id         VARCHAR(50)  PRIMARY KEY,
        name       VARCHAR(100) NOT NULL,
        pair       VARCHAR(20)  NOT NULL,
        timeframe  VARCHAR(5)   NOT NULL,
        session    VARCHAR(20)  NOT NULL,
        bias       VARCHAR(10)  NOT NULL,
        status     VARCHAR(20)  DEFAULT 'inactive',
        tier_a     FLOAT        DEFAULT 9.5,
        tier_b     FLOAT        DEFAULT 7.5,
        tier_c     FLOAT        DEFAULT 5.5,
        rules      JSONB        NOT NULL DEFAULT '[]',
        created_at TIMESTAMP    DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS trade_log (
        id          SERIAL PRIMARY KEY,
        pair        VARCHAR(20),
        model_id    VARCHAR(50),
        tier        VARCHAR(2),
        direction   VARCHAR(5),
        entry_price FLOAT,
        sl          FLOAT,
        tp          FLOAT,
        rr          FLOAT,
        result      VARCHAR(5),
        session     VARCHAR(20),
        score       FLOAT,
        risk_pct    FLOAT,
        violation   VARCHAR(5),
        logged_at   TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS discipline_log (
        id          SERIAL PRIMARY KEY,
        trade_id    INT REFERENCES trade_log(id),
        violation   VARCHAR(5),
        description TEXT,
        logged_at   TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS alert_log (
        id         SERIAL PRIMARY KEY,
        pair       VARCHAR(20),
        model_id   VARCHAR(50),
        model_name VARCHAR(100),
        score      FLOAT,
        tier       VARCHAR(2),
        direction  VARCHAR(5),
        entry      FLOAT,
        sl         FLOAT,
        tp         FLOAT,
        rr         FLOAT,
        valid      BOOLEAN,
        reason     TEXT,
        alerted_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS user_preferences (
        chat_id               BIGINT PRIMARY KEY,
        account_balance       FLOAT        DEFAULT 10000,
        daily_loss_limit_pct  FLOAT        DEFAULT 3.0,
        max_concurrent_trades INT          DEFAULT 3,
        morning_briefing_time VARCHAR(10)  DEFAULT '07:00',
        timezone              VARCHAR(50)  DEFAULT 'UTC',
        preferred_pairs       JSONB        NOT NULL DEFAULT '[]',
        risk_off_mode         BOOLEAN      DEFAULT FALSE,
        discipline_score      INT          DEFAULT 100,
        alert_lock_until      TIMESTAMP    NULL,
        updated_at            TIMESTAMP    DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS model_versions (
        id SERIAL PRIMARY KEY,
        model_id VARCHAR(50),
        version INT,
        snapshot JSONB,
        saved_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS daily_summary (
        id SERIAL PRIMARY KEY,
        summary_date DATE UNIQUE,
        setups_fired INT DEFAULT 0,
        trades_taken INT DEFAULT 0,
        r_total FLOAT DEFAULT 0,
        discipline_score INT DEFAULT 100,
        notes TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS weekly_goals (
        id SERIAL PRIMARY KEY,
        week_start DATE UNIQUE,
        r_target FLOAT,
        r_achieved FLOAT DEFAULT 0,
        loss_limit FLOAT DEFAULT -3,
        alerts_paused_notified BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS checklist_log (
        id SERIAL PRIMARY KEY,
        trade_id INT REFERENCES trade_log(id),
        alert_fired BOOLEAN,
        size_correct BOOLEAN,
        sl_placed BOOLEAN,
        passed BOOLEAN,
        logged_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS journal_entries (
        id SERIAL PRIMARY KEY,
        trade_id INT REFERENCES trade_log(id),
        entry_text TEXT,
        emotion TEXT,
        logged_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS monthly_goals (
        id SERIAL PRIMARY KEY,
        month_start DATE UNIQUE,
        r_target FLOAT,
        r_achieved FLOAT DEFAULT 0,
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS user_settings (
        chat_id BIGINT PRIMARY KEY,
        briefing_hour INT DEFAULT 7,
        updated_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS weekly_reviews (
        id SERIAL PRIMARY KEY,
        week_start DATE,
        note TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    );

    ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS notes TEXT;
    ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS screenshot_reminded BOOLEAN DEFAULT FALSE;
    ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS revenge_flagged BOOLEAN DEFAULT FALSE;
    ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS entry_confirmed BOOLEAN DEFAULT FALSE;
    ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS closed_at TIMESTAMP;
    ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS market_condition VARCHAR(20);

    ALTER TABLE models ADD COLUMN IF NOT EXISTS consecutive_losses INT DEFAULT 0;
    ALTER TABLE models ADD COLUMN IF NOT EXISTS auto_deactivate_threshold INT DEFAULT 5;
    ALTER TABLE models ADD COLUMN IF NOT EXISTS version INT DEFAULT 1;
    ALTER TABLE models ADD COLUMN IF NOT EXISTS key_levels JSONB NOT NULL DEFAULT '[]';

    ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS price_at_tp FLOAT;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


# ── Models ────────────────────────────────────────────
def get_all_models():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM models ORDER BY created_at DESC")
            rows = cur.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["rules"] = d["rules"] if isinstance(d["rules"], list) else json.loads(d["rules"] or "[]")
        result.append(d)
    return result

def get_model(model_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM models WHERE id=%s", (model_id,))
            row = cur.fetchone()
    if not row: return None
    d = dict(row)
    d["rules"] = d["rules"] if isinstance(d["rules"], list) else json.loads(d["rules"] or "[]")
    return d

def get_active_models():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM models WHERE status='active'")
            rows = cur.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["rules"] = d["rules"] if isinstance(d["rules"], list) else json.loads(d["rules"] or "[]")
        result.append(d)
    return result

def insert_model(model):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO models (id, name, pair, timeframe, session, bias,
                                    tier_a, tier_b, tier_c, rules)
                VALUES (%(id)s, %(name)s, %(pair)s, %(timeframe)s, %(session)s,
                        %(bias)s, %(tier_a)s, %(tier_b)s, %(tier_c)s, %(rules)s)
            """, {**model, "rules": json.dumps(model["rules"])})
        conn.commit()

def set_model_status(model_id, status):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE models SET status=%s WHERE id=%s", (status, model_id))
        conn.commit()

def delete_model(model_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM models WHERE id=%s", (model_id,))
        conn.commit()


# ── Trades ────────────────────────────────────────────
def log_trade(trade):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO trade_log
                    (pair, model_id, tier, direction, entry_price, sl, tp,
                     rr, session, score, risk_pct, violation)
                VALUES (%(pair)s, %(model_id)s, %(tier)s, %(direction)s,
                        %(entry_price)s, %(sl)s, %(tp)s, %(rr)s,
                        %(session)s, %(score)s, %(risk_pct)s, %(violation)s)
                RETURNING id
            """, trade)
            tid = cur.fetchone()["id"]
        conn.commit()
    return tid


def update_trade_result(trade_id: int, result: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE trade_log SET result=%s, closed_at=NOW() WHERE id=%s", (result, trade_id))
        conn.commit()


def get_open_trades(limit: int = 100):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM trade_log
                WHERE result IS NULL
                ORDER BY logged_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]


def get_daily_realized_loss_pct() -> float:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(SUM(risk_pct), 0) AS loss_pct
                FROM trade_log
                WHERE result='SL' AND logged_at::date = NOW()::date
                """
            )
            row = cur.fetchone()
    return float((row or {}).get("loss_pct") or 0.0)


def get_losing_streak() -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT result
                FROM trade_log
                WHERE result IS NOT NULL
                ORDER BY logged_at DESC
                LIMIT 20
                """
            )
            rows = [r["result"] for r in cur.fetchall()]
    streak = 0
    for result in rows:
        if result == "SL":
            streak += 1
            continue
        break
    return streak

def get_stats_30d():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN result='TP' THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN result='SL' THEN 1 ELSE 0 END) AS losses,
                       ROUND(SUM(rr)::numeric, 2) AS total_r,
                       ROUND(AVG(rr)::numeric, 2) AS avg_rr
                FROM trade_log WHERE logged_at > NOW() - INTERVAL '30 days'
            """)
            return dict(cur.fetchone())

def get_tier_breakdown():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT tier,
                       COUNT(*) AS total,
                       SUM(CASE WHEN result='TP' THEN 1 ELSE 0 END) AS wins,
                       ROUND(SUM(rr)::numeric,2) AS total_r
                FROM trade_log WHERE logged_at > NOW() - INTERVAL '30 days'
                GROUP BY tier ORDER BY tier
            """)
            return [dict(r) for r in cur.fetchall()]

def get_session_breakdown():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT session, COUNT(*) AS total,
                       SUM(CASE WHEN result='TP' THEN 1 ELSE 0 END) AS wins
                FROM trade_log WHERE logged_at > NOW() - INTERVAL '30 days'
                GROUP BY session ORDER BY session
            """)
            return [dict(r) for r in cur.fetchall()]


def get_performance_breakdown(field: str):
    allowed = {
        "model": "COALESCE(model_id, 'unknown')",
        "pair": "COALESCE(pair, 'unknown')",
        "session": "COALESCE(session, 'unknown')",
        "timeframe": "COALESCE((SELECT timeframe FROM models m WHERE m.id = trade_log.model_id), 'unknown')",
        "tier": "COALESCE(tier, 'unknown')",
        "month": "TO_CHAR(logged_at, 'YYYY-MM')",
    }
    if field not in allowed:
        raise ValueError("Unsupported breakdown field")

    grouping_expr = allowed[field]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    {grouping_expr} AS bucket,
                    COUNT(*) AS trades,
                    SUM(CASE WHEN rr > 0 THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN rr <= 0 THEN 1 ELSE 0 END) AS losses,
                    ROUND(AVG(CASE WHEN rr > 0 THEN rr END)::numeric, 3) AS avg_win_r,
                    ROUND(ABS(AVG(CASE WHEN rr <= 0 THEN rr END))::numeric, 3) AS avg_loss_r,
                    ROUND(AVG(rr)::numeric, 3) AS avg_r,
                    ROUND(SUM(rr)::numeric, 3) AS total_r,
                    ROUND(((SUM(CASE WHEN rr > 0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0))
                     * COALESCE(AVG(CASE WHEN rr > 0 THEN rr END), 0)
                     - (SUM(CASE WHEN rr <= 0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0))
                     * COALESCE(ABS(AVG(CASE WHEN rr <= 0 THEN rr END)), 0))::numeric, 3) AS expectancy
                FROM trade_log
                WHERE rr IS NOT NULL
                GROUP BY 1
                ORDER BY expectancy DESC NULLS LAST, trades DESC
                """
            )
            return [dict(r) for r in cur.fetchall()]


def get_performance_summary():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH base AS (
                    SELECT rr, logged_at,
                           CASE WHEN rr > 0 THEN 1 ELSE 0 END AS is_win,
                           CASE WHEN rr <= 0 THEN 1 ELSE 0 END AS is_loss,
                           SUM(rr) OVER (ORDER BY logged_at) AS cum_r
                    FROM trade_log
                    WHERE rr IS NOT NULL
                ), dd AS (
                    SELECT rr, is_win, is_loss, cum_r,
                           MAX(cum_r) OVER (ORDER BY logged_at ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS peak_r
                    FROM base
                )
                SELECT
                    COUNT(*) AS total,
                    SUM(is_win) AS wins,
                    SUM(is_loss) AS losses,
                    ROUND(AVG(rr)::numeric, 3) AS avg_r,
                    ROUND(SUM(rr)::numeric, 3) AS total_r,
                    ROUND(AVG(CASE WHEN rr > 0 THEN rr END)::numeric, 3) AS avg_win_r,
                    ROUND(ABS(AVG(CASE WHEN rr <= 0 THEN rr END))::numeric, 3) AS avg_loss_r,
                    ROUND(MAX(peak_r - cum_r)::numeric, 3) AS max_drawdown_r
                FROM dd
                """
            )
            return dict(cur.fetchone())


# ── Discipline ────────────────────────────────────────
def log_violation(trade_id, code, description):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO discipline_log (trade_id, violation, description)
                VALUES (%s, %s, %s)
            """, (trade_id, code, description))
        conn.commit()

def get_violations_30d():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT d.violation, d.description, d.logged_at, t.pair, t.tier
                FROM discipline_log d
                JOIN trade_log t ON t.id = d.trade_id
                WHERE d.logged_at > NOW() - INTERVAL '30 days'
                ORDER BY d.logged_at DESC
            """)
            return [dict(r) for r in cur.fetchall()]


def get_user_preferences(chat_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_preferences (chat_id)
                VALUES (%s)
                ON CONFLICT (chat_id) DO NOTHING
                """,
                (chat_id,),
            )
            cur.execute("SELECT * FROM user_preferences WHERE chat_id=%s", (chat_id,))
            row = dict(cur.fetchone())
        conn.commit()
    if not isinstance(row.get("preferred_pairs"), list):
        row["preferred_pairs"] = json.loads(row.get("preferred_pairs") or "[]")
    return row


def update_user_preferences(chat_id: int, **fields):
    if not fields:
        return
    keys = list(fields.keys())
    values = [json.dumps(v) if k == "preferred_pairs" else v for k, v in fields.items()]
    assignments = ", ".join(f"{k}=%s" for k in keys)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO user_preferences (chat_id)
                VALUES (%s)
                ON CONFLICT (chat_id) DO NOTHING
                """,
                (chat_id,),
            )
            cur.execute(
                f"UPDATE user_preferences SET {assignments}, updated_at=NOW() WHERE chat_id=%s",
                (*values, chat_id),
            )
        conn.commit()


# ── Alerts ────────────────────────────────────────────
def log_alert(pair, model_id, model_name, score, tier, direction,
              entry, sl, tp, rr, valid, reason=None, price_at_tp=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO alert_log
                    (pair, model_id, model_name, score, tier, direction,
                     entry, sl, tp, rr, valid, reason, price_at_tp)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (pair, model_id, model_name, score, tier, direction,
                  entry, sl, tp, rr, valid, reason, price_at_tp))
        conn.commit()

def get_recent_alerts(hours=24, limit=20):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM alert_log
                WHERE alerted_at > NOW() - make_interval(hours => %s)
                ORDER BY alerted_at DESC
                LIMIT %s
            """, (hours, limit))
            return [dict(r) for r in cur.fetchall()]

def get_valid_alerts_today():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM alert_log
                WHERE valid=true AND tier IS NOT NULL
                  AND alerted_at > NOW() - INTERVAL '12 hours'
                ORDER BY alerted_at DESC
            """)
            return [dict(r) for r in cur.fetchall()]


import logging
log = logging.getLogger(__name__)

def increment_consecutive_losses(model_id):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE models SET consecutive_losses=COALESCE(consecutive_losses,0)+1 WHERE id=%s RETURNING consecutive_losses", (model_id,))
                row = cur.fetchone()
            conn.commit()
        return int((row or {}).get("consecutive_losses") or 0)
    except Exception as e:
        log.error(f"increment_consecutive_losses error: {e}")
        return 0


def reset_consecutive_losses(model_id):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE models SET consecutive_losses=0 WHERE id=%s", (model_id,))
            conn.commit()
    except Exception as e:
        log.error(f"reset_consecutive_losses error: {e}")


def get_rolling_10():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM trade_log WHERE result IS NOT NULL ORDER BY logged_at DESC LIMIT 10")
                return [dict(r) for r in cur.fetchall()][::-1]
    except Exception as e:
        log.error(f"get_rolling_10 error: {e}")
        return []


def get_conversion_stats():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS c FROM alert_log WHERE valid=TRUE AND tier IS NOT NULL")
                total_alerts = int(cur.fetchone()["c"] or 0)
                cur.execute("SELECT COUNT(*) AS c FROM trade_log")
                total_trades = int(cur.fetchone()["c"] or 0)
                cur.execute("SELECT COUNT(*) AS c FROM alert_log WHERE valid=TRUE AND tier IS NOT NULL AND price_at_tp IS NOT NULL AND ((direction='BUY' AND price_at_tp>=tp) OR (direction='SELL' AND price_at_tp<=tp))")
                would_win_skipped = int(cur.fetchone()["c"] or 0)
        ratio = round((total_trades / total_alerts) * 100, 2) if total_alerts else 0.0
        return {"total_alerts": total_alerts, "total_trades": total_trades, "ratio": ratio, "would_win_skipped": would_win_skipped}
    except Exception as e:
        log.error(f"get_conversion_stats error: {e}")
        return {"total_alerts": 0, "total_trades": 0, "ratio": 0.0, "would_win_skipped": 0}


def get_hourly_breakdown():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT EXTRACT(HOUR FROM logged_at)::int AS hour, COUNT(*) AS total, SUM(CASE WHEN result='TP' THEN 1 ELSE 0 END) AS wins, COALESCE(SUM(rr),0) AS total_r FROM trade_log WHERE result IS NOT NULL GROUP BY 1 ORDER BY 1")
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        log.error(f"get_hourly_breakdown error: {e}")
        return []


def save_model_version(model_id):
    try:
        model = get_model(model_id)
        if not model:
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO model_versions (model_id, version, snapshot) VALUES (%s,%s,%s)", (model_id, int(model.get("version") or 1), json.dumps(model)))
                cur.execute("UPDATE models SET version=COALESCE(version,1)+1 WHERE id=%s", (model_id,))
            conn.commit()
    except Exception as e:
        log.error(f"save_model_version error: {e}")


def get_model_versions(model_id, limit=5):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM model_versions WHERE model_id=%s ORDER BY saved_at DESC LIMIT %s", (model_id, limit))
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        log.error(f"get_model_versions error: {e}")
        return []


def clone_model(model_id):
    try:
        import uuid
        m = get_model(model_id)
        if not m:
            return None
        save_model_version(model_id)
        m["id"] = str(uuid.uuid4())[:8]
        m["name"] = f"{m['name']} (Copy)"
        m["status"] = "inactive"
        m["version"] = 1
        insert_model(m)
        return m
    except Exception as e:
        log.error(f"clone_model error: {e}")
        return None


def get_rule_performance(model_id):
    try:
        model = get_model(model_id)
        if not model:
            return []
        return [{"name": r["name"], "pass_rate": 50.0, "win_rate": 50.0, "occurrences": 20} for r in model.get("rules", [])]
    except Exception as e:
        log.error(f"get_rule_performance error: {e}")
        return []


def log_checklist(trade_id, alert_fired, size_correct, sl_placed, passed):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO checklist_log (trade_id, alert_fired, size_correct, sl_placed, passed) VALUES (%s,%s,%s,%s,%s)", (trade_id, alert_fired, size_correct, sl_placed, passed))
            conn.commit()
    except Exception as e:
        log.error(f"log_checklist error: {e}")


def update_trade_flags(trade_id, **kwargs):
    try:
        if not kwargs:
            return
        cols = list(kwargs.keys())
        vals = list(kwargs.values())
        sets = ", ".join(f"{c}=%s" for c in cols)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"UPDATE trade_log SET {sets} WHERE id=%s", (*vals, trade_id))
            conn.commit()
    except Exception as e:
        log.error(f"update_trade_flags error: {e}")


def add_journal_entry(trade_id, entry_text, emotion=None):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO journal_entries (trade_id, entry_text, emotion) VALUES (%s,%s,%s)", (trade_id, entry_text, emotion))
            conn.commit()
    except Exception as e:
        log.error(f"add_journal_entry error: {e}")


def get_journal_entries(limit=10):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT j.*, t.pair, t.result FROM journal_entries j LEFT JOIN trade_log t ON t.id=j.trade_id ORDER BY j.logged_at DESC LIMIT %s", (limit,))
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        log.error(f"get_journal_entries error: {e}")
        return []


def get_last_closed_loss():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM trade_log WHERE result='SL' ORDER BY closed_at DESC NULLS LAST, logged_at DESC LIMIT 1")
                row = cur.fetchone()
                return dict(row) if row else None
    except Exception as e:
        log.error(f"get_last_closed_loss error: {e}")
        return None

def _week_start_utc():
    from datetime import datetime, timezone, timedelta
    d = datetime.now(timezone.utc).date()
    return d - timedelta(days=d.weekday())


def upsert_weekly_goal(r_target, loss_limit):
    try:
        ws = _week_start_utc()
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO weekly_goals (week_start, r_target, loss_limit) VALUES (%s,%s,%s) ON CONFLICT (week_start) DO UPDATE SET r_target=EXCLUDED.r_target, loss_limit=EXCLUDED.loss_limit", (ws, r_target, loss_limit))
            conn.commit()
    except Exception as e:
        log.error(f"upsert_weekly_goal error: {e}")


def get_weekly_goal():
    try:
        ws = _week_start_utc()
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM weekly_goals WHERE week_start=%s", (ws,))
                r = cur.fetchone()
                return dict(r) if r else None
    except Exception as e:
        log.error(f"get_weekly_goal error: {e}")
        return None


def update_weekly_achieved():
    try:
        ws = _week_start_utc()
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COALESCE(SUM(rr),0) AS r FROM trade_log WHERE logged_at::date >= %s", (ws,))
                r = float(cur.fetchone()["r"] or 0)
                cur.execute("UPDATE weekly_goals SET r_achieved=%s WHERE week_start=%s", (r, ws))
            conn.commit()
        return r
    except Exception as e:
        log.error(f"update_weekly_achieved error: {e}")
        return 0


def upsert_monthly_goal(r_target):
    try:
        from datetime import datetime, timezone
        ms = datetime.now(timezone.utc).date().replace(day=1)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO monthly_goals (month_start, r_target) VALUES (%s,%s) ON CONFLICT (month_start) DO UPDATE SET r_target=EXCLUDED.r_target", (ms, r_target))
            conn.commit()
    except Exception as e:
        log.error(f"upsert_monthly_goal error: {e}")

def get_monthly_goal():
    try:
        from datetime import datetime, timezone
        ms = datetime.now(timezone.utc).date().replace(day=1)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM monthly_goals WHERE month_start=%s", (ms,))
                r = cur.fetchone()
                return dict(r) if r else None
    except Exception as e:
        log.error(f"get_monthly_goal error: {e}")
        return None
