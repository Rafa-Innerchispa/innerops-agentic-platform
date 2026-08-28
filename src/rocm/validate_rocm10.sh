#!/bin/bash
# Validación de instalación ROCm 10.0.0

# Activar venv
venv_dir="/home/rlopez/data/rocm10-canary/venv"
source "$venv_dir/bin/activate"

# Verificar dispositivo GPU
if python3 -c "import torch; print('GPU detectada:', torch.cuda.is_available()); print('Nombre:', torch.cuda.get_device_name(0))"; then
  echo "GPU ROCm 10.0.0 detectada correctamente"
else
  echo "Error al detectar GPU"
  exit 1
fi

# Verificar vLLM
if python3 -c "import vllm; print('vLLM versión:', vllm.__version__)"; then
  echo "vLLM instalado correctamente"
else
  echo "Error al instalar vLLM"
  exit 1
fi

# Verificar modelos
if python3 -c "from transformers import AutoModel; print('Transformers OK')"; then
  echo "Transformers instalado correctamente"
else
  echo "Error al instalar Transformers"
  exit 1
fi

echo "Validación ROCm 10.0.0 completada"
