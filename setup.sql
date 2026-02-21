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
    logged_at   TIMESTAMP DEFAULT NOW()
);

ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS screenshot_reminded BOOLEAN DEFAULT FALSE;
ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS revenge_flagged BOOLEAN DEFAULT FALSE;
ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS entry_confirmed BOOLEAN DEFAULT FALSE;
ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS closed_at TIMESTAMP;
ALTER TABLE trade_log ADD COLUMN IF NOT EXISTS market_condition VARCHAR(20);

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
