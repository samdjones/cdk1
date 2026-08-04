#!/usr/bin/env bash
set -euo pipefail

# Manual vendoring script - NOT part of deploy.sh / prod's build pipeline.
#
# Prod's own build/deploy run can't make any AWS API call (not even a
# read-only one) and can't use the aws CLI, so the ADOT Node.js Lambda layer
# can't be fetched via `aws lambda get-layer-version` there either. Instead
# of pulling AWS's prebuilt artifact at all, this builds the equivalent layer
# from source - cloning the public aws-observability/aws-otel-lambda repo
# (which itself patches the upstream open-telemetry/opentelemetry-lambda
# project with AWS's X-Ray-specific collector components) and compiling it
# locally. No AWS credentials or API calls anywhere in this script - only
# `git clone` of public repos and local compilation.
#
# Run this by hand (e.g. on a developer machine, or a separate non-prod
# tooling job) whenever the vendored layer needs refreshing, then commit the
# resulting otel-layer.zip - it's checked into git like any other vendored
# dependency. frontend_stack.py's AdotLayerDogFetcher LayerVersion packages
# that committed zip directly (CDK uploads a .zip Code.from_asset as-is, no
# local unzip/rezip needed). See docs/xray-collector-setup.md for why
# xray-dog-fetcher vendors this and xray-invoker/xray-s3-writer don't.
#
# Prerequisites (all standard dev tooling, nothing AWS-specific): git, go,
# node/npm, patch, zip, unzip.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_ZIP="$SCRIPT_DIR/otel-layer.zip"
GOARCH="${GOARCH:-amd64}"

for tool in git go node npm patch zip unzip; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "Missing required tool: $tool" >&2
    exit 1
  }
done

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

echo "Cloning aws-observability/aws-otel-lambda (with opentelemetry-lambda submodule)..."
git clone --quiet --depth 1 https://github.com/aws-observability/aws-otel-lambda.git "$WORK_DIR/aws-otel-lambda"
cd "$WORK_DIR/aws-otel-lambda"
git submodule update --init --depth 1 --quiet

echo "Patching upstream opentelemetry-lambda with AWS's X-Ray-specific components..."
cp -rf adot/* opentelemetry-lambda/
cd opentelemetry-lambda
patch -p1 --quiet < ../terraformversion.patch
cd collector
[ -s ../../OTEL_Version.patch ] && patch -p2 --quiet < ../../OTEL_Version.patch
patch -p2 --quiet < ../../collector.patch
patch -p2 --quiet < ../../manager.patch
go mod edit -replace "github.com/open-telemetry/opentelemetry-lambda/collector/lambdacomponents=$WORK_DIR/aws-otel-lambda/adot/collector/lambdacomponents"
rm -f go.sum
go mod tidy

echo "Building the ADOT collector extension (includes the awsxray exporter)..."
OTELCOL_VERSION=$(grep "go.opentelemetry.io/collector/otelcol v" go.mod | awk '{print $2; exit}')
echo "$OTELCOL_VERSION" > VERSION
GIT_SHA=$(git -C "$WORK_DIR/aws-otel-lambda" rev-parse HEAD)
mkdir -p build/extensions
GO111MODULE=on CGO_ENABLED=0 GOOS=linux GOARCH="$GOARCH" go build -trimpath \
  -ldflags "-s -w -X main.GitHash=$GIT_SHA -X main.Version=$OTELCOL_VERSION -X github.com/open-telemetry/opentelemetry-collector-contrib/exporter/awsxrayexporter.collectorDistribution=opentelemetry-collector-lambda" \
  -o build/extensions .
mkdir -p build/collector-config
cp config* build/collector-config
(cd build && zip -qr "opentelemetry-collector-layer-$GOARCH.zip" collector-config extensions)

echo "Building the Node.js SDK/wrapper layer..."
cd "$WORK_DIR/aws-otel-lambda/nodejs/wrapper-adot"
npm install --silent
cd "$WORK_DIR/aws-otel-lambda/opentelemetry-lambda/nodejs"
npm install --silent
npm run build --silent

echo "Merging AWS's wrapper/adot-extension overlay onto the Node.js build output..."
WORKSPACE="$WORK_DIR/aws-otel-lambda/opentelemetry-lambda/nodejs/packages/layer/build/workspace"
mv "$WORKSPACE/otel-handler" "$WORKSPACE/otel-handler-upstream"
cp "$WORK_DIR/aws-otel-lambda/nodejs/scripts/otel-handler" "$WORKSPACE/otel-handler"
cp -r "$WORK_DIR/aws-otel-lambda/nodejs/wrapper-adot/node_modules/@opentelemetry" "$WORKSPACE/node_modules/"
cp "$WORK_DIR/aws-otel-lambda/nodejs/wrapper-adot/build/src/adot-extension."* "$WORKSPACE/"

echo "Merging in the collector extension and packaging the final layer..."
cd "$WORKSPACE"
unzip -qo "$WORK_DIR/aws-otel-lambda/opentelemetry-lambda/collector/build/opentelemetry-collector-layer-$GOARCH.zip"
rm -f "$OUT_ZIP"
zip -qr "$OUT_ZIP" *

echo "✓ ADOT layer built from source at ${OUT_ZIP} - commit this file."
