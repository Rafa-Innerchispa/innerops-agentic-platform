#!/usr/bin/env bash
# Túnel ngrok único → gateway :5188 (InnerOS /inneros + Hackathon /)
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")" && pwd)"
GATEWAY_PORT="${PUBLIC_GATEWAY_PORT:-5188}"
INNEROS_PORT="${ADMIN_PORT:-5173}"
HACKATHON_PORT="${HACKATHON_BAND_PORT:-5190}"
RUNTIME_CFG="$PROJECT/data/ngrok.runtime.yml"

# Authtoken persistente en .env (sobrevive actualizaciones snap ngrok)
if [[ -x "/home/rlopez/projects/raphiia-openai/scripts/sync_ngrok_authtoken.sh" ]]; then
  /home/rlopez/projects/raphiia-openai/scripts/sync_ngrok_authtoken.sh 2>/dev/null || true
fi

if [[ -f "$PROJECT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(grep -v '^\s*#' "$PROJECT/.env" | sed 's/\r$//')
  set +a
fi

_resolve_ngrok_authtoken() {
  if [[ -n "${NGROK_AUTHTOKEN:-}" ]]; then
    return 0
  fi
  local cfg
  for cfg in \
    "$PROJECT/data/ngrok.runtime.yml" \
    /home/rlopez/snap/ngrok/*/.config/ngrok/ngrok.yml \
    "$HOME/.config/ngrok/ngrok.yml"; do
    if [[ -f "$cfg" ]]; then
      NGROK_AUTHTOKEN=$(grep -E '^\s*authtoken:' "$cfg" 2>/dev/null | head -1 | awk '{print $2}' | tr -d '"'"'" || true)
      [[ -n "${NGROK_AUTHTOKEN:-}" ]] && return 0
    fi
  done
  return 1
}

if ! command -v ngrok >/dev/null 2>&1; then
  echo "ngrok no instalado" >&2
  exit 1
fi

if ! _resolve_ngrok_authtoken; then
  echo "Falta NGROK_AUTHTOKEN — ejecuta scripts/sync_ngrok_authtoken.sh" >&2
  exit 1
fi

# Si ya hay túnel activo (p. ej. otro proceso ngrok), NO hacer exit 0:
# Type=simple + Restart=always interpreta exit 0 como muerte → bucle cada RestartSec.
# En su lugar vigilamos el API y salimos con error solo si el túnel desaparece.
_check_existing_tunnel() {
  local api port
  for port in 4040 4041; do
    api=$(curl -sf "http://127.0.0.1:${port}/api/tunnels" 2>/dev/null || true)
    if [[ -n "$api" ]] && echo "$api" | grep -q 'public_url'; then
      echo "ngrok ya activo (API :${port}) — vigilando (no exit) para systemd Type=simple"
      while true; do
        api=$(curl -sf "http://127.0.0.1:${port}/api/tunnels" 2>/dev/null || true)
        if [[ -z "$api" ]] || ! echo "$api" | grep -q 'public_url'; then
          echo "túnel perdido en :${port} — saliendo para que systemd reinicie" >&2
          exit 1
        fi
        sleep 30
      done
    fi
  done
}
_check_existing_tunnel

mkdir -p "$PROJECT/data"

echo "Esperando InnerOS :${INNEROS_PORT}, Hackathon :${HACKATHON_PORT}..."
for _ in $(seq 1 60); do
  ok=0
  curl -sf "http://127.0.0.1:${INNEROS_PORT}/" >/dev/null 2>&1 && ok=$((ok + 1))
  curl -sf "http://127.0.0.1:${HACKATHON_PORT}/" >/dev/null 2>&1 && ok=$((ok + 1))
  [[ "$ok" -ge 2 ]] && break
  sleep 2
done

if ! curl -sf "http://127.0.0.1:${GATEWAY_PORT}/" >/dev/null 2>&1; then
  echo "Arrancando gateway público :${GATEWAY_PORT}..."
  nohup bash "$PROJECT/run_public_gateway.sh" >>"$PROJECT/data/public_gateway.log" 2>&1 &
  for _ in $(seq 1 30); do
    curl -sf "http://127.0.0.1:${GATEWAY_PORT}/" >/dev/null 2>&1 && break
    sleep 1
  done
fi

cat >"$RUNTIME_CFG" <<EOF
version: "2"
authtoken: ${NGROK_AUTHTOKEN}
tunnels:
  public:
    addr: ${GATEWAY_PORT}
    proto: http
EOF

exec ngrok start public --config "$RUNTIME_CFG" --log=stdout
