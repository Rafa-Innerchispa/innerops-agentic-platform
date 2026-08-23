#!/usr/bin/env bash
# Ejecutar al reiniciar (cron @reboot o manual). No requiere intervención humana.
set -euo pipefail

PROJECT="/home/rlopez/projects/innerspark-swarm-os-cursor-local"
LOG="$PROJECT/data/start_on_boot.log"
mkdir -p "$PROJECT/data"

{
  echo "=== $(date -Iseconds) start_on_boot ==="

  bash "$PROJECT/scripts/ensure_mongo.sh" || true

  start_systemd() {
    sudo -n systemctl start "$@" 2>/dev/null || systemctl start "$@" 2>/dev/null || true
  }

  # InnerOS: API + Admin
  if systemctl is-enabled swarm-api >/dev/null 2>&1; then
    start_systemd swarm-api swarm-admin
  else
    pgrep -f "uvicorn api.main:app" >/dev/null || nohup bash "$PROJECT/run_api.sh" >>"$LOG" 2>&1 &
    sleep 5
    pgrep -f "vite preview.*5173" >/dev/null || nohup bash "$PROJECT/run_admin.sh" >>"$LOG" 2>&1 &
  fi

  sleep 10

  # Hackathon Band: API :8210 + UI :5190
  if systemctl is-enabled swarm-hackathon-api >/dev/null 2>&1; then
    start_systemd swarm-hackathon-api swarm-hackathon-ui
  else
    pgrep -f "hackathon_band/api_server.py" >/dev/null || nohup bash "$PROJECT/run_hackathon_api.sh" >>"$LOG" 2>&1 &
    sleep 8
    pgrep -f "vite preview.*5190" >/dev/null || nohup bash "$PROJECT/run_hackathon_ui.sh" >>"$LOG" 2>&1 &
  fi

  sleep 15

  # Gateway :5188 (InnerOS /inneros + Hackathon / tras un solo ngrok)
  if systemctl is-enabled swarm-public-gateway >/dev/null 2>&1; then
    start_systemd swarm-public-gateway
  elif ! curl -sf "http://127.0.0.1:5188/" >/dev/null 2>&1; then
    nohup bash "$PROJECT/run_public_gateway.sh" >>"$LOG" 2>&1 &
    sleep 3
  fi

  # ngrok → gateway :5188
  if systemctl is-enabled swarm-ngrok >/dev/null 2>&1; then
    start_systemd swarm-ngrok
  elif ! curl -sf "http://127.0.0.1:4040/api/tunnels" >/dev/null 2>&1; then
    nohup bash "$PROJECT/run_ngrok_all.sh" >>"$PROJECT/data/ngrok.log" 2>&1 &
    echo "ngrok dual launching..."
    for _ in $(seq 1 45); do
      curl -sf "http://127.0.0.1:4040/api/tunnels" >/dev/null 2>&1 && break
      sleep 2
    done
  fi

  bash "$PROJECT/scripts/bootstrap_on_boot.sh" || true

  echo "=== done ==="
} >>"$LOG" 2>&1
