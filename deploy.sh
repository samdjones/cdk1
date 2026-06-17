#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== X-Ray POC Deploy ==="
echo ""

# ── Build Lambda: xray-invoker ─────────────────────────────────────────────
echo "Building lambda/xray-invoker..."
cd "$SCRIPT_DIR/lambda/xray-invoker"
npm install
npm run build
echo "✓ xray-invoker built"

# ── Build Lambda: xray-dog-fetcher ────────────────────────────────────────
echo "Building lambda/xray-dog-fetcher..."
cd "$SCRIPT_DIR/lambda/xray-dog-fetcher"
npm install
npm run build
echo "✓ xray-dog-fetcher built"

# ── Build Lambda: xray-s3-writer ──────────────────────────────────────────
echo "Building lambda/xray-s3-writer..."
cd "$SCRIPT_DIR/lambda/xray-s3-writer"
npm install
npm run build
echo "✓ xray-s3-writer built"

# ── Build ECS app: app-xray ───────────────────────────────────────────────
echo "Building app-xray..."
cd "$SCRIPT_DIR/app-xray"
npm install
npm run build
echo "✓ app-xray built"

# ── CDK Deploy ────────────────────────────────────────────────────────────
echo ""
echo "Deploying XrayPocStack..."
cd "$SCRIPT_DIR/iac"
source .venv/bin/activate
cdk deploy XrayPocStack \
  --require-approval never \
  --app "python app_xray.py"

echo ""
echo "=== Deploy complete ==="
echo "To trigger a trace, invoke the xray-invoker Lambda from the AWS Console or CLI:"
echo "  aws lambda invoke --function-name xray-invoker /tmp/response.json && cat /tmp/response.json"
