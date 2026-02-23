import psycopg2
import psycopg2.extras
from psycopg2 import pool as pg_pool
import json
import time
from datetime import datetime, timedelta, date
from config import DB_URL

_pool = None
_cache = {}
_CACHE_TTL = {
    "active_models": 30,
    "active_degen_models": 30,
    "tracked_wallets": 60,
    "demo_accounts": 10,
}


class _PooledConn:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self._conn.rollback()
        release_conn(self._conn)
        return False

    def __getattr__(self, item):
        return getattr(self._conn, item)


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < _CACHE_TTL.get(key, 30):
        return entry["data"]
    return None


def _cache_set(key: str, data):
    _cache[key] = {"data": data, "ts": time.time()}


def _cache_clear(key: str):
    _cache.pop(key, None)


def _ensure_pool():
    global _pool
    if _pool is None:
        _pool = pg_pool.ThreadedConnectionPool(
            minconn=3,
            maxconn=20,
            dsn=DB_URL,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )


def init_pool():
    """Backward-compatible public pool initializer used by main startup."""
    _ensure_pool()


def acquire_conn(timeout: float = 10.0):
    _ensure_pool()
    start = time.time()
    while True:
        try:
            conn = _pool.getconn()
            if conn:
                return conn
        except Exception:
            pass
        if time.time() - start > timeout:
            raise RuntimeError(
                f"DB pool exhausted — no connection available after {timeout}s"
            )
        time.sleep(0.1)


def get_conn(timeout: float = 10.0):
    return _PooledConn(acquire_conn(timeout=timeout))


