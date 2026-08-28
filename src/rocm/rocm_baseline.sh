#!/bin/bash
# Captura baseline del sistema para ROCm 10 canary

# Directorio de trabajo
dir="/home/rlopez/data/rocm10-canary"

# Crear directorio de trabajo
mkdir -p "$dir"

# Información del sistema
uname -a > "$dir/baseline_uname.txt"
lsb_release -a > "$dir/baseline_lsb_release.txt"

# Driver amdgpu
modinfo amdgpu > "$dir/baseline_amdgpu_modinfo.txt"

# ROCm info
rocm-smi --showall > "$dir/baseline_rocm_smi.txt"
rocminfo > "$dir/baseline_rocminfo.txt"

# Versiones de software
python --version > "$dir/baseline_python_version.txt"
torch.__version__ 2>&1 | grep -o "[0-9]\+\.[0-9]\+\.[0-9]\+" > "$dir/baseline_torch_version.txt"
vLLM --version > "$dir/baseline_vllm_version.txt"
transformers --version > "$dir/baseline_transformers_version.txt"

# Configuración de systemd
systemctl list-units --type=service | grep -i rocm > "$dir/baseline_systemd_services.txt"

# Variables de entorno
env | grep -i rocm > "$dir/baseline_env_vars.txt"

# VRAM y benchmark
rocm-smi --showmeminfo > "$dir/baseline_vram_info.txt"

# Modelo actual
ls -la /home/rlopez/data/models/qwen3-coder* > "$dir/baseline_model_refs.txt"

# Benchmark actual
python -c "import time; start = time.time(); print(f'benchmark_start: {start}')"
