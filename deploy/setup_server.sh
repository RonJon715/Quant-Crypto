#!/usr/bin/env bash
# =============================================================================
# Alpha Bot — Server Setup Script
# Run this ONCE on a fresh Ubuntu 22.04+ VPS to set up everything.
#
# Usage:
#   chmod +x deploy/setup_server.sh
#   sudo ./deploy/setup_server.sh
# =============================================================================

set -euo pipefail

APP_USER="botuser"
APP_DIR="/opt/alpha-bot"
REPO_URL="https://github.com/RonJon715/Quant-Crypto.git"
BRANCH="claude/crypto-trading-bot-f2BeU"
PYTHON_VERSION="3.12"

echo "============================================"
echo "  Alpha Bot — Server Setup"
echo "============================================"

# ------------------------------------------------------------------
# 1. System packages
# ------------------------------------------------------------------
echo "[1/7] Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    software-properties-common \
    python${PYTHON_VERSION} \
    python${PYTHON_VERSION}-venv \
    python3-pip \
    git \
    sqlite3 \
    curl \
    htop \
    unattended-upgrades > /dev/null

# Make sure python3 points to the right version
update-alternatives --install /usr/bin/python3 python3 /usr/bin/python${PYTHON_VERSION} 1 2>/dev/null || true

# ------------------------------------------------------------------
# 2. Create dedicated user (no login shell, no password)
# ------------------------------------------------------------------
echo "[2/7] Creating application user '${APP_USER}'..."
if ! id "${APP_USER}" &>/dev/null; then
    useradd --system --create-home --shell /usr/sbin/nologin "${APP_USER}"
fi

# ------------------------------------------------------------------
# 3. Clone repository
# ------------------------------------------------------------------
echo "[3/7] Cloning repository..."
if [ -d "${APP_DIR}" ]; then
    echo "  Directory ${APP_DIR} already exists — pulling latest..."
    cd "${APP_DIR}"
    sudo -u "${APP_USER}" git pull origin "${BRANCH}" || true
else
    git clone --branch "${BRANCH}" "${REPO_URL}" "${APP_DIR}"
    chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"
fi

# ------------------------------------------------------------------
# 4. Virtual environment + dependencies
# ------------------------------------------------------------------
echo "[4/7] Setting up Python virtual environment..."
cd "${APP_DIR}"
sudo -u "${APP_USER}" python3 -m venv venv
sudo -u "${APP_USER}" ./venv/bin/pip install --upgrade pip -q
sudo -u "${APP_USER}" ./venv/bin/pip install -r requirements.txt -q

# ------------------------------------------------------------------
# 5. Create directories for data and logs
# ------------------------------------------------------------------
echo "[5/7] Creating data directories..."
sudo -u "${APP_USER}" mkdir -p "${APP_DIR}/logs"
sudo -u "${APP_USER}" mkdir -p "${APP_DIR}/data_cache/onchain"
sudo -u "${APP_USER}" mkdir -p "${APP_DIR}/data_cache/macro"

# ------------------------------------------------------------------
# 6. Install systemd service
# ------------------------------------------------------------------
echo "[6/7] Installing systemd service..."
cp "${APP_DIR}/deploy/alpha-bot.service" /etc/systemd/system/alpha-bot.service
systemctl daemon-reload
systemctl enable alpha-bot.service
echo "  Service installed and enabled (will start on boot)."
echo "  NOTE: You must configure your .env file before starting!"

# ------------------------------------------------------------------
# 7. Create .env template
# ------------------------------------------------------------------
ENV_FILE="${APP_DIR}/.env"
if [ ! -f "${ENV_FILE}" ]; then
    echo "[7/7] Creating .env template..."
    cat > "${ENV_FILE}" << 'ENVEOF'
# =============================================================
# Alpha Bot — Environment Variables
# Fill in your API keys below, then start the bot with:
#   sudo systemctl start alpha-bot
# =============================================================

# REQUIRED — Coinbase Advanced Trade
COINBASE_API_KEY=
COINBASE_API_SECRET=

# OPTIONAL — Extra data sources (improve signal quality)
FRED_API_KEY=
GLASSNODE_API_KEY=
CRYPTOCOMPARE_API_KEY=
WHALE_ALERT_API_KEY=

# OPTIONAL — Alert delivery
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
DISCORD_WEBHOOK_URL=
ENVEOF
    chown "${APP_USER}:${APP_USER}" "${ENV_FILE}"
    chmod 600 "${ENV_FILE}"
    echo "  Created ${ENV_FILE} — edit this file with your API keys."
else
    echo "[7/7] .env already exists, skipping."
fi

echo ""
echo "============================================"
echo "  Setup complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Edit your API keys:    sudo nano ${APP_DIR}/.env"
echo "  2. Seed historical data:  sudo -u ${APP_USER} ${APP_DIR}/venv/bin/python -m scripts.seed_candles --months 6"
echo "  3. Run tests:             sudo -u ${APP_USER} ${APP_DIR}/venv/bin/python -m pytest tests/ -v"
echo "  4. Start paper trading:   sudo systemctl start alpha-bot"
echo "  5. Check status:          sudo systemctl status alpha-bot"
echo "  6. View logs:             sudo journalctl -u alpha-bot -f"
echo ""
echo "The bot defaults to PAPER mode. To switch to live, edit"
echo "config/settings.yaml and set sandbox: false, then restart."
echo ""
