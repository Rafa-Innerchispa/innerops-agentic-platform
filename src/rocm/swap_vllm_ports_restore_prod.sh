#!/usr/bin/env bash
# Restore prod vLLM on :8000; stop canary; revert systemd from :8001 backup.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CANARY_DIR="${ROCM_CANARY_DIR:-/home/rlopez/data/rocm10-canary}"
STATE="$CANARY_DIR/vllm_port_mode"
PROD_UNIT="${HOME}/.config/systemd/user/inneros-vllm-qwen3-coder-30b-awq.service"
PROD_UNIT_BAK="$CANARY_DIR/inneros-vllm-qwen3-coder-30b-awq.service.bak"

echo "=== restore prod :8000, stop canary ==="

bash "$ROOT/stop_canary_vllm.sh" || true
docker stop inneros-vllm-canary-rocm10 2>/dev/null || true

if [[ -f "$PROD_UNIT_BAK" ]]; then
  cp -a "$PROD_UNIT_BAK" "$PROD_UNIT"
  systemctl --user daemon-reload
  echo "INFO: prod systemd restored to :8000"
fi

systemctl --user start inneros-vllm-qwen3-coder-30b-awq.service
echo "prod_primary" >"$STATE"

for i in $(seq 1 40); do
  if curl -sf -o /dev/null --connect-timeout 2 http://127.0.0.1:8000/v1/models; then
    echo "PASS: prod on :8000"
    exit 0
  fi
  sleep 15
done
echo "WARN: prod :8000 not ready — check service log" >&2
exit 1
