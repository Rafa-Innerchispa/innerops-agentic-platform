#!/usr/bin/env bash
# ROCm 10 canary — prep-only SAFE installer.
# Creates isolated venv and verifies gfx1201. Does NOT touch vLLM :8000 production.
# Huge packages (torch/vllm/transformers) require explicit --install-packages;
# default mode only runs pip --dry-run when --dry-run is passed.
set -euo pipefail

CANARY_DIR="${ROCM_CANARY_DIR:-/home/rlopez/data/rocm10-canary}"
VENV_DIR="${ROCM_CANARY_VENV:-$CANARY_DIR/venv-rocm-canary}"
LOG="$CANARY_DIR/install_rocm10_canary.log"
DRY_RUN=false
INSTALL_PACKAGES=false

usage() {
  cat <<EOF
Usage: $(basename "$0") [--dry-run] [--install-packages]

  (default)   Prep only: mkdir, verify gfx1201, create venv, upgrade pip/wheel.
  --dry-run   Also run pip install --dry-run for planned ROCm 10 packages (no download).
  --install-packages
              Actually pip-install torch/vllm/transformers (explicit opt-in; large download).

Production vLLM on :8000 is never started or modified by this script.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --install-packages) INSTALL_PACKAGES=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

mkdir -p "$CANARY_DIR"
exec > >(tee -a "$LOG") 2>&1
echo "=== install_rocm10_canary start $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo "mode: dry_run=$DRY_RUN install_packages=$INSTALL_PACKAGES"

verify_gfx1201() {
  local ok=false
  local smi_out roc_out
  if [[ -x /opt/rocm/bin/rocm-smi ]]; then
    smi_out="$(/opt/rocm/bin/rocm-smi --showproductname 2>/dev/null || true)"
    if grep -qiE 'gfx1201|R9700|r9700' <<<"$smi_out"; then
      ok=true
      echo "PASS: rocm-smi reports gfx1201/R9700"
    fi
  else
    echo "WARN: /opt/rocm/bin/rocm-smi not found"
  fi
  if [[ "$ok" == false ]] && [[ -x /opt/rocm/bin/rocminfo ]]; then
    roc_out="$(/opt/rocm/bin/rocminfo 2>/dev/null || true)"
    if grep -q 'gfx1201' <<<"$roc_out"; then
      ok=true
      echo "PASS: rocminfo reports gfx1201"
    fi
  elif [[ "$ok" == false ]]; then
    echo "WARN: /opt/rocm/bin/rocminfo not found"
  fi
  if [[ "$ok" == false ]]; then
    echo "FAIL: gfx1201/R9700 not detected via rocm-smi or rocminfo"
    exit 1
  fi
}

if ss -ltnp 2>/dev/null | grep -q ':8000'; then
  echo "INFO: :8000 in use (production vLLM) — this script will NOT touch it"
fi

verify_gfx1201

if [[ ! -d "$VENV_DIR" ]]; then
  echo "Creating canary venv at $VENV_DIR"
  python3 -m venv "$VENV_DIR"
else
  echo "Canary venv already exists at $VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install -U pip wheel

AMD_ROCM10_INDEX="https://stable.repo.amd.com/rocm/whl-next/"
TORCH_SPECS=(
  "torch[device-gfx1201]==2.12.0+rocm10.0.0"
  "torchvision[device-gfx1201]==0.27.0+rocm10.0.0"
  "torchaudio==2.11.0+rocm10.0.0"
)

run_pip_dry_run() {
  echo "DRY-RUN: AMD ROCm 10 wheels (no CUDA PyPI)..."
  pip install --dry-run "${TORCH_SPECS[@]}" --index-url "$AMD_ROCM10_INDEX"
  pip install --dry-run 'transformers>=4.51'
  echo "NOTE: vLLM full model served via start_canary_vllm.sh (Docker rocm7.14 on :8001)"
}

run_pip_install() {
  echo "INSTALL: AMD ROCm 10 gfx1201 wheels + transformers..."
  pip install "${TORCH_SPECS[@]}" --index-url "$AMD_ROCM10_INDEX"
  pip install 'transformers>=4.51'
  echo "VERIFY torch hip..."
  python - <<'PY'
import torch
assert torch.version.cuda is None, f"unexpected CUDA torch: {torch.version.cuda}"
assert torch.cuda.is_available(), "GPU not visible"
print("PASS:", torch.__version__, torch.cuda.get_device_name(0), "hip", torch.version.hip)
PY
}

if [[ "$INSTALL_PACKAGES" == true ]]; then
  run_pip_install
elif [[ "$DRY_RUN" == true ]]; then
  run_pip_dry_run
else
  echo "SKIP: no huge pip installs (pass --dry-run or --install-packages to change)"
fi

cat <<EOF

=== prep complete ===
  venv:       $VENV_DIR
  log:        $LOG
  production: vLLM :8000 untouched

Manual steps remaining:
  1. Bind ROCm 10.0.0 runfile under $CANARY_DIR/rocm-10.0.0/
  2. Run validate_rocm10.sh after runfile bind
  3. Start vLLM canary on :8001 (never :8000) after validation PASS
EOF
