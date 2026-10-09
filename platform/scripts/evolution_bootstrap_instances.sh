#!/usr/bin/env bash
# Crea o repara instancias Evolution + webhook portal (Intel primary + AMD Innerchispa).
set -euo pipefail

APIKEY="${EVOLUTION_API_KEY:-swarm_os_evolution_key_2026}"
WEBHOOK_URL="${EVOLUTION_WEBHOOK_URL:-http://192.168.1.4:2002/api/whatsapp/evolution/webhook}"
WEBHOOK_SECRET="${EVOLUTION_WEBHOOK_SECRET:-1ffc51506d42b92604ad2d360738231c7f3d779cafa29b582d424cfcf6fd4526}"
INTEL="${RALFIA_INTEL_HOST:-192.168.1.4}"
AMD="${RALFIA_AMD_HOST:-192.168.1.5}"
PORT=8082

log() { echo "[evolution-bootstrap] $*"; }

api() {
  local base="$1" method="$2" path="$3" body="${4:-}"
  if [[ -n "$body" ]]; then
    curl -sf -m 30 -X "$method" -H "apikey: $APIKEY" -H "Content-Type: application/json" \
      -d "$body" "${base}${path}"
  else
    curl -sf -m 30 -X "$method" -H "apikey: $APIKEY" "${base}${path}"
  fi
}

ensure_instance() {
  local base="$1" name="$2" number="${3:-}"
  log "$base — comprobar instancia $name"
  local list
  list=$(api "$base" GET "/instance/fetchInstances" || echo "[]")
  if echo "$list" | python3 -c "import sys,json; n=sys.argv[1]; d=json.load(sys.stdin); sys.exit(0 if any(i.get('name')==n for i in d) else 1)" "$name" 2>/dev/null; then
    log "  ya existe $name"
    return 0
  fi
  log "  creando $name"
  local payload
  if [[ -n "$number" ]]; then
    payload=$(python3 - <<PY
import json
print(json.dumps({"instanceName": "$name", "number": "$number", "qrcode": True, "integration": "WHATSAPP-BAILEYS"}))
PY
)
  else
    payload=$(python3 - <<PY
import json
print(json.dumps({"instanceName": "$name", "qrcode": True, "integration": "WHATSAPP-BAILEYS"}))
PY
)
  fi
  api "$base" POST "/instance/create" "$payload" | head -c 200
  echo
}

ensure_webhook() {
  local base="$1" name="$2"
  log "$base — webhook $name → $WEBHOOK_URL"
  local payload
  payload=$(python3 - <<PY
import json
print(json.dumps({
  "webhook": {
    "enabled": True,
    "url": "$WEBHOOK_URL",
    "headers": {"X-RalfIA-Webhook-Secret": "$WEBHOOK_SECRET"},
    "byEvents": False,
    "base64": False,
    "events": ["MESSAGES_UPSERT", "SEND_MESSAGE", "CONNECTION_UPDATE"]
  }
}))
PY
)
  api "$base" POST "/webhook/set/${name}" "$payload" | head -c 200 || log "  webhook set falló (¿instancia existe?)"
  echo
}

for host in "$INTEL:primary" "$AMD:amd"; do
  ip="${host%%:*}"
  base="http://${ip}:${PORT}"
  if ! curl -sf -m 5 "${base}/" >/dev/null; then
    log "SKIP unreachable $base"
    continue
  fi
  ver=$(curl -sf "${base}/" | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','?'))")
  log "=== $base version=$ver ==="
  if [[ "$ver" == 2.4.* ]] || [[ "$ver" == "2.4.0" ]]; then
    st=$(curl -sf "${base}/license/status" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo inactive)
    if [[ "$st" != "active" ]]; then
      log "  LICENSE inactive — activa en ${base}/manager/login antes de bootstrap"
      continue
    fi
  fi
done

ensure_instance "http://${INTEL}:${PORT}" "RalphiIA-pcdoctor"
ensure_webhook "http://${INTEL}:${PORT}" "RalphiIA-pcdoctor"

ensure_instance "http://${AMD}:${PORT}" "Innerchispa" "593962546650"
ensure_webhook "http://${AMD}:${PORT}" "Innerchispa"

log "Listo. Manager Intel: http://${INTEL}:${PORT}/manager  AMD: http://${AMD}:${PORT}/manager"
