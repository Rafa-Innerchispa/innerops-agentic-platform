#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORTAL_PORT:-2002}"
if command -v fuser >/dev/null 2>&1; then
  fuser -k "${PORT}/tcp" 2>/dev/null || true
  fuser -k 8800/tcp 2>/dev/null || true
  sleep 1
fi
echo "RalfIA Control Center → http://192.168.1.4:${PORT}/"
exec venv/bin/uvicorn portal_server:app --host 0.0.0.0 --port "$PORT"
