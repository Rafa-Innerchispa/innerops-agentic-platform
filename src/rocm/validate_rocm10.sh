#!/usr/bin/env bash
# Validate ROCm 10 canary prep — venv + gfx1201 only.
# Does NOT start vLLM on :8000 (or any port).
set -euo pipefail

CANARY_DIR="${ROCM_CANARY_DIR:-/home/rlopez/data/rocm10-canary}"
VENV_DIR="${ROCM_CANARY_VENV:-$CANARY_DIR/venv-rocm-canary}"

echo "=== validate_rocm10 start $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

if [[ ! -d "$VENV_DIR" ]]; then
  echo "FAIL: canary venv missing at $VENV_DIR"
  echo "Run: src/rocm/install_rocm10_canary.sh"
  exit 1
fi
echo "PASS: canary venv exists at $VENV_DIR"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "FAIL: venv python not executable at $VENV_DIR/bin/python"
  exit 1
fi
echo "PASS: venv python executable"

gfx_ok=false
smi_out=""
roc_out=""
if [[ -x /opt/rocm/bin/rocm-smi ]]; then
  smi_out="$(/opt/rocm/bin/rocm-smi --showproductname 2>/dev/null || true)"
  if grep -qiE 'gfx1201|R9700|r9700' <<<"$smi_out"; then
    gfx_ok=true
    echo "PASS: rocm-smi reports gfx1201/R9700"
  else
    echo "WARN: rocm-smi did not match gfx1201/R9700"
    printf '%s\n' "$smi_out"
  fi
else
  echo "WARN: /opt/rocm/bin/rocm-smi not found"
fi

if [[ "$gfx_ok" == false ]] && [[ -x /opt/rocm/bin/rocminfo ]]; then
  roc_out="$(/opt/rocm/bin/rocminfo 2>/dev/null || true)"
  if grep -q 'gfx1201' <<<"$roc_out"; then
    gfx_ok=true
    echo "PASS: rocminfo reports gfx1201"
  else
    echo "WARN: rocminfo did not match gfx1201"
  fi
fi

if [[ "$gfx_ok" == false ]]; then
  echo "FAIL: gfx1201 not verified via rocm-smi or rocminfo"
  exit 1
fi

ROCM10_INSTALL="${ROCM10_INSTALL:-$CANARY_DIR/rocm-10-install/rocm/core-10.0}"
if [[ -x "$ROCM10_INSTALL/bin/rocminfo" ]]; then
  export ROCM_PATH="$ROCM10_INSTALL"
  export PATH="$ROCM10_INSTALL/bin:$PATH"
  export LD_LIBRARY_PATH="$ROCM10_INSTALL/lib:$ROCM10_INSTALL/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  canary_roc="$( "$ROCM10_INSTALL/bin/rocminfo" 2>/dev/null | head -5 || true)"
  if grep -qi 'HSA System Attributes' <<<"$canary_roc"; then
    echo "PASS: canary ROCm 10 rocminfo at $ROCM10_INSTALL"
  else
    echo "WARN: canary rocminfo did not report HSA attributes"
  fi
  if [[ -x "$ROCM10_INSTALL/bin/rocm-smi" ]]; then
    if "$ROCM10_INSTALL/bin/rocm-smi" --showproductname 2>/dev/null | grep -qiE 'R9700|gfx1201'; then
      echo "PASS: canary rocm-smi sees R9700/gfx1201"
    fi
  fi
else
  echo "INFO: canary ROCm 10 install not bound yet ($ROCM10_INSTALL); run manual_install_rocm10.sh"
fi

if ss -ltnp 2>/dev/null | grep -q ':8000'; then
  echo "INFO: :8000 listener present (production) — validation did not start or stop it"
fi

echo "PASS: validate_rocm10 complete (no vLLM start attempted)"
