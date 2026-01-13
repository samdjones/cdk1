#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../app"

docker build -t cdk1-app:ci .
