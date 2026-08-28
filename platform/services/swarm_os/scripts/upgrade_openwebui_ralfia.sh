#!/usr/bin/env bash
# Actualiza imagen Open WebUI y recrea contenedor con MCP RalfIA en env + volumen.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="/mnt/datos_agentes/ai-server-v2/open-webui"
IMAGE="${OPENWEBUI_IMAGE:-ghcr.io/open-webui/open-webui:main}"
NAME="${OPENWEBUI_CONTAINER:-open-webui}"
OLD="${OPENWEBUI_OLD_CONTAINER:-open-webui_before_codex_20260518}"

python3 "$ROOT/scripts/configure_openwebui_ralfia_mcp.py"
python3 "$ROOT/scripts/tune_openwebui_copilot.py"

CONN_FILE="$DATA/tool_server_connections.json"
ENV_FILE="$DATA/openwebui.env"
[[ -f "$CONN_FILE" ]] || { echo "Falta $CONN_FILE — ejecuta configure primero"; exit 1; }
[[ -f "$ENV_FILE" ]] || { echo "Falta $ENV_FILE"; exit 1; }

TOOL_JSON="$(tr -d '\n' < "$CONN_FILE")"

echo "Pull $IMAGE ..."
docker pull "$IMAGE"

docker stop "$OLD" 2>/dev/null || true
docker stop "$NAME" 2>/dev/null || true
docker rm "$OLD" 2>/dev/null || true
docker rm "$NAME" 2>/dev/null || true

docker run -d \
  --name "$NAME" \
  --restart unless-stopped \
  -p 3000:8080 \
  --add-host=host.docker.internal:host-gateway \
  -v "$DATA:/app/backend/data" \
  --env-file "$ENV_FILE" \
  -e "TOOL_SERVER_CONNECTIONS=$TOOL_JSON" \
  -e "ENABLE_PERSISTENT_CONFIG=true" \
  "$IMAGE"

sleep 8
curl -sf http://127.0.0.1:3000/api/config | python3 -c "import json,sys; d=json.load(sys.stdin); print('Open WebUI', d.get('version'))"
echo ""
echo "Listo: http://192.168.1.4:3000"
echo "Admin (rafagye@gmail.com) → Panel Admin → Settings → External Tools"
