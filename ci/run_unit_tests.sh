#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../app"

python -m venv .venv
source .venv/bin/activate

python -m pip install -U pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt

python -m pytest
