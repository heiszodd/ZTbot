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
