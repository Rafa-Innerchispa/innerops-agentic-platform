#!/usr/bin/env bash
# Aplica autostart completo: cron (sin sudo) + systemd (con sudo) + reinicia ngrok dual.
set -euo pipefail
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== 1/4 Crontab @reboot (sin sudo) ==="
bash "$PROJECT/scripts/install_autostart_cron.sh"

echo ""
echo "=== 2/4 Systemd (requiere contraseña sudo) ==="
if bash "$PROJECT/scripts/install_services.sh"; then
  echo "Systemd actualizado."
else
  echo "AVISO: install_services.sh necesita sudo. Ejecuta manualmente:"
  echo "  bash $PROJECT/scripts/install_services.sh"
fi

echo ""
echo "=== 3/4 Reiniciar ngrok → túneles duales :5173 + :5190 ==="
if systemctl is-active swarm-ngrok >/dev/null 2>&1; then
  sudo systemctl restart swarm-ngrok 2>/dev/null || {
    echo "Sin sudo: matando ngrok viejo; systemd debería relanzar run_ngrok_all.sh..."
    pkill -f "ngrok http 5173" 2>/dev/null || true
    pkill -f "ngrok start" 2>/dev/null || true
    sleep 5
  }
else
  pkill -f "ngrok http 5173" 2>/dev/null || true
  nohup bash "$PROJECT/run_ngrok_all.sh" >>"$PROJECT/data/ngrok.log" 2>&1 &
  sleep 8
fi

echo ""
echo "=== 4/4 Reiniciar hackathon (Evolution + .env) ==="
bash "$PROJECT/scripts/restart_hackathon_stack.sh"

sleep 5
bash "$PROJECT/scripts/bootstrap_on_boot.sh" || true

echo ""
echo "=== URLs ==="
cat "$PROJECT/data/public_demo_url.txt" 2>/dev/null || true
echo "---"
cat "$PROJECT/data/hackathon_public_url.txt" 2>/dev/null || echo "(hackathon_public_url.txt pendiente)"
