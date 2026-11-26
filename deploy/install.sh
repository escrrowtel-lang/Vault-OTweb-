#!/usr/bin/env bash
# Vault Store: install ya update (dono ke liye yehi script). Ubuntu/Debian, root/sudo se chalao.
#   sudo bash deploy/install.sh
# Code:  /opt/vault-store     Data (DB + uploads): /var/lib/vault-store  (update se data nahi mitta)
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "sudo se chalao: sudo bash deploy/install.sh"; exit 1; }

SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP=/opt/vault-store
DATA=/var/lib/vault-store

apt-get update -y
apt-get install -y nginx python3 rsync libpq5

id vault >/dev/null 2>&1 || useradd --system --home "$DATA" --shell /usr/sbin/nologin vault
mkdir -p "$APP" "$DATA/uploads"
rsync -a --delete "$SRC/server/" "$APP/server/"
rsync -a --delete "$SRC/web/" "$APP/web/"
chown -R root:root "$APP"
chown -R vault:vault "$DATA"
chmod 750 "$DATA"

cat > /etc/systemd/system/vault-store.service <<UNIT
[Unit]
Description=Vault Store
After=network.target

[Service]
User=vault
Group=vault
WorkingDirectory=$APP
Environment=HOST=127.0.0.1
Environment=PORT=8000
Environment=VAULT_DB=$DATA/store.db
Environment=VAULT_UPLOADS=$DATA/uploads
# Optional: SMTP (password reset email) /etc/vault-store.env mein: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM
EnvironmentFile=-/etc/vault-store.env
ExecStart=/usr/bin/python3 -I $APP/server/app.py
Restart=always
RestartSec=2
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$DATA

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/nginx/sites-available/vault-store <<'CONF'
limit_req_zone $binary_remote_addr zone=vault_auth:10m rate=10r/m;

server {
  listen 80 default_server;
  listen [::]:80 default_server;
  server_name _;
  client_max_body_size 2m;
  server_tokens off;

  location /api/auth/ {
    limit_req zone=vault_auth burst=10 nodelay;
    include /etc/nginx/vault-proxy.conf;
  }
  location / {
    include /etc/nginx/vault-proxy.conf;
  }
}
CONF

cat > /etc/nginx/vault-proxy.conf <<'CONF'
proxy_pass http://127.0.0.1:8000;
proxy_http_version 1.1;
proxy_set_header Connection "";
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_read_timeout 30s;
CONF

ln -sf /etc/nginx/sites-available/vault-store /etc/nginx/sites-enabled/vault-store
rm -f /etc/nginx/sites-enabled/default

install -m 750 "$SRC/deploy/backup.sh" /usr/local/sbin/vault-backup.sh
echo "30 3 * * * root /usr/local/sbin/vault-backup.sh >/dev/null 2>&1" > /etc/cron.d/vault-store-backup
chmod 644 /etc/cron.d/vault-store-backup

systemctl daemon-reload
systemctl enable vault-store >/dev/null
systemctl restart vault-store
nginx -t
systemctl enable --now nginx >/dev/null 2>&1 || true
systemctl reload nginx

sleep 1
if curl -fs http://127.0.0.1:8000/api/settings >/dev/null; then
  IP="$(curl -s https://api.ipify.org || hostname -I | awk '{print $1}')"
  echo
  echo "OK: server chal raha hai. Browser mein kholo: http://$IP"
  echo "Pehli baar ho to admin banao:  sudo bash deploy/admin.sh aapka@email.com"
else
  echo "Server start nahi hua. Log dekho: sudo journalctl -u vault-store -n 40 --no-pager"
  exit 1
fi
