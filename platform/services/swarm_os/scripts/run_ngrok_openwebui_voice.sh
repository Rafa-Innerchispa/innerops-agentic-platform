#!/usr/bin/env bash
# Ngrok directo → Open WebUI :3000 (HTTPS para micrófono / voz).
# Usar cuando quieras hablar con Ollama desde el móvil. Restaura gateway con run_ngrok_all.sh después.
set -euo pipefail
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_CFG="$PROJECT/data/ngrok.openwebui.yml"
NGROK_AUTHTOKEN="$(grep -E '^\s*authtoken:' "$PROJECT/data/ngrok.runtime.yml" | awk '{print $2}' | tr -d '"')"

cat >"$RUNTIME_CFG" <<EOF
version: "2"
authtoken: ${NGROK_AUTHTOKEN}
tunnels:
  voice:
    addr: 3000
    proto: http
EOF

echo "=== Modo VOZ — ngrok → Open WebUI :3000 ==="
echo "Detén el ngrok actual (Ctrl+C en su terminal) y ejecuta:"
echo "  ngrok start voice --config $RUNTIME_CFG"
echo ""
echo "URL típica: https://TU-DOMINIO.ngrok-free.dev  (click Visit Site)"
echo "Micrófono requiere HTTPS — no funciona en http://192.168.1.4:3000 desde el móvil."
echo ""
echo "Para volver al gateway hackathon:"
echo "  bash $PROJECT/run_ngrok_all.sh"
