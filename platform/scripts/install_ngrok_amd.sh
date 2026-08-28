#!/usr/bin/env bash
# AMD (.5) — NO segundo ngrok (ERR_NGROK_334: dominio reservado ya en Intel).
# Panel AMD público vía gateway Intel: https://sworn-profusely-alongside.ngrok-free.dev/amd-panel/
set -euo pipefail

echo "=== ngrok AMD — modo gateway Intel (sin segundo túnel) ==="
echo ""
echo "Cuenta ngrok free: un solo dominio reservado (sworn-profusely-alongside.ngrok-free.dev)."
echo "Segundo ngrok en .5 falla con ERR_NGROK_334."
echo ""
echo "URL pública panel AMD:"
echo "  https://sworn-profusely-alongside.ngrok-free.dev/amd-panel/"
echo ""
echo "LAN directo:"
echo "  http://192.168.1.5:2002/"
echo ""

if [[ "$(hostname)" == *amd* ]] || hostname -I 2>/dev/null | grep -q '192.168.1.5'; then
  systemctl --user disable --now ralfia-ngrok-amd.service 2>/dev/null || true
  echo "OK: ralfia-ngrok-amd deshabilitado en AMD (evita bucle de reinicio)."
fi

if curl -sf -H 'ngrok-skip-browser-warning: true' \
  'https://sworn-profusely-alongside.ngrok-free.dev/amd-panel/api/ops/health' >/dev/null 2>&1; then
  echo "Probe externo /amd-panel: OK"
else
  echo "Probe externo /amd-panel: pendiente — reinicia gateway Intel:"
  echo "  sudo systemctl restart swarm-public-gateway.service"
fi
