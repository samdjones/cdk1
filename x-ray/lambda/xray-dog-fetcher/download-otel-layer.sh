#!/usr/bin/env bash
set -euo pipefail

# Manual vendoring script - NOT part of deploy.sh / prod's build pipeline.
#
# Prod's own build/deploy run cannot make any AWS API calls beyond what `cdk
# deploy` itself does, so this can't run there. Instead, run this by hand
# (e.g. on a developer machine, or a separate non-prod tooling job) whenever
# the pinned ADOT layer version needs updating, then commit the resulting
# otel-layer.zip - it's checked into git like any other vendored dependency.
# frontend_stack.py's AdotLayerDogFetcher LayerVersion packages that
# committed zip directly (CDK uploads a .zip Code.from_asset as-is, no local
# unzip/rezip needed). See docs/xray-collector-setup.md for why
# xray-dog-fetcher vendors this and xray-invoker/xray-s3-writer don't.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGION="${AWS_REGION:-us-east-1}"
LAYER_NAME="arn:aws:lambda:${REGION}:901920570463:layer:aws-otel-nodejs-amd64-ver-1-18-1"
LAYER_VERSION=4
OUT_ZIP="$SCRIPT_DIR/otel-layer.zip"

echo "Resolving download URL for ${LAYER_NAME}:${LAYER_VERSION}..."
LAYER_URL=$(aws lambda get-layer-version \
  --layer-name "$LAYER_NAME" \
  --version-number "$LAYER_VERSION" \
  --region "$REGION" \
  --query 'Content.Location' \
  --output text)

echo "Downloading layer content to ${OUT_ZIP}..."
curl -sL -o "$OUT_ZIP" "$LAYER_URL"

echo "✓ ADOT layer content ready at ${OUT_ZIP} - commit this file."
