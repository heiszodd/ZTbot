# 🤖 ZTbot — Trading Intelligence Bot

A **Telegram-based trading intelligence bot** that combines ICT / SMC technical analysis, multi-chain execution, AI-powered chart reading, and disciplined risk management into a single automated assistant.

---

## ✨ Features

### 📊 Technical Analysis Engine
- **ICT / SMC pattern detection** — Fair Value Gaps, Order Blocks, Liquidity Sweeps, Breaker Blocks, Displacement Candles, and more.
- **Multi-timeframe scoring** — scans 1m through 4H candles and scores setups against customisable trading models.
- **Tier-based risk sizing** — Tier A / B / C classification with automatic position sizing.
- **ATR volatility bands** — dynamic volatility regime detection (Low → Extreme) with position-size adjustments.
- **Session awareness** — London, New York, Asia, and Overlap windows with smart session filtering.
- **Backtesting engine** — bar-by-bar backtester with optimisation over tier/threshold parameters.

### 🔗 Multi-Chain Execution
| Chain | Capabilities |
|---|---|
| **Hyperliquid** | Perps trading — account reading, order execution, trade planning, position monitoring, analytics |
| **Solana** | Token swaps via Jupiter, DCA execution, wallet tracking, auto-sell monitor |
| **Polymarket** | Prediction-market scanning, sentiment analysis, demo trading, alert monitoring |

### 🧠 AI-Powered Analysis
- **Gemini 2.0 Flash** integration for single-timeframe and multi-timeframe chart analysis.
- Contract-address (CA) deep-dive reports with rug-check scoring, dev-wallet age, and bonding-curve analysis.

### 🛡️ Security & Risk Management
- **User authentication** — allowlist of Telegram user IDs.
- **Encryption at rest** — API keys and secrets encrypted with Fernet symmetric encryption.
- **Emergency stop** — instant halt of all trading activity.
- **Spending limits** — configurable per-trade and daily caps.
- **Rate limiting** — protects against runaway API calls.
- **Anomaly detection** — flags unusual account behaviour.
- **Heartbeat** — daily health-check message to confirm the bot is alive.
- **Audit logging** — every significant action is written to the database.

### 📰 Market Intelligence
- **Economic calendar** — ForexFactory JSON feed + recurring macro events (NFP, CPI, FOMC, etc.).
- **Crypto news** — CryptoPanic headlines with sentiment scoring.
- **News blackout** — automatically suppresses new setups within a configurable window around high-impact events.
- **Correlation guard** — prevents over-exposure to correlated pairs (e.g. BTC ↔ SOL).

### 📈 Performance Tracking
- Discipline scoring with violation penalties (V1 – V5) and clean-trade bonuses.
- Rolling 10-trade window analysis.
- Win-rate heatmaps by hour.
- Per-tier and per-session statistics.

---

## 🏗️ Architecture

