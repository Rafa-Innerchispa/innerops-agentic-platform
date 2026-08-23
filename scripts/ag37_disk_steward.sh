#!/usr/bin/env bash
# AG-37 — Disk Steward run (cada timer)
set -euo pipefail
ROOT="${INNEROS_PLATFORM:-/home/rlopez/inneros/inneros_core/platform}"
PY="${ROOT}/venv/bin/python3"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
export RALPHIIA_OPENAI_ROOT="${ROOT}"
exec "${PY}" -c "
from raphiia_openai.disk_steward import run_check
import json
print(json.dumps(run_check(), indent=2, ensure_ascii=False))
"
