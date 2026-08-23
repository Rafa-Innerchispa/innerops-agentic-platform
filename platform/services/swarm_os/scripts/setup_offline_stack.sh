#!/usr/bin/env bash
# Stack offline completo: runbook + Open Terminal + preset Open WebUI
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$ROOT/scripts/build_offline_runbook.py"
bash "$ROOT/scripts/setup_open_terminal.sh"
python3 "$ROOT/scripts/tune_openwebui_copilot.py"
python3 "$ROOT/scripts/upload_offline_knowledge_http.py" 2>/dev/null || true

echo ""
echo "=== Modo offline listo ==="
echo "1. Open WebUI → http://192.168.1.4:3000"
echo "2. Modelo: RalfIA Offline (local)"
echo "3. Admin → Knowledge → subir:"
echo "   /mnt/datos_agentes/ai-server-v2/open-webui/offline-knowledge/RALFIA_OFFLINE_RUNBOOK.md"
echo "4. Nuevo chat → + → Integrations → MCP + Open Terminal"
echo "5. Memoria: Settings → Personalization → añade hechos clave (ver docs/OPENWEBUI_OFFLINE_MODE.md)"
