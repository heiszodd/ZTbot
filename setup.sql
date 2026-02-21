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
