#!/usr/bin/env bash
# Automatic payment verification ke secrets /etc/vault-store.env mein daalo (screen/history mein nahi dikhte).
#   sudo bash deploy/set-autopay.sh
# 1) UPI: ek Gmail/mailbox jahan bank/FamPay ke "credited" alerts aate hain. Gmail mein 2-step verification on karke
#    "App password" banao (normal password mat do). IMAP Gmail mein on hona chahiye.
# 2) Binance: API key jisme SIRF "Enable Reading" ho (trading/withdraw OFF), aur server IP whitelist.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "sudo se chalao"; exit 1; }
ENVF=/etc/vault-store.env
touch "$ENVF"; chmod 600 "$ENVF"
setv() { grep -v "^$1=" "$ENVF" > "$ENVF.tmp" || true; printf '%s=%s\n' "$1" "$2" >> "$ENVF.tmp"; mv "$ENVF.tmp" "$ENVF"; chmod 600 "$ENVF"; }

read -rp "UPI email set karni hai? [y/N] " A
if [ "$A" = y ] || [ "$A" = Y ]; then
  read -rp "IMAP host (Gmail: imap.gmail.com): " H
  read -rp "Mailbox email: " U
  read -rsp "App password (dikhega nahi): " P; echo
  setv IMAP_HOST "$H"; setv IMAP_USER "$U"; setv IMAP_PASS "$P"
fi
read -rp "Binance API set karni hai? [y/N] " B
if [ "$B" = y ] || [ "$B" = Y ]; then
  read -rsp "Binance API key (dikhegi nahi): " K; echo
  read -rsp "Binance API secret (dikhega nahi): " S; echo
  setv BINANCE_API_KEY "$K"; setv BINANCE_API_SECRET "$S"
fi
systemctl restart vault-store
echo "Ho gaya. Ab admin panel > Settings mein 'UPI auto-verify' / 'Binance auto-verify' 1 karo, aur bank sender email daalo."
