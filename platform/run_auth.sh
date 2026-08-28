#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
[[ -f venv/bin/activate ]] || python3 -m venv venv
source venv/bin/activate
pip install -q -r requirements.txt
export OAUTH_PORT="${OAUTH_PORT:-8103}"
export OAUTH_HOST="${OAUTH_HOST:-0.0.0.0}"
export PYTHONPATH="$ROOT"
echo "RalfIA OAuth en http://${OAUTH_HOST}:${OAUTH_PORT}"
exec python3 "$ROOT/raphiia_openai/auth_server.py"
