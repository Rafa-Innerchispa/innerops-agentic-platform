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
if [[ -x /opt/rocm/bin/rocm-smi ]]; then
  if /opt/rocm/bin/rocm-smi --showproductname 2>/dev/null | grep -qiE 'gfx1201|R9700|r9700'; then
    gfx_ok=true
    echo "PASS: rocm-smi reports gfx1201/R9700"
  else
    echo "WARN: rocm-smi did not match gfx1201/R9700"
    /opt/rocm/bin/rocm-smi --showproductname 2>&1 || true
  fi
else
  echo "WARN: /opt/rocm/bin/rocm-smi not found"
fi

if [[ "$gfx_ok" == false ]] && [[ -x /opt/rocm/bin/rocminfo ]]; then
  if /opt/rocm/bin/rocminfo 2>/dev/null | grep -q 'gfx1201'; then
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

if ss -ltnp 2>/dev/null | grep -q ':8000'; then
  echo "INFO: :8000 listener present (production) — validation did not start or stop it"
fi

echo "PASS: validate_rocm10 complete (no vLLM start attempted)"
