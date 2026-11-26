#!/usr/bin/env bash
# Admin banao ya password badlo.
#   sudo bash deploy/admin.sh create-admin you@example.com
#   sudo bash deploy/admin.sh set-password you@example.com
set -euo pipefail
CMD="${1:-}"; EMAIL="${2:-}"
if [ -z "$EMAIL" ] && [ -n "$CMD" ]; then EMAIL="$CMD"; CMD=create-admin; fi
[ -n "$CMD" ] && [ -n "$EMAIL" ] || { echo "Use: sudo bash deploy/admin.sh create-admin you@example.com"; exit 1; }
set -a; [ -f /etc/vault-store.env ] && . /etc/vault-store.env; set +a   # DATABASE_URL (Supabase) yahin se aata hai
exec runuser -u vault -- env VAULT_DB=/var/lib/vault-store/store.db VAULT_UPLOADS=/var/lib/vault-store/uploads \
  DATABASE_URL="${DATABASE_URL:-}" python3 -I /opt/vault-store/server/manage.py "$CMD" "$EMAIL"