def release_conn(conn):
    if _pool is None or conn is None:
        return
    raw_conn = getattr(conn, "_conn", conn)
    try:
        _pool.putconn(raw_conn)
    except Exception:
        try:
            raw_conn.close()
        except Exception:
            pass


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
        rr_target  FLOAT        DEFAULT 2.0,
        rules      JSONB        NOT NULL DEFAULT '[]',
        created_at TIMESTAMP    DEFAULT NOW(),
        updated_at TIMESTAMP    DEFAULT NOW()
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
    ALTER TABLE models ADD COLUMN IF NOT EXISTS description TEXT;
    ALTER TABLE models ADD COLUMN IF NOT EXISTS min_score FLOAT;
    ALTER TABLE models ADD COLUMN IF NOT EXISTS rr_target FLOAT DEFAULT 2.0;
    ALTER TABLE models ADD COLUMN IF NOT EXISTS tier_a_threshold FLOAT;
    ALTER TABLE models ADD COLUMN IF NOT EXISTS tier_b_threshold FLOAT;
    ALTER TABLE models ADD COLUMN IF NOT EXISTS tier_c_threshold FLOAT;
    ALTER TABLE models ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();
    ALTER TABLE models ADD COLUMN IF NOT EXISTS phase_timeframes JSONB DEFAULT '{"1":"4h","2":"1h","3":"15m","4":"5m"}';
    ALTER TABLE models ADD COLUMN IF NOT EXISTS regime_managed BOOLEAN DEFAULT FALSE;
    ALTER TABLE models ADD COLUMN IF NOT EXISTS quality_grade VARCHAR(5);
    ALTER TABLE models ADD COLUMN IF NOT EXISTS min_quality_grade VARCHAR(5);

    ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS model_name VARCHAR(100);
    ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS direction VARCHAR(20) DEFAULT 'Bullish';
    ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS timeframe VARCHAR(10);
    ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS phase VARCHAR(20);
    ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS quality_grade VARCHAR(5);
    ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS risk_level VARCHAR(10);
    ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS price_at_tp FLOAT;
    ALTER TABLE news_events ADD COLUMN IF NOT EXISTS suppressed BOOLEAN DEFAULT FALSE;

    CREATE TABLE IF NOT EXISTS pending_setups (
        id                  SERIAL PRIMARY KEY,
        model_id            VARCHAR(50) NOT NULL,
        model_name          VARCHAR(100),
        pair                VARCHAR(20) NOT NULL,
        timeframe           VARCHAR(10),
        direction           VARCHAR(10),
        entry_price         FLOAT,
        sl                  FLOAT,
        tp1                 FLOAT,
        tp2                 FLOAT,
        tp3                 FLOAT,
        current_score       FLOAT,
        max_possible_score  FLOAT,
        score_pct           FLOAT,
        min_score_threshold FLOAT,
        passed_rules        JSONB,
        failed_rules        JSONB,
        mandatory_passed    JSONB,
        mandatory_failed    JSONB,
        rule_snapshots      JSONB,
        telegram_message_id BIGINT,
        telegram_chat_id    BIGINT,
        status              VARCHAR(20) DEFAULT 'pending',
        first_detected_at   TIMESTAMP DEFAULT NOW(),
        last_updated_at     TIMESTAMP DEFAULT NOW(),
        promoted_at         TIMESTAMP,
        expired_at          TIMESTAMP,
        check_count         INT DEFAULT 1,
        peak_score_pct      FLOAT,
        UNIQUE(model_id, pair, timeframe)
    );

    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS model_name VARCHAR(100);
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS direction VARCHAR(10);
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS entry_price FLOAT;
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS sl FLOAT;
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS tp1 FLOAT;
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS tp2 FLOAT;
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS tp3 FLOAT;
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS current_score FLOAT;
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS max_possible_score FLOAT;
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS score_pct FLOAT;
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS min_score_threshold FLOAT;
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS passed_rules JSONB;
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS failed_rules JSONB;
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS mandatory_passed JSONB;
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS mandatory_failed JSONB;
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS rule_snapshots JSONB;
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS telegram_message_id BIGINT;
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS telegram_chat_id BIGINT;
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'pending';
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS first_detected_at TIMESTAMP DEFAULT NOW();
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS last_updated_at TIMESTAMP DEFAULT NOW();
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS promoted_at TIMESTAMP;
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS expired_at TIMESTAMP;
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS check_count INT DEFAULT 1;
    ALTER TABLE IF EXISTS pending_setups ADD COLUMN IF NOT EXISTS peak_score_pct FLOAT;

    CREATE TABLE IF NOT EXISTS setup_phases (
        id                  SERIAL PRIMARY KEY,
        model_id            VARCHAR(50) NOT NULL,
        model_name          VARCHAR(120),
        pair                VARCHAR(20) NOT NULL,
        direction           VARCHAR(10) NOT NULL,
        overall_status      VARCHAR(20) DEFAULT 'phase1',
        check_count         INT DEFAULT 0,

        phase1_status       VARCHAR(20) DEFAULT 'pending',
        phase1_score        FLOAT DEFAULT 0,
        phase1_max_score    FLOAT DEFAULT 0,
        phase1_passed_rules JSONB DEFAULT '[]',
        phase1_failed_rules JSONB DEFAULT '[]',
        phase1_data         JSONB DEFAULT '{}',
        phase1_completed_at TIMESTAMP,
        phase1_expires_at   TIMESTAMP,

        phase2_status       VARCHAR(20) DEFAULT 'waiting',
        phase2_score        FLOAT DEFAULT 0,
        phase2_max_score    FLOAT DEFAULT 0,
        phase2_passed_rules JSONB DEFAULT '[]',
        phase2_failed_rules JSONB DEFAULT '[]',
        phase2_data         JSONB DEFAULT '{}',
        phase2_completed_at TIMESTAMP,
        phase2_expires_at   TIMESTAMP,

        phase3_status       VARCHAR(20) DEFAULT 'waiting',
        phase3_score        FLOAT DEFAULT 0,
        phase3_max_score    FLOAT DEFAULT 0,
        phase3_passed_rules JSONB DEFAULT '[]',
        phase3_failed_rules JSONB DEFAULT '[]',
        phase3_data         JSONB DEFAULT '{}',
        phase3_completed_at TIMESTAMP,
        phase3_expires_at   TIMESTAMP,

        phase4_status       VARCHAR(20) DEFAULT 'waiting',
        phase4_score        FLOAT DEFAULT 0,
        phase4_max_score    FLOAT DEFAULT 0,
        phase4_passed_rules JSONB DEFAULT '[]',
        phase4_failed_rules JSONB DEFAULT '[]',
        phase4_data         JSONB DEFAULT '{}',
        phase4_completed_at TIMESTAMP,
        phase4_expires_at   TIMESTAMP,

        alert_message_id    BIGINT,
        entry_price         FLOAT,
        stop_loss           FLOAT,
        tp1                 FLOAT,
        tp2                 FLOAT,
        tp3                 FLOAT,

        created_at          TIMESTAMP DEFAULT NOW(),
        last_updated_at     TIMESTAMP DEFAULT NOW(),

        UNIQUE(model_id, pair, direction)
    );

    CREATE INDEX IF NOT EXISTS idx_setup_phases_status ON setup_phases (overall_status);

    CREATE TABLE IF NOT EXISTS alert_lifecycle (
        id               SERIAL PRIMARY KEY,
        setup_phase_id   INT REFERENCES setup_phases(id) ON DELETE CASCADE,
        model_id         VARCHAR(50) NOT NULL,
        pair             VARCHAR(20) NOT NULL,
        direction        VARCHAR(10) NOT NULL,
        entry_price      FLOAT,
        alert_sent_at    TIMESTAMP DEFAULT NOW(),
        entry_touched    BOOLEAN DEFAULT FALSE,
        entry_touched_at TIMESTAMP,
        phase4_result    VARCHAR(20),
        phase4_message   TEXT,
        phase4_sent_at   TIMESTAMP,
        outcome          VARCHAR(20),
        closed_at        TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_alert_lifecycle_setup_phase_id ON alert_lifecycle (setup_phase_id);
    CREATE INDEX IF NOT EXISTS idx_alert_lifecycle_outcome ON alert_lifecycle (outcome);

    CREATE TABLE IF NOT EXISTS model_performance (
        model_id        VARCHAR(50) PRIMARY KEY,
        total_alerts    INT DEFAULT 0,
        entries_touched INT DEFAULT 0,
        phase4_confirms INT DEFAULT 0,
        phase4_fails    INT DEFAULT 0,
        demo_trades     INT DEFAULT 0,
        demo_wins       INT DEFAULT 0,
        demo_losses     INT DEFAULT 0,
        demo_win_rate   FLOAT DEFAULT 0,
        avg_r           FLOAT DEFAULT 0,
        updated_at      TIMESTAMP DEFAULT NOW()
    );

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
        active                BOOLEAN      DEFAULT FALSE,
        regime_managed        BOOLEAN      DEFAULT FALSE,
        strategy              VARCHAR(50)  DEFAULT 'momentum',
        bias                  VARCHAR(20)  DEFAULT 'Both',
        pair                  VARCHAR(20)  DEFAULT 'ALL',
        chains                JSONB        DEFAULT '["SOL"]',
        rules                 JSONB        NOT NULL DEFAULT '[]',
        mandatory_rules       JSONB        NOT NULL DEFAULT '[]',
        phase_timeframes      JSONB        DEFAULT '{}',
        min_score             FLOAT        DEFAULT 50,
        min_score_threshold   FLOAT        DEFAULT 50.0,
        max_risk_level        VARCHAR(20)  DEFAULT 'HIGH',
        min_moon_score        INT          DEFAULT 40,
        max_risk_score        INT          DEFAULT 60,
        min_liquidity         FLOAT        DEFAULT 5000,
        min_age_minutes       INT          DEFAULT 5,
        max_age_minutes       INT          DEFAULT 120,
        max_token_age_minutes INT          DEFAULT 120,
        min_token_age_minutes INT          DEFAULT 2,
        risk_per_trade_pct    FLOAT        DEFAULT 1.0,
        max_open_trades       INT          DEFAULT 3,
        require_lp_locked     BOOLEAN      DEFAULT FALSE,
        require_mint_revoked  BOOLEAN      DEFAULT FALSE,
        require_verified      BOOLEAN      DEFAULT FALSE,
        block_serial_ruggers  BOOLEAN      DEFAULT TRUE,
        max_dev_rug_count     INT          DEFAULT 0,
        max_top1_holder_pct   FLOAT        DEFAULT 20,
        min_holder_count      INT          DEFAULT 10,
        alert_count           INT          DEFAULT 0,
        total_alerts          INT          DEFAULT 0,
        total_wins            INT          DEFAULT 0,
        total_losses          INT          DEFAULT 0,
        quality_grade         VARCHAR(5),
        last_alert_at         TIMESTAMP,
        created_at            TIMESTAMP    DEFAULT NOW(),
        updated_at            TIMESTAMP    DEFAULT NOW(),
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
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT FALSE;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS regime_managed BOOLEAN DEFAULT FALSE;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS strategy VARCHAR(50) DEFAULT 'momentum';
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS bias VARCHAR(20) DEFAULT 'Both';
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS pair VARCHAR(20) DEFAULT 'ALL';
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS chains JSONB DEFAULT '["SOL"]';
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS rules JSONB NOT NULL DEFAULT '[]';
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS mandatory_rules JSONB DEFAULT '[]';
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS phase_timeframes JSONB DEFAULT '{}';
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS min_score FLOAT DEFAULT 50;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS min_score_threshold FLOAT DEFAULT 50.0;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS max_risk_level VARCHAR(20) DEFAULT 'HIGH';
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS min_moon_score INT DEFAULT 40;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS max_risk_score INT DEFAULT 60;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS min_liquidity FLOAT DEFAULT 5000;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS min_age_minutes INT DEFAULT 5;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS max_age_minutes INT DEFAULT 120;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS max_token_age_minutes INT DEFAULT 120;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS min_token_age_minutes INT DEFAULT 2;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS risk_per_trade_pct FLOAT DEFAULT 1.0;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS max_open_trades INT DEFAULT 3;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS require_lp_locked BOOLEAN DEFAULT FALSE;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS require_mint_revoked BOOLEAN DEFAULT FALSE;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS require_verified BOOLEAN DEFAULT FALSE;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS block_serial_ruggers BOOLEAN DEFAULT TRUE;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS max_dev_rug_count INT DEFAULT 0;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS max_top1_holder_pct FLOAT DEFAULT 20;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS min_holder_count INT DEFAULT 10;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS alert_count INT DEFAULT 0;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS total_alerts INT DEFAULT 0;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS total_wins INT DEFAULT 0;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS total_losses INT DEFAULT 0;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS quality_grade VARCHAR(5);
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS last_alert_at TIMESTAMP;
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();
    ALTER TABLE degen_models ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();
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
            ALTER TABLE degen_tokens ADD COLUMN IF NOT EXISTS holder_check_progress INT DEFAULT 0;
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
                starting_balance FLOAT DEFAULT 1000,
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
            ALTER TABLE demo_accounts ADD COLUMN IF NOT EXISTS starting_balance FLOAT DEFAULT 1000;
            UPDATE demo_accounts
            SET starting_balance = COALESCE(starting_balance, initial_deposit, 1000);
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
            ALTER TABLE demo_trades ADD COLUMN IF NOT EXISTS remaining_size_usd FLOAT;
            ALTER TABLE demo_trades ADD COLUMN IF NOT EXISTS partial_closes JSONB DEFAULT '[]';
            ALTER TABLE demo_trades ADD COLUMN IF NOT EXISTS time_stop_minutes INT DEFAULT 30;
            ALTER TABLE demo_trades ADD COLUMN IF NOT EXISTS margin_reserved FLOAT DEFAULT 0;
            UPDATE demo_trades
            SET margin_reserved = COALESCE(risk_amount_usd, 0)
            WHERE margin_reserved IS NULL OR margin_reserved = 0;
            CREATE TABLE IF NOT EXISTS chart_analyses (
                id               SERIAL PRIMARY KEY,
                analysis_type    VARCHAR(10),
                pair_estimate    VARCHAR(20),
                timeframe        VARCHAR(20),
                action           VARCHAR(10),
                bias_direction   VARCHAR(10),
                confluence_score INT,
                setup_present    BOOLEAN,
                setup_type       VARCHAR(100),
                entry_zone       VARCHAR(50),
                stop_loss        VARCHAR(50),
                take_profit_1    VARCHAR(50),
                take_profit_2    VARCHAR(50),
                take_profit_3    VARCHAR(50),
                risk_reward      VARCHAR(20),
                full_result      JSONB,
                demo_trade_id    INT REFERENCES demo_trades(id),
                analysed_at      TIMESTAMP DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS degen_watchlist (
                id SERIAL PRIMARY KEY,
                address VARCHAR(100) UNIQUE,
                symbol VARCHAR(20),
                name VARCHAR(100),
                chain VARCHAR(20),
                added_at TIMESTAMP DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS ca_monitors (
                id              SERIAL PRIMARY KEY,
                address         VARCHAR(100) NOT NULL,
                symbol          VARCHAR(20),
                name            VARCHAR(100),
                chain           VARCHAR(20),
                price_at_add    FLOAT,
                price_alert_pct FLOAT DEFAULT 5.0,
                initial_holders INT,
                initial_risk    INT,
                trade_id        INT REFERENCES demo_trades(id),
                active          BOOLEAN DEFAULT TRUE,
                added_at        TIMESTAMP DEFAULT NOW(),
                last_checked_at TIMESTAMP,
                UNIQUE(address)
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
    validate_schema()


# ── Models ────────────────────────────────────────────
def get_all_models():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, pair, timeframe, session,
                       bias, status, rules, phase_timeframes, tier_a_threshold,
                       tier_b_threshold, tier_c_threshold, rr_target,
                       min_score, description, created_at,
                       tier_a, tier_b, tier_c, regime_managed
                FROM models
                ORDER BY
                    CASE WHEN id LIKE 'MM_%' THEN 0 ELSE 1 END,
                    created_at DESC
            """)
            rows = cur.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["rules"] = d["rules"] if isinstance(d["rules"], list) else json.loads(d["rules"] or "[]")
        d["phase_timeframes"] = d.get("phase_timeframes") if isinstance(d.get("phase_timeframes"), dict) else json.loads(d.get("phase_timeframes") or "{\"1\":\"4h\",\"2\":\"1h\",\"3\":\"15m\",\"4\":\"5m\"}")
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
    d["phase_timeframes"] = d.get("phase_timeframes") if isinstance(d.get("phase_timeframes"), dict) else json.loads(d.get("phase_timeframes") or "{\"1\":\"4h\",\"2\":\"1h\",\"3\":\"15m\",\"4\":\"5m\"}")
    return d

def get_active_models():
    cached = _cache_get("active_models")
    if cached is not None:
        return cached
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, pair, timeframe, session,
                       bias, status, rules, phase_timeframes, tier_a_threshold,
                       tier_b_threshold, tier_c_threshold, rr_target,
                       min_score, description, created_at,
                       tier_a, tier_b, tier_c, regime_managed
                FROM models
                WHERE status='active'
                ORDER BY created_at DESC
            """)
            rows = cur.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["rules"] = d["rules"] if isinstance(d["rules"], list) else json.loads(d["rules"] or "[]")
        d["phase_timeframes"] = d.get("phase_timeframes") if isinstance(d.get("phase_timeframes"), dict) else json.loads(d.get("phase_timeframes") or "{\"1\":\"4h\",\"2\":\"1h\",\"3\":\"15m\",\"4\":\"5m\"}")
        result.append(d)
    _cache_set("active_models", result)
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


def save_model(model: dict) -> str:
    import json
    _ensure_pool()
    conn = None
    try:
        conn = acquire_conn()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO models
                    (id, name, pair, timeframe, session, bias,
                     status, rules, phase_timeframes, tier_a_threshold,
                     tier_b_threshold, tier_c_threshold, rr_target,
                     min_score, description, created_at, updated_at)
                VALUES
                    (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())
                ON CONFLICT (id) DO UPDATE SET
                    name             = EXCLUDED.name,
                    pair             = EXCLUDED.pair,
                    timeframe        = EXCLUDED.timeframe,
                    session          = EXCLUDED.session,
                    bias             = EXCLUDED.bias,
                    rules            = EXCLUDED.rules,
                    phase_timeframes = EXCLUDED.phase_timeframes,
                    tier_a_threshold = EXCLUDED.tier_a_threshold,
                    tier_b_threshold = EXCLUDED.tier_b_threshold,
                    tier_c_threshold = EXCLUDED.tier_c_threshold,
                    rr_target        = EXCLUDED.rr_target,
                    min_score        = EXCLUDED.min_score,
                    description      = EXCLUDED.description,
                    updated_at       = NOW()
                RETURNING id
            """, (
                model["id"],
                model["name"],
                model.get("pair", "BTCUSDT"),
                model.get("timeframe", "1h"),
                model.get("session", "Any"),
                model.get("bias", "Both"),
                model.get("status", "inactive"),
                json.dumps(model.get("rules", [])),
                json.dumps(model.get("phase_timeframes", {"1":"4h","2":"1h","3":"15m","4":"5m"})),
                model.get("tier_a_threshold", 0),
                model.get("tier_b_threshold", 0),
                model.get("tier_c_threshold", 0),
                model.get("rr_target", 2.0),
                model.get("min_score", 0),
                model.get("description", ""),
            ))
            row = cur.fetchone()
            conn.commit()
            _cache_clear("active_models")
            if not row:
                return model["id"]
            if isinstance(row, dict):
                return row.get("id", model["id"])
            return row[0]
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        log.error(f"save_model error: {e}")
        raise
    finally:
        if conn:
            release_conn(conn)

def set_model_status(model_id, status):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE models SET status=%s WHERE id=%s", (status, model_id))
        conn.commit()
    _cache_clear("active_models")


def update_model_fields(model_id, fields: dict):
    allowed = {"pair", "timeframe", "session", "bias", "name", "tier_a", "tier_b", "tier_c", "min_score", "rr_target", "rules"}
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


def get_daily_realized_loss_pct(account_id: int = None) -> float:
    """
    If account_id is provided, returns today's realized demo loss percentage
    using actual closed-trade pnl_usd and starting_balance.
    Otherwise returns legacy live-trade realized loss based on risk_pct.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            if account_id is not None:
                cur.execute(
                    """
                    SELECT
                        COALESCE(SUM(dt.final_pnl_usd), 0) AS total_loss,
                        da.starting_balance
                    FROM demo_trades dt
                    JOIN demo_accounts da ON da.section = dt.section
                    WHERE da.id = %s
                      AND dt.result IS NOT NULL
                      AND dt.closed_at::date = CURRENT_DATE
                      AND COALESCE(dt.final_pnl_usd, 0) < 0
                    GROUP BY da.starting_balance
                    """,
                    (account_id,),
                )
                row = cur.fetchone()
                if not row:
                    return 0.0
                total_loss = float((row or {}).get("total_loss") or 0.0)
                starting = float((row or {}).get("starting_balance") or 0.0)
                if starting <= 0:
                    return 0.0
                return abs(total_loss) / starting * 100.0

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
    conn = None
    try:
        conn = acquire_conn()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO alert_log
                    (pair, model_id, model_name, score, tier, direction,
                     entry, sl, tp, rr, valid, reason, price_at_tp)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (pair, model_id, model_name, score, tier, direction,
                  entry, sl, tp, rr, valid, reason, price_at_tp))
        conn.commit()
    except Exception as e:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        log.error(f"alert_log insert failed: {e}")
    finally:
        if conn is not None:
            release_conn(conn)

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
                WHERE event_name=%s
                  AND pair=%s
                  AND event_time_utc BETWEEN %s::timestamp - INTERVAL '5 minutes' AND %s::timestamp + INTERVAL '5 minutes'
                ORDER BY ABS(EXTRACT(EPOCH FROM (event_time_utc - %s::timestamp))) ASC
                LIMIT 1
                """,
                (event.get("name"), event.get("pair"), event.get("time_utc"), event.get("time_utc"), event.get("time_utc")),
            )
            exists = cur.fetchone()
            if exists:
                cur.execute(
                    """
                    UPDATE news_events
                    SET impact=%s,
                        forecast=%s,
                        previous=%s,
                        actual=%s,
                        source=%s
                    WHERE id=%s
                    """,
                    (
                        event.get("impact"),
                        event.get("forecast"),
                        event.get("previous"),
                        event.get("actual"),
                        event.get("source"),
                        int(exists["id"]),
                    ),
                )
                conn.commit()
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
                  AND COALESCE(source,'') <> 'cryptonews'
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
                  AND COALESCE(source,'') <> 'cryptonews'
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
    d["mandatory_rules"] = _decode_json_field(d.get("mandatory_rules"), [])
    d["phase_timeframes"] = _decode_json_field(d.get("phase_timeframes"), {})
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
    cached = _cache_get("active_degen_models")
    if cached is not None:
        return cached
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id, name, description, status, active, regime_managed,
                    strategy, bias, pair,
                    chains, rules, mandatory_rules, phase_timeframes,
                    min_score, min_score_threshold, min_age_minutes, max_age_minutes,
                    max_risk_level, min_moon_score, max_risk_score, min_liquidity,
                    max_token_age_minutes, min_token_age_minutes, risk_per_trade_pct, max_open_trades,
                    require_lp_locked, require_mint_revoked, require_verified,
                    block_serial_ruggers, max_dev_rug_count, max_top1_holder_pct, min_holder_count,
                    alert_count, total_alerts, total_wins, total_losses, quality_grade,
                    last_alert_at, created_at, updated_at, version
                FROM degen_models
                WHERE status='active' OR active=TRUE
                ORDER BY name
                """
            )
            rows = [_normalize_degen_model(r) for r in cur.fetchall()]
    _cache_set("active_degen_models", rows)
    return rows


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



def save_degen_model(model: dict) -> str:
    payload = dict(model or {})
    model_id = str(payload.get("id") or "").strip()
    if not model_id:
        model_id = str(__import__("uuid").uuid4())[:12]

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO degen_models (
                    id, name, description, status, active, regime_managed,
                    strategy, bias, pair,
                    chains, rules, mandatory_rules, phase_timeframes,
                    min_score, min_score_threshold, min_age_minutes, max_age_minutes,
                    max_risk_level, min_moon_score, max_risk_score, min_liquidity,
                    max_token_age_minutes, min_token_age_minutes, risk_per_trade_pct, max_open_trades,
                    require_lp_locked, require_mint_revoked, require_verified,
                    block_serial_ruggers, max_dev_rug_count, max_top1_holder_pct, min_holder_count,
                    quality_grade, updated_at
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,
                    %s,%s,%s,
                    %s,%s,%s,%s,
                    %s,%s,%s,%s,
                    %s,%s,%s,%s,
                    %s,%s,%s,%s,
                    %s,%s,%s,
                    %s,%s,%s,%s,
                    %s,NOW()
                )
                ON CONFLICT (id) DO UPDATE SET
                    name=EXCLUDED.name,
                    description=EXCLUDED.description,
                    status=EXCLUDED.status,
                    active=EXCLUDED.active,
                    regime_managed=EXCLUDED.regime_managed,
                    strategy=EXCLUDED.strategy,
                    bias=EXCLUDED.bias,
                    pair=EXCLUDED.pair,
                    chains=EXCLUDED.chains,
                    rules=EXCLUDED.rules,
                    mandatory_rules=EXCLUDED.mandatory_rules,
                    phase_timeframes=EXCLUDED.phase_timeframes,
                    min_score=EXCLUDED.min_score,
                    min_score_threshold=EXCLUDED.min_score_threshold,
                    min_age_minutes=EXCLUDED.min_age_minutes,
                    max_age_minutes=EXCLUDED.max_age_minutes,
                    max_risk_level=EXCLUDED.max_risk_level,
                    min_moon_score=EXCLUDED.min_moon_score,
                    max_risk_score=EXCLUDED.max_risk_score,
                    min_liquidity=EXCLUDED.min_liquidity,
                    max_token_age_minutes=EXCLUDED.max_token_age_minutes,
                    min_token_age_minutes=EXCLUDED.min_token_age_minutes,
                    risk_per_trade_pct=EXCLUDED.risk_per_trade_pct,
                    max_open_trades=EXCLUDED.max_open_trades,
                    require_lp_locked=EXCLUDED.require_lp_locked,
                    require_mint_revoked=EXCLUDED.require_mint_revoked,
                    require_verified=EXCLUDED.require_verified,
                    block_serial_ruggers=EXCLUDED.block_serial_ruggers,
                    max_dev_rug_count=EXCLUDED.max_dev_rug_count,
                    max_top1_holder_pct=EXCLUDED.max_top1_holder_pct,
                    min_holder_count=EXCLUDED.min_holder_count,
                    quality_grade=EXCLUDED.quality_grade,
                    updated_at=NOW()
                RETURNING id
                """,
                (
                    model_id,
                    payload.get("name", "Unnamed"),
                    payload.get("description", ""),
                    payload.get("status", "inactive"),
                    bool(payload.get("active", str(payload.get("status", "inactive")).lower() == "active")),
                    bool(payload.get("regime_managed", False)),
                    payload.get("strategy", "momentum"),
                    payload.get("bias", "Both"),
                    payload.get("pair", "ALL"),
                    json.dumps(payload.get("chains", ["SOL"])),
                    json.dumps(payload.get("rules", [])),
                    json.dumps(payload.get("mandatory_rules", [])),
                    json.dumps(payload.get("phase_timeframes", {})),
                    float(payload.get("min_score", 50)),
                    float(payload.get("min_score_threshold", 50.0)),
                    int(payload.get("min_age_minutes", payload.get("min_token_age_minutes", 5))),
                    int(payload.get("max_age_minutes", payload.get("max_token_age_minutes", 120))),
                    payload.get("max_risk_level", "HIGH"),
                    int(payload.get("min_moon_score", 40)),
                    int(payload.get("max_risk_score", 60)),
                    float(payload.get("min_liquidity", 5000)),
                    int(payload.get("max_token_age_minutes", payload.get("max_age_minutes", 120))),
                    int(payload.get("min_token_age_minutes", payload.get("min_age_minutes", 5))),
                    float(payload.get("risk_per_trade_pct", 1.0)),
                    int(payload.get("max_open_trades", 3)),
                    bool(payload.get("require_lp_locked", False)),
                    bool(payload.get("require_mint_revoked", False)),
                    bool(payload.get("require_verified", False)),
                    bool(payload.get("block_serial_ruggers", True)),
                    int(payload.get("max_dev_rug_count", 0)),
                    float(payload.get("max_top1_holder_pct", 20)),
                    int(payload.get("min_holder_count", 10)),
                    payload.get("quality_grade"),
                ),
            )
            row = cur.fetchone()
        conn.commit()
    _cache_clear("active_degen_models")
    return str((row or {}).get("id", model_id))


def get_trade_model_pair(trade_id: int) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT model_id, pair FROM trade_log WHERE id=%s", (trade_id,))
            return dict(cur.fetchone() or {})


def activate_all_master_models() -> int:
    conn = None
    try:
        conn = acquire_conn()
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE models
                SET status = 'active',
                    pair = 'ALL',
                    bias = 'Both'
                WHERE id LIKE 'MM_%'
            """)
            updated = cur.rowcount
        conn.commit()
        _cache_clear("active_models")
        return updated
    finally:
        if conn:
            release_conn(conn)


