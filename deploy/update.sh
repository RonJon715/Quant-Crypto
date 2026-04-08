#!/usr/bin/env bash
# =============================================================================
# Alpha Bot — Update Script
# Pulls latest code, installs new dependencies, and restarts the bot.
#
# Usage:
#   sudo ./deploy/update.sh
# =============================================================================

set -euo pipefail

APP_DIR="/opt/alpha-bot"
BRANCH="claude/crypto-trading-bot-f2BeU"

echo "Stopping bot..."
systemctl stop alpha-bot || true

echo "Pulling latest code..."
cd "${APP_DIR}"
sudo -u botuser git pull origin "${BRANCH}"

echo "Updating dependencies..."
sudo -u botuser ./venv/bin/pip install -r requirements.txt -q

echo "Running tests..."
sudo -u botuser ./venv/bin/python -m pytest tests/ -v

echo "Restarting bot..."
systemctl start alpha-bot

echo "Done. Check status: sudo systemctl status alpha-bot"
