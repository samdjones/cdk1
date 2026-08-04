#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== X-Ray POC Deploy ==="
echo ""

# ── Install root dev deps (aws-cdk for npx) ───────────────────────────────
echo "Installing root dev dependencies..."
cd "$REPO_ROOT"
npm install
echo "✓ root deps installed"

# ── Build Lambda: xray-invoker ─────────────────────────────────────────────
echo "Building lambda/xray-invoker..."
cd "$SCRIPT_DIR/lambda/xray-invoker"
npm install
npm run build
echo "✓ xray-invoker built"

# ── Build Lambda: xray-dog-fetcher ────────────────────────────────────────
# Its ADOT layer content (otel-layer.zip) is a vendored, checked-in artifact,
# not downloaded here - this script must not make any AWS API call beyond
# the `cdk deploy` below. See lambda/xray-dog-fetcher/download-otel-layer.sh
# for how to refresh that vendored copy.
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

# ── Build ECS app: app-idp ────────────────────────────────────────────────
echo "Building app-idp..."
cd "$SCRIPT_DIR/app-idp"
npm install
npm run build
echo "✓ app-idp built"

# ── CDK Deploy ────────────────────────────────────────────────────────────
# --all deploys XraySharedStack, XrayIdpStack, XrayFrontendStack in
# dependency order (CDK computes this from the stacks' cross-stack
# references and explicit add_dependency() calls - see docs/multi-stack.md).
echo ""
echo "Deploying XraySharedStack, XrayIdpStack, XrayFrontendStack..."
cd "$SCRIPT_DIR"
source iac/.venv/bin/activate
CDK_DOCKER=podman npx cdk deploy --all \
  --require-approval never \
  --app "python iac/app_xray.py"

echo ""
echo "=== Deploy complete ==="
echo "To trigger a trace, run:"
echo "  ./trigger-trace.sh"
