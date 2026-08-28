#!/usr/bin/env bash
# Reinicio seguro del stack Ralphi IA vía systemd user (sin matar puertos manualmente).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

UNITS=(
  ralfia-app
  ralfia-mcp
  ralfia-portal
  ralfia-coordination-daemon
  ralfia-editorial-worker
)

echo "Reiniciando servicios user…"
for u in "${UNITS[@]}"; do
  if systemctl --user cat "${u}.service" &>/dev/null; then
    systemctl --user restart "${u}.service" || echo "WARN: ${u} falló"
  fi
done

sleep 3
echo "=== Estado ==="
systemctl --user is-active "${UNITS[@]}" 2>/dev/null || true
echo "=== HTTP ==="
curl -s -o /dev/null -w ":8101 %{http_code}\n" http://127.0.0.1:8101/status || true
curl -s -o /dev/null -w ":8102 %{http_code}\n" http://127.0.0.1:8102/mcp || true
curl -s -o /dev/null -w ":2002 %{http_code}\n" http://127.0.0.1:2002/ || true
