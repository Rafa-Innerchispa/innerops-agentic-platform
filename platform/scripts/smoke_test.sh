#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source venv/bin/activate 2>/dev/null || { python3 -m venv venv && source venv/bin/activate && pip install -q -r requirements.txt; }
[[ -f .env ]] || cp .env.example .env

PORT="$(grep -E '^RAPHI_IA_OPENAI_PORT=' .env 2>/dev/null | cut -d= -f2 || echo 8101)"
echo "== health FastAPI :${PORT} =="
curl -sf "http://127.0.0.1:${PORT}/api/v1/health" | python3 -m json.tool || echo "(FastAPI no arrancado ? ejecuta ./run.sh)"

echo "== mongo ping =="
python3 - <<'PY'
from raphiia_openai.mongo_store import ping_mongo
import json
print(json.dumps(ping_mongo(), indent=2, ensure_ascii=False))
PY

echo "== MCP tools smoke (in-process) =="
python3 - <<'PY'
from raphiia_openai import mongo_store
idea = mongo_store.save_idea(title="Smoke test RaphiIA MCP", body="Prueba autom?tica bridge ChatGPT")
results = mongo_store.search("Smoke test RaphiIA")
fetched = mongo_store.fetch(results[0]["id"]) if results else {"ok": False}
print("idea_id:", idea.get("_id"))
print("search_hits:", len(results))
print("fetch_ok:", fetched.get("ok"))
PY

echo "OK smoke_test"
