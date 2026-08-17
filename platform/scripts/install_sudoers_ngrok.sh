#!/usr/bin/env bash
# Permite a rlopez reiniciar swarm-ngrok sin contraseña (AG-31 auto-recovery).
# Ejecutar UNA VEZ con sudo: sudo bash scripts/install_sudoers_ngrok.sh
set -euo pipefail
FILE="/etc/sudoers.d/ralfia-ngrok-restart"
cat >"$FILE" <<'EOF'
# RalfIA AG-31 — reinicio ngrok tras corte de luz (sin contraseña)
rlopez ALL=(root) NOPASSWD: /usr/bin/systemctl restart swarm-ngrok.service
rlopez ALL=(root) NOPASSWD: /usr/bin/systemctl restart swarm-public-gateway.service
EOF
chmod 440 "$FILE"
visudo -cf "$FILE"
echo "OK $FILE — prueba: sudo systemctl restart swarm-ngrok.service"
