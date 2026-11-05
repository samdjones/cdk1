#!/usr/bin/env bash
# E2E app test (local only): deploy the three x-ray stacks into Floci with REAL
# ECS and Lambda, so the actual app/Envoy containers and Lambdas run, then send
# HTTP requests through the emulated ALB (ALB -> Envoy -> frontend -> Lambdas ->
# S3). Never touches real AWS. Needs internet (the dog-fetcher calls dog.ceo).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XRAY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$XRAY_DIR/.." && pwd)"

CONTAINER_CLI="${CONTAINER_CLI:-podman}"
FLOCI_IMAGE="${FLOCI_IMAGE:-docker.io/floci/floci:2.4.0}"
FLOCI_PORT="${FLOCI_PORT:-4566}"
E2E_ALB_PORT="${E2E_ALB_PORT:-8088}"
CONTAINER_NAME="floci-e2e-xray"   # also the hostname app containers use (emulator.py)
NETWORK_NAME="floci-e2e-xray"

SOCKET_PID=""
if [ "$CONTAINER_CLI" = "podman" ]; then
  SOCKET="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/podman/podman.sock"
  if [ ! -S "$SOCKET" ]; then
    mkdir -p "$(dirname "$SOCKET")"
    podman system service --time=0 "unix://$SOCKET" >/dev/null 2>&1 &
    SOCKET_PID=$!
    for _ in $(seq 1 10); do [ -S "$SOCKET" ] && break; sleep 1; done
  fi
else
  SOCKET="${DOCKER_SOCKET:-/var/run/docker.sock}"
fi
[ -S "$SOCKET" ] || { echo "No container API socket at $SOCKET" >&2; exit 1; }

cleanup() {
  if [ -n "${KEEP:-}" ] && [ -n "${STARTED:-}" ]; then echo "KEEP set: leaving Floci up ($CONTAINER_NAME)"; return; fi
  "$CONTAINER_CLI" rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  "$CONTAINER_CLI" ps -aq --filter name=floci-aws- | xargs -r "$CONTAINER_CLI" rm -f >/dev/null 2>&1 || true
  "$CONTAINER_CLI" network rm "$NETWORK_NAME" >/dev/null 2>&1 || true
  [ -z "$SOCKET_PID" ] || kill "$SOCKET_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup
STARTED=1

echo "=== x-ray e2e test (Floci real ECS + Lambda via $CONTAINER_CLI) ==="

# Floci only puts a task's containers in one shared network namespace (so Envoy
# can reach the app on 127.0.0.1, as on Fargate) with security-group enforcement
# on - which also makes the SG rules part of what this test exercises.

# Local images, used straight from the local store. Tags must match
# emulator.py's `-c e2e=true` naming (localhost/cdk1-xray-<dir>:e2e).
for dir in app-xray app-idp; do
  echo "--- building $dir"
  "$CONTAINER_CLI" build -q -t "localhost/cdk1-xray-${dir}:e2e" "$XRAY_DIR/$dir" >/dev/null
done

for fn in xray-invoker xray-dog-fetcher xray-s3-writer; do
  (cd "$XRAY_DIR/lambda/$fn" && npm ci --silent && npm run build --silent)
done

"$CONTAINER_CLI" network create "$NETWORK_NAME" >/dev/null

"$CONTAINER_CLI" run -d --name "$CONTAINER_NAME" --network "$NETWORK_NAME" \
  -p "$FLOCI_PORT:4566" -p "$E2E_ALB_PORT:80" \
  --sysctl net.ipv4.ip_unprivileged_port_start=0 \
  -v "$SOCKET:/var/run/docker.sock" \
  -e FLOCI_SERVICES_ECS_DOCKER_NETWORK="$NETWORK_NAME" \
  -e FLOCI_SERVICES_ECS_IMAGE_PULL_BEHAVIOR=prefer-cached \
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
export E2E_ALB_URL="http://localhost:$E2E_ALB_PORT"

cd "$REPO_ROOT" && npm ci --silent

cd "$XRAY_DIR"
if [ ! -d iac/.venv ]; then python3 -m venv iac/.venv; fi
# shellcheck disable=SC1091
source iac/.venv/bin/activate
pip install -q -r iac/requirements.txt -r iac/requirements-dev.txt

npx cdk bootstrap aws://000000000000/us-east-1 --app "python iac/app_xray.py"
npx cdk deploy --all --require-approval never -c emulator=true -c e2e=true --app "python iac/app_xray.py"

pytest iac/e2e -v
echo "=== x-ray e2e test passed ==="
