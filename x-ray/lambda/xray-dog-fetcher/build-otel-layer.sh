#!/usr/bin/env bash
set -euo pipefail

# Phase 3 of 3 for vendoring the ADOT Node.js Lambda layer from source.
# Entirely offline - no network access, no AWS credentials, no aws CLI, no
# git. It only reads the two zips already staged in otel-build-inputs/ (put
# there by the download team, per otel-layer-download-manifest.txt - see
# resolve-otel-layer-urls.sh for phase 1) and compiles the layer locally.
#
#   Phase 1 (resolve-otel-layer-urls.sh): resolve exact commit SHAs -> write
#                           a download manifest.
#   Phase 2 (another team): download each URL in the manifest into
#                           otel-build-inputs/<filename>, add those files to
#                           this repo.
#   Phase 3 (this script):  build the layer from the staged zips.
#
# Run this by hand (e.g. on a developer machine, or a separate non-prod
# tooling job) whenever the vendored layer needs refreshing, then commit the
# resulting otel-layer.zip - it's checked into git like any other vendored
# dependency. frontend_stack.py's AdotLayerDogFetcher LayerVersion packages
# that committed zip directly (CDK uploads a .zip Code.from_asset as-is, no
# local unzip/rezip needed). See docs/xray-collector-setup.md for why
# xray-dog-fetcher vendors this and xray-invoker/xray-s3-writer don't.
#
# Prerequisites (all standard dev tooling, nothing AWS-specific): go,
# node/npm, patch, zip, unzip.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INPUTS_DIR="$SCRIPT_DIR/otel-build-inputs"
OUT_ZIP="$SCRIPT_DIR/otel-layer.zip"
GOARCH="${GOARCH:-amd64}"

for tool in go node npm patch zip unzip; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "Missing required tool: $tool" >&2
    exit 1
  }
done

AWS_OTEL_LAMBDA_ZIP="$INPUTS_DIR/aws-otel-lambda.zip"
SUBMODULE_ZIP="$INPUTS_DIR/opentelemetry-lambda.zip"
for f in "$AWS_OTEL_LAMBDA_ZIP" "$SUBMODULE_ZIP"; do
  [ -f "$f" ] || {
    echo "Missing $f" >&2
    echo "Run resolve-otel-layer-urls.sh, hand the resulting manifest to the" >&2
    echo "download team, and stage the two zips it lists under ${INPUTS_DIR}/ first." >&2
    exit 1
  }
done

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

echo "Extracting staged aws-otel-lambda.zip..."
unzip -q "$AWS_OTEL_LAMBDA_ZIP" -d "$WORK_DIR"
REPO_DIR=$(find "$WORK_DIR" -maxdepth 1 -type d -name 'aws-otel-lambda-*')
AWS_OTEL_LAMBDA_SHA="${REPO_DIR##*aws-otel-lambda-}"

echo "Extracting staged opentelemetry-lambda.zip..."
unzip -q "$SUBMODULE_ZIP" -d "$WORK_DIR"
SUBMODULE_DIR=$(find "$WORK_DIR" -maxdepth 1 -type d -name 'opentelemetry-lambda-*')
rm -rf "$REPO_DIR/opentelemetry-lambda"
mv "$SUBMODULE_DIR" "$REPO_DIR/opentelemetry-lambda"

cd "$REPO_DIR"

echo "Patching upstream opentelemetry-lambda with AWS's X-Ray-specific components..."
cp -rf adot/* opentelemetry-lambda/
cd opentelemetry-lambda
patch -p1 --quiet < ../terraformversion.patch
cd collector
[ -s ../../OTEL_Version.patch ] && patch -p2 --quiet < ../../OTEL_Version.patch
patch -p2 --quiet < ../../collector.patch
patch -p2 --quiet < ../../manager.patch
go mod edit -replace "github.com/open-telemetry/opentelemetry-lambda/collector/lambdacomponents=$REPO_DIR/adot/collector/lambdacomponents"
rm -f go.sum
go mod tidy

echo "Building the ADOT collector extension (includes the awsxray exporter)..."
OTELCOL_VERSION=$(grep "go.opentelemetry.io/collector/otelcol v" go.mod | awk '{print $2; exit}')
echo "$OTELCOL_VERSION" > VERSION
mkdir -p build/extensions
GO111MODULE=on CGO_ENABLED=0 GOOS=linux GOARCH="$GOARCH" go build -trimpath \
  -ldflags "-s -w -X main.GitHash=$AWS_OTEL_LAMBDA_SHA -X main.Version=$OTELCOL_VERSION -X github.com/open-telemetry/opentelemetry-collector-contrib/exporter/awsxrayexporter.collectorDistribution=opentelemetry-collector-lambda" \
  -o build/extensions .
mkdir -p build/collector-config
cp config* build/collector-config
(cd build && zip -qr "opentelemetry-collector-layer-$GOARCH.zip" collector-config extensions)

echo "Building the Node.js SDK/wrapper layer..."
cd "$REPO_DIR/nodejs/wrapper-adot"
npm install --silent
cd "$REPO_DIR/opentelemetry-lambda/nodejs"
npm install --silent
npm run build --silent

echo "Merging AWS's wrapper/adot-extension overlay onto the Node.js build output..."
WORKSPACE="$REPO_DIR/opentelemetry-lambda/nodejs/packages/layer/build/workspace"
mv "$WORKSPACE/otel-handler" "$WORKSPACE/otel-handler-upstream"
cp "$REPO_DIR/nodejs/scripts/otel-handler" "$WORKSPACE/otel-handler"
cp -r "$REPO_DIR/nodejs/wrapper-adot/node_modules/@opentelemetry" "$WORKSPACE/node_modules/"
cp "$REPO_DIR/nodejs/wrapper-adot/build/src/adot-extension."* "$WORKSPACE/"

echo "Merging in the collector extension and packaging the final layer..."
cd "$WORKSPACE"
unzip -qo "$REPO_DIR/opentelemetry-lambda/collector/build/opentelemetry-collector-layer-$GOARCH.zip"
rm -f "$OUT_ZIP"
zip -qr "$OUT_ZIP" *

echo "✓ ADOT layer built from source at ${OUT_ZIP} - commit this file."
