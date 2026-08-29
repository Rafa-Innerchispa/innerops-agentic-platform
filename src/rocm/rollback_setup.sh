#!/bin/bash
# Script para preparar rollback de ROCm

# Directorio de backup
backup_dir="/home/rlopez/data/rocm-rollback-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup_dir"

# Copiar unidades systemd
if [ -d "/etc/systemd/system" ]; then
  cp -r "/etc/systemd/system"/* "$backup_dir/systemd-units" 2>/dev/null || true
fi

# Copiar variables de entorno
if [ -f "/etc/environment" ]; then
  cp "/etc/environment" "$backup_dir/environment"
fi

# Copiar configuraciones de ROCm
if [ -d "/opt/rocm" ]; then
  cp -r "/opt/rocm" "$backup_dir/opt-rocm"
fi

# Registrar paquetes
pip freeze > "$backup_dir/pip-freeze.txt"

# Registrar estado actual
rocminfo > "$backup_dir/rocminfo-before.txt" 2>/dev/null || true
rocm-smi --showall > "$backup_dir/rocm-smi-before.txt" 2>/dev/null || true

# Mostrar instrucciones
echo "Backup creado en $backup_dir"
echo "Para restaurar:"
echo "  sudo cp -r $backup_dir/opt-rocm/* /opt/rocm/"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl restart <servicio>"
