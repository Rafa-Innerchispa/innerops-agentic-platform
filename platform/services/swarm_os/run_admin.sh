#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/admin"
PORT="${ADMIN_PORT:-5173}"

# Liberar :5173 y :5174 (evita admin en puerto equivocado y ngrok roto)
if command -v fuser >/dev/null 2>&1; then
  fuser -k "${PORT}/tcp" 5174/tcp 2>/dev/null || true
  sleep 1
fi

if [[ ! -d node_modules ]]; then
  npm install
fi
# Siempre build al arrancar (systemd) — así tras reinicio no hace falta npm manual
npm run build
exec npx vite preview --host 0.0.0.0 --port "$PORT"
