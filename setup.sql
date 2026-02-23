-- Run once in Supabase SQL Editor

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

ALTER TABLE models ADD COLUMN IF NOT EXISTS consecutive_losses INT DEFAULT 0;
ALTER TABLE models ADD COLUMN IF NOT EXISTS auto_deactivate_threshold INT DEFAULT 5;
ALTER TABLE models ADD COLUMN IF NOT EXISTS version INT DEFAULT 1;
ALTER TABLE models ADD COLUMN IF NOT EXISTS key_levels JSONB NOT NULL DEFAULT '[]';
ALTER TABLE models ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE models ADD COLUMN IF NOT EXISTS min_score FLOAT;
ALTER TABLE models ADD COLUMN IF NOT EXISTS tier_a_threshold FLOAT;
ALTER TABLE models ADD COLUMN IF NOT EXISTS tier_b_threshold FLOAT;
ALTER TABLE models ADD COLUMN IF NOT EXISTS tier_c_threshold FLOAT;

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

ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS screenshot_reminded BOOLEAN DEFAULT FALSE;
ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS revenge_flagged BOOLEAN DEFAULT FALSE;
ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS entry_confirmed BOOLEAN DEFAULT FALSE;
ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS closed_at TIMESTAMP;
ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS market_condition VARCHAR(20);
ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS source VARCHAR(30) DEFAULT 'signal';

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
ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS price_at_tp FLOAT;

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

ALTER TABLE news_events ADD COLUMN IF NOT EXISTS suppressed BOOLEAN DEFAULT FALSE;

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

