#!/usr/bin/env bash
set -euo pipefail

# Run this by hand, somewhere with AWS CLI + credentials (any AWS account -
# it's a public layer, no special access needed). Not part of any
# build/deploy pipeline.
#
# Finds the latest published version number of AWSOpenTelemetryDistroJs, the
# AWS-managed Lambda layer for the new/recommended ADOT Node.js approach
# (https://aws-otel.github.io/docs/getting-started/lambda), published by
# AWS's own account 615299751070. Run this before bumping the layer version
# in iac/xray_poc/frontend_stack.py.
#
# Unlike the legacy aws-otel-nodejs-* layer this replaced, there's no
# separate amd64/arm64 variant here - it's a single architecture-agnostic
# layer name (confirmed: AWSOpenTelemetryDistroJs-amd64/-arm64/Arm64 all
# come back AccessDenied, i.e. don't exist), so there's only one axis to
# probe: the version number.
#
# Why probing instead of `aws lambda list-layer-versions`: that API lists
# versions *in the caller's own account*. For a layer published by a
# different account, there's no list operation available to us - only
# `get-layer-version`, which reads one specific version number and is
# allowed cross-account by the layer's own public resource policy. So we
# probe version numbers one at a time and see which ones the resource
# policy lets us read.
#
# A nonexistent version and a permissions problem look identical from the
# caller's side (both come back as AccessDeniedException, since there's no
# ResourceNotFoundException for a resource-based-policy check) - but since
# lower version numbers succeed with the same identity, a failure on a
# higher number reliably means "doesn't exist yet", not "no access".
#
# This tolerates a few consecutive gaps rather than stopping at the first
# miss, in case AWS's own publishes aren't contiguous (confirmed on the old
# layer line - see git history of this script) - better safe than reporting
# a stale "latest".
#
# Usage: ./find-latest-otel-layer-version.sh [region]
# Example: ./find-latest-otel-layer-version.sh us-east-1

REGION="${1:-us-east-1}"
MAX_VERSION="${MAX_VERSION:-30}"
GAP_TOLERANCE="${GAP_TOLERANCE:-5}"

LAYER_NAME="arn:aws:lambda:${REGION}:615299751070:layer:AWSOpenTelemetryDistroJs"
echo "=== ${LAYER_NAME} ==="

LATEST_VERSION=""
LATEST_DATE=""
MISSES_SINCE_HIT=0

for VERSION in $(seq 1 "$MAX_VERSION"); do
  if DATE=$(aws lambda get-layer-version \
    --layer-name "$LAYER_NAME" \
    --version-number "$VERSION" \
    --region "$REGION" \
    --query 'CreatedDate' \
    --output text 2>/dev/null); then
    LATEST_VERSION="$VERSION"
    LATEST_DATE="$DATE"
    MISSES_SINCE_HIT=0
  else
    MISSES_SINCE_HIT=$((MISSES_SINCE_HIT + 1))
    if [ "$MISSES_SINCE_HIT" -ge "$GAP_TOLERANCE" ]; then
      break
    fi
  fi
done

if [ -z "$LATEST_VERSION" ]; then
  echo "  No versions found up to ${MAX_VERSION} - check the layer name/region."
else
  echo "  Latest: ${LAYER_NAME}:${LATEST_VERSION} (published ${LATEST_DATE})"
fi
