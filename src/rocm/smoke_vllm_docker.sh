#!/usr/bin/env bash
set -euo pipefail
IMAGE="${VLLM_CANARY_IMAGE:-rocm/vllm:rocm7.14.0_rdna_ubuntu24.04_py3.14_pytorch_2.11.0_vllm_0.23.0}"
LOG="${ROCM_CANARY_DIR:-/home/rlopez/data/rocm10-canary}/smoke_vllm_docker.log"
{ echo "=== smoke_vllm_docker $(date -u +%Y-%m-%dT%H:%M:%SZ) image=$IMAGE";
  docker run --rm --name rocm-canary-vllm-smoke --device=/dev/kfd --device=/dev/dri --group-add video --ipc=host "$IMAGE" \
    python3 -c "import torch,vllm; print('vllm',vllm.__version__); print('torch',torch.__version__); print('gpu',torch.cuda.get_device_name(0)); x=torch.randn(64,64,device='cuda'); print('ok',float((x@x)[0,0]))";
  echo PASS; } 2>&1 | tee -a "$LOG"
