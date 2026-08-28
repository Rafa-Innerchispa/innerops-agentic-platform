#!/usr/bin/env bash
# Túnel público → Hackathon UI :5190 (proxy incluye /api y /ws → :8210)
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")" && pwd)"
PORT="${HACKATHON_BAND_PORT:-5190}"
OUT="$PROJECT/data/hackathon_public_url.txt"

if [[ -f "$PROJECT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(grep -E '^(NGROK_AUTHTOKEN|HACKATHON_BAND_PORT)=' "$PROJECT/.env" | sed 's/\r$//')
  set +a
fi

if ! command -v ngrok >/dev/null 2>&1; then
  echo "ngrok no instalado. Instala: https://ngrok.com/download" >&2
  exit 1
fi

if [[ -n "${NGROK_AUTHTOKEN:-}" ]]; then
  ngrok config add-authtoken "$NGROK_AUTHTOKEN" 2>/dev/null || true
fi

echo "Esperando UI en http://127.0.0.1:${PORT}/ ..."
for _ in $(seq 1 45); do
  if curl -sf "http://127.0.0.1:${PORT}/" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

mkdir -p "$PROJECT/data"
echo "Iniciando ngrok http ${PORT} ..."
ngrok http "$PORT" --log=stdout &
NGROK_PID=$!

sleep 4
PUBLIC=""
for _ in $(seq 1 20); do
  PUBLIC=$(curl -sf http://127.0.0.1:4040/api/tunnels 2>/dev/null | python3 -c "
import sys, json
try:
    d=json.load(sys.stdin)
    for t in d.get('tunnels',[]):
        u=t.get('public_url','')
        if u.startswith('https://'):
            print(u); break
except Exception: pass
" 2>/dev/null || true)
  [[ -n "$PUBLIC" ]] && break
  sleep 1
done

if [[ -n "$PUBLIC" ]]; then
  {
    echo "public_hackathon_ui: ${PUBLIC}"
    echo "updated: $(date -Iseconds)"
    echo "note: Share this URL with jury. Keep api_server :8210 and npm run dev :5190 running."
  } > "$OUT"
  echo ""
  echo "=== URL PÚBLICA HACKATHON ==="
  echo "$PUBLIC"
  echo "Guardada en: $OUT"
else
  echo "No se pudo leer URL de ngrok. Abre http://127.0.0.1:4040" >&2
fi

wait $NGROK_PID