```
main.py                  ← Entry point — registers handlers & scheduled jobs
├── config.py            ← Environment config, risk parameters, model rules
├── engine.py            ← Core scoring, backtesting, volatility classification
├── prices.py            ← OHLCV data (Binance + CryptoCompare), FVG/OB detection
├── news.py              ← Economic calendar, crypto news, event sentiment
├── formatters.py        ← Telegram message formatting (alerts, stats, reports)
├── db.py                ← PostgreSQL / Supabase persistence layer
│
├── engine/
│   ├── phase_engine.py        ← Scheduled scan → score → alert pipeline
│   ├── ict_engine.py          ← ICT / SMC pattern evaluation
│   ├── risk_engine.py         ← Position sizing & risk checks
│   ├── rules.py               ← Model rule definitions & evaluation
│   ├── quality_scorer.py      ← Setup quality grading
│   ├── regime_detector.py     ← Market-regime classification
│   ├── correlation_guard.py   ← Cross-pair exposure limits
│   ├── execution_pipeline.py  ← Trade execution orchestration
│   ├── session_checklist.py   ← Pre-session checklists
│   ├── session_journal.py     ← Post-session journaling
│   ├── notification_filter.py ← Alert deduplication & throttling
│   │
│   ├── hyperliquid/           ← Hyperliquid perps integration
│   ├── solana/                ← Solana token trading (Jupiter, DCA)
│   ├── polymarket/            ← Polymarket prediction markets
│   ├── predictions/           ← Prediction models
│   └── degen/                 ← Degen-mode scanner & wallet tracker
│
├── handlers/
│   ├── commands.py            ← /start, /stop, /resume, /security, /help
│   ├── router.py              ← Callback-query & free-text routing
│   ├── perps_handler.py       ← Perps UI flows
│   ├── degen_handler.py       ← Degen UI flows
│   ├── predictions_handler.py ← Predictions UI flows
│   ├── wallet_setup.py        ← Guided wallet-connection wizards
│   ├── nav.py                 ← Navigation menus
│   └── settings_handler.py    ← Bot settings
│
├── security/
│   ├── auth.py                ← User ID allowlist
│   ├── encryption.py          ← Fernet encrypt / decrypt helpers
│   ├── key_manager.py         ← API key storage & retrieval
│   ├── emergency_stop.py      ← Global trading halt
│   ├── spending_limits.py     ← Per-trade & daily limits
│   ├── rate_limiter.py        ← API call throttling
│   ├── anomaly_detector.py    ← Unusual-activity flagging
│   ├── heartbeat.py           ← Daily alive-check
│   ├── audit.py               ← Audit-trail logging
│   └── confirmation.py        ← Trade confirmation prompts
│
└── degen/                     ← Degen token analysis library
    ├── scanner.py             ← New-token scanner
    ├── moon_engine.py         ← Moon-shot scoring
    ├── risk_engine.py         ← Token risk assessment
    ├── wallet_tracker.py      ← Smart-wallet copy-trading
    ├── rule_library.py        ← Degen rule definitions
    ├── model_engine.py        ← Degen model evaluation
    ├── narrative_tracker.py   ← Narrative / trend detection
    ├── dev_checker.py         ← Developer-wallet analysis
    ├── postmortem.py          ← Trade post-mortem reports
    └── templates.py           ← Message templates
```

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.11+**
- **PostgreSQL** (or a Supabase project)
- A **Telegram Bot Token** (via [@BotFather](https://t.me/BotFather))
- A **Gemini API key** (free tier works)

### 1. Clone & install

```bash
git clone https://github.com/heiszodd/ZTbot.git
cd ZTbot
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your values
```

**Required variables:**

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Telegram bot token |
| `CHAT_ID` | Your Telegram chat / user ID |
| `DATABASE_URL` | PostgreSQL connection string |
| `GEMINI_API_KEY` | Google Gemini API key |

**Optional variables** (bot works without these):

| Variable | Description |
|---|---|
| `CRYPTOPANIC_TOKEN` | CryptoPanic API key for crypto news |
| `HELIUS_API_KEY` | Helius RPC for Solana |
| `ETHERSCAN_KEY` | Etherscan API key |
| `BSCSCAN_KEY` | BSCScan API key |
| `BIRDEYE_API_KEY` | Birdeye token data |
| `ENCRYPTION_KEY` | Fernet key for encrypting stored secrets |
| `ALLOWED_USER_IDS` | Comma-separated Telegram user IDs |

### 3. Set up the database

```bash
psql -U <user> -d <dbname> -f setup.sql
```

### 4. Run

```bash
python main.py
```

The bot will start polling Telegram for updates and run its scheduled engines:

| Job | Interval | Description |
|---|---|---|
| **Phase Engine** | 5 min | Scan pairs → score setups → fire alerts |
| **HL Monitor** | 5 min | Monitor Hyperliquid positions |
| **Auto-Sell** | 1 min | Solana auto-sell checks |
| **Poly Monitor** | 15 min | Polymarket alert scanning |
| **Heartbeat** | Daily 08:00 UTC | Health-check message |

---

## 🐳 Docker

```bash
docker build -t ztbot .
docker run --env-file .env ztbot
```

---

## 🚄 Deploy to Railway

The repo includes a `Procfile` and `nixpacks.toml` for one-click Railway deployment:

1. Connect your GitHub repo to [Railway](https://railway.app).
2. Set the required environment variables in the Railway dashboard.
3. Deploy — Railway will auto-detect the Procfile and start the bot.

---

## 🖥️ Deploy to a VPS

A one-shot deployment script is included for Ubuntu 24.04:

```bash
# As root on a fresh VPS:
bash deploy.sh
# Then edit /home/tradingbot/trading_bot/.env
systemctl start tradingbot
journalctl -u tradingbot -f
```

---

## 🤝 Telegram Commands

| Command | Description |
|---|---|
| `/start` | Launch the bot menu |
| `/stop` | Emergency-halt all trading |
| `/resume` | Resume trading after a halt |
| `/security` | View security status & controls |
| `/help` | Show available commands |

---

## ⚙️ Configuration Reference

Key parameters in `config.py`:

| Parameter | Default | Description |
|---|---|---|
| `TIER_RISK` | A: 2%, B: 1%, C: 0.5% | Risk % per tier |
| `ATR_BANDS` | 4 bands | Volatility regime thresholds |
| `SESSIONS` | London / NY / Asia / Overlap | Session hour windows (UTC) |
| `NEWS_BLACKOUT_MIN` | 30 | Minutes to suppress alerts around events |
| `SCANNER_INTERVAL` | 300 | Seconds between scans |
| `CRYPTO_PAIRS` | BTCUSDT, SOLUSDT | Watched trading pairs |
| `TIMEFRAMES` | 1m – 4H | Candle timeframes |

---

## 📄 License

This project is private. All rights reserved.
