#!/usr/bin/env bash
# Database ka backup. SQLite ho ya Supabase, dono ke liye. install.sh ise roz 03:30 par chalata hai.
# DHYAN: backup mein inventory (account details) aur password hashes hain, isliye private rakho.
set -euo pipefail
DATA=/var/lib/vault-store
DEST=/var/backups/vault-store
mkdir -p "$DEST"; chmod 700 "$DEST"
set -a; [ -f /etc/vault-store.env ] && . /etc/vault-store.env; set +a
STAMP="$(date +%F-%H%M)"
if [ -n "${DATABASE_URL:-}" ]; then
  F="$DEST/store-$STAMP.json"
  # vault user se likho, phir root-only folder mein
  TMP="$(mktemp -p "$DATA" backup.XXXXXX)"; chown vault "$TMP"
  runuser -u vault -- env DATABASE_URL="$DATABASE_URL" VAULT_UPLOADS="$DATA/uploads" python3 -I /opt/vault-store/server/manage.py backup-json "$TMP" >/dev/null
  mv "$TMP" "$F"; chown root:root "$F"
else
  F="$DEST/store-$STAMP.db"
  python3 - "$DATA/store.db" "$F" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1]); dst = sqlite3.connect(sys.argv[2])
src.backup(dst); dst.close(); src.close()
PY
fi
chmod 600 "$F"
find "$DEST" -name 'store-*' -mtime +14 -delete
echo "Backup ready: $F"
