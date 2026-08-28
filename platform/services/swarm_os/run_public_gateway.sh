#!/usr/bin/env bash
# Gateway público :5188 — InnerOS (/inneros) + Hackathon (/) en un solo puerto ngrok
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PUBLIC_GATEWAY_PORT:-5188}"

# Solo matar ocupantes del puerto si YA hay LISTEN (evita carreras con systemd
# cuando otro arranque hace fuser -k sobre un gateway sano).
if command -v fuser >/dev/null 2>&1; then
  if ss -tln "sport = :${PORT}" 2>/dev/null | grep -q LISTEN; then
    echo "Puerto ${PORT} ocupado — liberando antes de bind"
    fuser -k "${PORT}/tcp" 2>/dev/null || true
    sleep 1
  fi
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(grep -v '^\s*#' .env | sed 's/\r$//')
  set +a
fi

source venv/bin/activate
exec python scripts/public_gateway.py
