#!/bin/bash
# Instalación y validación de herramientas de profiling de ROCm 10.0.0

# Directorio de instalación
dir="/home/rlopez/data/rocm10-canary"

# Instalar herramientas de profiling
apt-get update
apt-get install -y rocprofiler-sdk rocprofv3

# Validar instalación
rocprofv3 --help > "$dir/profiling_help.txt"
rocprofiler-sdk --version > "$dir/rocprofiler_version.txt"

# Ejecutar benchmark de profiling
rocprofv3 --output "$dir/profile_output.txt" --target "vLLM" --duration 30s
