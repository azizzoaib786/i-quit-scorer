#!/bin/bash
# =============================================================================
# i-quit-scorer — EC2 deploy / redeploy script
# Deploys FastAPI app at https://52patta.azizzoaib.com
# Idempotent — safe to re-run.
#
# Prerequisites on the EC2:
#   - python3, pip, nginx, certbot, python3-certbot-nginx, git
#     (installed by Terraform user_data in zizabot/terraform/ec2)
#   - Ports 80/443 open in the security group
#   - DNS A record for 52patta.azizzoaib.com → this EC2's public IP
# =============================================================================
set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────────────
APP_DIR="/home/ec2-user/i-quit-scorer"
APP_USER="ec2-user"
SERVICE_NAME="i-quit-scorer"
APP_PORT="8000"
REPO_URL="${REPO_URL:-git@github.com:azizzoaib786/i-quit-scorer.git}"

DOMAIN="52patta.azizzoaib.com"
CERTBOT_EMAIL="aziz@azizzoaib.com"

AWS_REGION="eu-west-1"
GAMES_TABLE="iquit_games"
EVENTS_TABLE="iquit_events"
HISTORY_TABLE="iquit_history"

# SECRET_KEY persists across deploys — generated once, chmod 600.
SECRET_FILE="/etc/i-quit-scorer.env"
# ─────────────────────────────────────────────────────────────────────────────

echo "▶ [1/7] Sanity check tools..."
for bin in python3 pip3 nginx certbot git; do
    command -v "$bin" >/dev/null || { echo "❌ Missing $bin — run Terraform user_data first."; exit 1; }
done

echo "▶ [2/7] Provision SECRET_KEY (only on first run)..."
if [ ! -f "$SECRET_FILE" ]; then
    sudo bash -c "echo SECRET_KEY=$(openssl rand -hex 32) > $SECRET_FILE"
    sudo chmod 600 "$SECRET_FILE"
    echo "   Created $SECRET_FILE"
else
    echo "   $SECRET_FILE exists — leaving as-is"
fi

echo "▶ [3/7] Clone or pull repo..."
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" fetch --all
    git -C "$APP_DIR" reset --hard origin/HEAD
else
    sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR"
fi
sudo chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "▶ [4/7] Python venv + deps..."
sudo -u "$APP_USER" bash -c "
    python3 -m venv '$APP_DIR/.venv'
    '$APP_DIR/.venv/bin/pip' install --upgrade pip
    '$APP_DIR/.venv/bin/pip' install -r '$APP_DIR/requirements.txt'
"

echo "▶ [5/7] systemd service..."
sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" > /dev/null <<EOF
[Unit]
Description=IQuit Scoreboard (FastAPI)
After=network.target

[Service]
User=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${SECRET_FILE}
Environment="AWS_REGION=${AWS_REGION}"
Environment="GAMES_TABLE=${GAMES_TABLE}"
Environment="EVENTS_TABLE=${EVENTS_TABLE}"
Environment="HISTORY_TABLE=${HISTORY_TABLE}"
ExecStart=${APP_DIR}/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port ${APP_PORT} --proxy-headers --forwarded-allow-ips="127.0.0.1"
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo "▶ [6/7] nginx vhost for ${DOMAIN}..."
sudo tee "/etc/nginx/conf.d/${SERVICE_NAME}.conf" > /dev/null <<EOF
server {
    listen 80;
    server_name ${DOMAIN};

    location /.well-known/acme-challenge/ { root /var/www/certbot; }

    location / {
        proxy_pass http://127.0.0.1:${APP_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 120s;
    }
}
EOF
sudo mkdir -p /var/www/certbot
sudo nginx -t && sudo systemctl reload nginx

echo "▶ [7/7] Let's Encrypt cert for ${DOMAIN}..."
if sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$CERTBOT_EMAIL" --redirect; then
    echo "   ✅ HTTPS configured."
else
    echo "   ⚠️  Certbot failed — verify DNS + firewall, then run:"
    echo "       sudo certbot --nginx -d $DOMAIN -m $CERTBOT_EMAIL --agree-tos --redirect"
fi

echo "▶ Bootstrapping DynamoDB tables (idempotent)..."
sudo -u "$APP_USER" AWS_REGION="$AWS_REGION" \
    GAMES_TABLE="$GAMES_TABLE" EVENTS_TABLE="$EVENTS_TABLE" HISTORY_TABLE="$HISTORY_TABLE" \
    "$APP_DIR/.venv/bin/python" "$APP_DIR/setup_db.py" || true

echo ""
echo "✅ i-quit-scorer deployed."
echo "   Live at:  https://${DOMAIN}"
echo "   Logs:     sudo journalctl -u ${SERVICE_NAME} -f"
echo "   Restart:  sudo systemctl restart ${SERVICE_NAME}"
