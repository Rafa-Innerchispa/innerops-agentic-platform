#!/usr/bin/env bash
# Genera todos los JSON de evidencia hackathon (Intel orquesta + SSH AMD benchmark).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EV="$ROOT/../var/evidence"
PY="${ROOT}/venv/bin/python3"
export PYTHONPATH="$ROOT"

mkdir -p "$EV"
TS="$(date -u +%Y%m%dT%H%M%SZ)"

echo "== AMD inference benchmark =="
ssh -o BatchMode=yes "rlopez@${PARADE_SSH_AMD:-192.168.1.5}" \
  "cd $ROOT && PYTHONPATH=. venv/bin/python3 scripts/hackathon_amd_inference_benchmark.py" \
  | tee "$EV/hackathon_benchmark_run_${TS}.log"

echo "== Router Intel =="
"$PY" - <<'PY' | tee "$EV/hackathon_router_intel.json"
import json, time
from inneros_core_runtime import local_model_router as lmr
from inneros_core_runtime import dev_swarm_scheduler as ds
t0 = time.perf_counter()
r = lmr.route_ai_task("hackathon_github", "Responde solo: ROUTER_OK", task_type="coding")
out = {
    "latency_s": round(time.perf_counter() - t0, 4),
    "route": {k: r.get(k) for k in ("ok", "backend", "selected_node", "local_model", "runtime", "decision")},
    "capacity": ds.capacity_status().get("recommendation"),
}
print(json.dumps(out, indent=2))
PY

echo "== Cross-smoke (opcional, export AUTO)=1) =="
if [[ "${RUN_CROSS_SMOKE:-1}" == "1" ]]; then
  export INNEROS_COORD_AUTO_OWNER_APPROVE=1 NOTIFY_OPS_CREATE_AUTH=0
  "$PY" scripts/coordination_cross_smoke_v2.py | tee "$EV/hackathon_cross_smoke_${TS}.log" || true
fi

echo "== Bundle summary =="
"$PY" scripts/hackathon_write_github_summary.py

echo "Done. See $EV/hackathon_github_summary.json and CHATGPT_HANDOFF_HACKATHON.md"
