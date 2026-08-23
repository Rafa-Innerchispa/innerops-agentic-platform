#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if command -v fuser >/dev/null 2>&1; then
  fuser -k 8800/tcp 2>/dev/null || true
  sleep 1
fi
exec venv/bin/uvicorn redirect_8800:app --host 0.0.0.0 --port 8800