def activate_master_models_by_category(cat_key: str) -> int:
    conn = None
    try:
        conn = acquire_conn()
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE models
                SET status = 'active',
                    pair = 'ALL',
                    bias = 'Both'
                WHERE id LIKE %s
            """, (f"MM_{cat_key}_%",))
            updated = cur.rowcount
        conn.commit()
        _cache_clear("active_models")
        return updated
    finally:
        if conn:
            release_conn(conn)


def get_end_of_day_counts() -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) c FROM alert_log WHERE alerted_at::date=NOW()::date")
            setups = int(cur.fetchone()["c"] or 0)
            cur.execute("SELECT COUNT(*) c, COALESCE(SUM(rr),0) r FROM trade_log WHERE logged_at::date=NOW()::date")
            row = cur.fetchone()
            trades = int(row["c"] or 0)
            total_r = float(row["r"] or 0)
    return {"setups": setups, "trades": trades, "total_r": total_r}

def set_degen_model_status(model_id: str, status: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE degen_models SET status=%s WHERE id=%s", (status, model_id))
        conn.commit()
    _cache_clear("active_degen_models")


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
    _cache_clear("tracked_wallets")
    _cache_clear("tracked_wallets:all")
    return wid


def get_tracked_wallets(active_only: bool = True) -> list:
    key = "tracked_wallets" if active_only else "tracked_wallets:all"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    with get_conn() as conn:
        with conn.cursor() as cur:
            sql = "SELECT * FROM tracked_wallets" + (" WHERE active=TRUE" if active_only else "") + " ORDER BY added_at DESC"
            cur.execute(sql)
            rows = [dict(r) for r in cur.fetchall()]
    _cache_set(key, rows)
    return rows


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
    _cache_clear("tracked_wallets")
    _cache_clear("tracked_wallets:all")


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
    key = "demo_accounts"
    cached = _cache_get(key) or {}
    if section in cached:
        return cached[section]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM demo_accounts WHERE section=%s", (section,))
            r = cur.fetchone()
            out = dict(r) if r else None
    cached[section] = out
    _cache_set(key, cached)
    return out


def create_demo_account(section: str, initial_deposit: float) -> dict:
    amt = max(100.0, float(initial_deposit))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO demo_accounts (section,balance,initial_deposit,starting_balance,peak_balance,lowest_balance)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (section) DO UPDATE SET balance=EXCLUDED.balance,initial_deposit=EXCLUDED.initial_deposit,starting_balance=EXCLUDED.starting_balance,peak_balance=EXCLUDED.peak_balance,lowest_balance=EXCLUDED.lowest_balance
                RETURNING *
                """,
                (section, amt, amt, amt, amt, amt),
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
            cur.execute("UPDATE demo_accounts SET balance=initial_deposit,starting_balance=initial_deposit,total_pnl=0,total_pnl_pct=0,total_trades=0,winning_trades=0,losing_trades=0,last_reset_at=NOW(),reset_id=%s WHERE section=%s RETURNING *", (new_reset, section))
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
    margin_reserved = risk
    balance = float(acct.get("balance") or 0)
    if margin_reserved > balance:
        margin_reserved = balance
        risk = margin_reserved
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO demo_trades (section,pair,token_symbol,direction,entry_price,sl,tp1,tp2,tp3,position_size_usd,risk_amount_usd,margin_reserved,risk_pct,current_price,current_pnl_usd,current_pnl_pct,current_x,model_id,model_name,tier,score,source,notes,reset_id,remaining_size_usd)
                VALUES (%(section)s,%(pair)s,%(token_symbol)s,%(direction)s,%(entry_price)s,%(sl)s,%(tp1)s,%(tp2)s,%(tp3)s,%(position_size_usd)s,%(risk_amount_usd)s,%(margin_reserved)s,%(risk_pct)s,%(entry_price)s,0,0,1,%(model_id)s,%(model_name)s,%(tier)s,%(score)s,%(source)s,%(notes)s,%(reset_id)s,%(remaining_size_usd)s)
                RETURNING id
                """,
                {
                    **trade,
                    "risk_amount_usd": risk,
                    "margin_reserved": margin_reserved,
                    "reset_id": acct.get("reset_id", 0),
                    "remaining_size_usd": float(trade.get("position_size_usd") or 0),
                },
            )
            tid = int(cur.fetchone()["id"])
            cur.execute("UPDATE demo_accounts SET balance=GREATEST(balance-%s,0) WHERE section=%s", (margin_reserved, section))
        conn.commit()
    _cache_clear("demo_accounts")
    log_demo_transaction(section, "trade_open", -margin_reserved, f"Open demo trade #{tid}")
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
            if tr.get("result"):
                return tr
            e = float(tr.get("entry_price") or 0)
            size = float(tr.get("remaining_size_usd") or tr.get("position_size_usd") or 0)
            margin_reserved = float(tr.get("margin_reserved") or tr.get("risk_amount_usd") or 0)
            mult = 1 if str(tr.get("direction", "LONG")).upper() in {"LONG", "BUY"} else -1
            pnl_pct = ((float(exit_price) - e) / e * 100 * mult) if e else 0
            pnl_usd = size * pnl_pct / 100
            final_x = 1 + pnl_pct / 100
            cur.execute(
                """
                UPDATE demo_trades
                SET result=%s,exit_price=%s,final_pnl_usd=%s,final_pnl_pct=%s,final_x=%s,
                    closed_at=NOW(),current_price=%s,current_pnl_usd=%s,current_pnl_pct=%s,
                    margin_reserved=0,remaining_size_usd=0
                WHERE id=%s
                """,
                (result, exit_price, pnl_usd, pnl_pct, final_x, exit_price, pnl_usd, pnl_pct, trade_id),
            )
            cur.execute(
                """
                UPDATE demo_accounts
                SET balance=GREATEST(balance+%s+%s, 0),
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
                (margin_reserved, pnl_usd, pnl_usd, pnl_usd, margin_reserved, pnl_usd, margin_reserved, pnl_usd, pnl_usd, pnl_usd, tr["section"]),
            )
            acct = dict(cur.fetchone() or {})
        conn.commit()
    _cache_clear("demo_accounts")
    log_demo_transaction(tr["section"], "trade_close", pnl_usd, f"Close demo trade #{trade_id} ({result})")
    return {**tr, "exit_price": exit_price, "final_pnl_usd": pnl_usd, "final_pnl_pct": pnl_pct, "final_x": final_x, "balance": acct.get("balance")}


