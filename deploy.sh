#!/bin/bash
# =============================================================================
# IQuit Scoreboard — EC2 Amazon Linux Deployment Script
# Usage: bash deploy.sh
# Run this once on a fresh EC2 Amazon Linux 2/2023 instance.
# =============================================================================

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
APP_DIR="/home/ec2-user/iquitscorer"
APP_USER="ec2-user"
SERVICE_NAME="iquitscorer"
REPO_URL="https://github.com/YOUR_USERNAME/iquitscorer.git"  # ← update this

# AWS / App env vars
AWS_REGION="eu-west-1"
GAMES_TABLE="iquit_games"
EVENTS_TABLE="iquit_events"
# ─────────────────────────────────────────────────────────────────────────────

echo "▶ [1/7] Installing system packages..."
if command -v dnf &>/dev/null; then
    sudo dnf update -y
    sudo dnf install -y python3-pip python3 nginx certbot python3-certbot-nginx git
else
    sudo yum update -y
    sudo yum install -y python3-pip python3 nginx certbot python3-certbot-nginx git
fi

echo "▶ [2/7] Cloning / updating repo..."
if [ -d "$APP_DIR/.git" ]; then
    echo "   Repo exists, pulling latest..."
    git -C "$APP_DIR" pull
else
    git clone "$REPO_URL" "$APP_DIR"
fi

echo "▶ [3/7] Setting up Python venv and installing dependencies..."
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "▶ [4/7] Creating systemd service..."
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<EOF
[Unit]
Description=IQuit Scoreboard
After=network.target

[Service]
User=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment="AWS_REGION=${AWS_REGION}"
Environment="GAMES_TABLE=${GAMES_TABLE}"
Environment="EVENTS_TABLE=${EVENTS_TABLE}"
ExecStart=${APP_DIR}/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
echo "   Service status:"
sudo systemctl status "$SERVICE_NAME" --no-pager

echo "▶ [5/7] Configuring Nginx..."
sudo tee /etc/nginx/conf.d/${SERVICE_NAME}.conf > /dev/null <<'EOF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

sudo systemctl enable nginx
sudo systemctl start nginx
sudo nginx -t && sudo systemctl reload nginx

echo "▶ [6/7] Setting up DynamoDB tables..."
"$APP_DIR/.venv/bin/python" "$APP_DIR/setup_db.py"

echo ""
echo "✅ Deployment complete!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  App is running at: http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)"
echo ""
echo "  To enable SSL (requires a domain name pointing to this IP):"
echo "    sudo certbot --nginx -d your-domain.com"
echo "    sudo systemctl enable certbot-renew.timer"
echo ""
echo "  Useful commands:"
echo "    sudo systemctl status $SERVICE_NAME"
echo "    sudo journalctl -u $SERVICE_NAME -f"
echo "    sudo systemctl restart $SERVICE_NAME"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
