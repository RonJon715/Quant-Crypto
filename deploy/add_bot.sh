#!/usr/bin/env bash
# =============================================================================
# Add Any Bot — Deploy a completely different bot to the same server.
#
# This sets up an isolated environment for ANY Python bot:
#   - Its own directory under /opt/<name>
#   - Its own Python virtual environment
#   - Its own systemd service (auto-start, auto-restart)
#   - Its own .env file for secrets
#   - Its own log stream via journalctl
#
# Usage:
#   sudo ./deploy/add_bot.sh <name> <git-repo-url> [branch] [start-command]
#
# Examples:
#   sudo ./deploy/add_bot.sh dca-bot https://github.com/you/dca-bot.git
#   sudo ./deploy/add_bot.sh arb-bot https://github.com/you/arb-bot.git main "python bot.py"
#   sudo ./deploy/add_bot.sh grid-bot https://github.com/you/grid-bot.git master "python run.py --live"
# =============================================================================

set -euo pipefail

# ------------------------------------------------------------------
# Parse arguments
# ------------------------------------------------------------------
if [ $# -lt 2 ]; then
    echo "Usage: sudo $0 <name> <git-repo-url> [branch] [start-command]"
    echo ""
    echo "Arguments:"
    echo "  name           Short name for the bot (e.g. dca-bot, arb-bot)"
    echo "  git-repo-url   HTTPS URL of the git repository"
    echo "  branch         Git branch to use (default: main)"
    echo "  start-command  Command to start the bot (default: python main.py)"
    echo ""
    echo "Examples:"
    echo "  sudo $0 dca-bot https://github.com/you/dca-bot.git"
    echo "  sudo $0 arb-bot https://github.com/you/arb-bot.git main \"python bot.py --config prod.yaml\""
    exit 1
fi

BOT_NAME="$1"
REPO_URL="$2"
BRANCH="${3:-main}"
START_CMD="${4:-python main.py}"

BOT_DIR="/opt/${BOT_NAME}"
BOT_USER="botuser"
SERVICE_NAME="${BOT_NAME}"

# Validate name
if [[ ! "${BOT_NAME}" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]]; then
    echo "ERROR: Bot name must be alphanumeric (hyphens and underscores OK)."
    exit 1
fi

if [ -d "${BOT_DIR}" ]; then
    echo "ERROR: ${BOT_DIR} already exists. Remove it first or pick a different name."
    exit 1
fi

echo "============================================"
echo "  Adding bot: ${BOT_NAME}"
echo "============================================"
echo "  Repo:    ${REPO_URL}"
echo "  Branch:  ${BRANCH}"
echo "  Dir:     ${BOT_DIR}"
echo "  Command: ${START_CMD}"
echo ""

# ------------------------------------------------------------------
# 1. System prerequisites (idempotent)
# ------------------------------------------------------------------
echo "[1/6] Checking system prerequisites..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git > /dev/null

# Create shared bot user if it doesn't exist
if ! id "${BOT_USER}" &>/dev/null; then
    echo "  Creating user '${BOT_USER}'..."
    useradd --system --create-home --shell /usr/sbin/nologin "${BOT_USER}"
fi

# ------------------------------------------------------------------
# 2. Clone the repo
# ------------------------------------------------------------------
echo "[2/6] Cloning repository..."
git clone --branch "${BRANCH}" "${REPO_URL}" "${BOT_DIR}"
chown -R "${BOT_USER}:${BOT_USER}" "${BOT_DIR}"

# ------------------------------------------------------------------
# 3. Virtual environment + dependencies
# ------------------------------------------------------------------
echo "[3/6] Setting up Python virtual environment..."
cd "${BOT_DIR}"
sudo -u "${BOT_USER}" python3 -m venv venv

# Install dependencies from whatever file exists
if [ -f "requirements.txt" ]; then
    sudo -u "${BOT_USER}" ./venv/bin/pip install --upgrade pip -q
    sudo -u "${BOT_USER}" ./venv/bin/pip install -r requirements.txt -q
    echo "  Installed from requirements.txt"
elif [ -f "pyproject.toml" ]; then
    sudo -u "${BOT_USER}" ./venv/bin/pip install --upgrade pip -q
    sudo -u "${BOT_USER}" ./venv/bin/pip install -e . -q
    echo "  Installed from pyproject.toml"
elif [ -f "setup.py" ]; then
    sudo -u "${BOT_USER}" ./venv/bin/pip install --upgrade pip -q
    sudo -u "${BOT_USER}" ./venv/bin/pip install -e . -q
    echo "  Installed from setup.py"
else
    sudo -u "${BOT_USER}" ./venv/bin/pip install --upgrade pip -q
    echo "  WARNING: No requirements.txt, pyproject.toml, or setup.py found."
    echo "  You may need to install dependencies manually:"
    echo "    sudo -u ${BOT_USER} ${BOT_DIR}/venv/bin/pip install <package>"
fi

# ------------------------------------------------------------------
# 4. Create .env file
# ------------------------------------------------------------------
echo "[4/6] Creating .env file..."
ENV_FILE="${BOT_DIR}/.env"
if [ ! -f "${ENV_FILE}" ]; then
    cat > "${ENV_FILE}" << ENVEOF
# =============================================================
# ${BOT_NAME} — Environment Variables
# Add your API keys and secrets here.
# This file is only readable by ${BOT_USER}.
# =============================================================

# Add your keys below, for example:
# API_KEY=
# API_SECRET=
# TELEGRAM_BOT_TOKEN=
ENVEOF
    chown "${BOT_USER}:${BOT_USER}" "${ENV_FILE}"
    chmod 600 "${ENV_FILE}"
fi

# ------------------------------------------------------------------
# 5. Create log directory
# ------------------------------------------------------------------
echo "[5/6] Creating log directory..."
sudo -u "${BOT_USER}" mkdir -p "${BOT_DIR}/logs"

# ------------------------------------------------------------------
# 6. Create and install systemd service
# ------------------------------------------------------------------
echo "[6/6] Installing systemd service..."

# Resolve start command: prepend venv python if command starts with "python"
if [[ "${START_CMD}" == python* ]]; then
    EXEC_CMD="${BOT_DIR}/venv/bin/${START_CMD}"
else
    EXEC_CMD="${START_CMD}"
fi

cat > "/etc/systemd/system/${SERVICE_NAME}.service" << SVCEOF
[Unit]
Description=${BOT_NAME} Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${BOT_USER}
Group=${BOT_USER}
WorkingDirectory=${BOT_DIR}
EnvironmentFile=${BOT_DIR}/.env
ExecStart=${EXEC_CMD}
Restart=on-failure
RestartSec=30
StartLimitIntervalSec=300
StartLimitBurst=5

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${BOT_NAME}

# Security hardening
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=${BOT_DIR}

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service"

echo ""
echo "============================================"
echo "  Bot '${BOT_NAME}' installed!"
echo "============================================"
echo ""
echo "Directory:   ${BOT_DIR}/"
echo "Service:     ${SERVICE_NAME}"
echo "Start cmd:   ${EXEC_CMD}"
echo ""
echo "Next steps:"
echo "  1. Edit secrets:     sudo nano ${BOT_DIR}/.env"
echo "  2. Edit config:      sudo nano ${BOT_DIR}/<config file>"
echo "  3. Start:            sudo systemctl start ${SERVICE_NAME}"
echo "  4. Check status:     sudo systemctl status ${SERVICE_NAME}"
echo "  5. View logs:        sudo journalctl -u ${SERVICE_NAME} -f"
echo ""
echo "Other commands:"
echo "  Stop:                sudo systemctl stop ${SERVICE_NAME}"
echo "  Restart:             sudo systemctl restart ${SERVICE_NAME}"
echo "  Disable on boot:     sudo systemctl disable ${SERVICE_NAME}"
echo "  Update code:         cd ${BOT_DIR} && sudo -u ${BOT_USER} git pull && sudo systemctl restart ${SERVICE_NAME}"
echo ""
