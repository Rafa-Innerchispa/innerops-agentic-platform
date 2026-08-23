#!/usr/bin/env bash
# API Hackathon Band - :8210; :8200 is reserved for RalfIA Voice Gateway
set -euo pipefail
cd "$(dirname "$0")"
PORT="${HACKATHON_API_PORT:-8210}"
if [[ "$PORT" == "8200" ]]; then
  echo "WARN: HACKATHON_API_PORT=8200 conflicts with RalfIA Voice; using 8210" >&2
  PORT=8210
fi
export HACKATHON_API_PORT="$PORT"
if command -v fuser >/dev/null 2>&1; then
  fuser -k "${PORT}/tcp" 2>/dev/null || true
  sleep 1
fi
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(grep -v '^\s*#' .env | sed 's/\r$//')
  set +a
fi
if [[ "${HACKATHON_API_PORT:-$PORT}" == "8200" ]]; then
  echo "WARN: .env requested HACKATHON_API_PORT=8200; using 8210 for Hackathon API" >&2
  PORT=8210
else
  PORT="${HACKATHON_API_PORT:-$PORT}"
fi
export HACKATHON_API_PORT="$PORT"
source venv/bin/activate
exec python hackathon_band/api_server.py
