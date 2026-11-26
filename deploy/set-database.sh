#!/usr/bin/env bash
# Supabase (Postgres) ko database banao. Connection string yahan paste karo; screen par ya history mein nahi dikhegi.
#   sudo bash deploy/set-database.sh
# Supabase: Project Settings > Database > Connection string > "Session pooler" (URI). [YOUR-PASSWORD] ki jagah apna password.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "sudo se chalao"; exit 1; }
ENVF=/etc/vault-store.env
APP=/opt/vault-store
[ -d "$APP/server" ] || { echo "Pehle: sudo bash deploy/install.sh"; exit 1; }

read -rsp "Supabase connection string paste karo (dikhegi nahi): " URL; echo
case "$URL" in postgres://*|postgresql://*) ;; *) echo "String postgresql:// se shuru honi chahiye"; exit 1;; esac
case "$URL" in *"[YOUR-PASSWORD]"*) echo "[YOUR-PASSWORD] ki jagah apna asli password daalo"; exit 1;; esac

echo "Connection test (tables bhi ban jaayengi)..."
if ! runuser -u vault -- env DATABASE_URL="$URL" python3 -I "$APP/server/manage.py" >/dev/null; then
  echo "Connect nahi hua. Password sahi hai? 'Session pooler' wali string use ki? (special characters URL-encode hone chahiye)"; exit 1
fi

touch "$ENVF"; chmod 600 "$ENVF"
grep -v '^DATABASE_URL=' "$ENVF" > "$ENVF.tmp" || true
printf 'DATABASE_URL=%s\n' "$URL" >> "$ENVF.tmp"
mv "$ENVF.tmp" "$ENVF"; chmod 600 "$ENVF"

OLD=/var/lib/vault-store/store.db
if [ -f "$OLD" ]; then
  read -rp "Purana SQLite data (users, orders, inventory) Supabase mein le jaayein? [y/N] " A
  if [ "$A" = "y" ] || [ "$A" = "Y" ]; then
    runuser -u vault -- env DATABASE_URL="$URL" python3 -I "$APP/server/manage.py" migrate-sqlite "$OLD" \
      && echo "Migration ho gaya. Purani file $OLD safe rakhi hai." || echo "Migration nahi hua (khaali DB chahiye). Purana SQLite data waisa hi hai."
  fi
fi

systemctl restart vault-store
sleep 2
if curl -fs http://127.0.0.1:8000/api/settings >/dev/null; then
  echo "OK: ab database Supabase hai."
  echo "Naya database hai to admin banao:  sudo bash deploy/admin.sh create-admin aapka@email.com"
else
  echo "Server start nahi hua: sudo journalctl -u vault-store -n 40 --no-pager"; exit 1
fi
