#!/usr/bin/env bash
set -euo pipefail

# Run this by hand, somewhere with AWS CLI + credentials - NOT prod's own
# build/deploy pipeline (deploy.sh never runs this; it only consumes the
# already-committed otel-layer.zip).
#
# Resolves a presigned download URL for AWS's real, official ADOT Node.js
# Lambda layer zip (a metadata read on a public layer via
# `aws lambda get-layer-version` - not an attach) and writes it to a
# manifest. Hand that manifest to a separate download team: they don't need
# AWS credentials to fetch a presigned URL, just `curl`. They should save
# the result as lambda/xray-dog-fetcher/otel-layer.zip and add it to this
# repo - no build step, it's AWS's ready-to-use layer content as-is.
#
# The presigned URL expires in ~10 minutes. If the download team can't act
# in time, just re-run this script for a fresh one.
#
# See docs/xray-collector-setup.md for why xray-dog-fetcher vendors this and
# xray-invoker/xray-s3-writer don't.
#
# Prerequisites: aws CLI (configured with credentials for the account that
# can read the public ADOT layer - any account works, it's a public layer).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGION="${AWS_REGION:-us-east-1}"
LAYER_NAME="arn:aws:lambda:${REGION}:901920570463:layer:aws-otel-nodejs-amd64-ver-1-18-1"
LAYER_VERSION=4
MANIFEST="$SCRIPT_DIR/otel-layer-download-manifest.txt"
TTL_SECONDS=600

echo "Resolving presigned download URL for ${LAYER_NAME}:${LAYER_VERSION}..."
LAYER_URL=$(aws lambda get-layer-version \
  --layer-name "$LAYER_NAME" \
  --version-number "$LAYER_VERSION" \
  --region "$REGION" \
  --query 'Content.Location' \
  --output text)

GENERATED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EXPIRES_AT=$(date -u -d "+${TTL_SECONDS} seconds" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
  || date -u -v +${TTL_SECONDS}S +%Y-%m-%dT%H:%M:%SZ)

cat > "$MANIFEST" <<EOF
# ADOT layer source download manifest
# Generated ${GENERATED_AT} - THIS URL EXPIRES AT ${EXPIRES_AT} (~${TTL_SECONDS}s TTL)
#
# Hand this off to the download team: fetch the URL below before it expires
# and save the result as lambda/xray-dog-fetcher/otel-layer.zip, then add
# that file to this repo. No build step needed - it's AWS's ready-to-use
# layer content as-is.
#
# If the download team can't act before the expiry above, just re-run
# resolve-otel-layer-url.sh for a fresh URL.
#
# filename	url
otel-layer.zip	${LAYER_URL}
EOF

echo "✓ Wrote ${MANIFEST}"
echo "  Expires at ${EXPIRES_AT} (UTC) - hand it to the download team now."