def get_open_demo_trades(section: str = None) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            if section:
                cur.execute("SELECT * FROM demo_trades WHERE section=%s AND result IS NULL ORDER BY opened_at DESC", (section,))
            else:
                cur.execute("SELECT * FROM demo_trades WHERE result IS NULL ORDER BY opened_at DESC")
            return [dict(r) for r in cur.fetchall()]


def get_open_demo_trades_all() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    pair,
                    direction,
                    entry_price,
                    COALESCE(sl, 0) AS stop_loss,
                    COALESCE(position_size_usd, 0) AS position_size,
                    COALESCE(risk_amount_usd, 0) AS risk_amount
                FROM demo_trades
                WHERE result IS NULL
                ORDER BY opened_at DESC
                """
            )
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


# ── Pending Setups ───────────────────────────────────
def _pending_row_to_dict(row):
    if not row:
        return None
    d = dict(row)
    for k in ("passed_rules", "failed_rules", "mandatory_passed", "mandatory_failed", "rule_snapshots"):
        if d.get(k) is None:
            d[k] = [] if k != "rule_snapshots" else {}
    return d


def save_pending_setup(setup: dict) -> int:
    payload = dict(setup or {})
    for key in ("passed_rules", "failed_rules", "mandatory_passed", "mandatory_failed", "rule_snapshots"):
        payload[key] = json.dumps(payload.get(key, [] if key != "rule_snapshots" else {}))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO pending_setups (
                    model_id, model_name, pair, timeframe, direction,
                    entry_price, sl, tp1, tp2, tp3, current_score, max_possible_score,
                    score_pct, min_score_threshold, passed_rules, failed_rules,
                    mandatory_passed, mandatory_failed, rule_snapshots,
                    telegram_message_id, telegram_chat_id, status,
                    first_detected_at, last_updated_at, check_count, peak_score_pct
                ) VALUES (
                    %(model_id)s, %(model_name)s, %(pair)s, %(timeframe)s, %(direction)s,
                    %(entry_price)s, %(sl)s, %(tp1)s, %(tp2)s, %(tp3)s, %(current_score)s, %(max_possible_score)s,
                    %(score_pct)s, %(min_score_threshold)s, %(passed_rules)s::jsonb, %(failed_rules)s::jsonb,
                    %(mandatory_passed)s::jsonb, %(mandatory_failed)s::jsonb, %(rule_snapshots)s::jsonb,
                    %(telegram_message_id)s, %(telegram_chat_id)s, %(status)s,
                    COALESCE(%(first_detected_at)s, NOW()), NOW(), COALESCE(%(check_count)s, 1), %(peak_score_pct)s
                )
                ON CONFLICT (model_id, pair, timeframe) DO UPDATE SET
                    model_name=EXCLUDED.model_name,
                    direction=EXCLUDED.direction,
                    entry_price=EXCLUDED.entry_price,
                    sl=EXCLUDED.sl,
                    tp1=EXCLUDED.tp1,
                    tp2=EXCLUDED.tp2,
                    tp3=EXCLUDED.tp3,
                    current_score=EXCLUDED.current_score,
                    max_possible_score=EXCLUDED.max_possible_score,
                    score_pct=EXCLUDED.score_pct,
                    min_score_threshold=EXCLUDED.min_score_threshold,
                    passed_rules=EXCLUDED.passed_rules,
                    failed_rules=EXCLUDED.failed_rules,
                    mandatory_passed=EXCLUDED.mandatory_passed,
                    mandatory_failed=EXCLUDED.mandatory_failed,
                    rule_snapshots=EXCLUDED.rule_snapshots,
                    telegram_message_id=COALESCE(EXCLUDED.telegram_message_id, pending_setups.telegram_message_id),
                    telegram_chat_id=COALESCE(EXCLUDED.telegram_chat_id, pending_setups.telegram_chat_id),
                    status=EXCLUDED.status,
                    last_updated_at=NOW(),
                    check_count=COALESCE(pending_setups.check_count, 0) + 1,
                    peak_score_pct=GREATEST(COALESCE(pending_setups.peak_score_pct, 0), COALESCE(EXCLUDED.score_pct, 0))
                RETURNING id
            """, payload)
            row = cur.fetchone()
        conn.commit()
    return int(row["id"])


