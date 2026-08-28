#!/usr/bin/env bash
# AG-39 Atlas — hidratación local catálogo Contifico (AMD .5, 0 créditos cloud)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"
export OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
LOG="${LOG:-/home/rlopez/data/logs/atlas_hydrator.log}"
mkdir -p "$(dirname "$LOG")"
echo "[$(date -Iseconds)] AG-39 Atlas starting" | tee -a "$LOG"
exec "$ROOT/venv/bin/python3" -c "
from raphiia_openai.local_catalog_hydrator import run_local_hydration
import json
r = run_local_hydration(resume=True, ollama_reports=True)
print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
" 2>&1 | tee -a "$LOG"
