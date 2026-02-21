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
            cur.execute("UPDATE trade_log SET result=%s WHERE id=%s", (result, trade_id))
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
              entry, sl, tp, rr, valid, reason=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO alert_log
                    (pair, model_id, model_name, score, tier, direction,
                     entry, sl, tp, rr, valid, reason)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (pair, model_id, model_name, score, tier, direction,
                  entry, sl, tp, rr, valid, reason))
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
