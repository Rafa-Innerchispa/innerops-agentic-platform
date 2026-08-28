#!/usr/bin/env bash
# ROCm 10 canary aislado — NO cutover :8000 productivo.
set -euo pipefail

dir="${ROCM_CANARY_DIR:-/home/rlopez/data/rocm10-canary}"
log="$dir/install_canary.log"
mkdir -p "$dir"

exec > >(tee -a "$log") 2>&1
echo "=== rocm_install_canary start $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

if ! rocm-smi --showproductname 2>/dev/null | grep -qiE 'gfx1201|R9700'; then
  if ! rocminfo 2>/dev/null | grep -q 'gfx1201'; then
    echo "FAIL: gfx1201/R9700 not detected"
    exit 1
  fi
fi

if ss -ltnp 2>/dev/null | grep -q ':8001'; then
  echo "WARN: :8001 already in use; skip vllm canary start"
  exit 0
fi

venv="$dir/venv-rocm-canary"
if [[ ! -d "$venv" ]]; then
  python3 -m venv "$venv"
fi
# shellcheck disable=SC1091
source "$venv/bin/activate"
pip install -U pip wheel >/dev/null

echo "Canary venv ready at $venv"
echo "Production :8000 untouched."
echo "Next: bind ROCm 10 runfile under $dir/rocm-10.0.0/ then start vLLM :8001 after validation."
