#!/usr/bin/env bash
set -euo pipefail

# Downloads the AWS Distro for OpenTelemetry Node.js Lambda layer content and
# extracts it locally so CDK can package it as a self-owned LayerVersion
# asset (frontend_stack.py's AdotLayerDogFetcher) instead of referencing
# AWS's shared cross-account layer ARN at deploy time. See
# docs/xray-collector-setup.md for why xray-dog-fetcher does this and
# xray-invoker/xray-s3-writer don't.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGION="${AWS_REGION:-us-east-1}"
LAYER_NAME="arn:aws:lambda:${REGION}:901920570463:layer:aws-otel-nodejs-amd64-ver-1-18-1"
LAYER_VERSION=4
OUT_DIR="$SCRIPT_DIR/otel-layer"

echo "Resolving download URL for ${LAYER_NAME}:${LAYER_VERSION}..."
LAYER_URL=$(aws lambda get-layer-version \
  --layer-name "$LAYER_NAME" \
  --version-number "$LAYER_VERSION" \
  --region "$REGION" \
  --query 'Content.Location' \
  --output text)

TMP_ZIP="$(mktemp)"
trap 'rm -f "$TMP_ZIP"' EXIT

echo "Downloading layer content..."
curl -sL -o "$TMP_ZIP" "$LAYER_URL"

echo "Extracting to ${OUT_DIR}..."
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"
unzip -q "$TMP_ZIP" -d "$OUT_DIR"

echo "✓ ADOT layer content ready at ${OUT_DIR}"
