#!/bin/bash
# Script de rollback para ROCm 10.0.0 canary

# Restaurar servicios
systemctl stop rocm10-service 2>/dev/null || true

# Eliminar directorio de instalación
rm -rf "/home/rlopez/data/rocm10-canary"

# Restaurar configuraciones
restore_configurations()
{
  # Restaurar unidades systemd
  cp /etc/systemd/system/rocm6.4.service /etc/systemd/system/rocm.service
  systemctl daemon-reload
  systemctl restart rocm.service
}

# Restaurar paquetes
apt-get install --reinstall rocm-6.4

# Restaurar symlinks
ln -sf /opt/rocm-6.4 /opt/rocm

# Reiniciar sistema
systemctl restart systemd-journald
