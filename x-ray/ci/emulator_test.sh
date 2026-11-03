#!/usr/bin/env bash
# Emulator test: deploy the three x-ray stacks into a local Floci AWS emulator
# and assert on the resources created. Never touches real AWS. Run manually only.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XRAY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$XRAY_DIR/.." && pwd)"

CONTAINER_CLI="${CONTAINER_CLI:-podman}"
FLOCI_IMAGE="${FLOCI_IMAGE:-docker.io/floci/floci:2.4.0}"
FLOCI_PORT="${FLOCI_PORT:-4566}"
CONTAINER_NAME="floci-emulator-test-xray"

cleanup() { "$CONTAINER_CLI" rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

echo "=== x-ray emulator test (Floci via $CONTAINER_CLI) ==="

# ECS mock: no Docker daemon needed. Unsupported CloudFormation types fail
# instead of silently reaching CREATE_COMPLETE.
"$CONTAINER_CLI" run -d --name "$CONTAINER_NAME" -p "$FLOCI_PORT:4566" \
  -e FLOCI_SERVICES_ECS_MOCK=true \
  -e FLOCI_SERVICES_CLOUDFORMATION_ALLOW_STUB_UNSUPPORTED_RESOURCE_TYPES=false \
  "$FLOCI_IMAGE" >/dev/null

for _ in $(seq 1 30); do
  curl -fs -o /dev/null "http://localhost:$FLOCI_PORT/" && break
  sleep 1
done
curl -fs -o /dev/null "http://localhost:$FLOCI_PORT/" || { echo "Floci did not start" >&2; exit 1; }

export AWS_ENDPOINT_URL="http://localhost:$FLOCI_PORT"
export AWS_ENDPOINT_URL_S3="http://s3.localhost.floci.io:$FLOCI_PORT"
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1

cd "$REPO_ROOT" && npm ci --silent

# Lambda code assets are zipped from each function's dist/ (they go to
# Floci's S3, so unlike container images they are not skipped).
for fn in xray-invoker xray-dog-fetcher xray-s3-writer; do
  (cd "$XRAY_DIR/lambda/$fn" && npm ci --silent && npm run build --silent)
done

cd "$XRAY_DIR"
if [ ! -d iac/.venv ]; then python3 -m venv iac/.venv; fi
# shellcheck disable=SC1091
source iac/.venv/bin/activate
pip install -q -r iac/requirements.txt -r iac/requirements-dev.txt

# `-c emulator=true` swaps container image assets for a placeholder image
# (Floci's ECR can't accept pushes without a Docker daemon).
npx cdk bootstrap aws://000000000000/us-east-1 --app "python iac/app_xray.py"
npx cdk deploy --all --require-approval never -c emulator=true --app "python iac/app_xray.py"

pytest iac/tests -v
echo "=== x-ray emulator test passed ==="
