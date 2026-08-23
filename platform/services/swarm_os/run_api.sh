#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PORT="${API_PORT:-8100}"
if command -v fuser >/dev/null 2>&1; then
  fuser -k "${PORT}/tcp" 2>/dev/null || true
  sleep 1
fi
bash scripts/ensure_mongo.sh || true
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(grep -v '^\s*#' .env | sed 's/\r$//')
  set +a
fi
source venv/bin/activate
exec uvicorn api.main:app --host 0.0.0.0 --port "${API_PORT:-8100}"
