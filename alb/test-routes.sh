#!/usr/bin/env bash
set -uo pipefail

LOCAL_PORT="${1:-8080}"
BASE_URL="http://localhost:$LOCAL_PORT"

echo "=== ALB POC Route Tests (via $BASE_URL) ==="
echo "(requires ./connect.sh $LOCAL_PORT running in another terminal)"
echo ""

check() {
  local path="$1"
  local expected_service="$2"
  local body
  body=$(curl -s --max-time 5 "$BASE_URL$path")

  if [[ -z "$body" ]]; then
    echo "FAIL  $path -> could not connect (is ./connect.sh running?)"
    return 1
  fi

  if echo "$body" | grep -q "\"service\":\"$expected_service\""; then
    echo "PASS  $path -> $body"
    return 0
  else
    echo "FAIL  $path -> expected service=$expected_service, got: $body"
    return 1
  fi
}

fail=0
check "/main/foo" "main"    || fail=1
check "/auth/bar" "auth"    || fail=1
check "/anything" "default" || fail=1

echo ""
if [[ $fail -eq 0 ]]; then
  echo "All routes OK."
else
  echo "Some routes failed - see above."
  exit 1
fi
