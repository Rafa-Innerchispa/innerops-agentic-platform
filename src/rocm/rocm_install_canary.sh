#!/bin/bash
# Instala ROCm 10.0.0 en paralelo sin afectar producción

# Directorio de instalación
dir="/home/rlopez/data/rocm10-canary"

# Verificar compatibilidad
if ! grep -q "gfx1201" /proc/cpuinfo; then
  echo "Error: Arquitectura no compatible con ROCm 10.0.0"
  exit 1
fi

# Descargar e instalar ROCm 10.0.0
wget https://repo.radeon.com/amdgpu/10.0/ubuntu/focal/pool/main/r/rocm/rocm-10.0.0.tar.xz -O "$dir/rocm-10.0.0.tar.xz"
tar -xf "$dir/rocm-10.0.0.tar.xz" -C "$dir"

# Crear entorno virtual
python3 -m venv "$dir/venv-rocm10"
source "$dir/venv-rocm10/bin/activate"

# Instalar paquetes
pip install torch==2.4.0+rocm5.7 --index-url https://download.pytorch.org/whl/rocm5.7
pip install vLLM==0.5.0
pip install transformers

# Configurar variables de entorno
export ROCM_PATH="$dir"
export LD_LIBRARY_PATH="$dir/lib:$LD_LIBRARY_PATH"

# Levantar servicio de prueba en puerto 8001
nohup python -m vllm.entrypoints.api_server --host 0.0.0.0 --port 8001 --model qwen3-coder > "$dir/vllm_service.log" 2>&1 &
