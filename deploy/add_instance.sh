#!/usr/bin/env bash
# =============================================================================
# Alpha Bot — Add a New Bot Instance
#
# Creates a separate instance with its own config, database, API keys,
# and systemd service. All instances share the same code but run independently.
#
# Usage:
#   sudo ./deploy/add_instance.sh <instance-name>
#
# Examples:
#   sudo ./deploy/add_instance.sh btc-aggressive
#   sudo ./deploy/add_instance.sh altcoin-conservative
#   sudo ./deploy/add_instance.sh eth-only
# =============================================================================

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: sudo $0 <instance-name>"
    echo ""
    echo "Examples:"
    echo "  sudo $0 btc-aggressive"
    echo "  sudo $0 altcoin-conservative"
    echo "  sudo $0 eth-only"
    exit 1
fi

INSTANCE_NAME="$1"
APP_DIR="/opt/alpha-bot"
INSTANCE_DIR="${APP_DIR}/instances/${INSTANCE_NAME}"
SERVICE_NAME="alpha-bot-${INSTANCE_NAME}"
APP_USER="botuser"

# Validate instance name (alphanumeric + hyphens only)
if [[ ! "${INSTANCE_NAME}" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]*$ ]]; then
    echo "ERROR: Instance name must be alphanumeric with hyphens only."
    exit 1
fi

# Check the base installation exists
if [ ! -d "${APP_DIR}" ]; then
    echo "ERROR: Base installation not found at ${APP_DIR}."
    echo "Run deploy/setup_server.sh first."
    exit 1
fi

# Check instance doesn't already exist
if [ -d "${INSTANCE_DIR}" ]; then
    echo "ERROR: Instance '${INSTANCE_NAME}' already exists at ${INSTANCE_DIR}."
    exit 1
fi

echo "============================================"
echo "  Creating instance: ${INSTANCE_NAME}"
echo "============================================"

# ------------------------------------------------------------------
# 1. Create instance directory
# ------------------------------------------------------------------
echo "[1/4] Creating instance directory..."
sudo -u "${APP_USER}" mkdir -p "${INSTANCE_DIR}/logs"
sudo -u "${APP_USER}" mkdir -p "${INSTANCE_DIR}/data_cache"

# ------------------------------------------------------------------
# 2. Copy and customize config files
# ------------------------------------------------------------------
echo "[2/4] Creating instance config..."
sudo -u "${APP_USER}" cp "${APP_DIR}/config/settings.yaml" "${INSTANCE_DIR}/settings.yaml"
sudo -u "${APP_USER}" cp "${APP_DIR}/config/signals.yaml" "${INSTANCE_DIR}/signals.yaml"

# Update the settings to use instance-specific paths
# (user will customize assets, thresholds, etc. manually)
echo "  Config files created at ${INSTANCE_DIR}/"
echo "  Edit these to customize this instance's behavior."

# ------------------------------------------------------------------
# 3. Create instance .env file
# ------------------------------------------------------------------
echo "[3/4] Creating instance .env..."
ENV_FILE="${INSTANCE_DIR}/.env"
cat > "${ENV_FILE}" << ENVEOF
# =============================================================
# Alpha Bot — Instance: ${INSTANCE_NAME}
# Each instance can use different Coinbase API keys (different
# portfolios) or the same keys with different asset universes.
# =============================================================

# REQUIRED — Coinbase Advanced Trade
COINBASE_API_KEY=
COINBASE_API_SECRET=

# OPTIONAL — Extra data sources
FRED_API_KEY=
GLASSNODE_API_KEY=
CRYPTOCOMPARE_API_KEY=
WHALE_ALERT_API_KEY=

# OPTIONAL — Alert delivery (can be shared across instances)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
DISCORD_WEBHOOK_URL=
ENVEOF
chown "${APP_USER}:${APP_USER}" "${ENV_FILE}"
chmod 600 "${ENV_FILE}"

# ------------------------------------------------------------------
# 4. Create and install systemd service
# ------------------------------------------------------------------
echo "[4/4] Installing systemd service..."
cat > "/etc/systemd/system/${SERVICE_NAME}.service" << SVCEOF
[Unit]
Description=Alpha Bot — ${INSTANCE_NAME}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${INSTANCE_DIR}/.env
ExecStart=${APP_DIR}/venv/bin/python main.py --paper --config ${INSTANCE_DIR}/settings.yaml
Restart=on-failure
RestartSec=30
StartLimitIntervalSec=300
StartLimitBurst=5

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

# Security hardening
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=${APP_DIR}

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service"

echo ""
echo "============================================"
echo "  Instance '${INSTANCE_NAME}' created!"
echo "============================================"
echo ""
echo "Directory:  ${INSTANCE_DIR}/"
echo "Service:    ${SERVICE_NAME}"
echo ""
echo "Next steps:"
echo "  1. Edit API keys:     sudo nano ${INSTANCE_DIR}/.env"
echo "  2. Edit config:       sudo nano ${INSTANCE_DIR}/settings.yaml"
echo "     - Change assets:   e.g. [\"BTC-USD\"] or [\"ETH-USD\", \"SOL-USD\"]"
echo "     - Change thresholds, cycle interval, risk limits, etc."
echo "  3. Edit signals:      sudo nano ${INSTANCE_DIR}/signals.yaml"
echo "  4. Seed data:         sudo -u ${APP_USER} ${APP_DIR}/venv/bin/python -m scripts.seed_candles --months 6"
echo "  5. Start instance:    sudo systemctl start ${SERVICE_NAME}"
echo "  6. View logs:         sudo journalctl -u ${SERVICE_NAME} -f"
echo ""
