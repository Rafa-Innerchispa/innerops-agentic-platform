#!/usr/bin/env bash
# Verificación post-reinicio — AG-31 + WhatsApp si hay problemas.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source venv/bin/activate
export PYTHONPATH="$ROOT"
python3 - <<'PY'
from raphiia_openai.recovery_agent import run_post_restart_verify

run_post_restart_verify(trigger="boot_verify")
PY
