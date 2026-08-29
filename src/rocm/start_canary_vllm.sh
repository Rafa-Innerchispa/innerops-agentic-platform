#!/usr/bin/env bash
set -euo pipefail
CANARY_DIR="${ROCM_CANARY_DIR:-/home/rlopez/data/rocm10-canary}"
PORT="${VLLM_CANARY_PORT:-8001}"
IMAGE="${VLLM_CANARY_IMAGE:-rocm/vllm:rocm7.14.0_rdna_ubuntu24.04_py3.14_pytorch_2.11.0_vllm_0.23.0}"
MODEL="${VLLM_CANARY_MODEL:-/models/QuantTrio__Qwen3-Coder-30B-A3B-Instruct-AWQ}"
SERVED="${VLLM_CANARY_SERVED_NAME:-QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ}"
MODELS="${VLLM_MODELS_DIR:-/home/rlopez/inneros/inneros_core/var/local_models}"
NAME="inneros-vllm-canary-rocm10"
LOG="$CANARY_DIR/vllm_canary_${PORT}.log"
mkdir -p "$CANARY_DIR" "$MODELS/_logs"
if ss -ltnp 2>/dev/null | grep -q ":${PORT} "; then echo "INFO: :${PORT} up"; curl -sf "http://127.0.0.1:${PORT}/v1/models" | head -c 200; exit 0; fi
docker rm -f "$NAME" 2>/dev/null || true
nohup docker run --rm --name "$NAME" --device=/dev/kfd --device=/dev/dri --group-add video --ipc=host --network host \
  -v "$MODELS:/models" "$IMAGE" python3 -m vllm.entrypoints.openai.api_server \
  --model "$MODEL" --served-model-name "$SERVED" --host 127.0.0.1 --port "$PORT" \
  --max-model-len 8192 --gpu-memory-utilization 0.82 --dtype float16 --trust-remote-code >>"$LOG" 2>&1 &
echo $! >"$CANARY_DIR/vllm_canary_${PORT}.pid"
echo "STARTED vLLM canary :${PORT} log=$LOG"
