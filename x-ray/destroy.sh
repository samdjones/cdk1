#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== X-Ray POC Destroy ==="
echo ""
echo "This will destroy XraySharedStack, XrayIdpStack, XrayFrontendStack and all their resources."
read -p "Are you sure? (yes/no): " confirm
if [[ "$confirm" != "yes" ]]; then
  echo "Aborted."
  exit 0
fi

# --all destroys in reverse dependency order (XrayFrontendStack, then
# XrayIdpStack, then XraySharedStack) - see docs/multi-stack.md.
echo ""
echo "Destroying XrayFrontendStack, XrayIdpStack, XraySharedStack..."
cd "$SCRIPT_DIR"
source iac/.venv/bin/activate
CDK_DOCKER=podman npx cdk destroy --all \
  --force \
  --app "python iac/app_xray.py"

echo ""
echo "=== Destroy complete ==="
