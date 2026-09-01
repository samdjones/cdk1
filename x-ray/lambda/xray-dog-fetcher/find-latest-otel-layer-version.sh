#!/usr/bin/env bash
set -euo pipefail

# Run this by hand, somewhere with AWS CLI + credentials (any AWS account -
# it's a public layer, no special access needed). Not part of any
# build/deploy pipeline.
#
# Finds the latest published version number for a given ADOT layer name
# (e.g. aws-otel-nodejs-amd64-ver-1-30-2), for both amd64 and arm64.
#
# Why probing instead of `aws lambda list-layer-versions`: that API lists
# versions *in the caller's own account*. For a layer published by a
# different account (this one belongs to AWS's 901920570463), there's no
# list operation available to us - only `get-layer-version`, which reads one
# specific version number and is allowed cross-account by the layer's own
# public resource policy. So we probe version numbers one at a time and see
# which ones the resource policy lets us read.
#
# A nonexistent version and a permissions problem look identical from the
# caller's side (both come back as AccessDeniedException, since there's no
# ResourceNotFoundException for a resource-based-policy check) - but since
# lower version numbers succeed with the same identity, a failure on a
# higher number reliably means "doesn't exist yet", not "no access".
#
# Versions aren't guaranteed contiguous - a failed publish on AWS's side can
# leave a gap (confirmed empirically: aws-otel-nodejs-arm64-ver-1-30-0 has
# versions 1, 2, 4 but no 3). So this keeps probing past single gaps up to
# MAX_VERSION rather than stopping at the first miss, and reports the
# highest version actually found.
#
# Usage: ./find-latest-otel-layer-version.sh <ver-x-y-z> [region]
# Example: ./find-latest-otel-layer-version.sh ver-1-30-2 us-east-1

LAYER_VER="${1:?Usage: $0 <ver-x-y-z> [region]}"
REGION="${2:-us-east-1}"
MAX_VERSION="${MAX_VERSION:-20}"
GAP_TOLERANCE="${GAP_TOLERANCE:-3}"

for ARCH in amd64 arm64; do
  LAYER_NAME="arn:aws:lambda:${REGION}:901920570463:layer:aws-otel-nodejs-${ARCH}-${LAYER_VER}"
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
done
