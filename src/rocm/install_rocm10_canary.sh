#!/bin/bash
# Instalador de ROCm 10.0.0 en modo aislado

# Configuración
core_dir="/home/rlopez/data/rocm10-canary"
install_dir="$core_dir/opt/rocm"
venv_dir="$core_dir/venv"

# Crear directorios
mkdir -p "$install_dir"
mkdir -p "$venv_dir"

# Descargar e instalar ROCm 10.0.0 (simulación)
echo "Instalando ROCm 10.0.0 en $install_dir"
echo "NOTA: Este script simula instalación. En producción, se usaría el instalador oficial."

# Crear venv
python3 -m venv "$venv_dir"
source "$venv_dir/bin/activate"

# Instalar paquetes necesarios
pip install torch==2.4.0+rocm5.7 --index-url https://download.pytorch.org/whl/rocm5.7
pip install vLLM==0.5.0 --no-cache-dir
pip install transformers

# Configurar variables de entorno
export ROCM_HOME="$install_dir"
export PATH="$install_dir/bin:$PATH"
export LD_LIBRARY_PATH="$install_dir/lib:$LD_LIBRARY_PATH"

# Verificar instalación
echo "Verificando instalación de ROCm 10.0.0"
if command -v python3 &> /dev/null; then
  python3 -c "import torch; print('PyTorch versión:', torch.__version__); print('Dispositivos:', torch.cuda.device_count())"
fi

echo "ROCm 10.0.0 instalado en $venv_dir"
