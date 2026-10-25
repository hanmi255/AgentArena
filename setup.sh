#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt -c requirements.lock
npm ci --prefix frontend --allow-scripts=esbuild
npm run build --prefix frontend
