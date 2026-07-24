#!/usr/bin/env bash
set -euo pipefail

OUT_FILE="$(mktemp)"

echo "=== X-Ray POC Trigger ==="
echo ""
echo "Invoking xray-invoker..."

aws lambda invoke --function-name xray-invoker "$OUT_FILE" >/dev/null

echo ""
if command -v jq >/dev/null 2>&1; then
  jq . "$OUT_FILE"
else
  cat "$OUT_FILE"
  echo ""
fi

rm -f "$OUT_FILE"

echo ""
echo "=== Trace triggered ==="
echo "View results in AWS Console -> X-Ray -> Traces or Service Map"
echo "  https://console.aws.amazon.com/xray/home#/traces"
