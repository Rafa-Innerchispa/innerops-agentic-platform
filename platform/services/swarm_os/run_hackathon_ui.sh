#!/usr/bin/env bash
# UI Hackathon Band — :5190 (proxy /api y /ws → :8200)
set -euo pipefail
cd "$(dirname "$0")/hackathon_band/ui"
PORT="${HACKATHON_BAND_PORT:-5190}"

if command -v fuser >/dev/null 2>&1; then
  fuser -k "${PORT}/tcp" 2>/dev/null || true
  sleep 1
fi

if [[ ! -d node_modules ]]; then
  npm install
fi
npm run build
exec npx vite preview --host 0.0.0.0 --port "$PORT"
