#!/usr/bin/env bash
# Mantiene el stack hackathon + gateway + ngrok activo (cron cada 10 min + @reboot).
set -euo pipefail

PROJECT="/home/rlopez/projects/innerspark-swarm-os-cursor-local"
LOG="$PROJECT/data/ensure_stack.log"
mkdir -p "$PROJECT/data"

_log() {
  echo "[$(date -Iseconds)] $*" >>"$LOG"
}

_port_up() {
  curl -sf "http://127.0.0.1:$1/" >/dev/null 2>&1 || \
    curl -sf "http://127.0.0.1:$1/api/status" >/dev/null 2>&1
}

_start_if_down() {
  local port="$1"
  local script="$2"
  local label="$3"
  if _port_up "$port"; then
    return 0
  fi
  _log "starting $label (port $port down)"
  nohup bash "$script" >>"$LOG" 2>&1 &
  sleep 4
}

start_systemd() {
  sudo -n systemctl start "$@" 2>/dev/null || systemctl start "$@" 2>/dev/null || true
}

# InnerOS (systemd preferido)
if systemctl is-enabled swarm-api >/dev/null 2>&1; then
  start_systemd swarm-api swarm-admin 2>/dev/null || true
else
  pgrep -f "uvicorn api.main:app" >/dev/null || _start_if_down 8100 "$PROJECT/run_api.sh" "swarm-api"
  pgrep -f "vite preview.*5173" >/dev/null || _start_if_down 5173 "$PROJECT/run_admin.sh" "swarm-admin"
fi

# Hackathon
if systemctl is-enabled swarm-hackathon-api >/dev/null 2>&1; then
  start_systemd swarm-hackathon-api swarm-hackathon-ui swarm-public-gateway swarm-ngrok 2>/dev/null || true
else
  pgrep -f "hackathon_band/api_server.py" >/dev/null || _start_if_down 8210 "$PROJECT/run_hackathon_api.sh" "hackathon-api"
  pgrep -f "vite preview.*5190" >/dev/null || _start_if_down 5190 "$PROJECT/run_hackathon_ui.sh" "hackathon-ui"
  pgrep -f "public_gateway.py" >/dev/null || _start_if_down 5188 "$PROJECT/run_public_gateway.sh" "public-gateway"
  if ! curl -sf "http://127.0.0.1:4040/api/tunnels" >/dev/null 2>&1; then
    _log "starting ngrok"
    nohup bash "$PROJECT/run_ngrok_all.sh" >>"$LOG" 2>&1 &
  fi
fi

# Actualizar URLs públicas si ngrok responde
if curl -sf "http://127.0.0.1:4040/api/tunnels" >/dev/null 2>&1; then
  bash "$PROJECT/scripts/bootstrap_on_boot.sh" >>"$LOG" 2>&1 || true
fi
