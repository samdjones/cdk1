#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

for svc in main auth default; do
  cd "$SCRIPT_DIR/../app/$svc" && npm ci && npm run build
done
