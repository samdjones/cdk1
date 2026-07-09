#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

for svc in main auth default; do
  cd "$SCRIPT_DIR/../app/$svc"
  docker build -t "cdk1-alb-app-$svc:ci" .
done
