#!/bin/bash
set -euo pipefail
# Captura baseline del sistema para ROCm 10 canary (producción :8000 intacta)

dir="/home/rlopez/data/rocm10-canary"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="${dir}/baseline_${stamp}"
mkdir -p "$out" "$dir"

uname -a >"$out/uname.txt"
(lsb_release -a 2>/dev/null || true) >"$out/lsb_release.txt"
(modinfo amdgpu 2>/dev/null || true) >"$out/amdgpu_modinfo.txt"

if command -v /opt/rocm/bin/rocm-smi >/dev/null 2>&1; then
  /opt/rocm/bin/rocm-smi --showproductname >"$out/rocm_smi_product.txt" 2>&1 || true
  /opt/rocm/bin/rocm-smi --showmeminfo vram >"$out/rocm_smi_vram.txt" 2>&1 || true
fi
if command -v /opt/rocm/bin/rocminfo >/dev/null 2>&1; then
  /opt/rocm/bin/rocminfo >"$out/rocminfo.txt" 2>&1 || true
fi

python3 --version >"$out/python_version.txt" 2>&1 || true
(pip list 2>/dev/null | rg -i 'torch|vllm|transformers' || true) >"$out/pip_packages.txt"
(systemctl list-units --type=service --no-pager 2>/dev/null | rg -i 'vllm|rocm|qwen' || true) >"$out/systemd_services.txt"
(env | rg -i 'rocm|hip|vllm|cuda' || true) >"$out/env_vars.txt"
(curl -sS -m 3 http://127.0.0.1:8000/v1/models || true) >"$out/vllm_8000_models.json"

ln -sfn "$out" "${dir}/latest"
echo "Baseline guardada en $out"