-- Upgrade: degen enhancements + demo mode
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
    id                SERIAL PRIMARY KEY,
    token_id          INT REFERENCES degen_tokens(id),
    token_address     VARCHAR(100),
    token_symbol      VARCHAR(20),
    initial_risk_score INT,
    final_risk_score  INT,
    initial_moon_score INT,
    price_at_alert    FLOAT,
    price_at_rug      FLOAT,
    drop_pct          FLOAT,
    time_to_rug_minutes INT,
    was_alerted       BOOLEAN,
    was_in_watchlist  BOOLEAN,
    triggered_risk_factors JSONB,
    missed_signals    JSONB,
    detected_at       TIMESTAMP,
    rugged_at         TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS narrative_trends (
    id              SERIAL PRIMARY KEY,
    narrative       VARCHAR(50),
    token_count     INT DEFAULT 0,
    avg_moon_score  FLOAT DEFAULT 0,
    avg_risk_score  FLOAT DEFAULT 0,
    total_volume    FLOAT DEFAULT 0,
    win_rate        FLOAT DEFAULT 0,
    week_start      DATE,
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS demo_accounts (
    id              SERIAL PRIMARY KEY,
    section         VARCHAR(10) NOT NULL,
    balance         FLOAT NOT NULL DEFAULT 0,
    initial_deposit FLOAT NOT NULL DEFAULT 0,
    total_pnl       FLOAT DEFAULT 0,
    total_pnl_pct   FLOAT DEFAULT 0,
    peak_balance    FLOAT DEFAULT 0,
    lowest_balance  FLOAT DEFAULT 0,
    total_trades    INT DEFAULT 0,
    winning_trades  INT DEFAULT 0,
    losing_trades   INT DEFAULT 0,
    reset_id        INT DEFAULT 0,
    created_at      TIMESTAMP DEFAULT NOW(),
    last_reset_at   TIMESTAMP,
    UNIQUE(section)
);

CREATE TABLE IF NOT EXISTS demo_trades (
    id              SERIAL PRIMARY KEY,
    section         VARCHAR(10) NOT NULL,
    pair            VARCHAR(20),
    token_symbol    VARCHAR(20),
    direction       VARCHAR(5),
    entry_price     FLOAT,
    sl              FLOAT,
    tp1             FLOAT,
    tp2             FLOAT,
    tp3             FLOAT,
    position_size_usd FLOAT,
    risk_amount_usd FLOAT,
    risk_pct        FLOAT,
    current_price   FLOAT,
    current_pnl_usd FLOAT,
    current_pnl_pct FLOAT,
    current_x       FLOAT,
    result          VARCHAR(10),
    exit_price      FLOAT,
    final_pnl_usd   FLOAT,
    final_pnl_pct   FLOAT,
    final_x         FLOAT,
    model_id        VARCHAR(50),
    model_name      VARCHAR(100),
    tier            VARCHAR(5),
    score           FLOAT,
    source          VARCHAR(30),
    notes           TEXT,
    tp1_hit         BOOLEAN DEFAULT FALSE,
    reset_id        INT DEFAULT 0,
    opened_at       TIMESTAMP DEFAULT NOW(),
    closed_at       TIMESTAMP
);

CREATE TABLE IF NOT EXISTS demo_transactions (
    id          SERIAL PRIMARY KEY,
    section     VARCHAR(10),
    type        VARCHAR(20),
    amount      FLOAT,
    balance_after FLOAT,
    description TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
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

CREATE TABLE IF NOT EXISTS degen_watchlist (
    id SERIAL PRIMARY KEY,
    address VARCHAR(100) UNIQUE,
    symbol VARCHAR(20),
    name VARCHAR(100),
    chain VARCHAR(20),
    added_at TIMESTAMP DEFAULT NOW()
);

ALTER TABLE demo_trades ADD COLUMN IF NOT EXISTS remaining_size_usd FLOAT;
ALTER TABLE demo_trades ADD COLUMN IF NOT EXISTS partial_closes JSONB DEFAULT '[]';
ALTER TABLE demo_trades ADD COLUMN IF NOT EXISTS time_stop_minutes INT DEFAULT 30;

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

CREATE TABLE IF NOT EXISTS setup_phases (
    id                  SERIAL PRIMARY KEY,
    model_id            VARCHAR(100) NOT NULL,
    model_name          VARCHAR(200),
    pair                VARCHAR(20) NOT NULL,
    direction           VARCHAR(10),
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
    phase4_status       VARCHAR(20) DEFAULT 'waiting',
    phase4_score        FLOAT DEFAULT 0,
    phase4_passed_rules JSONB DEFAULT '[]',
    phase4_data         JSONB DEFAULT '{}',
    phase4_completed_at TIMESTAMP,
    alert_message_id    BIGINT,
    alert_sent_at       TIMESTAMP,
    entry_price         FLOAT,
    stop_loss           FLOAT,
    tp1                 FLOAT,
    tp2                 FLOAT,
    tp3                 FLOAT,
    overall_status      VARCHAR(20) DEFAULT 'phase1',
    check_count         INT DEFAULT 0,
    first_detected_at   TIMESTAMP DEFAULT NOW(),
    last_updated_at     TIMESTAMP DEFAULT NOW(),
    invalidated_at      TIMESTAMP,
    invalidation_reason TEXT,
    UNIQUE(model_id, pair, direction)
);
CREATE INDEX IF NOT EXISTS idx_setup_phases_status ON setup_phases(overall_status);
CREATE INDEX IF NOT EXISTS idx_setup_phases_model ON setup_phases(model_id);

CREATE TABLE IF NOT EXISTS session_journal (
    id SERIAL PRIMARY KEY,
    session_date DATE NOT NULL,
    session_name VARCHAR(20) NOT NULL,
    pair VARCHAR(20) NOT NULL,
    asian_high FLOAT,
    asian_low FLOAT,
    asian_range_pts FLOAT,
    london_swept VARCHAR(10),
    london_swept_at TIMESTAMP,
    ny_direction VARCHAR(10),
    ny_reversed BOOLEAN DEFAULT FALSE,
    key_levels JSONB DEFAULT '[]',
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(session_date, pair)
);

CREATE TABLE IF NOT EXISTS alert_lifecycle (
    id SERIAL PRIMARY KEY,
    setup_phase_id INT REFERENCES setup_phases(id),
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

CREATE TABLE IF NOT EXISTS model_performance (
    id SERIAL PRIMARY KEY,
    model_id VARCHAR(100) UNIQUE NOT NULL,
    model_name VARCHAR(200),
    total_alerts INT DEFAULT 0,
    entries_touched INT DEFAULT 0,
    phase4_confirms INT DEFAULT 0,
    phase4_fails INT DEFAULT 0,
    demo_trades INT DEFAULT 0,
    demo_wins INT DEFAULT 0,
    demo_losses INT DEFAULT 0,
    demo_win_rate FLOAT DEFAULT 0,
    avg_r FLOAT DEFAULT 0,
    grade VARCHAR(5) DEFAULT 'N/A',
    graded_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT NOW()
);
ALTER TABLE models ADD COLUMN IF NOT EXISTS phase_timeframes JSONB DEFAULT '{"1":"4h","2":"1h","3":"15m","4":"5m"}';

-- Security hardening: enable RLS on all public application tables exposed by PostgREST.
ALTER TABLE IF EXISTS public.discipline_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.candles ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.alert_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.user_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.model_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.daily_summary ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.weekly_goals ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.checklist_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.journal_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.monthly_goals ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.user_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.weekly_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.tracked_wallets ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.wallet_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.degen_watchlist ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.trade_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.wallet_copy_trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.news_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.news_trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.degen_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.demo_trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.rug_postmortems ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.narrative_trends ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.demo_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.chart_analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.demo_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.ca_monitors ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.pending_setups ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.model_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.models ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.degen_trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.degen_models ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.degen_model_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.degen_model_versions ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS risk_settings (
    id                  SERIAL PRIMARY KEY,
    account_size        FLOAT DEFAULT 1000.0,
    risk_per_trade_pct  FLOAT DEFAULT 1.0,
    max_daily_loss_pct  FLOAT DEFAULT 3.0,
    max_open_trades     INT DEFAULT 3,
    max_exposure_pct    FLOAT DEFAULT 5.0,
    max_pair_exposure   FLOAT DEFAULT 2.0,
    risk_reward_min     FLOAT DEFAULT 1.5,
    enabled             BOOLEAN DEFAULT TRUE,
    min_quality_grade   VARCHAR(5) DEFAULT 'C',
    updated_at          TIMESTAMP DEFAULT NOW()
);
INSERT INTO risk_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

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

ALTER TABLE alert_lifecycle
    ADD COLUMN IF NOT EXISTS risk_level VARCHAR(10),
    ADD COLUMN IF NOT EXISTS risk_amount FLOAT,
    ADD COLUMN IF NOT EXISTS position_size FLOAT,
    ADD COLUMN IF NOT EXISTS leverage FLOAT,
    ADD COLUMN IF NOT EXISTS rr_ratio FLOAT,
    ADD COLUMN IF NOT EXISTS quality_grade VARCHAR(5),
    ADD COLUMN IF NOT EXISTS quality_score FLOAT;

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

ALTER TABLE models
    ADD COLUMN IF NOT EXISTS regime_managed BOOLEAN DEFAULT FALSE;

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
    tx_hash          VARCHAR(100),
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

INSERT INTO degen_risk_settings (id) VALUES (1)
ON CONFLICT (id) DO NOTHING;

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
    id                SERIAL PRIMARY KEY,
    contract_address  VARCHAR(100),
    chain             VARCHAR(20),
    token_symbol      VARCHAR(20),
    token_name        VARCHAR(100),
    narrative         VARCHAR(50),
    entry_price       FLOAT,
    entry_time        TIMESTAMP,
    entry_mcap        FLOAT,
    entry_liquidity   FLOAT,
    entry_holders     INT,
    entry_age_hours   FLOAT,
    entry_rug_grade   VARCHAR(5),
    position_size_usd FLOAT,
    risk_usd          FLOAT,
    exit_price        FLOAT,
    exit_time         TIMESTAMP,
    exit_reason       VARCHAR(100),
    peak_price        FLOAT,
    peak_multiplier   FLOAT,
    final_multiplier  FLOAT,
    followed_exit_plan BOOLEAN,
    pnl_usd           FLOAT,
    outcome           VARCHAR(20),
    early_score       FLOAT,
    social_velocity   FLOAT,
    rug_score         FLOAT,
    notes             TEXT,
    tags              JSONB DEFAULT '[]',
    created_at        TIMESTAMP DEFAULT NOW(),
    updated_at        TIMESTAMP DEFAULT NOW()
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
    created_at       TIMESTAMP DEFAULT NOW()
);

INSERT INTO narrative_tracking (narrative)
VALUES
  ('AI'), ('DeFi'), ('Gaming'), ('Meme'),
  ('RWA'), ('Layer2'), ('DePIN'), ('SocialFi'),
  ('Liquid Staking'), ('NFT'), ('DAO'), ('Metaverse')
ON CONFLICT (narrative) DO NOTHING;

CREATE TABLE IF NOT EXISTS auto_scan_results (
    id               SERIAL PRIMARY KEY,
    scan_run_id      VARCHAR(50) NOT NULL,
    contract_address VARCHAR(100) NOT NULL,
    chain            VARCHAR(20) DEFAULT 'solana',
    token_symbol     VARCHAR(20),
    token_name       VARCHAR(100),
    probability_score FLOAT DEFAULT 0,
    risk_score       FLOAT DEFAULT 0,
    early_score      FLOAT DEFAULT 0,
    social_score     FLOAT DEFAULT 0,
    momentum_score   FLOAT DEFAULT 0,
    rank             INT DEFAULT 1,
    alert_message_id INT,
    user_action      VARCHAR(20),
    action_at        TIMESTAMP,
    scan_data        JSONB DEFAULT '{}',
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_auto_scan_address
    ON auto_scan_results(contract_address);
CREATE INDEX IF NOT EXISTS idx_auto_scan_action
    ON auto_scan_results(user_action);

CREATE TABLE IF NOT EXISTS watchlist (
    id               SERIAL PRIMARY KEY,
    contract_address VARCHAR(100) NOT NULL UNIQUE,
    chain            VARCHAR(20) DEFAULT 'solana',
    token_symbol     VARCHAR(20),
    token_name       VARCHAR(100),
    added_at         TIMESTAMP DEFAULT NOW(),
    added_by         VARCHAR(30) DEFAULT 'auto_scan',
    last_scanned     TIMESTAMP,
    last_score       FLOAT,
    status           VARCHAR(20) DEFAULT 'watching',
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS ignored_tokens (
    id               SERIAL PRIMARY KEY,
    contract_address VARCHAR(100) NOT NULL UNIQUE,
    token_symbol     VARCHAR(20),
    ignored_at       TIMESTAMP DEFAULT NOW(),
    expires_at       TIMESTAMP,
    reason           VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS scanner_settings (
    id                    SERIAL PRIMARY KEY,
    enabled               BOOLEAN DEFAULT TRUE,
    interval_minutes      INT DEFAULT 60,
    min_liquidity         FLOAT DEFAULT 50000,
    max_liquidity         FLOAT DEFAULT 5000000,
    min_volume_1h         FLOAT DEFAULT 10000,
    max_age_hours         FLOAT DEFAULT 72,
    min_probability_score FLOAT DEFAULT 55,
    chains                JSONB DEFAULT '["solana"]',
    min_rug_grade         VARCHAR(5) DEFAULT 'C',
    require_mint_revoked  BOOLEAN DEFAULT TRUE,
    require_lp_locked     BOOLEAN DEFAULT TRUE,
    max_top_holder_pct    FLOAT DEFAULT 15,
    updated_at            TIMESTAMP DEFAULT NOW()
);

INSERT INTO scanner_settings (id) VALUES (1)
ON CONFLICT (id) DO NOTHING;
