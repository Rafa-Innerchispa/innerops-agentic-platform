#!/usr/bin/env bash
# Reinicia stack hackathon (API :8210 + UI :5190) leyendo .env actual — Evolution incluido.
set -euo pipefail
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT"
chmod +x run_hackathon_api.sh run_hackathon_ui.sh

echo "Reiniciando hackathon API :8210..."
fuser -k 8210/tcp 2>/dev/null || true
sleep 1
nohup bash "$PROJECT/run_hackathon_api.sh" >>"$PROJECT/data/hackathon_api.log" 2>&1 &

echo "Reiniciando hackathon UI :5190..."
fuser -k 5190/tcp 2>/dev/null || true
sleep 1
nohup bash "$PROJECT/run_hackathon_ui.sh" >>"$PROJECT/data/hackathon_ui.log" 2>&1 &

for _ in $(seq 1 30); do
  curl -sf "http://127.0.0.1:8210/api/status" >/dev/null 2>&1 && break
  sleep 2
done

echo ""
echo "Estado:"
curl -sf "http://127.0.0.1:8210/api/status" | python3 -c "
import json,sys
d=json.load(sys.stdin)
evo=d.get('evolution',{})
print('  Evolution:', 'OK' if evo.get('configured') else 'FALTA EVOLUTION_API_KEY')
print('  Instancia:', evo.get('instance'))
print('  WhatsApp hackathon:', evo.get('hackathon_notify_to') or '(añade HACKATHON_WHATSAPP_TO en .env)')
" 2>/dev/null || echo "  API aún arrancando — ver data/hackathon_api.log"
