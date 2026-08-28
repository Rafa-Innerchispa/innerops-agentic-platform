#!/usr/bin/env bash
# Test de baseline ROCm canary (no toca :8000 productivo)
set -euo pipefail

CANARY_DIR="${ROCM_CANARY_DIR:-/home/rlopez/data/rocm10-canary}"

bash src/rocm/rocm_baseline.sh

echo "Verificando archivos de salida..."
latest="$CANARY_DIR/latest"
if [[ -L "$latest" ]] && [[ -d "$latest" ]]; then
  echo "✓ Baseline capturada correctamente en $latest"
  ls -la "$latest"
else
  echo "✗ Error: symlink latest no apunta a baseline válida en $CANARY_DIR"
  exit 1
fi

echo "Test de baseline completado"
