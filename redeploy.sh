#!/bin/bash
# =============================================================================
# IQuit Scoreboard — Redeploy script (pull latest + restart)
# Usage: bash redeploy.sh
# Run this whenever you push new changes and want to update the server.
# =============================================================================

set -euo pipefail

APP_DIR="/home/ec2-user/iquitscorer"
SERVICE_NAME="iquitscorer"

echo "▶ Pulling latest changes..."
git -C "$APP_DIR" pull

echo "▶ Installing any new dependencies..."
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "▶ Restarting service..."
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl status "$SERVICE_NAME" --no-pager

echo "✅ Redeployed successfully."
