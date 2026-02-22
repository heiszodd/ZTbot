#!/bin/bash
# Run this on a fresh Ubuntu 24.04 VPS as root.
# Usage:  bash deploy.sh

set -e

echo "=== 1. System packages ==="
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv postgresql postgresql-contrib git nano

echo "=== 2. Create bot user ==="
id -u tradingbot &>/dev/null || useradd -m -s /bin/bash tradingbot

echo "=== 3. PostgreSQL ==="
sudo -u postgres psql <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='tradingbot') THEN
    CREATE USER tradingbot WITH PASSWORD 'changeme_strong_password';
  END IF;
END $$;
SELECT 'CREATE DATABASE tradingbot' WHERE NOT EXISTS (
  SELECT FROM pg_database WHERE datname='tradingbot'
)\gexec
GRANT ALL PRIVILEGES ON DATABASE tradingbot TO tradingbot;
SQL

echo "=== 4. Project setup ==="
BOT_DIR=/home/tradingbot/trading_bot
mkdir -p $BOT_DIR
chown -R tradingbot:tradingbot $BOT_DIR

echo "=== 5. Copy files ==="
# If you're running this from the project folder:
cp -r . $BOT_DIR/
chown -R tradingbot:tradingbot $BOT_DIR

echo "=== 6. Python venv ==="
sudo -u tradingbot bash -c "
  python3 -m venv $BOT_DIR/venv
  $BOT_DIR/venv/bin/pip install --upgrade pip
  $BOT_DIR/venv/bin/pip install -r $BOT_DIR/requirements.txt
"

echo "=== 7. Database tables ==="
sudo -u tradingbot psql -U tradingbot -d tradingbot -f $BOT_DIR/setup.sql

echo "=== 8. Systemd service ==="
cp $BOT_DIR/tradingbot.service /etc/systemd/system/tradingbot.service
sed -i 's|/home/tradingbot/trading_bot|'"$BOT_DIR"'|g' /etc/systemd/system/tradingbot.service
systemctl daemon-reload
systemctl enable tradingbot

echo ""
echo "=== DONE ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env:  nano $BOT_DIR/.env"
echo "     BOT_TOKEN=..."
echo "     CHAT_ID=..."
echo "     DB_URL=postgresql://tradingbot:changeme_strong_password@localhost/tradingbot"
echo "     GEMINI_API_KEY=..."
echo ""
echo "  2. Start:  systemctl start tradingbot"
echo "  3. Logs:   journalctl -u tradingbot -f"


echo "Railway checklist: BOT_TOKEN, CHAT_ID, DB_URL, GEMINI_API_KEY must be set."