def get_pending_setup(model_id: str, pair: str, timeframe: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM pending_setups WHERE model_id=%s AND pair=%s AND timeframe=%s", (model_id, pair, timeframe))
            return _pending_row_to_dict(cur.fetchone())


def get_all_pending_setups(status: str = 'pending') -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM pending_setups WHERE status=%s ORDER BY score_pct DESC NULLS LAST, last_updated_at DESC", (status,))
            return [_pending_row_to_dict(r) for r in cur.fetchall()]


def update_pending_setup(id: int, fields: dict) -> None:
    if not fields:
        return
    data = dict(fields)
    for key in ("passed_rules", "failed_rules", "mandatory_passed", "mandatory_failed", "rule_snapshots"):
        if key in data:
            data[key] = json.dumps(data[key])
    keys = list(data.keys())
    sets = ", ".join([f"{k}=%s" + ("::jsonb" if k in ("passed_rules", "failed_rules", "mandatory_passed", "mandatory_failed", "rule_snapshots") else "") for k in keys])
    vals = [data[k] for k in keys]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE pending_setups SET {sets} WHERE id=%s", (*vals, id))
        conn.commit()


def promote_pending_setup(id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE pending_setups SET status='promoted', promoted_at=NOW(), last_updated_at=NOW() WHERE id=%s", (id,))
        conn.commit()


def expire_pending_setup(id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE pending_setups SET status='expired', expired_at=NOW(), last_updated_at=NOW() WHERE id=%s", (id,))
        conn.commit()


def delete_pending_setup(id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM pending_setups WHERE id=%s", (id,))
        conn.commit()


def delete_old_expired_setups(hours: int = 24) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM pending_setups WHERE status='expired' AND expired_at < NOW() - make_interval(hours => %s)", (hours,))
        conn.commit()


def get_pending_setups_for_model(model_id: str) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM pending_setups WHERE model_id=%s ORDER BY last_updated_at DESC", (model_id,))
            return [_pending_row_to_dict(r) for r in cur.fetchall()]
def add_degen_watchlist(token_data: dict) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO degen_watchlist (address,symbol,name,chain)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (address) DO UPDATE SET symbol=EXCLUDED.symbol,name=EXCLUDED.name,chain=EXCLUDED.chain
                RETURNING id
                """,
                (token_data.get("address"), token_data.get("symbol"), token_data.get("name"), token_data.get("chain") or "SOL"),
            )
            rid = int(cur.fetchone()["id"])
        conn.commit()
    return rid


def add_ca_monitor(token_data: dict) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ca_monitors (address,symbol,name,chain,price_at_add,initial_holders,initial_risk,active,last_checked_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,TRUE,NOW())
                ON CONFLICT (address) DO UPDATE SET
                    symbol=EXCLUDED.symbol,
                    name=EXCLUDED.name,
                    chain=EXCLUDED.chain,
                    price_at_add=EXCLUDED.price_at_add,
                    initial_holders=EXCLUDED.initial_holders,
                    initial_risk=EXCLUDED.initial_risk,
                    active=TRUE,
                    last_checked_at=NOW()
                RETURNING id
                """,
                (
                    token_data.get("address"),
                    token_data.get("symbol"),
                    token_data.get("name"),
                    token_data.get("chain") or "SOL",
                    float(token_data.get("price_usd") or 0),
                    int(token_data.get("holder_count") or 0),
                    int(token_data.get("risk_score") or 0),
                ),
            )
            rid = int(cur.fetchone()["id"])
        conn.commit()
    return rid


def get_active_ca_monitors() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM ca_monitors WHERE active=TRUE ORDER BY added_at DESC")
            return [dict(r) for r in cur.fetchall()]


def remove_ca_monitor(address: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE ca_monitors SET active=FALSE WHERE address=%s", (address,))
        conn.commit()


def update_ca_monitor_check(address: str, price: float, holders: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE ca_monitors SET last_checked_at=NOW(),price_at_add=COALESCE(price_at_add,%s),initial_holders=COALESCE(initial_holders,%s) WHERE address=%s", (price, holders, address))
        conn.commit()


def link_ca_monitor_trade(address: str, trade_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE ca_monitors SET trade_id=%s WHERE address=%s", (trade_id, address))
        conn.commit()


def get_demo_trade_by_id(trade_id: int) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM demo_trades WHERE id=%s", (trade_id,))
            r = cur.fetchone()
            return dict(r) if r else None


def partial_close_demo_trade(trade_id: int, fraction: float = 0.5) -> dict | None:
    fraction = max(0.01, min(0.99, float(fraction)))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM demo_trades WHERE id=%s", (trade_id,))
            tr = dict(cur.fetchone() or {})
            if not tr or tr.get("result"):
                return None
            remaining = float(tr.get("remaining_size_usd") or tr.get("position_size_usd") or 0)
            close_size = remaining * fraction
            new_remaining = remaining - close_size
            margin_reserved = float(tr.get("margin_reserved") or tr.get("risk_amount_usd") or 0)
            margin_return = margin_reserved * fraction
            new_margin = margin_reserved - margin_return
            pnl_pct = float(tr.get("current_pnl_pct") or 0)
            realized = close_size * pnl_pct / 100
            cur.execute(
                "UPDATE demo_accounts SET balance=balance+%s+%s,total_pnl=COALESCE(total_pnl,0)+%s WHERE section=%s",
                (margin_return, realized, realized, tr.get("section")),
            )
            partials = _decode_json_field(tr.get("partial_closes"), [])
            partials.append(
                {
                    "ts": int(time.time()),
                    "fraction": fraction,
                    "size": close_size,
                    "price": tr.get("current_price"),
                    "pnl_usd": realized,
                    "margin_returned": margin_return,
                }
            )
            cur.execute(
                "UPDATE demo_trades SET remaining_size_usd=%s, margin_reserved=%s, partial_closes=%s, sl=entry_price WHERE id=%s",
                (new_remaining, new_margin, json.dumps(partials), trade_id),
            )
        conn.commit()
    _cache_clear("demo_accounts")
    return get_demo_trade_by_id(trade_id)


def extend_demo_trade_time_stop(trade_id: int, minutes: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE demo_trades SET time_stop_minutes=COALESCE(time_stop_minutes,30)+%s WHERE id=%s", (int(minutes), trade_id))
        conn.commit()


def save_chart_analysis(result: dict) -> int:
    setup = result.get("setup", {}) or {}
    bias = result.get("bias", {}) or {}
    htf = result.get("htf", {}) or {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chart_analyses (
                    analysis_type, pair_estimate, timeframe, action, bias_direction,
                    confluence_score, setup_present, setup_type, entry_zone, stop_loss,
                    take_profit_1, take_profit_2, take_profit_3, risk_reward, full_result, analysed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s::timestamp, NOW()))
                RETURNING id
                """,
                (
                    result.get("analysis_type", "single"),
                    result.get("pair_estimate") or htf.get("pair_estimate") or "unknown",
                    result.get("timeframe_estimate") or htf.get("timeframe_estimate") or "unknown",
                    result.get("action", "wait"),
                    bias.get("direction") or htf.get("bias") or "neutral",
                    int(result.get("confluence_score", 0) or 0),
                    bool(setup.get("setup_present")),
                    setup.get("setup_type"),
                    str(setup.get("entry_zone") or "")[:50],
                    str(setup.get("stop_loss") or "")[:50],
                    str(setup.get("take_profit_1") or "")[:50],
                    str(setup.get("take_profit_2") or "")[:50],
                    str(setup.get("take_profit_3") or "")[:50],
                    str(setup.get("risk_reward") or "")[:20],
                    json.dumps(result),
                    result.get("analysed_at"),
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return int(row["id"])


def get_chart_analyses(limit: int = 20) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM chart_analyses ORDER BY analysed_at DESC LIMIT %s", (max(1, int(limit)),))
            return [dict(r) for r in cur.fetchall()]


def link_chart_to_demo_trade(analysis_id: int, trade_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE chart_analyses SET demo_trade_id=%s WHERE id=%s", (trade_id, analysis_id))
        conn.commit()


def get_setup_phase(model_id, pair, direction):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM setup_phases WHERE model_id=%s AND pair=%s AND direction=%s", (model_id, pair, direction))
            return cur.fetchone()


def save_setup_phase(phase: dict) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            if phase.get("id"):
                sets = ", ".join(f"{k}=%s" for k in phase if k != "id")
                vals = [phase[k] for k in phase if k != "id"]
                cur.execute(f"UPDATE setup_phases SET {sets}, last_updated_at=NOW() WHERE id=%s RETURNING id", (*vals, phase["id"]))
            else:
                cur.execute(
                    """
                    INSERT INTO setup_phases (model_id, model_name, pair, direction, overall_status, check_count, last_updated_at)
                    VALUES (%s,%s,%s,%s,COALESCE(%s,'phase1'),COALESCE(%s,0),NOW())
                    ON CONFLICT (model_id,pair,direction) DO UPDATE SET model_name=EXCLUDED.model_name,last_updated_at=NOW()
                    RETURNING id
                    """,
                    (phase["model_id"], phase.get("model_name"), phase["pair"], phase.get("direction"), phase.get("overall_status"), phase.get("check_count", 0)),
                )
            row = cur.fetchone()
        conn.commit()
    return row[0] if row else 0


def update_phase_status(id, phase_num, status, data):
    now = datetime.utcnow()
    expires = now + timedelta(seconds={1: 14400, 2: 3600, 3: 0, 4: 2700}.get(phase_num, 0)) if phase_num in (1, 2, 4) else None
    next_status = {1: "phase2", 2: "phase3", 3: "phase4", 4: "phase1"}.get(phase_num, "phase1")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE setup_phases
                SET phase{phase_num}_status=%s,
                    phase{phase_num}_score=%s,
                    phase{phase_num}_max_score=%s,
                    phase{phase_num}_passed_rules=%s,
                    phase{phase_num}_failed_rules=%s,
                    phase{phase_num}_data=%s,
                    phase{phase_num}_completed_at=%s,
                    phase{phase_num}_expires_at=COALESCE(%s, phase{phase_num}_expires_at),
                    overall_status=%s,
                    last_updated_at=NOW(),
                    check_count=COALESCE(check_count,0)+1
                WHERE id=%s
                """,
                (status, data.get("score", 0), data.get("max_score", 0), json.dumps(data.get("passed_rules", [])), json.dumps(data.get("failed_rules", [])), json.dumps(data.get("phase_data", {})), now, expires, next_status, id),
            )
        conn.commit()


def get_active_setup_phases() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM setup_phases WHERE overall_status IN ('phase1','phase2','phase3','phase4') ORDER BY last_updated_at DESC")
            return cur.fetchall()


def get_phases_awaiting_phase4() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM setup_phases WHERE overall_status='phase4'")
            return cur.fetchall()


def expire_old_phases() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM setup_phases WHERE overall_status='phase2' AND phase1_completed_at < NOW() - interval '4 hours'")
            cur.execute("DELETE FROM setup_phases WHERE overall_status='phase3' AND phase2_completed_at < NOW() - interval '1 hour'")
        conn.commit()


def save_alert_lifecycle(data: dict) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alert_lifecycle (
                    setup_phase_id,model_id,pair,direction,entry_price,alert_sent_at,
                    risk_level,risk_amount,position_size,leverage,rr_ratio,
                    quality_grade,quality_score
                ) VALUES (%s,%s,%s,%s,%s,COALESCE(%s,NOW()),%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (
                    data.get("setup_phase_id"), data.get("model_id"), data.get("pair"), data.get("direction"), data.get("entry_price"), data.get("alert_sent_at"),
                    data.get("risk_level"), data.get("risk_amount"), data.get("position_size"), data.get("leverage"), data.get("rr_ratio"),
                    data.get("quality_grade"), data.get("quality_score"),
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return row[0] if row else 0


def update_alert_lifecycle(id, fields: dict) -> None:
    if not fields:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            sets = ", ".join(f"{k}=%s" for k in fields)
            cur.execute(f"UPDATE alert_lifecycle SET {sets} WHERE id=%s", (*fields.values(), id))
        conn.commit()


def get_alert_lifecycle(setup_phase_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM alert_lifecycle WHERE setup_phase_id=%s ORDER BY id DESC LIMIT 1", (setup_phase_id,))
            return cur.fetchone()


def get_active_lifecycles() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM alert_lifecycle WHERE outcome IS NULL")
            return cur.fetchall()


def get_model_performance(model_id: str) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM model_performance WHERE model_id=%s", (model_id,))
            row = cur.fetchone()
            if row:
                return dict(row)
            cur.execute("INSERT INTO model_performance (model_id) VALUES (%s) RETURNING *", (model_id,))
            row = cur.fetchone()
        conn.commit()
    return dict(row)


def update_model_performance(model_id: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO model_performance (model_id,total_alerts,entries_touched,phase4_confirms,phase4_fails,demo_trades,demo_wins,demo_losses,demo_win_rate,avg_r,updated_at)
                SELECT %s,
                    COUNT(*),
                    COUNT(*) FILTER (WHERE entry_touched),
                    COUNT(*) FILTER (WHERE phase4_result='confirmed'),
                    COUNT(*) FILTER (WHERE phase4_result='failed'),
                    COUNT(*) FILTER (WHERE outcome IN ('win','loss')),
                    COUNT(*) FILTER (WHERE outcome='win'),
                    COUNT(*) FILTER (WHERE outcome='loss'),
                    COALESCE(COUNT(*) FILTER (WHERE outcome='win')::float / NULLIF(COUNT(*) FILTER (WHERE outcome IN ('win','loss')),0),0),
                    0,
                    NOW()
                FROM alert_lifecycle WHERE model_id=%s
                ON CONFLICT (model_id) DO UPDATE SET
                    total_alerts=EXCLUDED.total_alerts,
                    entries_touched=EXCLUDED.entries_touched,
                    phase4_confirms=EXCLUDED.phase4_confirms,
                    phase4_fails=EXCLUDED.phase4_fails,
                    demo_trades=EXCLUDED.demo_trades,
                    demo_wins=EXCLUDED.demo_wins,
                    demo_losses=EXCLUDED.demo_losses,
                    demo_win_rate=EXCLUDED.demo_win_rate,
                    updated_at=NOW()
                """,
                (model_id, model_id),
            )
        conn.commit()


def save_session_journal(data: dict) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO session_journal (session_date,session_name,pair,asian_high,asian_low,asian_range_pts,london_swept,london_swept_at,ny_direction,ny_reversed,key_levels,notes)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (session_date,pair) DO UPDATE SET
                    session_name=EXCLUDED.session_name,
                    asian_high=EXCLUDED.asian_high,
                    asian_low=EXCLUDED.asian_low,
                    asian_range_pts=EXCLUDED.asian_range_pts,
                    london_swept=EXCLUDED.london_swept,
                    key_levels=EXCLUDED.key_levels,
                    notes=EXCLUDED.notes
                """,
                (data.get("session_date"), data.get("session_name"), data.get("pair"), data.get("asian_high"), data.get("asian_low"), data.get("asian_range_pts"), data.get("london_swept"), data.get("london_swept_at"), data.get("ny_direction"), data.get("ny_reversed", False), json.dumps(data.get("key_levels", [])), data.get("notes")),
            )
        conn.commit()


def get_session_journal(pair: str, days: int = 30) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM session_journal WHERE pair=%s AND session_date >= CURRENT_DATE - make_interval(days => %s) ORDER BY session_date DESC", (pair, days))
            return cur.fetchall()


def _ensure_risk_tables() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS risk_settings (
                    id                  SERIAL PRIMARY KEY,
                    account_size        FLOAT DEFAULT 1000.0,
                    risk_per_trade_pct  FLOAT DEFAULT 1.0,
                    max_daily_loss_pct  FLOAT DEFAULT 3.0,
                    max_open_trades     INT DEFAULT 3,
                    max_exposure_pct    FLOAT DEFAULT 5.0,
                    max_pair_exposure   FLOAT DEFAULT 2.0,
                    risk_reward_min     FLOAT DEFAULT 1.0,
                    enabled             BOOLEAN DEFAULT TRUE,
                    min_quality_grade   VARCHAR(5) DEFAULT 'C',
                    updated_at          TIMESTAMP DEFAULT NOW()
                );
                INSERT INTO risk_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
                UPDATE risk_settings
                SET risk_reward_min = 1.0
                WHERE id = 1 AND (risk_reward_min IS NULL OR risk_reward_min = 1.5);
                CREATE TABLE IF NOT EXISTS daily_risk_tracker (
                    id               SERIAL PRIMARY KEY,
                    track_date       DATE NOT NULL UNIQUE,
                    starting_balance FLOAT,
                    current_balance  FLOAT,
                    realised_pnl     FLOAT DEFAULT 0,
                    open_risk        FLOAT DEFAULT 0,
                    trades_taken     INT DEFAULT 0,
                    daily_loss_hit   BOOLEAN DEFAULT FALSE,
                    updated_at       TIMESTAMP DEFAULT NOW()
                );
                """
            )
        conn.commit()


def get_risk_settings() -> dict:
    _ensure_risk_tables()
    _ensure_degen_intel_tables()
    defaults = {
        "id": 1,
        "account_size": 1000.0,
        "risk_per_trade_pct": 1.0,
        "max_daily_loss_pct": 3.0,
        "max_open_trades": 3,
        "max_exposure_pct": 5.0,
        "max_pair_exposure": 2.0,
        "risk_reward_min": 1.0,
        "enabled": True,
        "min_quality_grade": "C",
    }
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM risk_settings WHERE id=1")
            row = cur.fetchone()
            if row:
                data = dict(row)
                return {**defaults, **data}
            cur.execute("INSERT INTO risk_settings (id) VALUES (1) RETURNING *")
            row = cur.fetchone()
        conn.commit()
    return {**defaults, **dict(row or {})}


def update_risk_settings(fields: dict) -> None:
    if not fields:
        return
    _ensure_risk_tables()
    _ensure_degen_intel_tables()
    payload = dict(fields)
    payload["updated_at"] = datetime.utcnow()
    sets = ", ".join(f"{k}=%s" for k in payload)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE risk_settings SET {sets} WHERE id=1", tuple(payload.values()))
        conn.commit()


def get_daily_tracker() -> dict:
    _ensure_risk_tables()
    _ensure_degen_intel_tables()
    today = date.today()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM daily_risk_tracker WHERE track_date=%s", (today,))
            row = cur.fetchone()
            if row:
                return dict(row)
            settings = get_risk_settings()
            acct = float(settings.get("account_size") or 1000.0)
            cur.execute(
                """
                INSERT INTO daily_risk_tracker (track_date, starting_balance, current_balance)
                VALUES (%s,%s,%s)
                RETURNING *
                """,
                (today, acct, acct),
            )
            row = cur.fetchone()
        conn.commit()
    return dict(row)


def update_daily_tracker(fields: dict) -> None:
    if not fields:
        return
    tracker = get_daily_tracker()
    payload = dict(fields)
    payload["updated_at"] = datetime.utcnow()
    sets = ", ".join(f"{k}=%s" for k in payload)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE daily_risk_tracker SET {sets} WHERE id=%s", (*payload.values(), tracker["id"]))
        conn.commit()


def get_notification_pattern(key: str) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM notification_patterns WHERE pattern_key=%s", (key,))
            row = cur.fetchone()
            return dict(row) if row else {}


def increment_pattern_alert(key: str) -> None:
    pattern_type = key.split("_", 1)[0]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO notification_patterns (pattern_key, pattern_type, total_alerts, entries_touched, action_rate, updated_at)
                VALUES (%s,%s,1,0,0,NOW())
                ON CONFLICT (pattern_key) DO UPDATE SET
                    total_alerts=notification_patterns.total_alerts+1,
                    updated_at=NOW()
                """,
                (key, pattern_type),
            )
        conn.commit()
    recalculate_action_rate(key)


def increment_pattern_action(key: str) -> None:
    pattern_type = key.split("_", 1)[0]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO notification_patterns (pattern_key, pattern_type, total_alerts, entries_touched, action_rate, updated_at)
                VALUES (%s,%s,1,1,1,NOW())
                ON CONFLICT (pattern_key) DO UPDATE SET
                    entries_touched=notification_patterns.entries_touched+1,
                    updated_at=NOW()
                """,
                (key, pattern_type),
            )
        conn.commit()


def recalculate_action_rate(key: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE notification_patterns
                SET action_rate = COALESCE(entries_touched::float / NULLIF(total_alerts, 0), 0),
                    updated_at = NOW()
                WHERE pattern_key=%s
                """,
                (key,),
            )
        conn.commit()


def update_notification_pattern(key, fields) -> None:
    if not fields:
        return
    payload = dict(fields)
    payload["updated_at"] = datetime.utcnow()
    sets = ", ".join(f"{k}=%s" for k in payload)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE notification_patterns SET {sets} WHERE pattern_key=%s", (*payload.values(), key))
        conn.commit()


def get_all_notification_patterns() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM notification_patterns ORDER BY action_rate ASC, total_alerts DESC")
            return [dict(r) for r in cur.fetchall()]


def save_market_regime(data: dict) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO market_regimes (regime_date, regime, confidence, btc_atr_pct, btc_trend, range_size, details, detected_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (regime_date) DO UPDATE SET
                    regime=EXCLUDED.regime,
                    confidence=EXCLUDED.confidence,
                    btc_atr_pct=EXCLUDED.btc_atr_pct,
                    btc_trend=EXCLUDED.btc_trend,
                    range_size=EXCLUDED.range_size,
                    details=EXCLUDED.details,
                    detected_at=NOW()
                """,
                (
                    data.get("regime_date"),
                    data.get("regime"),
                    data.get("confidence", 0),
                    data.get("btc_atr_pct", 0),
                    data.get("btc_trend"),
                    data.get("range_size", 0),
                    json.dumps(data.get("details", {})),
                ),
            )
        conn.commit()


def get_latest_regime() -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM market_regimes ORDER BY regime_date DESC LIMIT 1")
            row = cur.fetchone()
            return dict(row) if row else None


def get_model_regime_performance(model_id, regime) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM model_regime_performance WHERE model_id=%s AND regime=%s", (model_id, regime))
            row = cur.fetchone()
            return dict(row) if row else {}


def update_model_regime_performance(model_id, regime, confirmed: bool) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO model_regime_performance (model_id, regime, total_alerts, p4_confirms, confirm_rate, updated_at)
                VALUES (%s,%s,1,%s,%s,NOW())
                ON CONFLICT (model_id, regime) DO UPDATE SET
                    total_alerts=model_regime_performance.total_alerts+1,
                    p4_confirms=model_regime_performance.p4_confirms+EXCLUDED.p4_confirms,
                    confirm_rate=(model_regime_performance.p4_confirms+EXCLUDED.p4_confirms)::float/(model_regime_performance.total_alerts+1),
                    updated_at=NOW()
                """,
                (model_id, regime, 1 if confirmed else 0, 1.0 if confirmed else 0.0),
            )
        conn.commit()


def set_model_active(model_id: str, active: bool, regime_managed: bool = False) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE models SET status=%s, regime_managed=%s, updated_at=NOW() WHERE id=%s",
                ("active" if active else "inactive", regime_managed, model_id),
            )
            _cache_clear("active_models")
        conn.commit()


def ensure_intelligence_tables() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                ALTER TABLE models ADD COLUMN IF NOT EXISTS regime_managed BOOLEAN DEFAULT FALSE;
                CREATE TABLE IF NOT EXISTS alert_lifecycle (
                    id SERIAL PRIMARY KEY,
                    setup_phase_id INT,
                    model_id VARCHAR(100),
                    pair VARCHAR(20),
                    direction VARCHAR(10),
                    entry_price FLOAT,
                    alert_sent_at TIMESTAMP DEFAULT NOW(),
                    entry_touched BOOLEAN DEFAULT FALSE,
                    entry_touched_at TIMESTAMP,
                    phase4_result VARCHAR(20),
                    phase4_message TEXT,
                    phase4_sent_at TIMESTAMP,
                    demo_trade_id INT,
                    outcome VARCHAR(20),
                    closed_at TIMESTAMP
                );
                ALTER TABLE alert_lifecycle ADD COLUMN IF NOT EXISTS risk_level VARCHAR(10);
                ALTER TABLE alert_lifecycle ADD COLUMN IF NOT EXISTS risk_amount FLOAT;
                ALTER TABLE alert_lifecycle ADD COLUMN IF NOT EXISTS position_size FLOAT;
                ALTER TABLE alert_lifecycle ADD COLUMN IF NOT EXISTS leverage FLOAT;
                ALTER TABLE alert_lifecycle ADD COLUMN IF NOT EXISTS rr_ratio FLOAT;
                ALTER TABLE alert_lifecycle ADD COLUMN IF NOT EXISTS quality_grade VARCHAR(5);
                ALTER TABLE alert_lifecycle ADD COLUMN IF NOT EXISTS quality_score FLOAT;
                CREATE TABLE IF NOT EXISTS notification_patterns (
                    id              SERIAL PRIMARY KEY,
                    pattern_key     VARCHAR(100) UNIQUE NOT NULL,
                    pattern_type    VARCHAR(30),
                    total_alerts    INT DEFAULT 0,
                    entries_touched INT DEFAULT 0,
                    action_rate     FLOAT DEFAULT 0,
                    suppressed      BOOLEAN DEFAULT FALSE,
                    suppressed_at   TIMESTAMP,
                    override        BOOLEAN DEFAULT FALSE,
                    updated_at      TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS market_regimes (
                    id           SERIAL PRIMARY KEY,
                    regime_date  DATE NOT NULL UNIQUE,
                    regime       VARCHAR(30) NOT NULL,
                    confidence   FLOAT DEFAULT 0,
                    btc_atr_pct  FLOAT,
                    btc_trend    VARCHAR(20),
                    range_size   FLOAT,
                    details      JSONB DEFAULT '{}',
                    detected_at  TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS model_regime_performance (
                    id           SERIAL PRIMARY KEY,
                    model_id     VARCHAR(100) NOT NULL,
                    regime       VARCHAR(30) NOT NULL,
                    total_alerts INT DEFAULT 0,
                    p4_confirms  INT DEFAULT 0,
                    confirm_rate FLOAT DEFAULT 0,
                    updated_at   TIMESTAMP DEFAULT NOW(),
                    UNIQUE(model_id, regime)
                );
                """
            )
        conn.commit()
    _ensure_risk_tables()
    _ensure_degen_intel_tables()


def _ensure_degen_intel_tables() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS contract_scans (
                    id                  SERIAL PRIMARY KEY,
                    contract_address    VARCHAR(100) NOT NULL,
                    chain               VARCHAR(20) NOT NULL,
                    token_name          VARCHAR(100),
                    token_symbol        VARCHAR(20),
                    is_honeypot         BOOLEAN,
                    honeypot_reason     TEXT,
                    mint_enabled        BOOLEAN,
                    owner_can_blacklist BOOLEAN,
                    owner_can_whitelist BOOLEAN,
                    is_proxy            BOOLEAN,
                    is_open_source      BOOLEAN,
                    trading_cooldown    BOOLEAN,
                    transfer_pausable   BOOLEAN,
                    buy_tax             FLOAT,
                    sell_tax            FLOAT,
                    holder_count        INT,
                    top10_holder_pct    FLOAT,
                    dev_wallet          VARCHAR(100),
                    dev_holding_pct     FLOAT,
                    lp_holder_count     INT,
                    lp_locked_pct       FLOAT,
                    liquidity_usd       FLOAT,
                    volume_24h          FLOAT,
                    price_usd           FLOAT,
                    market_cap          FLOAT,
                    pair_created_at     TIMESTAMP,
                    dex_name            VARCHAR(50),
                    rug_score           FLOAT,
                    rug_grade           VARCHAR(5),
                    safety_flags        JSONB DEFAULT '[]',
                    passed_checks       JSONB DEFAULT '[]',
                    scanned_at          TIMESTAMP DEFAULT NOW(),
                    raw_goplus          JSONB DEFAULT '{}',
                    UNIQUE(contract_address, chain)
                );
                CREATE TABLE IF NOT EXISTS dev_wallets (
                    id               SERIAL PRIMARY KEY,
                    contract_address VARCHAR(100) NOT NULL,
                    chain            VARCHAR(20) NOT NULL,
                    wallet_address   VARCHAR(100) NOT NULL,
                    label            VARCHAR(50) DEFAULT 'deployer',
                    watching         BOOLEAN DEFAULT TRUE,
                    first_seen       TIMESTAMP DEFAULT NOW(),
                    last_activity    TIMESTAMP,
                    alert_on_sell    BOOLEAN DEFAULT TRUE,
                    alert_on_buy     BOOLEAN DEFAULT TRUE,
                    UNIQUE(contract_address, wallet_address)
                );
                CREATE TABLE IF NOT EXISTS dev_wallet_events (
                    id               SERIAL PRIMARY KEY,
                    wallet_address   VARCHAR(100) NOT NULL,
                    contract_address VARCHAR(100),
                    chain            VARCHAR(20),
                    event_type       VARCHAR(30),
                    token_amount     FLOAT,
                    usd_value        FLOAT,
                    tx_hash          VARCHAR(100) UNIQUE,
                    detected_at      TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS degen_risk_settings (
                    id                   SERIAL PRIMARY KEY,
                    account_size         FLOAT DEFAULT 500.0,
                    max_position_pct     FLOAT DEFAULT 2.0,
                    max_degen_exposure   FLOAT DEFAULT 10.0,
                    min_liquidity_usd    FLOAT DEFAULT 50000.0,
                    max_buy_tax          FLOAT DEFAULT 5.0,
                    max_sell_tax         FLOAT DEFAULT 5.0,
                    max_top10_holder_pct FLOAT DEFAULT 50.0,
                    min_rug_grade        VARCHAR(5) DEFAULT 'C',
                    block_honeypots      BOOLEAN DEFAULT TRUE,
                    block_no_lp_lock     BOOLEAN DEFAULT FALSE,
                    updated_at           TIMESTAMP DEFAULT NOW()
                );
                INSERT INTO degen_risk_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

                CREATE TABLE IF NOT EXISTS narrative_tracking (
                    id              SERIAL PRIMARY KEY,
                    narrative       VARCHAR(50) NOT NULL UNIQUE,
                    mention_count   INT DEFAULT 0,
                    prev_count      INT DEFAULT 0,
                    velocity        FLOAT DEFAULT 0,
                    trend           VARCHAR(20) DEFAULT 'neutral',
                    tokens          JSONB DEFAULT '[]',
                    last_updated    TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS degen_journal (
                    id                 SERIAL PRIMARY KEY,
                    contract_address   VARCHAR(100),
                    chain              VARCHAR(20),
                    token_symbol       VARCHAR(20),
                    token_name         VARCHAR(100),
                    narrative          VARCHAR(50),
                    entry_price        FLOAT,
                    entry_time         TIMESTAMP,
                    entry_mcap         FLOAT,
                    entry_liquidity    FLOAT,
                    entry_holders      INT,
                    entry_age_hours    FLOAT,
                    entry_rug_grade    VARCHAR(5),
                    position_size_usd  FLOAT,
                    risk_usd           FLOAT,
                    exit_price         FLOAT,
                    exit_time          TIMESTAMP,
                    exit_reason        VARCHAR(100),
                    peak_price         FLOAT,
                    peak_multiplier    FLOAT,
                    final_multiplier   FLOAT,
                    followed_exit_plan BOOLEAN,
                    pnl_usd            FLOAT,
                    outcome            VARCHAR(20),
                    early_score        FLOAT,
                    social_velocity    FLOAT,
                    rug_score          FLOAT,
                    notes              TEXT,
                    tags               JSONB DEFAULT '[]',
                    created_at         TIMESTAMP DEFAULT NOW(),
                    updated_at         TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS exit_reminders (
                    id               SERIAL PRIMARY KEY,
                    journal_id       INT REFERENCES degen_journal(id),
                    contract_address VARCHAR(100),
                    token_symbol     VARCHAR(20),
                    entry_price      FLOAT,
                    current_price    FLOAT,
                    multiplier       FLOAT,
                    reminder_type    VARCHAR(30),
                    sent             BOOLEAN DEFAULT FALSE,
                    sent_at          TIMESTAMP,
                    created_at       TIMESTAMP DEFAULT NOW(),
                    UNIQUE(journal_id, reminder_type)
                );
                INSERT INTO narrative_tracking (narrative)
                VALUES
                  ('AI'), ('DeFi'), ('Gaming'), ('Meme'),
                  ('RWA'), ('Layer2'), ('DePIN'), ('SocialFi'),
                  ('Liquid Staking'), ('NFT'), ('DAO'), ('Metaverse')
                ON CONFLICT (narrative) DO NOTHING;
                """
            )
        conn.commit()


def save_contract_scan(scan: dict) -> None:
    payload = {
        **scan,
        "safety_flags_json": json.dumps(scan.get("safety_flags", [])),
        "passed_checks_json": json.dumps(scan.get("passed_checks", [])),
        "raw_goplus_json": json.dumps(scan.get("raw_goplus", {})),
    }
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO contract_scans (
                    contract_address,chain,token_name,token_symbol,is_honeypot,honeypot_reason,mint_enabled,
                    owner_can_blacklist,owner_can_whitelist,is_proxy,is_open_source,trading_cooldown,transfer_pausable,
                    buy_tax,sell_tax,holder_count,top10_holder_pct,dev_wallet,dev_holding_pct,lp_holder_count,lp_locked_pct,
                    liquidity_usd,volume_24h,price_usd,market_cap,pair_created_at,dex_name,rug_score,rug_grade,safety_flags,
                    passed_checks,scanned_at,raw_goplus
                ) VALUES (
                    %(contract_address)s,%(chain)s,%(token_name)s,%(token_symbol)s,%(is_honeypot)s,%(honeypot_reason)s,%(mint_enabled)s,
                    %(owner_can_blacklist)s,%(owner_can_whitelist)s,%(is_proxy)s,%(is_open_source)s,%(trading_cooldown)s,%(transfer_pausable)s,
                    %(buy_tax)s,%(sell_tax)s,%(holder_count)s,%(top10_holder_pct)s,%(dev_wallet)s,%(dev_holding_pct)s,%(lp_holder_count)s,%(lp_locked_pct)s,
                    %(liquidity_usd)s,%(volume_24h)s,%(price_usd)s,%(market_cap)s,%(pair_created_at)s,%(dex_name)s,%(rug_score)s,%(rug_grade)s,%(safety_flags_json)s,
                    %(passed_checks_json)s,NOW(),%(raw_goplus_json)s
                )
                ON CONFLICT (contract_address, chain) DO UPDATE SET
                    token_name=EXCLUDED.token_name,
                    token_symbol=EXCLUDED.token_symbol,
                    is_honeypot=EXCLUDED.is_honeypot,
                    honeypot_reason=EXCLUDED.honeypot_reason,
                    mint_enabled=EXCLUDED.mint_enabled,
                    owner_can_blacklist=EXCLUDED.owner_can_blacklist,
                    owner_can_whitelist=EXCLUDED.owner_can_whitelist,
                    is_proxy=EXCLUDED.is_proxy,
                    is_open_source=EXCLUDED.is_open_source,
                    trading_cooldown=EXCLUDED.trading_cooldown,
                    transfer_pausable=EXCLUDED.transfer_pausable,
                    buy_tax=EXCLUDED.buy_tax,
                    sell_tax=EXCLUDED.sell_tax,
                    holder_count=EXCLUDED.holder_count,
                    top10_holder_pct=EXCLUDED.top10_holder_pct,
                    dev_wallet=EXCLUDED.dev_wallet,
                    dev_holding_pct=EXCLUDED.dev_holding_pct,
                    lp_holder_count=EXCLUDED.lp_holder_count,
                    lp_locked_pct=EXCLUDED.lp_locked_pct,
                    liquidity_usd=EXCLUDED.liquidity_usd,
                    volume_24h=EXCLUDED.volume_24h,
                    price_usd=EXCLUDED.price_usd,
                    market_cap=EXCLUDED.market_cap,
                    pair_created_at=EXCLUDED.pair_created_at,
                    dex_name=EXCLUDED.dex_name,
                    rug_score=EXCLUDED.rug_score,
                    rug_grade=EXCLUDED.rug_grade,
                    safety_flags=EXCLUDED.safety_flags,
                    passed_checks=EXCLUDED.passed_checks,
                    scanned_at=NOW(),
                    raw_goplus=EXCLUDED.raw_goplus
                """,
                payload,
            )
        conn.commit()


def get_contract_scan(address: str, chain: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM contract_scans WHERE LOWER(contract_address)=LOWER(%s) AND LOWER(chain)=LOWER(%s)",
                (address, chain),
            )
            row = cur.fetchone()
            if not row:
                return None
            data = dict(row)
            for field in ("safety_flags", "passed_checks", "raw_goplus"):
                data[field] = _decode_json_field(data.get(field), [] if field != "raw_goplus" else {})
            return data


def save_dev_wallet(data: dict) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO dev_wallets (contract_address,chain,wallet_address,label,watching)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (contract_address, wallet_address) DO NOTHING
                """,
                (
                    data.get("contract_address"),
                    data.get("chain", "eth"),
                    data.get("wallet_address"),
                    data.get("label", "deployer"),
                    bool(data.get("watching", True)),
                ),
            )
        conn.commit()


def get_watched_dev_wallets() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM dev_wallets WHERE watching=TRUE ORDER BY first_seen DESC")
            return [dict(r) for r in cur.fetchall()]


def save_dev_wallet_event(event: dict) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO dev_wallet_events (wallet_address,contract_address,chain,event_type,token_amount,usd_value,tx_hash,detected_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tx_hash) DO NOTHING
                """,
                (
                    event.get("wallet_address"),
                    event.get("contract_address"),
                    event.get("chain"),
                    event.get("event_type"),
                    event.get("token_amount"),
                    event.get("usd_value"),
                    event.get("tx_hash"),
                    event.get("detected_at"),
                ),
            )
        conn.commit()


def dev_wallet_event_exists(tx_hash: str) -> bool:
    if not tx_hash:
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM dev_wallet_events WHERE tx_hash=%s LIMIT 1", (tx_hash,))
            return cur.fetchone() is not None


def update_dev_wallet(wallet: str, contract: str, fields: dict) -> None:
    if not fields:
        return
    allowed = {"watching", "last_activity", "alert_on_sell", "alert_on_buy", "label"}
    updates = []
    values = []
    for key, val in fields.items():
        if key in allowed:
            updates.append(f"{key}=%s")
            values.append(val)
    if not updates:
        return
    values.extend([wallet, contract])
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE dev_wallets SET {', '.join(updates)} WHERE wallet_address=%s AND contract_address=%s",
                tuple(values),
            )
        conn.commit()


def get_degen_risk_settings() -> dict:
    defaults = {
        "account_size": 500.0,
        "max_position_pct": 2.0,
        "max_degen_exposure": 10.0,
        "min_liquidity_usd": 50000.0,
        "max_buy_tax": 5.0,
        "max_sell_tax": 5.0,
        "max_top10_holder_pct": 50.0,
        "min_rug_grade": "C",
        "block_honeypots": True,
        "block_no_lp_lock": False,
    }
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM degen_risk_settings WHERE id=1")
            row = cur.fetchone()
            return {**defaults, **(dict(row) if row else {})}


def create_degen_journal(entry: dict) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO degen_journal (
                    contract_address,chain,token_symbol,token_name,narrative,entry_price,entry_time,entry_mcap,entry_liquidity,
                    entry_holders,entry_age_hours,entry_rug_grade,position_size_usd,risk_usd,early_score,social_velocity,rug_score
                ) VALUES (%s,%s,%s,%s,%s,%s,NOW(),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (
                    entry.get("contract_address"),
                    entry.get("chain"),
                    entry.get("token_symbol"),
                    entry.get("token_name"),
                    entry.get("narrative"),
                    entry.get("entry_price"),
                    entry.get("entry_mcap"),
                    entry.get("entry_liquidity"),
                    entry.get("entry_holders"),
                    entry.get("entry_age_hours"),
                    entry.get("entry_rug_grade"),
                    entry.get("position_size_usd"),
                    entry.get("risk_usd"),
                    entry.get("early_score"),
                    entry.get("social_velocity"),
                    entry.get("rug_score"),
                ),
            )
            jid = int(cur.fetchone()["id"])
        conn.commit()
    return jid


def update_degen_journal(id: int, fields: dict) -> None:
    if not fields:
        return
    allowed = {
        "exit_price", "exit_time", "exit_reason", "peak_price", "peak_multiplier", "final_multiplier", "followed_exit_plan",
        "pnl_usd", "outcome", "notes", "tags",
    }
    sets, values = [], []
    for k, v in fields.items():
        if k in allowed:
            if k == "tags":
                sets.append(f"{k}=%s")
                values.append(json.dumps(v or []))
            else:
                sets.append(f"{k}=%s")
                values.append(v)
    if not sets:
        return
    values.append(id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE degen_journal SET {', '.join(sets)}, updated_at=NOW() WHERE id=%s", tuple(values))
        conn.commit()


def get_degen_journal_entries(limit: int = 50, outcome: str = None) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            if outcome:
                cur.execute("SELECT * FROM degen_journal WHERE outcome=%s ORDER BY created_at DESC LIMIT %s", (outcome, limit))
            else:
                cur.execute("SELECT * FROM degen_journal ORDER BY created_at DESC LIMIT %s", (limit,))
            return [dict(r) for r in cur.fetchall()]


def get_open_degen_journal_entries() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM degen_journal WHERE outcome IS NULL ORDER BY created_at DESC")
            return [dict(r) for r in cur.fetchall()]


def save_exit_reminder(data: dict) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO exit_reminders (journal_id,contract_address,token_symbol,entry_price,current_price,multiplier,reminder_type,sent,sent_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,CASE WHEN %s THEN NOW() ELSE NULL END)
                ON CONFLICT (journal_id, reminder_type) DO NOTHING
                """,
                (
                    data.get("journal_id"),
                    data.get("contract_address"),
                    data.get("token_symbol"),
                    data.get("entry_price"),
                    data.get("current_price"),
                    data.get("multiplier"),
                    data.get("reminder_type"),
                    bool(data.get("sent", False)),
                    bool(data.get("sent", False)),
                ),
            )
        conn.commit()


def exit_reminder_sent(journal_id: int, multiplier: float) -> bool:
    reminder_type = f"{float(multiplier):g}x"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM exit_reminders WHERE journal_id=%s AND reminder_type=%s AND sent=TRUE LIMIT 1",
                (journal_id, reminder_type),
            )
            return cur.fetchone() is not None


def get_narrative_count(narrative: str) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT mention_count FROM narrative_tracking WHERE narrative=%s", (narrative,))
            row = cur.fetchone()
            return int((row or {}).get("mention_count", 0)) if row else 0


def update_narrative(narrative: str, data: dict) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO narrative_tracking (narrative,mention_count,prev_count,velocity,trend,tokens,last_updated)
                VALUES (%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (narrative) DO UPDATE SET
                    mention_count=EXCLUDED.mention_count,
                    prev_count=EXCLUDED.prev_count,
                    velocity=EXCLUDED.velocity,
                    trend=EXCLUDED.trend,
                    tokens=EXCLUDED.tokens,
                    last_updated=NOW()
                """,
                (
                    narrative,
                    data.get("mention_count", 0),
                    data.get("prev_count", 0),
                    data.get("velocity", 0),
                    data.get("trend", "stable"),
                    json.dumps(data.get("tokens", [])),
                ),
            )
        conn.commit()


def get_all_narratives() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM narrative_tracking ORDER BY velocity DESC, mention_count DESC")
            rows = [dict(r) for r in cur.fetchall()]
            for row in rows:
                row["tokens"] = _decode_json_field(row.get("tokens"), [])
            return rows


def get_scanner_settings() -> dict:
    defaults = {
        "id": 1,
        "enabled": True,
        "interval_minutes": 60,
        "min_liquidity": 50000.0,
        "max_liquidity": 5000000.0,
        "min_volume_1h": 10000.0,
        "max_age_hours": 72.0,
        "min_probability_score": 55.0,
        "chains": ["solana"],
        "min_rug_grade": "C",
        "require_mint_revoked": True,
        "require_lp_locked": True,
        "max_top_holder_pct": 15.0,
    }
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM scanner_settings WHERE id=1")
            row = cur.fetchone()
            if not row:
                cur.execute("INSERT INTO scanner_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
                conn.commit()
                return defaults
            data = dict(row)
            data["chains"] = _decode_json_field(data.get("chains"), ["solana"])
            return {**defaults, **data}


def update_scanner_settings(fields: dict) -> None:
    if not fields:
        return
    allowed = {
        "enabled", "interval_minutes", "min_liquidity", "max_liquidity", "min_volume_1h", "max_age_hours",
        "min_probability_score", "chains", "min_rug_grade", "require_mint_revoked", "require_lp_locked",
        "max_top_holder_pct",
    }
    sets, values = [], []
    for key, value in fields.items():
        if key in allowed:
            sets.append(f"{key}=%s")
            values.append(json.dumps(value) if key == "chains" else value)
    if not sets:
        return
    values.append(1)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO scanner_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
            cur.execute(f"UPDATE scanner_settings SET {', '.join(sets)}, updated_at=NOW() WHERE id=%s", tuple(values))
        conn.commit()


def save_auto_scan_result(data: dict) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auto_scan_results (
                    scan_run_id, contract_address, chain, token_symbol, token_name,
                    probability_score, risk_score, early_score, social_score,
                    momentum_score, rank, alert_message_id, user_action, action_at, scan_data
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    data.get("scan_run_id"),
                    data.get("contract_address"),
                    data.get("chain", "solana"),
                    data.get("token_symbol"),
                    data.get("token_name"),
                    data.get("probability_score", 0),
                    data.get("risk_score", 0),
                    data.get("early_score", 0),
                    data.get("social_score", 0),
                    data.get("momentum_score", 0),
                    data.get("rank", 1),
                    data.get("alert_message_id"),
                    data.get("user_action"),
                    data.get("action_at"),
                    json.dumps(data.get("scan_data", {})),
                ),
            )
        conn.commit()


def get_latest_auto_scan(address: str) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM auto_scan_results
                WHERE contract_address=%s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (address,),
            )
            row = cur.fetchone()
            if not row:
                return {}
            data = dict(row)
            data["scan_data"] = _decode_json_field(data.get("scan_data"), {})
            return data


def update_auto_scan_action(address: str, action: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE auto_scan_results
                SET user_action=%s, action_at=NOW()
                WHERE id = (
                    SELECT id
                    FROM auto_scan_results
                    WHERE contract_address=%s AND user_action IS NULL
                    ORDER BY created_at DESC
                    LIMIT 1
                )
                """,
                (action, address),
            )
        conn.commit()


def add_to_watchlist(data: dict) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO watchlist (
                    contract_address, chain, token_symbol, token_name,
                    added_by, last_scanned, last_score, status, notes
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (contract_address) DO UPDATE SET
                    chain=EXCLUDED.chain,
                    token_symbol=EXCLUDED.token_symbol,
                    token_name=EXCLUDED.token_name,
                    last_scanned=COALESCE(EXCLUDED.last_scanned, watchlist.last_scanned),
                    last_score=EXCLUDED.last_score,
                    status='watching',
                    notes=COALESCE(EXCLUDED.notes, watchlist.notes)
                """,
                (
                    data.get("contract_address"),
                    data.get("chain", "solana"),
                    data.get("token_symbol", ""),
                    data.get("token_name", ""),
                    data.get("added_by", "auto_scan"),
                    data.get("last_scanned"),
                    data.get("last_score", 0),
                    data.get("status", "watching"),
                    data.get("notes"),
                ),
            )
        conn.commit()


def get_active_watchlist() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM watchlist
                WHERE status='watching'
                ORDER BY added_at DESC
                """
            )
            return [dict(row) for row in cur.fetchall()]


def update_watchlist_item(address: str, fields: dict) -> None:
    if not fields:
        return
    allowed = {"chain", "token_symbol", "token_name", "last_scanned", "last_score", "status", "notes"}
    sets, values = [], []
    for key, value in fields.items():
        if key in allowed:
            sets.append(f"{key}=%s")
            values.append(value)
    if not sets:
        return
    values.append(address)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE watchlist SET {', '.join(sets)} WHERE contract_address=%s", tuple(values))
        conn.commit()


def add_to_ignored(data: dict) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ignored_tokens (
                    contract_address, token_symbol, ignored_at,
                    expires_at, reason
                ) VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (contract_address) DO UPDATE SET
                    token_symbol=EXCLUDED.token_symbol,
                    ignored_at=EXCLUDED.ignored_at,
                    expires_at=EXCLUDED.expires_at,
                    reason=EXCLUDED.reason
                """,
                (
                    data.get("contract_address"),
                    data.get("token_symbol", ""),
                    data.get("ignored_at"),
                    data.get("expires_at"),
                    data.get("reason", "user_ignored"),
                ),
            )
        conn.commit()


def get_ignored_addresses() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT contract_address
                FROM ignored_tokens
                WHERE expires_at > NOW()
                """
            )
            return [row["contract_address"] for row in cur.fetchall()]


def validate_schema() -> None:
    """
    Read-only schema checks for critical runtime columns.
    Logs warnings for missing columns but does not raise.
    """
    checks = [
        ("demo_trades", "margin_reserved"),
        ("demo_accounts", "starting_balance"),
        ("degen_models", "strategy"),
        ("degen_models", "mandatory_rules"),
        ("degen_models", "min_age_minutes"),
        ("degen_models", "phase_timeframes"),
        ("alert_log", "direction"),
        ("alert_log", "quality_grade"),
        ("models", "phase_timeframes"),
        ("models", "regime_managed"),
    ]
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                for table, column in checks:
                    cur.execute(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.columns
                        WHERE table_name = %s
                          AND column_name = %s
                        """,
                        (table, column),
                    )
                    row = cur.fetchone()
                    exists = int((row or {}).get("count", 0)) > 0
                    if not exists:
                        log.warning(
                            "SCHEMA WARNING: %s.%s is missing — run ALTER TABLE to add it",
                            table,
                            column,
                        )
    except Exception as exc:
        log.warning("SCHEMA WARNING: validation failed: %s", exc)
