#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$ROOT/stop_canary_vllm.sh" || true
bash "$ROOT/swap_vllm_ports_restore_prod.sh"
