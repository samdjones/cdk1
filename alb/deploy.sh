#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== ALB POC Deploy ==="
echo ""

# ── Install root dev deps (aws-cdk for npx) ───────────────────────────────
echo "Installing root dev dependencies..."
cd "$REPO_ROOT"
npm install
echo "✓ root deps installed"

# ── Build ECS apps: main, auth, default ───────────────────────────────────
for svc in main auth default; do
  echo "Building app/$svc..."
  cd "$SCRIPT_DIR/app/$svc"
  npm install
  npm run build
  echo "✓ app/$svc built"
done

# ── CDK Deploy ────────────────────────────────────────────────────────────
echo ""
echo "Deploying AlbPocStack..."
cd "$SCRIPT_DIR"
source iac/.venv/bin/activate
CDK_DOCKER=podman npx cdk deploy AlbPocStack \
  --require-approval never \
  --app "python iac/app_alb.py"

echo ""
echo "=== Deploy complete ==="
echo "The ALB is internal-only. Reach it via an SSM port-forward through the bastion:"
echo ""
echo "  ./connect.sh          # terminal 1 - opens localhost:8080 -> internal ALB:80"
echo "  ./test-routes.sh      # terminal 2 - exercises all 3 path-routing rules"
