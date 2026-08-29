#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
failures=0
step(){ echo "=== $1 ==="; if eval "$2"; then echo "PASS: $1"; else echo "FAIL: $1" >&2; failures=$((failures+1)); fi; }
step validate bash "$ROOT/validate_rocm10.sh"
step smoke bash "$ROOT/smoke_vllm_docker.sh"
if curl -sf -o /dev/null --connect-timeout 3 http://127.0.0.1:8001/v1/models; then echo "PASS: vllm_8001"; else echo "WARN: vllm_8001 not ready yet"; fi
export ROCM_PATH="${ROCM10_INSTALL:-/home/rlopez/data/rocm10-canary/rocm-10-install/rocm/core-10.0}"
export PATH="$ROCM_PATH/bin:$PATH"
export LD_LIBRARY_PATH="$ROCM_PATH/lib:$ROCM_PATH/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
step torch "/home/rlopez/data/rocm10-canary/venv-rocm-canary/bin/python -c \"import torch; x=torch.randn(256,256,device='cuda',dtype=torch.float16); torch.cuda.synchronize(); print(float((x@x)[0,0]))\""
[[ $failures -eq 0 ]] && echo STACK_PASS || { echo STACK_FAIL; exit 1; }
