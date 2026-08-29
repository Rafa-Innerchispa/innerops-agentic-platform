#!/usr/bin/env bash
# Canary vLLM on :8000 (InnerOS default); prod unit repointed to :8001 for rollback.
# Only one model fits in 32GB VRAM — prod stays stopped until restore script.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CANARY_DIR="${ROCM_CANARY_DIR:-/home/rlopez/data/rocm10-canary}"
STATE="$CANARY_DIR/vllm_port_mode"
PROD_UNIT="${HOME}/.config/systemd/user/inneros-vllm-qwen3-coder-30b-awq.service"
PROD_UNIT_BAK="$CANARY_DIR/inneros-vllm-qwen3-coder-30b-awq.service.bak"

mkdir -p "$CANARY_DIR"

echo "=== swap canary -> :8000, prod config -> :8001 ==="

systemctl --user stop inneros-vllm-qwen3-coder-30b-awq.service 2>/dev/null || true
docker stop inneros-vllm-canary-rocm10 2>/dev/null || true
docker rm -f inneros-vllm-canary-rocm10 2>/dev/null || true
sleep 2

if [[ -f "$PROD_UNIT" && ! -f "$PROD_UNIT_BAK" ]]; then
  cp -a "$PROD_UNIT" "$PROD_UNIT_BAK"
fi
if [[ -f "$PROD_UNIT" ]]; then
  sed -i 's/--port 8000/--port 8001/g' "$PROD_UNIT"
  systemctl --user daemon-reload
  echo "INFO: prod systemd now targets :8001 (stopped)"
fi

VLLM_CANARY_PORT=8000 bash "$ROOT/start_canary_vllm.sh"

echo "canary_primary" >"$STATE"
echo "Waiting for :8000..."
for i in $(seq 1 40); do
  if curl -sf -o /dev/null --connect-timeout 2 http://127.0.0.1:8000/v1/models; then
    echo "PASS: canary on :8000"
    curl -sf http://127.0.0.1:8000/v1/models | head -c 200
    echo
    exit 0
  fi
  sleep 15
done
echo "WARN: :8000 not ready yet — check $CANARY_DIR/vllm_canary_8000.log" >&2
exit 1
