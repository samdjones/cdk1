#!/usr/bin/env bash
set -euo pipefail

# Manual vendoring script - NOT part of deploy.sh / prod's build pipeline.
#
# Prod's own build/deploy run can't make any AWS API call (not even a
# read-only one), can't use the aws CLI, and can't run `git clone` either -
# only plain HTTPS downloads of zip files are allowed. So this builds the
# ADOT Node.js Lambda layer from source using nothing but zip-archive
# downloads: GitHub's codeload endpoint serves any repo ref as a plain .zip
# (https://github.com/<owner>/<repo>/archive/<ref>.zip), no git binary
# needed. The one wrinkle is that a repo's zip archive does NOT include its
# git submodules' content (aws-observability/aws-otel-lambda pulls in
# open-telemetry/opentelemetry-lambda as a submodule) - GitHub's public,
# unauthenticated Contents API (a plain GET, not a git operation) reports
# which exact commit a submodule path is pinned to, which we then download
# as its own separate zip.
#
# Run this by hand (e.g. on a developer machine, or a separate non-prod
# tooling job) whenever the vendored layer needs refreshing, then commit the
# resulting otel-layer.zip - it's checked into git like any other vendored
# dependency. frontend_stack.py's AdotLayerDogFetcher LayerVersion packages
# that committed zip directly (CDK uploads a .zip Code.from_asset as-is, no
# local unzip/rezip needed). See docs/xray-collector-setup.md for why
# xray-dog-fetcher vendors this and xray-invoker/xray-s3-writer don't.
#
# Prerequisites (all standard dev tooling, nothing AWS-specific, no git):
# curl, jq, go, node/npm, patch, zip, unzip.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_ZIP="$SCRIPT_DIR/otel-layer.zip"
GOARCH="${GOARCH:-amd64}"
AWS_OTEL_LAMBDA_REF="${AWS_OTEL_LAMBDA_REF:-main}"

for tool in curl jq go node npm patch zip unzip; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "Missing required tool: $tool" >&2
    exit 1
  }
done

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

echo "Downloading aws-observability/aws-otel-lambda (ref: ${AWS_OTEL_LAMBDA_REF})..."
curl -sL -o "$WORK_DIR/aws-otel-lambda.zip" \
  "https://github.com/aws-observability/aws-otel-lambda/archive/refs/heads/${AWS_OTEL_LAMBDA_REF}.zip"
# GitHub embeds the resolved commit SHA as the zip's archive comment.
AWS_OTEL_LAMBDA_SHA=$(unzip -qz "$WORK_DIR/aws-otel-lambda.zip")
unzip -q "$WORK_DIR/aws-otel-lambda.zip" -d "$WORK_DIR"
REPO_DIR="$WORK_DIR/aws-otel-lambda-${AWS_OTEL_LAMBDA_REF}"

echo "Resolving the pinned opentelemetry-lambda submodule commit via GitHub's Contents API..."
SUBMODULE_SHA=$(curl -sL \
  "https://api.github.com/repos/aws-observability/aws-otel-lambda/contents/opentelemetry-lambda?ref=${AWS_OTEL_LAMBDA_SHA}" \
  | jq -r '.sha')

echo "Downloading open-telemetry/opentelemetry-lambda @ ${SUBMODULE_SHA}..."
curl -sL -o "$WORK_DIR/opentelemetry-lambda.zip" \
  "https://github.com/open-telemetry/opentelemetry-lambda/archive/${SUBMODULE_SHA}.zip"
unzip -q "$WORK_DIR/opentelemetry-lambda.zip" -d "$WORK_DIR"
rm -rf "$REPO_DIR/opentelemetry-lambda"
mv "$WORK_DIR/opentelemetry-lambda-${SUBMODULE_SHA}" "$REPO_DIR/opentelemetry-lambda"

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
