#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$ROOT/stop_canary_vllm.sh" || true
systemctl --user start inneros-vllm-qwen3-coder-30b-awq.service
echo RESTORE prod :8000 starting
