#!/usr/bin/env bash
# Open Terminal — shell real para Open WebUI (crear carpetas, scripts, etc.)
set -euo pipefail

NAME="${OPEN_TERMINAL_CONTAINER:-open-terminal}"
PORT="${OPEN_TERMINAL_PORT:-8010}"
IMAGE="${OPEN_TERMINAL_IMAGE:-ghcr.io/open-webui/open-terminal}"
DATA="/home/rlopez/data/open-terminal"
KEY_FILE="$DATA/.api_key"
ENV_FILE="$DATA/open-terminal.env"

mkdir -p "$DATA"
if [[ ! -f "$KEY_FILE" ]]; then
  openssl rand -hex 24 > "$KEY_FILE"
  chmod 600 "$KEY_FILE"
fi
API_KEY="$(tr -d '\n' < "$KEY_FILE")"
printf 'OPEN_TERMINAL_API_KEY=%s\n' "$API_KEY" > "$ENV_FILE"
chmod 600 "$ENV_FILE"

echo "Pull $IMAGE ..."
docker pull "$IMAGE"

docker stop "$NAME" 2>/dev/null || true
docker rm "$NAME" 2>/dev/null || true

# Montajes: proyectos + datos Rafael (offline ops en LAN)
docker run -d \
  --name "$NAME" \
  --restart unless-stopped \
  -p "${PORT}:8000" \
  -v "$DATA/home:/home/user" \
  -v /home/rlopez/projects:/home/rlopez/projects \
  -v /home/rlopez/data:/home/rlopez/data \
  -e "OPEN_TERMINAL_API_KEY=${API_KEY}" \
  -e OPEN_TERMINAL_MULTI_USER=true \
  "$IMAGE"

sleep 4
curl -sf "http://127.0.0.1:${PORT}/health" | head -c 200
echo ""
echo "Open Terminal: http://192.168.1.4:${PORT}"
echo "Conectar en Open WebUI → Integrations → Open Terminal"
echo "  URL (desde contenedor open-webui): http://host.docker.internal:${PORT}"
