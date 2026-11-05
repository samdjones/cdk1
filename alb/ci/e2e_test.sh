#!/usr/bin/env bash
# E2E app test (local only): deploy AlbPocStack into Floci with REAL ECS, so the
# actual alb app images run as containers behind the emulated ALB, then send
# HTTP requests through the ALB and assert on which backend answers.
# Never touches real AWS. Slower than ci/emulator_test.sh (builds 3 images).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALB_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$ALB_DIR/.." && pwd)"

CONTAINER_CLI="${CONTAINER_CLI:-podman}"
FLOCI_IMAGE="${FLOCI_IMAGE:-docker.io/floci/floci:2.4.0}"
FLOCI_PORT="${FLOCI_PORT:-4566}"
E2E_ALB_PORT="${E2E_ALB_PORT:-8088}"
CONTAINER_NAME="floci-e2e-alb"
NETWORK_NAME="floci-e2e-alb"

# Floci launches the app containers through a Docker-compatible API socket.
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
  "$CONTAINER_CLI" rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  # App containers Floci started (named floci-aws-ecs-*).
  "$CONTAINER_CLI" ps -aq --filter name=floci-aws- | xargs -r "$CONTAINER_CLI" rm -f >/dev/null 2>&1 || true
  "$CONTAINER_CLI" network rm "$NETWORK_NAME" >/dev/null 2>&1 || true
  [ -z "$SOCKET_PID" ] || kill "$SOCKET_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

echo "=== alb e2e test (Floci real ECS via $CONTAINER_CLI) ==="

# Images are built locally and used straight from the local store: no ECR push.
# Tags must match emulator.py's `-c e2e=true` naming.
for svc in main auth default; do
  "$CONTAINER_CLI" build -q -t "localhost/cdk1-alb-${svc}:e2e" "$ALB_DIR/app/$svc" >/dev/null
done

"$CONTAINER_CLI" network create "$NETWORK_NAME" >/dev/null

# - ECS mock off: tasks are real containers on $NETWORK_NAME.
# - prefer-cached: use the locally built images instead of attempting a pull.
# - unprivileged_port_start=0: Floci's ALB data plane binds port 80 as non-root.
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

cd "$ALB_DIR"
if [ ! -d iac/.venv ]; then python3 -m venv iac/.venv; fi
# shellcheck disable=SC1091
source iac/.venv/bin/activate
pip install -q -r iac/requirements.txt -r iac/requirements-dev.txt

npx cdk bootstrap aws://000000000000/us-east-1 --app "python iac/app_alb.py"
npx cdk deploy --all --require-approval never -c emulator=true -c e2e=true --app "python iac/app_alb.py"

pytest iac/e2e -v
echo "=== alb e2e test passed ==="
