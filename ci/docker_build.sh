#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Build Lambda (required for CDK synth/deploy)
cd "$SCRIPT_DIR/../lambda/multiply"
npm ci
npm run build

# Build Express app
cd "$SCRIPT_DIR/../app"
npm ci
npm run build

docker build -t cdk1-app:ci .
