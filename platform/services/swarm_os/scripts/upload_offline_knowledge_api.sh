#!/usr/bin/env bash
# Sube runbook a Knowledge vía API HTTP (usa app viva + embeddings).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNBOOK="/mnt/datos_agentes/ai-server-v2/open-webui/offline-knowledge/RALFIA_OFFLINE_RUNBOOK.md"
WEBUI="${OPENWEBUI_URL:-http://127.0.0.1:3000}"
DB="/mnt/datos_agentes/ai-server-v2/open-webui/webui.db"
KB_NAME="RalfIA Offline"

[[ -f "$RUNBOOK" ]] || { echo "Falta runbook: $RUNBOOK"; exit 1; }

API_KEY="$(python3 - <<'PY'
import sqlite3
c = sqlite3.connect("/mnt/datos_agentes/ai-server-v2/open-webui/webui.db")
row = c.execute("select key from api_key order by created_at desc limit 1").fetchone()
if not row:
    raise SystemExit("No API key — habilita auth.enable_api_keys y crea una")
print(row[0])
PY
)"

AUTH=(-H "Authorization: Bearer ${API_KEY}")

KB_ID="$(python3 - <<'PY'
import sqlite3
c = sqlite3.connect("/mnt/datos_agentes/ai-server-v2/open-webui/webui.db")
row = c.execute("select id from knowledge where name='RalfIA Offline' limit 1").fetchone()
print(row[0] if row else "")
PY
)"

if [[ -z "$KB_ID" ]]; then
  KB_ID="$(curl -sf "${AUTH[@]}" -H 'Content-Type: application/json' \
    -d "{\"name\":\"${KB_NAME}\",\"description\":\"Runbook LAN sin internet\",\"access_grants\":[]}" \
    "$WEBUI/api/v1/knowledge/create" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")"
  echo "KB creada $KB_ID"
else
  echo "KB existente $KB_ID"
fi

# ¿Ya indexado?
LINKED="$(python3 - <<PY
import sqlite3
c=sqlite3.connect("$DB")
q="""select count(*) from knowledge_file kf
 join file f on f.id=kf.file_id
 where kf.knowledge_id=? and f.filename like '%RUNBOOK%'"""
print(c.execute(q,("$KB_ID",)).fetchone()[0])
PY
)"

if [[ "$LINKED" != "0" ]]; then
  echo "Runbook ya en Knowledge — OK"
else
  echo "Subiendo e indexando runbook..."
  FILE_JSON="$(curl -sf "${AUTH[@]}" \
    -F "file=@${RUNBOOK};type=text/markdown" \
    -F 'metadata={"source":"offline-runbook"}' \
    "$WEBUI/api/v1/files/?process=true&process_in_background=false")"
  FILE_ID="$(python3 -c "import json,sys; print(json.load(sys.stdin)['id'])" <<<"$FILE_JSON")"
  echo "File $FILE_ID"

  curl -sf "${AUTH[@]}" -H 'Content-Type: application/json' \
    -d "{\"file_id\":\"${FILE_ID}\"}" \
    "$WEBUI/api/v1/knowledge/${KB_ID}/file/add" >/dev/null
  echo "Adjuntado a Knowledge"
fi

python3 "$ROOT/scripts/setup_openwebui_offline_mode.py" >/dev/null 2>&1 || true
python3 - <<PY
import sqlite3, json
c=sqlite3.connect("$DB")
meta=json.loads(c.execute("select meta from model where id='ralfia-offline'").fetchone()[0] or '{}')
meta["knowledge"]=[{"id":"$KB_ID","name":"$KB_NAME"}]
c.execute("update model set meta=? where id='ralfia-offline'", (json.dumps(meta),))
c.commit()
print("Modelo ralfia-offline enlazado a Knowledge")
PY

echo "DONE Knowledge listo"
