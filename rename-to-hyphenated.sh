#!/bin/bash
# =============================================================================
# Rename `iquitscorer` -> `i-quit-scorer` on the EC2 host.
#
# What this migrates:
#   * systemd unit         iquitscorer.service        -> i-quit-scorer.service
#   * env file             /etc/iquitscorer.env       -> /etc/i-quit-scorer.env
#   * nginx vhost          /etc/nginx/conf.d/iquitscorer.conf
#                          -> /etc/nginx/conf.d/i-quit-scorer.conf
#   * app directory        /home/ec2-user/iquitscorer -> /home/ec2-user/i-quit-scorer
#
# Idempotent — safe to re-run. Anything already migrated is skipped.
# After it finishes, run `./deploy.sh` to (re)write the systemd unit with the
# new WorkingDirectory / ExecStart paths and pull the latest code.
# =============================================================================
set -euo pipefail

OLD_NAME="iquitscorer"
NEW_NAME="i-quit-scorer"

OLD_SERVICE="/etc/systemd/system/${OLD_NAME}.service"
NEW_SERVICE="/etc/systemd/system/${NEW_NAME}.service"

OLD_ENV="/etc/${OLD_NAME}.env"
NEW_ENV="/etc/${NEW_NAME}.env"

OLD_NGINX="/etc/nginx/conf.d/${OLD_NAME}.conf"
NEW_NGINX="/etc/nginx/conf.d/${NEW_NAME}.conf"

OLD_DIR="/home/ec2-user/${OLD_NAME}"
NEW_DIR="/home/ec2-user/${NEW_NAME}"

echo "▶ [1/6] Stop old service (if running)..."
if systemctl list-unit-files | grep -q "^${OLD_NAME}.service"; then
    sudo systemctl stop "$OLD_NAME" || true
    sudo systemctl disable "$OLD_NAME" || true
else
    echo "   (no ${OLD_NAME}.service — skipping)"
fi

echo "▶ [2/6] Move env file..."
if [ -f "$OLD_ENV" ] && [ ! -f "$NEW_ENV" ]; then
    sudo mv "$OLD_ENV" "$NEW_ENV"
    sudo chmod 600 "$NEW_ENV"
    echo "   $OLD_ENV -> $NEW_ENV"
elif [ -f "$NEW_ENV" ]; then
    echo "   $NEW_ENV already exists — leaving old file (if any) in place for you to delete"
else
    echo "   (no $OLD_ENV — will be created by deploy.sh on first run)"
fi

echo "▶ [3/6] Move app directory..."
if [ -d "$OLD_DIR" ] && [ ! -d "$NEW_DIR" ]; then
    sudo mv "$OLD_DIR" "$NEW_DIR"
    sudo chown -R ec2-user:ec2-user "$NEW_DIR"
    echo "   $OLD_DIR -> $NEW_DIR"
elif [ -d "$OLD_DIR" ] && [ -d "$NEW_DIR" ]; then
    echo "   ⚠️  Both $OLD_DIR and $NEW_DIR exist."
    echo "       Keeping $NEW_DIR (assumed authoritative) and archiving the old one:"
    sudo mv "$OLD_DIR" "${OLD_DIR}.bak.$(date +%s)"
elif [ -d "$NEW_DIR" ]; then
    echo "   $NEW_DIR already present — nothing to move"
else
    echo "   (no app directory yet — deploy.sh will clone into $NEW_DIR)"
fi

echo "▶ [4/6] Move nginx vhost..."
if [ -f "$OLD_NGINX" ] && [ ! -f "$NEW_NGINX" ]; then
    sudo mv "$OLD_NGINX" "$NEW_NGINX"
    echo "   $OLD_NGINX -> $NEW_NGINX"
elif [ -f "$OLD_NGINX" ] && [ -f "$NEW_NGINX" ]; then
    echo "   Both nginx confs exist — removing old $OLD_NGINX"
    sudo rm -f "$OLD_NGINX"
else
    echo "   (nginx conf already migrated or not present — deploy.sh will (re)write it)"
fi
sudo nginx -t && sudo systemctl reload nginx || {
    echo "   ⚠️  nginx config test failed — inspect /etc/nginx/conf.d/*.conf before continuing."
    exit 1
}

echo "▶ [5/6] Remove old systemd unit..."
if [ -f "$OLD_SERVICE" ]; then
    sudo rm -f "$OLD_SERVICE"
    sudo systemctl daemon-reload
    echo "   removed $OLD_SERVICE"
else
    echo "   (already gone)"
fi

echo "▶ [6/6] Done."
echo ""
echo "Next steps:"
echo "  cd $NEW_DIR"
echo "  ./deploy.sh    # writes the new i-quit-scorer.service and starts it"
echo ""
echo "Verify with:"
echo "  systemctl status i-quit-scorer --no-pager"
echo "  curl -I https://52patta.azizzoaib.com"
