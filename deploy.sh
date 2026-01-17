#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLEAN=false

while getopts "c" opt; do
    case $opt in
        c) CLEAN=true ;;
        *) echo "Usage: $0 [-c]"; echo "  -c  Clean install (delete node_modules)"; exit 1 ;;
    esac
done

echo "=== Build: Lambda ==="
cd "$SCRIPT_DIR/lambda/multiply"
rm -rf dist
if [ "$CLEAN" = true ]; then
    rm -rf node_modules
    npm ci
else
    npm install
fi
npm run build

echo "=== Build: App ==="
cd "$SCRIPT_DIR/app"
rm -rf dist
if [ "$CLEAN" = true ]; then
    rm -rf node_modules
    npm ci
else
    npm install
fi
npm run build

echo "=== Deploy CDK Stack ==="
cd "$SCRIPT_DIR/iac"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
cdk deploy --require-approval never

echo "=== Deployment complete ==="
