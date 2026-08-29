#!/usr/bin/env bash
set -euo pipefail
EV="/home/rlopez/data/rocm10-canary/profiling"
mkdir -p "$EV"
python3 - <<'PY' > "$EV/inference_benchmark.json"
import json, time, statistics, urllib.request
url = "http://127.0.0.1:8000/v1/completions"
payload = {"model":"QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ","prompt":"def add(a,b): return a+b","max_tokens":32,"temperature":0}
data = json.dumps(payload).encode()
lat=[]
for _ in range(5):
    t0=time.perf_counter()
    with urllib.request.urlopen(urllib.request.Request(url,data=data,headers={"Content-Type":"application/json"}),timeout=120) as r:
        r.read()
    lat.append(time.perf_counter()-t0)
print(json.dumps({"samples":len(lat),"latency_sec_mean":round(statistics.mean(lat),3),"latency_sec_min":round(min(lat),3),"latency_sec_max":round(max(lat),3)},indent=2))
PY
echo "Evidence: $EV/inference_benchmark.json"
