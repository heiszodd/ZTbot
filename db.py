import psycopg2
import psycopg2.extras
import json
from config import DB_URL


def get_conn():
    return psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def setup_db():
    """Create all tables if they don't exist."""
    sql = """
    CREATE TABLE IF NOT EXISTS models (
        id          VARCHAR(50) PRIMARY KEY,
        name        VARCHAR(100) NOT NULL,
        pair        VARCHAR(20)  NOT NULL,
        timeframe   VARCHAR(5)   NOT NULL,
        session     VARCHAR(20)  NOT NULL,
        bias        VARCHAR(10)  NOT NULL,
        status      VARCHAR(20)  DEFAULT 'inactive',
        tier_a      FLOAT        DEFAULT 9.5,
        tier_b      FLOAT        DEFAULT 7.5,
        tier_c      FLOAT        DEFAULT 5.5,
        rules       JSONB        NOT NULL DEFAULT '[]',
        created_at  TIMESTAMP    DEFAULT NOW()
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
        id           SERIAL PRIMARY KEY,
        trade_id     INT REFERENCES trade_log(id),
        violation    VARCHAR(5),
        description  TEXT,
        logged_at    TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS alert_log (
        id          SERIAL PRIMARY KEY,
        pair        VARCHAR(20),
        model_id    VARCHAR(50),
        score       FLOAT,
        tier        VARCHAR(2),
        valid       BOOLEAN,
        reason      TEXT,
        alerted_at  TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS candles (
        id        SERIAL PRIMARY KEY,
        pair      VARCHAR(20),
        timeframe VARCHAR(5),
        ts        BIGINT,
        open      FLOAT, high FLOAT, low FLOAT, close FLOAT, volume FLOAT,
        atr14     FLOAT,
        UNIQUE(pair, timeframe, ts)
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
            return cur.fetchall()

def get_model(model_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM models WHERE id=%s", (model_id,))
            return cur.fetchone()

def get_active_models():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM models WHERE status='active'")
            return cur.fetchall()

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


# ── Trade log ─────────────────────────────────────────
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
            return cur.fetchone()["id"]
        conn.commit()

def get_stats_30d():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*)                                          AS total,
                    SUM(CASE WHEN result='TP' THEN 1 ELSE 0 END)    AS wins,
                    SUM(CASE WHEN result='SL' THEN 1 ELSE 0 END)    AS losses,
                    ROUND(SUM(rr)::numeric, 2)                       AS total_r,
                    ROUND(AVG(rr)::numeric, 2)                       AS avg_rr
                FROM trade_log
                WHERE logged_at > NOW() - INTERVAL '30 days'
            """)
            return cur.fetchone()

def get_tier_breakdown():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    tier,
                    COUNT(*) AS total,
                    SUM(CASE WHEN result='TP' THEN 1 ELSE 0 END) AS wins,
                    ROUND(SUM(rr)::numeric, 2) AS total_r
                FROM trade_log
                WHERE logged_at > NOW() - INTERVAL '30 days'
                GROUP BY tier ORDER BY tier
            """)
            return cur.fetchall()

def get_session_breakdown():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    session,
                    COUNT(*) AS total,
                    SUM(CASE WHEN result='TP' THEN 1 ELSE 0 END) AS wins
                FROM trade_log
                WHERE logged_at > NOW() - INTERVAL '30 days'
                GROUP BY session ORDER BY session
            """)
            return cur.fetchall()


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
                SELECT d.violation, d.description, d.logged_at,
                       t.pair, t.tier
                FROM discipline_log d
                JOIN trade_log t ON t.id = d.trade_id
                WHERE d.logged_at > NOW() - INTERVAL '30 days'
                ORDER BY d.logged_at DESC
            """)
            return cur.fetchall()


# ── Alert log ─────────────────────────────────────────
def log_alert(pair, model_id, score, tier, valid, reason=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO alert_log (pair, model_id, score, tier, valid, reason)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (pair, model_id, score, tier, valid, reason))
        conn.commit()
