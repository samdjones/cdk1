#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== ALB POC Destroy ==="
echo ""
echo "This will destroy AlbPocStack and all its resources."
read -p "Are you sure? (yes/no): " confirm
if [[ "$confirm" != "yes" ]]; then
  echo "Aborted."
  exit 0
fi

echo ""
echo "Destroying AlbPocStack..."
cd "$SCRIPT_DIR"
source iac/.venv/bin/activate
CDK_DOCKER=podman npx cdk destroy AlbPocStack \
  --force \
  --app "python iac/app_alb.py"

echo ""
echo "=== Destroy complete ==="
