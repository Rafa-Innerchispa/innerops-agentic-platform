#!/bin/bash
# Test de baseline ROCm

# Ejecutar script de baseline
bash src/rocm/rocm_baseline.sh

# Verificar resultados
echo "Verificando archivos de salida..."
if [ -d "/home/rlopez/data/rocm-baseline-*" ]; then
  echo "✓ Baseline capturada correctamente"
  ls -la /home/rlopez/data/rocm-baseline-*/
else
  echo "✗ Error al capturar baseline"
  exit 1
fi

echo "Test de baseline completado"
