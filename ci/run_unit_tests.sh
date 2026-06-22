#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR/../lambda/xray-invoker" && npm ci && npm run build
cd "$SCRIPT_DIR/../lambda/xray-dog-fetcher" && npm ci && npm run build
cd "$SCRIPT_DIR/../lambda/xray-s3-writer" && npm ci && npm run build
cd "$SCRIPT_DIR/../app-xray" && npm ci && npm run build
