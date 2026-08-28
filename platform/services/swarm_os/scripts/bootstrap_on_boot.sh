#!/usr/bin/env bash
# Tras reinicio: seed demo + guarda URLs públicas ngrok (InnerOS + Hackathon).
set -euo pipefail

PROJECT="/home/rlopez/projects/innerspark-swarm-os-cursor-local"
API="http://127.0.0.1:8100/api/v1"
OUT="$PROJECT/data/public_demo_url.txt"
HACK_OUT="$PROJECT/data/hackathon_public_url.txt"
LOG="$PROJECT/data/bootstrap.log"

mkdir -p "$PROJECT/data"
echo "[$(date -Iseconds)] bootstrap start" >>"$LOG"

bash "$PROJECT/scripts/ensure_mongo.sh" >>"$LOG" 2>&1 || true

for _ in $(seq 1 90); do
  if curl -sf "$API/stats" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if curl -sf "$API/stats" >/dev/null 2>&1; then
  curl -sf -X POST "$API/hackathon/seed-demo" >>"$LOG" 2>&1 || true
  echo "[$(date -Iseconds)] seed-demo done" >>"$LOG"
else
  echo "[$(date -Iseconds)] API no disponible" >>"$LOG"
fi

sleep 10

read -r INNEROS_URL HACKATHON_URL <<<"$(python3 - <<'PY' 2>/dev/null || true
import json, urllib.request
try:
    d = json.load(urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=5))
    base = ""
    for t in d.get("tunnels", []):
        u = t.get("public_url", "")
        if u.startswith("https://"):
            base = u.rstrip("/")
            break
    inneros = f"{base}/inneros" if base else ""
    hackathon = base or ""
    print(inneros, hackathon)
except Exception:
    print("", "")
PY
)"

{
  echo "updated: $(date -Iseconds)"
  echo "local_inneros: http://192.168.1.4:5173/inneros"
  echo "local_hackathon: http://192.168.1.4:5190"
  echo "local_api: http://192.168.1.4:8100/docs"
  echo "local_hackathon_api: http://192.168.1.4:8210/api/status"
  if [[ -n "$INNEROS_URL" ]]; then
    echo "ngrok_inneros: ${INNEROS_URL}"
    echo "ngrok_datacenter: ${INNEROS_URL%/inneros}/datacenter"
  else
    echo "ngrok_inneros: (pending — systemctl status swarm-ngrok)"
  fi
  if [[ -n "$HACKATHON_URL" ]]; then
    echo "ngrok_hackathon: ${HACKATHON_URL}"
    echo "ngrok_base: ${HACKATHON_URL}"
  else
    echo "ngrok_hackathon: (pending — swarm-hackathon-ui + swarm-ngrok)"
  fi
} >"$OUT"

{
  echo "updated: $(date -Iseconds)"
  if [[ -n "$HACKATHON_URL" ]]; then
    echo "public_hackathon_ui: ${HACKATHON_URL}"
  else
    echo "public_hackathon_ui: (pending)"
  fi
} >"$HACK_OUT"

echo "[$(date -Iseconds)] bootstrap end inneros=${INNEROS_URL:-none} hackathon=${HACKATHON_URL:-none}" >>"$LOG"
