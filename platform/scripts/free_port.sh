#!/usr/bin/env bash
# Libera un puerto TCP si está ocupado (sin error si está libre).
set -euo pipefail
PORT="${1:?usage: free_port.sh PORT}"
if command -v fuser >/dev/null 2>&1; then
  fuser -k "${PORT}/tcp" 2>/dev/null || true
elif command -v lsof >/dev/null 2>&1; then
  pids="$(lsof -t -i ":${PORT}" 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    kill ${pids} 2>/dev/null || true
  fi
fi
sleep 1
