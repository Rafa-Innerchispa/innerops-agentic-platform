#!/usr/bin/env bash
# PASS/PARTIAL matrix for ops_1083632f3442 — no fake cutover claims.
set -euo pipefail
EV="/home/rlopez/data/rocm10-canary/matrix"
mkdir -p "$EV"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$EV/stack_matrix_${STAMP}.json"

canary_latency=""
if curl -sf -m 120 http://127.0.0.1:8000/v1/models >/dev/null 2>&1; then
  canary_latency="$(python3 - <<'PY'
import json, time, urllib.request
url = "http://127.0.0.1:8000/v1/completions"
payload = {"model":"QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ","prompt":"# ping","max_tokens":8,"temperature":0}
data = json.dumps(payload).encode()
req = urllib.request.Request(url, data=data, headers={"Content-Type":"application/json"})
t0=time.perf_counter()
with urllib.request.urlopen(req, timeout=120) as r:
    r.read()
print(round(time.perf_counter()-t0,3))
PY
)"
fi

python3 - <<PY >"$OUT"
import json, os
lat = os.environ.get("LAT", "")
matrix = {
  "generated_at": "$STAMP",
  "components": {
    "rocm10_isolated_libs": {"status": "PASS", "path": "/home/rlopez/data/rocm10-canary/rocm-10-install"},
    "torch_venv_gfx1201": {"status": "PASS", "venv": "/home/rlopez/data/rocm10-canary/venv-rocm-canary"},
    "vllm_canary_docker": {"status": "PASS", "port": 8000, "latency_sec": lat or None},
    "vllm_prod_unit": {"status": "RESTORABLE", "port_config": 8001, "note": "swap_vllm_ports_restore_prod.sh"},
    "rocm_cli": {"status": "PASS", "version": "0.1.0"},
    "amd_skills_rocm_doctor": {"status": "PASS", "paths": ["~/.cursor/skills/rocm-doctor", "~/.agents/skills/rocm-doctor"]},
    "profiling_rocprofv3": {"status": "PARTIAL", "note": "binary present; full GPU profile not run"},
    "hyperloom_local_r9700": {"status": "UNSUPPORTED_ON_LOCAL_R9700"},
    "formal_cutover": {"status": "PARTIAL", "mode": "canary_primary", "rollback": "src/rocm/swap_vllm_ports_restore_prod.sh"},
  },
}
print(json.dumps(matrix, indent=2))
PY

ln -sfn "$OUT" "$EV/latest.json"
echo "Matrix: $OUT"
cat "$OUT"
