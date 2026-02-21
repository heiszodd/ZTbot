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
        source      VARCHAR(30) DEFAULT 'signal',
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
    CREATE TABLE IF NOT EXISTS news_events (
        id              SERIAL PRIMARY KEY,
        event_name      VARCHAR(200),
        pair            VARCHAR(20),
        event_time_utc  TIMESTAMP,
        impact          VARCHAR(10),
        forecast        VARCHAR(50),
        previous        VARCHAR(50),
        actual          VARCHAR(50),
        direction       VARCHAR(10),
        confidence      VARCHAR(10),
        reasoning       TEXT,
        signal_sent     BOOLEAN DEFAULT FALSE,
        briefing_sent   BOOLEAN DEFAULT FALSE,
        suppressed      BOOLEAN DEFAULT FALSE,
        source          VARCHAR(50),
        created_at      TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS news_trades (
        id              SERIAL PRIMARY KEY,
        news_event_id   INT REFERENCES news_events(id),
        pair            VARCHAR(20),
        direction       VARCHAR(5),
        entry_price     FLOAT,
        sl              FLOAT,
        tp1             FLOAT,
        tp2             FLOAT,
        tp3             FLOAT,
        rr              FLOAT,
        pre_news_price  FLOAT,
        signal_sent_at  TIMESTAMP DEFAULT NOW(),
        result          VARCHAR(5),
        closed_at       TIMESTAMP
    );

    ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS notes TEXT;
    ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS screenshot_reminded BOOLEAN DEFAULT FALSE;
    ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS revenge_flagged BOOLEAN DEFAULT FALSE;
    ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS entry_confirmed BOOLEAN DEFAULT FALSE;
    ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS closed_at TIMESTAMP;
    ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS market_condition VARCHAR(20);
    ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS source VARCHAR(30) DEFAULT 'signal';

    ALTER TABLE models ADD COLUMN IF NOT EXISTS consecutive_losses INT DEFAULT 0;
    ALTER TABLE models ADD COLUMN IF NOT EXISTS auto_deactivate_threshold INT DEFAULT 5;
    ALTER TABLE models ADD COLUMN IF NOT EXISTS version INT DEFAULT 1;
    ALTER TABLE models ADD COLUMN IF NOT EXISTS key_levels JSONB NOT NULL DEFAULT '[]';

    ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS model_name VARCHAR(100);
    ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS price_at_tp FLOAT;
    ALTER TABLE news_events ADD COLUMN IF NOT EXISTS suppressed BOOLEAN DEFAULT FALSE;
    """
    degen_sql = """
    CREATE TABLE IF NOT EXISTS degen_tokens (
        id SERIAL PRIMARY KEY,
        address VARCHAR(100) UNIQUE,
        symbol VARCHAR(20),
        chain VARCHAR(20) DEFAULT 'SOL',
        token_data JSONB DEFAULT '{}',
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS degen_trades (
        id SERIAL PRIMARY KEY,
        token_id INT REFERENCES degen_tokens(id),
        token_symbol VARCHAR(20),
        result VARCHAR(10),
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS degen_models (
        id                    VARCHAR(50)  PRIMARY KEY,
        name                  VARCHAR(100) NOT NULL,
        description           TEXT,
        status                VARCHAR(20)  DEFAULT 'inactive',
        chains                JSONB        DEFAULT '["SOL"]',
        rules                 JSONB        NOT NULL DEFAULT '[]',
        min_score             FLOAT        DEFAULT 50,
        max_risk_level        VARCHAR(20)  DEFAULT 'HIGH',
        min_moon_score        INT          DEFAULT 40,
        max_risk_score        INT          DEFAULT 60,
        min_liquidity         FLOAT        DEFAULT 5000,
        max_token_age_minutes INT          DEFAULT 120,
        min_token_age_minutes INT          DEFAULT 2,
        require_lp_locked     BOOLEAN      DEFAULT FALSE,
        require_mint_revoked  BOOLEAN      DEFAULT FALSE,
        require_verified      BOOLEAN      DEFAULT FALSE,
        block_serial_ruggers  BOOLEAN      DEFAULT TRUE,
        max_dev_rug_count     INT          DEFAULT 0,
        max_top1_holder_pct   FLOAT        DEFAULT 20,
        min_holder_count      INT          DEFAULT 10,
        alert_count           INT          DEFAULT 0,
        last_alert_at         TIMESTAMP,
        created_at            TIMESTAMP    DEFAULT NOW(),
        version               INT          DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS degen_model_alerts (
        id              SERIAL PRIMARY KEY,
        model_id        VARCHAR(50) REFERENCES degen_models(id),
        token_id        INT REFERENCES degen_tokens(id),
        token_address   VARCHAR(100),
        token_symbol    VARCHAR(20),
        score           FLOAT,
        risk_score      INT,
        moon_score      INT,
        triggered_rules JSONB,
        alerted_at      TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS degen_model_versions (
        id         SERIAL PRIMARY KEY,
        model_id   VARCHAR(50),
        version    INT,
        snapshot   JSONB,
        saved_at   TIMESTAMP DEFAULT NOW()
    );
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS description TEXT;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'inactive';
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS chains JSONB DEFAULT '["SOL"]';
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS rules JSONB NOT NULL DEFAULT '[]';
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS min_score FLOAT DEFAULT 50;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS max_risk_level VARCHAR(20) DEFAULT 'HIGH';
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS min_moon_score INT DEFAULT 40;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS max_risk_score INT DEFAULT 60;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS min_liquidity FLOAT DEFAULT 5000;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS max_token_age_minutes INT DEFAULT 120;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS min_token_age_minutes INT DEFAULT 2;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS require_lp_locked BOOLEAN DEFAULT FALSE;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS require_mint_revoked BOOLEAN DEFAULT FALSE;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS require_verified BOOLEAN DEFAULT FALSE;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS block_serial_ruggers BOOLEAN DEFAULT TRUE;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS max_dev_rug_count INT DEFAULT 0;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS max_top1_holder_pct FLOAT DEFAULT 20;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS min_holder_count INT DEFAULT 10;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS alert_count INT DEFAULT 0;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS last_alert_at TIMESTAMP;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS version INT DEFAULT 1;

    CREATE TABLE IF NOT EXISTS tracked_wallets (
        id                SERIAL PRIMARY KEY,
        address           VARCHAR(100) NOT NULL,
        chain             VARCHAR(20)  NOT NULL,
        label             VARCHAR(100),
        tier              VARCHAR(20),
        tier_label        VARCHAR(50),
        credibility       VARCHAR(20),
        wallet_age_days   INT,
        tx_count          INT,
        estimated_win_rate FLOAT,
        total_value_usd   FLOAT,
        portfolio_size_label VARCHAR(20),
        last_tx_hash      VARCHAR(200),
        last_checked_at   TIMESTAMP,
        alert_on_buy      BOOLEAN DEFAULT TRUE,
        alert_on_sell     BOOLEAN DEFAULT TRUE,
        alert_min_usd     FLOAT   DEFAULT 100,
        active            BOOLEAN DEFAULT TRUE,
        added_at          TIMESTAMP DEFAULT NOW(),
        notes             TEXT,
        UNIQUE(address, chain)
    );
    CREATE TABLE IF NOT EXISTS wallet_transactions (
        id               SERIAL PRIMARY KEY,
        wallet_id        INT REFERENCES tracked_wallets(id),
        wallet_address   VARCHAR(100),
        tx_hash          VARCHAR(200) UNIQUE,
        chain            VARCHAR(20),
        tx_type          VARCHAR(20),
        token_address    VARCHAR(100),
        token_name       VARCHAR(100),
        token_symbol     VARCHAR(20),
        amount_token     FLOAT,
        amount_usd       FLOAT,
        price_per_token  FLOAT,
        token_risk_score INT,
        token_moon_score INT,
        token_risk_level VARCHAR(20),
        alert_sent       BOOLEAN DEFAULT FALSE,
        tx_timestamp     TIMESTAMP,
        detected_at      TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS wallet_copy_trades (
        id               SERIAL PRIMARY KEY,
        wallet_tx_id     INT REFERENCES wallet_transactions(id),
        token_address    VARCHAR(100),
        token_symbol     VARCHAR(20),
        entry_price      FLOAT,
        entry_usd        FLOAT,
        tp1              FLOAT,
        tp2              FLOAT,
        tp3              FLOAT,
        sl               FLOAT,
        result           VARCHAR(10),
        exit_price       FLOAT,
        pnl_x            FLOAT,
        logged_at        TIMESTAMP DEFAULT NOW(),
        closed_at        TIMESTAMP
    );
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(degen_sql)
            cur.execute("""
            ALTER TABLE degen_tokens ADD COLUMN IF NOT EXISTS initial_risk_score INT;
            ALTER TABLE degen_tokens ADD COLUMN IF NOT EXISTS initial_scored_at TIMESTAMP;
            ALTER TABLE degen_tokens ADD COLUMN IF NOT EXISTS latest_risk_score INT;
            ALTER TABLE degen_tokens ADD COLUMN IF NOT EXISTS last_rescored_at TIMESTAMP;
            ALTER TABLE degen_tokens ADD COLUMN IF NOT EXISTS trajectory VARCHAR(20);
            ALTER TABLE degen_tokens ADD COLUMN IF NOT EXISTS initial_reply_count INT;
            ALTER TABLE degen_tokens ADD COLUMN IF NOT EXISTS replies_per_hour FLOAT;
            ALTER TABLE degen_tokens ADD COLUMN IF NOT EXISTS social_velocity_score INT;
            ALTER TABLE degen_tokens ADD COLUMN IF NOT EXISTS token_profile VARCHAR(40);
            ALTER TABLE degen_tokens ADD COLUMN IF NOT EXISTS holders_last_checked_at TIMESTAMP;
            ALTER TABLE degen_tokens ADD COLUMN IF NOT EXISTS rugged BOOLEAN DEFAULT FALSE;
            CREATE TABLE IF NOT EXISTS rug_postmortems (
                id SERIAL PRIMARY KEY,
                token_id INT REFERENCES degen_tokens(id),
                token_address VARCHAR(100),
                token_symbol VARCHAR(20),
                initial_risk_score INT,
                final_risk_score INT,
                initial_moon_score INT,
                price_at_alert FLOAT,
                price_at_rug FLOAT,
                drop_pct FLOAT,
                time_to_rug_minutes INT,
                was_alerted BOOLEAN,
                was_in_watchlist BOOLEAN,
                triggered_risk_factors JSONB,
                missed_signals JSONB,
                detected_at TIMESTAMP,
                rugged_at TIMESTAMP DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS narrative_trends (
                id SERIAL PRIMARY KEY,
                narrative VARCHAR(50),
                token_count INT DEFAULT 0,
                avg_moon_score FLOAT DEFAULT 0,
                avg_risk_score FLOAT DEFAULT 0,
                total_volume FLOAT DEFAULT 0,
                win_rate FLOAT DEFAULT 0,
                week_start DATE,
                updated_at TIMESTAMP DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS demo_accounts (
                id SERIAL PRIMARY KEY,
                section VARCHAR(10) NOT NULL,
                balance FLOAT NOT NULL DEFAULT 0,
                initial_deposit FLOAT NOT NULL DEFAULT 0,
                total_pnl FLOAT DEFAULT 0,
                total_pnl_pct FLOAT DEFAULT 0,
                peak_balance FLOAT DEFAULT 0,
                lowest_balance FLOAT DEFAULT 0,
                total_trades INT DEFAULT 0,
                winning_trades INT DEFAULT 0,
                losing_trades INT DEFAULT 0,
                reset_id INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                last_reset_at TIMESTAMP,
                UNIQUE(section)
            );
            CREATE TABLE IF NOT EXISTS demo_trades (
                id SERIAL PRIMARY KEY,
                section VARCHAR(10) NOT NULL,
                pair VARCHAR(20),
                token_symbol VARCHAR(20),
                direction VARCHAR(5),
                entry_price FLOAT,
                sl FLOAT,
                tp1 FLOAT,
                tp2 FLOAT,
                tp3 FLOAT,
                position_size_usd FLOAT,
                risk_amount_usd FLOAT,
                risk_pct FLOAT,
                current_price FLOAT,
                current_pnl_usd FLOAT,
                current_pnl_pct FLOAT,
                current_x FLOAT,
                result VARCHAR(10),
                exit_price FLOAT,
                final_pnl_usd FLOAT,
                final_pnl_pct FLOAT,
                final_x FLOAT,
                model_id VARCHAR(50),
                model_name VARCHAR(100),
                tier VARCHAR(5),
                score FLOAT,
                source VARCHAR(30),
                notes TEXT,
                tp1_hit BOOLEAN DEFAULT FALSE,
                reset_id INT DEFAULT 0,
                opened_at TIMESTAMP DEFAULT NOW(),
                closed_at TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS demo_transactions (
                id SERIAL PRIMARY KEY,
                section VARCHAR(10),
                type VARCHAR(20),
                amount FLOAT,
                balance_after FLOAT,
                description TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );
            """)
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


def update_model_fields(model_id, fields: dict):
    allowed = {"pair", "timeframe", "session", "bias", "name", "tier_a", "tier_b", "tier_c", "rules"}
    clean = {k: v for k, v in (fields or {}).items() if k in allowed}
    if not clean:
        return False

    if "rules" in clean and isinstance(clean["rules"], list):
        clean["rules"] = json.dumps(clean["rules"])

    set_clause = ", ".join([f"{k}=%s" for k in clean.keys()])
    values = list(clean.values()) + [model_id]

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE models SET {set_clause} WHERE id=%s", values)
            updated = cur.rowcount > 0
        conn.commit()
    return updated

def delete_model(model_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM model_versions WHERE model_id=%s", (model_id,))
            cur.execute("DELETE FROM models WHERE id=%s", (model_id,))
        conn.commit()


def delete_all_models():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM model_versions")
            cur.execute("DELETE FROM models")
        conn.commit()


# ── Trades ────────────────────────────────────────────
def log_trade(trade):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO trade_log
                    (pair, model_id, tier, direction, entry_price, sl, tp,
                     rr, session, score, risk_pct, violation, source)
                VALUES (%(pair)s, %(model_id)s, %(tier)s, %(direction)s,
                        %(entry_price)s, %(sl)s, %(tp)s, %(rr)s,
                        %(session)s, %(score)s, %(risk_pct)s, %(violation)s, %(source)s)
                RETURNING id
            """, {**trade, "source": trade.get("source", "signal")})
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


def save_news_event(event: dict) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM news_events
                WHERE event_name=%s AND pair=%s AND event_time_utc=%s
                LIMIT 1
                """,
                (event.get("name"), event.get("pair"), event.get("time_utc")),
            )
            exists = cur.fetchone()
            if exists:
                return int(exists["id"])
            cur.execute(
                """
                INSERT INTO news_events
                (event_name, pair, event_time_utc, impact, forecast, previous, actual, source)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (
                    event.get("name"),
                    event.get("pair"),
                    event.get("time_utc"),
                    event.get("impact"),
                    event.get("forecast"),
                    event.get("previous"),
                    event.get("actual"),
                    event.get("source"),
                ),
            )
            row_id = int(cur.fetchone()["id"])
        conn.commit()
    return row_id


def get_unsent_briefings(minutes_ahead: int) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM news_events
                WHERE briefing_sent=FALSE
                  AND suppressed=FALSE
                  AND event_time_utc BETWEEN NOW() + (%s || ' minutes')::interval AND NOW() + (%s || ' minutes')::interval
                ORDER BY event_time_utc ASC
                """,
                (minutes_ahead - 2, minutes_ahead),
            )
            return [dict(r) for r in cur.fetchall()]


def get_unsent_signals() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM news_events
                WHERE signal_sent=FALSE
                  AND suppressed=FALSE
                  AND event_time_utc BETWEEN NOW() - INTERVAL '60 seconds' AND NOW() + INTERVAL '60 seconds'
                ORDER BY event_time_utc ASC
                """
            )
            return [dict(r) for r in cur.fetchall()]


def mark_briefing_sent(event_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE news_events SET briefing_sent=TRUE WHERE id=%s", (event_id,))
        conn.commit()


def mark_signal_sent(event_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE news_events SET signal_sent=TRUE WHERE id=%s", (event_id,))
        conn.commit()


def log_news_trade(trade: dict) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO news_trades
                (news_event_id, pair, direction, entry_price, sl, tp1, tp2, tp3, rr, pre_news_price)
                VALUES (%(news_event_id)s,%(pair)s,%(direction)s,%(entry_price)s,%(sl)s,%(tp1)s,%(tp2)s,%(tp3)s,%(rr)s,%(pre_news_price)s)
                RETURNING id
                """,
                trade,
            )
            tid = int(cur.fetchone()["id"])
        conn.commit()
    return tid


def suppress_news_event(event_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE news_events SET suppressed=TRUE WHERE id=%s", (event_id,))
        conn.commit()


def get_news_event(event_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM news_events WHERE id=%s", (event_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def get_news_trade(trade_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM news_trades WHERE id=%s", (trade_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def get_news_history(limit: int = 10):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ne.event_name, ne.pair, ne.direction, nt.result,
                       CASE
                         WHEN ne.direction='bullish' AND nt.direction='BUY' AND nt.result='TP' THEN TRUE
                         WHEN ne.direction='bearish' AND nt.direction='SELL' AND nt.result='TP' THEN TRUE
                         WHEN nt.result IS NULL THEN NULL
                         ELSE FALSE
                       END AS correct
                FROM news_events ne
                LEFT JOIN news_trades nt ON nt.news_event_id = ne.id
                ORDER BY ne.created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]


# ── Degen Models ────────────────────────────────────────────
def _decode_json_field(v, default):
    if isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v) if v else default
    except Exception:
        return default


def _normalize_degen_model(row):
    if not row:
        return None
    d = dict(row)
    d["chains"] = _decode_json_field(d.get("chains"), ["SOL"])
    d["rules"] = _decode_json_field(d.get("rules"), [])
    return d


def get_all_degen_models() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM degen_models ORDER BY created_at DESC")
            return [_normalize_degen_model(r) for r in cur.fetchall()]


def get_degen_model(model_id: str) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM degen_models WHERE id=%s", (model_id,))
            return _normalize_degen_model(cur.fetchone())


def get_active_degen_models() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM degen_models WHERE status='active' ORDER BY created_at DESC")
            return [_normalize_degen_model(r) for r in cur.fetchall()]


def insert_degen_model(model: dict) -> None:
    payload = dict(model)
    payload["chains"] = json.dumps(payload.get("chains", ["SOL"]))
    payload["rules"] = json.dumps(payload.get("rules", []))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO degen_models (
                    id,name,description,status,chains,rules,min_score,max_risk_level,min_moon_score,max_risk_score,
                    min_liquidity,max_token_age_minutes,min_token_age_minutes,require_lp_locked,require_mint_revoked,
                    require_verified,block_serial_ruggers,max_dev_rug_count,max_top1_holder_pct,min_holder_count,
                    alert_count,last_alert_at,version
                ) VALUES (
                    %(id)s,%(name)s,%(description)s,%(status)s,%(chains)s,%(rules)s,%(min_score)s,%(max_risk_level)s,%(min_moon_score)s,%(max_risk_score)s,
                    %(min_liquidity)s,%(max_token_age_minutes)s,%(min_token_age_minutes)s,%(require_lp_locked)s,%(require_mint_revoked)s,
                    %(require_verified)s,%(block_serial_ruggers)s,%(max_dev_rug_count)s,%(max_top1_holder_pct)s,%(min_holder_count)s,
                    %(alert_count)s,%(last_alert_at)s,%(version)s
                )
                """,
                {
                    "id": payload["id"], "name": payload["name"], "description": payload.get("description"), "status": payload.get("status", "inactive"),
                    "chains": payload["chains"], "rules": payload["rules"], "min_score": payload.get("min_score", 50),
                    "max_risk_level": payload.get("max_risk_level", "HIGH"), "min_moon_score": payload.get("min_moon_score", 40),
                    "max_risk_score": payload.get("max_risk_score", 60), "min_liquidity": payload.get("min_liquidity", 5000),
                    "max_token_age_minutes": payload.get("max_token_age_minutes", 120), "min_token_age_minutes": payload.get("min_token_age_minutes", 2),
                    "require_lp_locked": payload.get("require_lp_locked", False), "require_mint_revoked": payload.get("require_mint_revoked", False),
                    "require_verified": payload.get("require_verified", False), "block_serial_ruggers": payload.get("block_serial_ruggers", True),
                    "max_dev_rug_count": payload.get("max_dev_rug_count", 0), "max_top1_holder_pct": payload.get("max_top1_holder_pct", 20),
                    "min_holder_count": payload.get("min_holder_count", 10), "alert_count": payload.get("alert_count", 0),
                    "last_alert_at": payload.get("last_alert_at"), "version": payload.get("version", 1),
                },
            )
        conn.commit()


def set_degen_model_status(model_id: str, status: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE degen_models SET status=%s WHERE id=%s", (status, model_id))
        conn.commit()


def delete_degen_model(model_id: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM degen_model_alerts WHERE model_id=%s", (model_id,))
            cur.execute("DELETE FROM degen_model_versions WHERE model_id=%s", (model_id,))
            cur.execute("DELETE FROM degen_models WHERE id=%s", (model_id,))
        conn.commit()


def delete_all_degen_models() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM degen_model_alerts")
            cur.execute("DELETE FROM degen_model_versions")
            cur.execute("DELETE FROM degen_models")
        conn.commit()


def update_degen_model(model_id: str, fields: dict) -> None:
    if not fields:
        return
    allowed = {
        "name", "description", "status", "chains", "rules", "min_score", "max_risk_level", "min_moon_score", "max_risk_score",
        "min_liquidity", "max_token_age_minutes", "min_token_age_minutes", "require_lp_locked", "require_mint_revoked", "require_verified",
        "block_serial_ruggers", "max_dev_rug_count", "max_top1_holder_pct", "min_holder_count", "alert_count", "last_alert_at", "version"
    }
    keys = [k for k in fields if k in allowed]
    if not keys:
        return
    params = []
    values = []
    for k in keys:
        params.append(f"{k}=%s")
        v = fields[k]
        if k in {"chains", "rules"}:
            v = json.dumps(v)
        values.append(v)
    values.append(model_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE degen_models SET {', '.join(params)} WHERE id=%s", values)
        conn.commit()


def log_degen_model_alert(model_id, token_id, address, symbol, score, risk_score, moon_score, triggered_rules) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO degen_model_alerts (model_id, token_id, token_address, token_symbol, score, risk_score, moon_score, triggered_rules)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (model_id, token_id, address, symbol, score, risk_score, moon_score, json.dumps(triggered_rules or [])),
            )
            cur.execute("UPDATE degen_models SET alert_count=alert_count+1,last_alert_at=NOW() WHERE id=%s", (model_id,))
        conn.commit()


def get_degen_model_stats(model_id: str) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total_alerts FROM degen_model_alerts WHERE model_id=%s", (model_id,))
            total = int(cur.fetchone()["total_alerts"])
            cur.execute(
                """
                SELECT token_symbol, token_address FROM degen_model_alerts
                WHERE model_id=%s ORDER BY alerted_at DESC LIMIT 5
                """,
                (model_id,),
            )
            last = [f"{r['token_symbol']}" for r in cur.fetchall()]
            cur.execute(
                """
                SELECT token_symbol, moon_score FROM degen_model_alerts
                WHERE model_id=%s ORDER BY moon_score DESC NULLS LAST LIMIT 1
                """,
                (model_id,),
            )
            best = cur.fetchone()
            return {
                "total_alerts": total,
                "last_tokens": last,
                "best_find": f"{best['token_symbol']} ({best['moon_score']})" if best else None,
            }


def save_degen_model_version(model_id: str) -> None:
    model = get_degen_model(model_id)
    if not model:
        return
    version = int(model.get("version") or 1)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO degen_model_versions (model_id, version, snapshot) VALUES (%s,%s,%s)",
                (model_id, version, json.dumps(model)),
            )
            cur.execute("UPDATE degen_models SET version=version+1 WHERE id=%s", (model_id,))
        conn.commit()


def clone_degen_model(model_id: str) -> str:
    model = get_degen_model(model_id)
    if not model:
        return ""
    new_id = str(__import__("uuid").uuid4())[:12]
    model["id"] = new_id
    model["name"] = f"{model['name']} (Copy)"
    model["status"] = "inactive"
    model["version"] = 1
    model["alert_count"] = 0
    model["last_alert_at"] = None
    insert_degen_model(model)
    return new_id


def get_degen_model_versions(model_id: str) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM degen_model_versions WHERE model_id=%s ORDER BY version DESC", (model_id,))
            rows = cur.fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["snapshot"] = _decode_json_field(d.get("snapshot"), {})
                out.append(d)
            return out


def has_recent_degen_model_alert(model_id: str, token_address: str, hours: int = 2) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM degen_model_alerts
                WHERE model_id=%s AND token_address=%s AND alerted_at >= NOW() - (%s || ' hours')::interval
                LIMIT 1
                """,
                (model_id, token_address, hours),
            )
            return cur.fetchone() is not None


def increment_degen_model_alert_count(model_id: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE degen_models SET alert_count=alert_count+1,last_alert_at=NOW() WHERE id=%s", (model_id,))
        conn.commit()


def get_recent_degen_tokens(limit: int = 100) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id,address,symbol,chain,token_data
                FROM degen_tokens
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = []
            for r in cur.fetchall():
                d = dict(r)
                extra = _decode_json_field(d.get("token_data"), {})
                extra.update({"id": d.get("id"), "address": d.get("address"), "symbol": d.get("symbol"), "chain": d.get("chain")})
                rows.append(extra)
            return rows


def get_degen_rule_performance(model_id: str) -> list:
    model = get_degen_model(model_id)
    if not model:
        return []
    rule_ids = [r.get("id") for r in model.get("rules", [])]
    if not rule_ids:
        return []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT triggered_rules FROM degen_model_alerts WHERE model_id=%s", (model_id,))
            alerts = cur.fetchall()
            cur.execute(
                """
                SELECT dma.triggered_rules, dt.result
                FROM degen_model_alerts dma
                LEFT JOIN degen_trades dt ON dt.token_id = dma.token_id
                WHERE dma.model_id=%s
                """,
                (model_id,),
            )
            joined = cur.fetchall()

    total_alerts = max(len(alerts), 1)
    results = []
    for rid in rule_ids:
        rule_name = rid
        passed = 0
        entry = 0
        wins = 0
        for row in joined:
            triggered = _decode_json_field(row.get("triggered_rules"), [])
            triggered_ids = {x.get("id") if isinstance(x, dict) else x for x in triggered}
            if rid in triggered_ids:
                passed += 1
                if row.get("result") is not None:
                    entry += 1
                    if str(row.get("result")).upper() == "WIN":
                        wins += 1
        pass_rate = round((passed / total_alerts) * 100, 2)
        entry_rate = round((entry / passed) * 100, 2) if passed else 0.0
        win_rate = round((wins / entry) * 100, 2) if entry else 0.0
        contribution = round((pass_rate * win_rate) / 100, 2)
        results.append({
            "rule_id": rid,
            "rule_name": rule_name,
            "samples": passed,
            "pass_rate": pass_rate,
            "entry_rate": entry_rate,
            "win_rate": win_rate,
            "contribution_score": contribution,
        })
    return results


# ── Wallet Tracker ────────────────────────────────────────────
def add_tracked_wallet(wallet: dict) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tracked_wallets
                (address, chain, label, tier, tier_label, credibility, wallet_age_days, tx_count, estimated_win_rate, total_value_usd, portfolio_size_label, last_tx_hash, alert_on_buy, alert_on_sell, alert_min_usd, active, notes)
                VALUES (%(address)s,%(chain)s,%(label)s,%(tier)s,%(tier_label)s,%(credibility)s,%(age_days)s,%(tx_count)s,%(estimated_win_rate)s,%(total_value_usd)s,%(portfolio_size_label)s,%(last_tx_hash)s,%(alert_on_buy)s,%(alert_on_sell)s,%(alert_min_usd)s,TRUE,%(notes)s)
                ON CONFLICT (address, chain) DO UPDATE SET
                    label=EXCLUDED.label, tier=EXCLUDED.tier, tier_label=EXCLUDED.tier_label, credibility=EXCLUDED.credibility,
                    wallet_age_days=EXCLUDED.wallet_age_days, tx_count=EXCLUDED.tx_count, estimated_win_rate=EXCLUDED.estimated_win_rate,
                    total_value_usd=EXCLUDED.total_value_usd, portfolio_size_label=EXCLUDED.portfolio_size_label,
                    alert_on_buy=EXCLUDED.alert_on_buy, alert_on_sell=EXCLUDED.alert_on_sell, alert_min_usd=EXCLUDED.alert_min_usd
                RETURNING id
            """, {**wallet, "notes": wallet.get("notes"), "last_tx_hash": wallet.get("last_tx_hash")})
            wid = int(cur.fetchone()["id"])
        conn.commit()
    return wid


def get_tracked_wallets(active_only: bool = True) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            sql = "SELECT * FROM tracked_wallets" + (" WHERE active=TRUE" if active_only else "") + " ORDER BY added_at DESC"
            cur.execute(sql)
            return [dict(r) for r in cur.fetchall()]


def get_tracked_wallet(wallet_id: int) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM tracked_wallets WHERE id=%s", (wallet_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def get_tracked_wallet_by_address(address: str, chain: str) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM tracked_wallets WHERE address=%s AND chain=%s", (address, chain))
            row = cur.fetchone()
            return dict(row) if row else None


def update_wallet_last_tx(wallet_id: int, tx_hash: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE tracked_wallets SET last_tx_hash=%s,last_checked_at=NOW() WHERE id=%s", (tx_hash, wallet_id))
        conn.commit()


def update_wallet_profile(wallet_id: int, profile: dict) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE tracked_wallets
                SET tier=%s,tier_label=%s,credibility=%s,wallet_age_days=%s,tx_count=%s,estimated_win_rate=%s,total_value_usd=%s,portfolio_size_label=%s,last_checked_at=NOW()
                WHERE id=%s
            """, (profile.get("tier"), profile.get("tier_label"), profile.get("credibility"), profile.get("age_days"), profile.get("tx_count"), profile.get("estimated_win_rate"), profile.get("total_value_usd"), profile.get("portfolio_size_label"), wallet_id))
        conn.commit()


def set_wallet_active(wallet_id: int, active: bool) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE tracked_wallets SET active=%s WHERE id=%s", (active, wallet_id))
        conn.commit()


def delete_tracked_wallet(wallet_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tracked_wallets WHERE id=%s", (wallet_id,))
        conn.commit()


def log_wallet_transaction(tx: dict) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO wallet_transactions
                (wallet_id,wallet_address,tx_hash,chain,tx_type,token_address,token_name,token_symbol,amount_token,amount_usd,price_per_token,token_risk_score,token_moon_score,token_risk_level,alert_sent,tx_timestamp)
                VALUES (%(wallet_id)s,%(wallet_address)s,%(tx_hash)s,%(chain)s,%(tx_type)s,%(token_address)s,%(token_name)s,%(token_symbol)s,%(amount_token)s,%(amount_usd)s,%(price_per_token)s,%(token_risk_score)s,%(token_moon_score)s,%(token_risk_level)s,%(alert_sent)s,%(tx_timestamp)s)
                ON CONFLICT (tx_hash) DO UPDATE SET alert_sent=EXCLUDED.alert_sent
                RETURNING id
            """, tx)
            row = cur.fetchone()
            wid = int(row["id"]) if row else 0
        conn.commit()
    return wid


def get_wallet_transactions(wallet_id: int, limit: int = 20) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM wallet_transactions WHERE wallet_id=%s ORDER BY tx_timestamp DESC NULLS LAST, detected_at DESC LIMIT %s", (wallet_id, limit))
            return [dict(r) for r in cur.fetchall()]


def get_recent_wallet_alerts(hours: int = 24) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT wt.*, tw.label
                FROM wallet_transactions wt
                LEFT JOIN tracked_wallets tw ON tw.id = wt.wallet_id
                WHERE wt.detected_at >= NOW() - (%s || ' hours')::interval
                ORDER BY wt.detected_at DESC
            """, (hours,))
            return [dict(r) for r in cur.fetchall()]


def log_copy_trade(trade: dict) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO wallet_copy_trades
                (wallet_tx_id, token_address, token_symbol, entry_price, entry_usd, tp1, tp2, tp3, sl, result, exit_price, pnl_x, closed_at)
                VALUES (%(wallet_tx_id)s,%(token_address)s,%(token_symbol)s,%(entry_price)s,%(entry_usd)s,%(tp1)s,%(tp2)s,%(tp3)s,%(sl)s,%(result)s,%(exit_price)s,%(pnl_x)s,%(closed_at)s)
                RETURNING id
            """, {**trade, "result": trade.get("result"), "exit_price": trade.get("exit_price"), "pnl_x": trade.get("pnl_x"), "closed_at": trade.get("closed_at")})
            tid = int(cur.fetchone()["id"])
        conn.commit()
    return tid


def log_degen_copy_trade(token_symbol: str, token_id: int) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO degen_trades (token_id, token_symbol, result) VALUES (%s,%s,%s) RETURNING id", (token_id, token_symbol, None))
            tid = int(cur.fetchone()["id"])
        conn.commit()
    return tid


def get_best_wallet_calls(limit: int = 20) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COALESCE(tw.label, wt.wallet_address) AS wallet_label, wct.token_symbol, wct.entry_price, wct.pnl_x
                FROM wallet_copy_trades wct
                LEFT JOIN wallet_transactions wt ON wt.id = wct.wallet_tx_id
                LEFT JOIN tracked_wallets tw ON tw.id = wt.wallet_id
                ORDER BY wct.pnl_x DESC NULLS LAST, wct.logged_at DESC
                LIMIT %s
            """, (limit,))
            return [dict(r) for r in cur.fetchall()]

# ── Degen token helpers / postmortem / narrative ───────────────────────────
def upsert_degen_token_snapshot(token: dict) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO degen_tokens (address, symbol, chain, token_data, initial_risk_score, initial_scored_at, latest_risk_score, last_rescored_at, trajectory, initial_reply_count, replies_per_hour, social_velocity_score, token_profile, holders_last_checked_at)
                VALUES (%s,%s,%s,%s,%s,NOW(),%s,NOW(),%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (address) DO UPDATE SET
                    symbol=EXCLUDED.symbol,
                    chain=EXCLUDED.chain,
                    token_data=EXCLUDED.token_data,
                    latest_risk_score=EXCLUDED.latest_risk_score,
                    last_rescored_at=NOW(),
                    trajectory=EXCLUDED.trajectory,
                    replies_per_hour=EXCLUDED.replies_per_hour,
                    social_velocity_score=EXCLUDED.social_velocity_score,
                    token_profile=EXCLUDED.token_profile
                RETURNING id
                """,
                (
                    token.get("address"), token.get("symbol"), token.get("chain", "SOL"), json.dumps(token),
                    token.get("initial_risk_score"), token.get("latest_risk_score"), token.get("trajectory"),
                    token.get("initial_reply_count"), token.get("replies_per_hour"), token.get("social_velocity_score"), token.get("token_profile"),
                ),
            )
            tid = int(cur.fetchone()["id"])
        conn.commit()
    return tid


def update_degen_token_rescore(address: str, chain: str, payload: dict) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE degen_tokens
                SET latest_risk_score=%s,last_rescored_at=NOW(),trajectory=%s,token_data=%s
                WHERE address=%s AND chain=%s
                """,
                (payload.get("risk_score"), payload.get("trajectory"), json.dumps(payload), address, chain),
            )
        conn.commit()


def get_degen_token_by_address(address: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM degen_tokens WHERE address=%s", (address,))
            r = cur.fetchone()
            if not r:
                return None
            d = dict(r)
            d.update(_decode_json_field(d.get("token_data"), {}))
            return d


def get_degen_token_by_id(token_id: int) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM degen_tokens WHERE id=%s", (token_id,))
            r = cur.fetchone()
            if not r:
                return None
            d = dict(r)
            d.update(_decode_json_field(d.get("token_data"), {}))
            return d


def mark_degen_token_rugged(token_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE degen_tokens SET rugged=TRUE WHERE id=%s", (token_id,))
        conn.commit()


def insert_rug_postmortem(pm: dict) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO rug_postmortems (token_id,token_address,token_symbol,initial_risk_score,final_risk_score,initial_moon_score,price_at_alert,price_at_rug,drop_pct,time_to_rug_minutes,was_alerted,was_in_watchlist,triggered_risk_factors,missed_signals,detected_at)
                VALUES (%(token_id)s,%(token_address)s,%(token_symbol)s,%(initial_risk_score)s,%(final_risk_score)s,%(initial_moon_score)s,%(price_at_alert)s,%(price_at_rug)s,%(drop_pct)s,%(time_to_rug_minutes)s,%(was_alerted)s,%(was_in_watchlist)s,%(triggered_risk_factors)s,%(missed_signals)s,%(detected_at)s)
                RETURNING id
                """,
                {**pm, "triggered_risk_factors": json.dumps(pm.get("triggered_risk_factors") or []), "missed_signals": json.dumps(pm.get("missed_signals") or [])},
            )
            rid = int(cur.fetchone()["id"])
        conn.commit()
    return rid


def get_rug_postmortem_stats() -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) n, COALESCE(AVG(time_to_rug_minutes),0) avg_mins, SUM(CASE WHEN was_alerted THEN 1 ELSE 0 END) alerted FROM rug_postmortems")
            row = dict(cur.fetchone() or {})
            cur.execute("SELECT jsonb_array_elements_text(triggered_risk_factors) f, COUNT(*) c FROM rug_postmortems GROUP BY f ORDER BY c DESC LIMIT 3")
            top = [r["f"] for r in cur.fetchall()]
            cur.execute("SELECT jsonb_array_elements_text(missed_signals) f, COUNT(*) c FROM rug_postmortems GROUP BY f ORDER BY c DESC LIMIT 3")
            miss = [r["f"] for r in cur.fetchall()]
    total = int(row.get("n") or 0)
    alerted = int(row.get("alerted") or 0)
    return {"total": total, "alerted": alerted, "alerted_pct": round((alerted/total*100),2) if total else 0, "avg_minutes": round(float(row.get("avg_mins") or 0), 1), "top_signals": top, "missed": miss}


def upsert_narrative_trend(narrative: str, week_start, moon_score: int, risk_score: int, volume: float) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO narrative_trends (narrative,token_count,avg_moon_score,avg_risk_score,total_volume,week_start)
                VALUES (%s,1,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
                """,
                (narrative, moon_score, risk_score, volume, week_start),
            )
            cur.execute(
                """
                UPDATE narrative_trends
                SET token_count=token_count+1,
                    avg_moon_score=((avg_moon_score*token_count)+%s)/(token_count+1),
                    avg_risk_score=((avg_risk_score*token_count)+%s)/(token_count+1),
                    total_volume=total_volume+%s,
                    updated_at=NOW()
                WHERE narrative=%s AND week_start=%s
                """,
                (moon_score, risk_score, volume, narrative, week_start),
            )
        conn.commit()


def get_hot_narratives(limit: int = 5) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT narrative, token_count, avg_moon_score, ((token_count*0.6)+(avg_moon_score*0.4)) heat
                FROM narrative_trends
                ORDER BY heat DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]


def get_cold_narratives() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT narrative, token_count, avg_moon_score FROM narrative_trends WHERE token_count < 3 OR avg_moon_score < 40 ORDER BY token_count ASC, avg_moon_score ASC LIMIT 5")
            return [dict(r) for r in cur.fetchall()]


# ── Demo trading ───────────────────────────
def log_demo_transaction(section: str, type: str, amount: float, description: str) -> None:
    acct = get_demo_account(section) or {"balance": 0}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO demo_transactions (section,type,amount,balance_after,description) VALUES (%s,%s,%s,%s,%s)", (section, type, amount, acct.get("balance", 0), description))
        conn.commit()


def get_demo_account(section: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM demo_accounts WHERE section=%s", (section,))
            r = cur.fetchone()
            return dict(r) if r else None


def create_demo_account(section: str, initial_deposit: float) -> dict:
    amt = max(100.0, float(initial_deposit))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO demo_accounts (section,balance,initial_deposit,peak_balance,lowest_balance)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (section) DO UPDATE SET balance=EXCLUDED.balance,initial_deposit=EXCLUDED.initial_deposit,peak_balance=EXCLUDED.peak_balance,lowest_balance=EXCLUDED.lowest_balance
                RETURNING *
                """,
                (section, amt, amt, amt, amt),
            )
            row = dict(cur.fetchone())
        conn.commit()
    log_demo_transaction(section, "deposit", amt, "Initial demo deposit")
    return row


def deposit_demo_funds(section: str, amount: float) -> dict:
    amount = max(0.0, float(amount))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE demo_accounts SET balance=balance+%s, peak_balance=GREATEST(peak_balance,balance+%s) WHERE section=%s RETURNING *", (amount, amount, section))
            row = dict(cur.fetchone())
        conn.commit()
    log_demo_transaction(section, "deposit", amount, "Demo deposit")
    return row


def withdraw_demo_funds(section: str, amount: float) -> dict:
    acct = get_demo_account(section)
    if not acct:
        raise ValueError("Demo account not found")
    amount = min(float(amount), float(acct.get("balance") or 0))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE demo_accounts SET balance=balance-%s, lowest_balance=LEAST(lowest_balance,balance-%s) WHERE section=%s RETURNING *", (amount, amount, section))
            row = dict(cur.fetchone())
        conn.commit()
    log_demo_transaction(section, "withdrawal", -amount, "Demo withdrawal")
    return row


def reset_demo_account(section: str) -> dict:
    acct = get_demo_account(section)
    if not acct:
        raise ValueError("Demo account not found")
    new_reset = int(acct.get("reset_id") or 0) + 1
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE demo_accounts SET balance=initial_deposit,total_pnl=0,total_pnl_pct=0,total_trades=0,winning_trades=0,losing_trades=0,last_reset_at=NOW(),reset_id=%s WHERE section=%s RETURNING *", (new_reset, section))
            row = dict(cur.fetchone())
        conn.commit()
    log_demo_transaction(section, "deposit", row.get("initial_deposit", 0), f"Demo reset #{new_reset}")
    return row


def open_demo_trade(trade: dict) -> int:
    section = trade["section"]
    acct = get_demo_account(section)
    if not acct:
        raise ValueError("No demo account")
    risk = max(0.0, float(trade.get("risk_amount_usd") or 0))
    balance = float(acct.get("balance") or 0)
    if risk > balance:
        risk = balance
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO demo_trades (section,pair,token_symbol,direction,entry_price,sl,tp1,tp2,tp3,position_size_usd,risk_amount_usd,risk_pct,current_price,current_pnl_usd,current_pnl_pct,current_x,model_id,model_name,tier,score,source,notes,reset_id)
                VALUES (%(section)s,%(pair)s,%(token_symbol)s,%(direction)s,%(entry_price)s,%(sl)s,%(tp1)s,%(tp2)s,%(tp3)s,%(position_size_usd)s,%(risk_amount_usd)s,%(risk_pct)s,%(entry_price)s,0,0,1,%(model_id)s,%(model_name)s,%(tier)s,%(score)s,%(source)s,%(notes)s,%(reset_id)s)
                RETURNING id
                """,
                {**trade, "risk_amount_usd": risk, "reset_id": acct.get("reset_id", 0)},
            )
            tid = int(cur.fetchone()["id"])
            cur.execute("UPDATE demo_accounts SET balance=GREATEST(balance-%s,0) WHERE section=%s", (risk, section))
        conn.commit()
    log_demo_transaction(section, "trade_open", -risk, f"Open demo trade #{tid}")
    return tid


def update_demo_trade_pnl(trade_id: int, current_price: float) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM demo_trades WHERE id=%s", (trade_id,))
            tr = dict(cur.fetchone() or {})
            if not tr or tr.get("result"):
                return
            e = float(tr.get("entry_price") or 0)
            size = float(tr.get("position_size_usd") or 0)
            mult = 1 if str(tr.get("direction", "LONG")).upper() in {"LONG", "BUY"} else -1
            pnl_pct = ((float(current_price) - e) / e * 100 * mult) if e else 0
            pnl_usd = size * pnl_pct / 100
            cur.execute("UPDATE demo_trades SET current_price=%s,current_pnl_pct=%s,current_pnl_usd=%s,current_x=%s WHERE id=%s", (current_price, pnl_pct, pnl_usd, 1 + pnl_pct / 100, trade_id))
        conn.commit()


def close_demo_trade(trade_id: int, exit_price: float, result: str) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM demo_trades WHERE id=%s", (trade_id,))
            tr = dict(cur.fetchone() or {})
            if not tr:
                return {}
            e = float(tr.get("entry_price") or 0)
            size = float(tr.get("position_size_usd") or 0)
            risk_amt = float(tr.get("risk_amount_usd") or 0)
            mult = 1 if str(tr.get("direction", "LONG")).upper() in {"LONG", "BUY"} else -1
            pnl_pct = ((float(exit_price) - e) / e * 100 * mult) if e else 0
            pnl_usd = size * pnl_pct / 100
            final_x = 1 + pnl_pct / 100
            cur.execute("UPDATE demo_trades SET result=%s,exit_price=%s,final_pnl_usd=%s,final_pnl_pct=%s,final_x=%s,closed_at=NOW(),current_price=%s,current_pnl_usd=%s,current_pnl_pct=%s WHERE id=%s", (result, exit_price, pnl_usd, pnl_pct, final_x, exit_price, pnl_usd, pnl_pct, trade_id))
            cur.execute(
                """
                UPDATE demo_accounts
                SET balance=balance+%s+%s,
                    total_pnl=COALESCE(total_pnl,0)+%s,
                    total_pnl_pct=CASE WHEN initial_deposit>0 THEN ((COALESCE(total_pnl,0)+%s)/initial_deposit)*100 ELSE 0 END,
                    peak_balance=GREATEST(peak_balance,balance+%s+%s),
                    lowest_balance=LEAST(lowest_balance,balance+%s+%s),
                    total_trades=total_trades+1,
                    winning_trades=winning_trades+CASE WHEN %s>0 THEN 1 ELSE 0 END,
                    losing_trades=losing_trades+CASE WHEN %s<=0 THEN 1 ELSE 0 END
                WHERE section=%s
                RETURNING *
                """,
                (size, pnl_usd, pnl_usd, pnl_usd, size, pnl_usd, size, pnl_usd, pnl_usd, pnl_usd, tr["section"]),
            )
            acct = dict(cur.fetchone() or {})
        conn.commit()
    log_demo_transaction(tr["section"], "trade_close", pnl_usd, f"Close demo trade #{trade_id} ({result})")
    return {**tr, "exit_price": exit_price, "final_pnl_usd": pnl_usd, "final_pnl_pct": pnl_pct, "final_x": final_x, "balance": acct.get("balance")}


def get_open_demo_trades(section: str) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM demo_trades WHERE section=%s AND result IS NULL ORDER BY opened_at DESC", (section,))
            return [dict(r) for r in cur.fetchall()]


def get_demo_trade_history(section: str, limit: int = 50) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM demo_trades WHERE section=%s ORDER BY opened_at DESC LIMIT %s", (section, limit))
            return [dict(r) for r in cur.fetchall()]


def get_demo_stats(section: str) -> dict:
    acct = get_demo_account(section)
    if not acct:
        return {}
    total = int(acct.get("total_trades") or 0)
    win = int(acct.get("winning_trades") or 0)
    acct["win_rate"] = (win / total * 100) if total else 0
    return acct
