#!/usr/bin/env bash
# Vault Store: Ubuntu/Debian VPS par install (nginx, HTTP, bina domain ke).
# Use:  sudo bash deploy/install.sh https://<backend-url>
# Backend URL = jahan aapka bot/mini-app server chalta hai (jahan /app/catalog milta hai).
# Bina backend ke bhi chalta hai (DEMO data dikhega): sudo bash deploy/install.sh
set -euo pipefail
BACKEND="${1:-}"
WEBROOT=/var/www/vault-store
SRC="$(cd "$(dirname "$0")/.." && pwd)"

apt-get update -y
apt-get install -y nginx rsync

mkdir -p "$WEBROOT"
rsync -a --delete --exclude .git --exclude deploy --exclude README.md "$SRC/" "$WEBROOT/"

PROXY=""
if [ -n "$BACKEND" ]; then
  BACKEND="${BACKEND%/}"
  HOST="$(echo "$BACKEND" | sed -E 's#^https?://([^/]+).*#\1#')"
  PROXY="
  location /app/ {
    proxy_pass ${BACKEND}/app/;
    proxy_set_header Host ${HOST};
    proxy_ssl_server_name on;
    proxy_http_version 1.1;
    proxy_connect_timeout 5s;
    proxy_read_timeout 15s;
  }"
fi

cat > /etc/nginx/sites-available/vault-store <<CONF
server {
  listen 80 default_server;
  listen [::]:80 default_server;
  server_name _;
  root ${WEBROOT};
  index index.html;
  add_header X-Content-Type-Options nosniff always;
  add_header Referrer-Policy strict-origin-when-cross-origin always;
  location / { try_files \$uri \$uri/ =404; }
  location ~* \.(css|js|svg|png|jpg|webp)\$ { expires 1h; }${PROXY}
}
CONF

ln -sf /etc/nginx/sites-available/vault-store /etc/nginx/sites-enabled/vault-store
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx
systemctl reload nginx
echo "Done. Browser mein kholo: http://$(curl -s https://api.ipify.org || hostname -I | awk '{print $1}')"
