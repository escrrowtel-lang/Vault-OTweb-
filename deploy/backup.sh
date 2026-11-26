#!/usr/bin/env bash
# Database ka safe backup (sqlite backup API). install.sh ise roz 03:30 par chalata hai.
# DHYAN: DB mein inventory (account details) hai, isliye backup bhi private rakho.
set -euo pipefail
DATA=/var/lib/vault-store
DEST=/var/backups/vault-store
mkdir -p "$DEST"; chmod 700 "$DEST"
F="$DEST/store-$(date +%F-%H%M).db"
python3 - "$DATA/store.db" "$F" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1]); dst = sqlite3.connect(sys.argv[2])
src.backup(dst); dst.close(); src.close()
PY
chmod 600 "$F"
find "$DEST" -name 'store-*.db' -mtime +14 -delete
echo "Backup ready: $F"
