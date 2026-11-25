#!/usr/bin/env bash
# Naya code laao aur restart karo:  sudo bash deploy/update.sh
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --ff-only
bash deploy/install.sh
