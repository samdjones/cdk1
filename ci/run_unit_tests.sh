#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Build and test Lambda
cd "$SCRIPT_DIR/../lambda/multiply"
npm ci
npm run build
npm test

# Build and test Express app
cd "$SCRIPT_DIR/../app"
npm ci
npm run build
npm test
