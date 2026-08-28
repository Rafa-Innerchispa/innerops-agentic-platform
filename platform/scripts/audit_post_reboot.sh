#!/usr/bin/env bash
# Auditoría post-reinicio — servicios críticos 192.168.1.4 (+ opcional .5)
set -euo pipefail
HOST4="${RALFIA_HOST:-192.168.1.4}"
HOST5="${RALFIA_HOST_AMD:-192.168.1.5}"

check_local() {
  echo "========== SERVIDOR $HOST4 ($(hostname)) =========="
  echo "--- systemd system (swarm) ---"
  for u in swarm-ngrok swarm-public-gateway swarm-uipath-copilot swarm-api swarm-admin swarm-funding-hub; do
    printf "  %-28s %s\n" "$u" "$(systemctl is-active ${u}.service 2>/dev/null || echo '?')"
  done
  echo "--- systemd user (ralfia) ---"
  for u in ralfia-mcp ralfia-app ralfia-portal ralfia-coordination-daemon ralfia-smart-quoter ralfia-notify.timer; do
    printf "  %-28s %s\n" "$u" "$(systemctl --user is-active ${u} 2>/dev/null || echo '?')"
  done
  echo "--- HTTP probes ---"
  for url in \
    "http://127.0.0.1:5188/" \
    "http://127.0.0.1:8097/dashboard" \
    "http://127.0.0.1:8101/status" \
    "http://127.0.0.1:8102/mcp" \
    "http://127.0.0.1:2002/login" \
    "http://127.0.0.1:2026/"; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null || echo '000')
    printf "  %-6s %s\n" "$code" "$url"
  done
  echo "--- ngrok ---"
  pgrep -a ngrok 2>/dev/null | head -2 || echo "  (sin proceso ngrok)"
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 12 -H 'ngrok-skip-browser-warning: true' \
    'https://sworn-profusely-alongside.ngrok-free.dev/uipath/dashboard' 2>/dev/null || echo '000')
  echo "  externo uipath/dashboard: HTTP $code"
  if command -v python3 >/dev/null; then
    cd /home/rlopez/projects/raphiia-openai && source venv/bin/activate 2>/dev/null || true
    python3 - <<'PY'
from raphiia_openai import ngrok_watch, service_registry
service_registry.seed_defaults(force=False)
ng = ngrok_watch.check_ngrok_tunnel()
print(f"  ngrok registry: {ng.get('status')} — {ng.get('last_error','')[:100]}")
down = [s for s in service_registry.list_services(visible_only=False, limit=200).get('services',[])
        if s.get('risk_level') in ('critical','high') and s.get('status') in ('down','timeout','degraded')]
if down:
    print("  ALERTA critical/high degradados:")
    for s in down:
        print(f"    - {s.get('service_id')}: {s.get('status')} {s.get('last_error','')[:60]}")
else:
    print("  critical/high: OK (tras seed; ejecuta watchdog para checks frescos)")
PY
  fi
}

check_remote() {
  echo ""
  echo "========== SERVIDOR $HOST5 =========="
  if ! ssh -o BatchMode=yes -o ConnectTimeout=6 "rlopez@${HOST5}" 'hostname' 2>/dev/null; then
    echo "  SSH no disponible a $HOST5"
    return
  fi
  ssh -o BatchMode=yes -o ConnectTimeout=10 "rlopez@${HOST5}" bash -s <<'REMOTE'
echo "--- systemd user ralfia ---"
for u in ralfia-mcp ralfia-app ralfia-portal ralfia-coordination-daemon ralfia-full-stack ralfia-node-agent; do
  printf "  %-28s %s\n" "$u" "$(systemctl --user is-active ${u} 2>/dev/null || echo '?')"
done
echo "--- HTTP ---"
for url in http://127.0.0.1:8101/status http://127.0.0.1:2002/ http://127.0.0.1:8800/; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null || echo '000')
  printf "  %-6s %s\n" "$code" "$url"
done
echo "--- docker ---"
systemctl is-active docker 2>/dev/null || true
REMOTE
}

check_local
check_remote
