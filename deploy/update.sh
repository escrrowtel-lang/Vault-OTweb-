#!/usr/bin/env bash
# Naya code laane ke liye: sudo bash deploy/update.sh https://<backend-url>
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --ff-only
bash deploy/install.sh "${1:-}"
