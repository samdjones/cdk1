#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../app"

npm ci
npm run build
npm test
