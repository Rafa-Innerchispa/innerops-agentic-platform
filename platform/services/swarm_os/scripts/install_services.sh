#!/usr/bin/env bash
# Instala unidades systemd — todo arranca solo tras apagón/reinicio.
set -euo pipefail

PROJECT="/home/rlopez/projects/innerspark-swarm-os-cursor-local"
USER_NAME="rlopez"

chmod +x "${PROJECT}/run_portal.sh" "${PROJECT}/run_api.sh" "${PROJECT}/run_admin.sh"
chmod +x "${PROJECT}/run_ngrok.sh" "${PROJECT}/run_ngrok_all.sh"
chmod +x "${PROJECT}/run_hackathon_api.sh" "${PROJECT}/run_hackathon_ui.sh"
chmod +x "${PROJECT}/run_public_gateway.sh"
chmod +x "${PROJECT}/scripts/ensure_mongo.sh" "${PROJECT}/scripts/bootstrap_on_boot.sh"

sudo tee /etc/systemd/system/swarm-api.service >/dev/null <<EOF
[Unit]
Description=Swarm-OS API (PC Doctor FastAPI)
After=network-online.target docker.service
Wants=network-online.target docker.service

[Service]
Type=simple
User=${USER_NAME}
Group=${USER_NAME}
WorkingDirectory=${PROJECT}
ExecStartPre=${PROJECT}/scripts/ensure_mongo.sh
ExecStart=/usr/bin/bash ${PROJECT}/run_api.sh
Restart=always
RestartSec=5
Environment=API_PORT=8100

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/swarm-admin.service >/dev/null <<EOF
[Unit]
Description=PC Doctor Admin (Refine React + InnerOS)
After=network-online.target swarm-api.service
Wants=network-online.target

[Service]
Type=simple
User=${USER_NAME}
Group=${USER_NAME}
WorkingDirectory=${PROJECT}
ExecStart=/usr/bin/bash ${PROJECT}/run_admin.sh
Restart=always
RestartSec=10
TimeoutStartSec=300
Environment=ADMIN_PORT=5173

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/swarm-hackathon-api.service >/dev/null <<EOF
[Unit]
Description=Hackathon Band API (FastAPI :8200)
After=network-online.target swarm-api.service
Wants=network-online.target

[Service]
Type=simple
User=${USER_NAME}
Group=${USER_NAME}
WorkingDirectory=${PROJECT}
ExecStart=/usr/bin/bash ${PROJECT}/run_hackathon_api.sh
Restart=always
RestartSec=8
TimeoutStartSec=120
Environment=HACKATHON_API_PORT=8200

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/swarm-hackathon-ui.service >/dev/null <<EOF
[Unit]
Description=Hackathon Band UI (React :5190)
After=network-online.target swarm-hackathon-api.service
Wants=network-online.target

[Service]
Type=simple
User=${USER_NAME}
Group=${USER_NAME}
WorkingDirectory=${PROJECT}
ExecStart=/usr/bin/bash ${PROJECT}/run_hackathon_ui.sh
Restart=always
RestartSec=10
TimeoutStartSec=300
Environment=HACKATHON_BAND_PORT=5190

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/swarm-public-gateway.service >/dev/null <<EOF
[Unit]
Description=Public gateway :5188 — InnerOS + Hackathon tras un ngrok
After=network-online.target swarm-admin.service swarm-hackathon-ui.service
Wants=network-online.target

[Service]
Type=simple
User=${USER_NAME}
Group=${USER_NAME}
WorkingDirectory=${PROJECT}
ExecStart=/usr/bin/bash ${PROJECT}/run_public_gateway.sh
Restart=always
RestartSec=8
Environment=PUBLIC_GATEWAY_PORT=5188

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/swarm-ngrok.service >/dev/null <<EOF
[Unit]
Description=ngrok → gateway :5188 (InnerOS /inneros + Hackathon /)
After=network-online.target swarm-public-gateway.service
Wants=network-online.target

[Service]
Type=simple
User=${USER_NAME}
Group=${USER_NAME}
WorkingDirectory=${PROJECT}
ExecStart=/usr/bin/bash ${PROJECT}/run_ngrok_all.sh
Restart=always
RestartSec=20
TimeoutStartSec=180
Environment=PUBLIC_GATEWAY_PORT=5188
Environment=ADMIN_PORT=5173
Environment=HACKATHON_BAND_PORT=5190

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/swarm-bootstrap.service >/dev/null <<EOF
[Unit]
Description=Bootstrap — seed demo + URLs públicas InnerOS y Hackathon
After=swarm-api.service swarm-ngrok.service swarm-hackathon-ui.service
Wants=swarm-api.service swarm-hackathon-api.service

[Service]
Type=oneshot
User=${USER_NAME}
Group=${USER_NAME}
WorkingDirectory=${PROJECT}
ExecStart=/usr/bin/bash ${PROJECT}/scripts/bootstrap_on_boot.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/ralf-portal.service >/dev/null <<EOF
[Unit]
Description=RALF IA v2.0 Portal de acceso
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${USER_NAME}
Group=${USER_NAME}
WorkingDirectory=${PROJECT}
ExecStart=/usr/bin/bash ${PROJECT}/run_portal.sh
Restart=always
RestartSec=5
Environment=PORTAL_PORT=8800

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/filebrowser.service >/dev/null <<EOF
[Unit]
Description=FileBrowser gestor de archivos web
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/docker compose -f ${PROJECT}/docker/filebrowser-compose.yml up -d
ExecStop=/usr/bin/docker compose -f ${PROJECT}/docker/filebrowser-compose.yml down
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable \
  swarm-api.service \
  swarm-admin.service \
  swarm-hackathon-api.service \
  swarm-hackathon-ui.service \
  swarm-public-gateway.service \
  swarm-ngrok.service \
  swarm-bootstrap.service \
  ralf-portal.service \
  filebrowser.service

sudo systemctl restart swarm-api.service
sudo systemctl restart swarm-admin.service
sudo systemctl restart swarm-hackathon-api.service || true
sudo systemctl restart swarm-hackathon-ui.service || true
sudo systemctl restart swarm-public-gateway.service || true
sudo systemctl restart swarm-ngrok.service || true
sudo systemctl start swarm-bootstrap.service || true
sudo systemctl restart ralf-portal.service filebrowser.service || true

echo ""
echo "=== Arranque automático configurado ==="
echo "Tras reinicio, todo sube solo:"
echo "  swarm-api            → :8100 (InnerOS + Evolution WhatsApp)"
echo "  swarm-admin          → :5173 InnerOS"
echo "  swarm-hackathon-api  → :8200 Band pipeline"
echo "  swarm-hackathon-ui   → :5190 Dashboard jurado"
echo "  swarm-public-gateway → :5188 (InnerOS /inneros + Hackathon /)"
echo "  swarm-ngrok          → 1 URL ngrok → gateway (plan free compatible)"
echo "  swarm-bootstrap      → data/public_demo_url.txt + hackathon_public_url.txt"
echo ""
echo "URLs públicas:"
echo "  cat ${PROJECT}/data/public_demo_url.txt"
echo "  cat ${PROJECT}/data/hackathon_public_url.txt"
echo ""
echo "Estado:"
systemctl is-active swarm-api swarm-admin swarm-hackathon-api swarm-hackathon-ui swarm-ngrok 2>/dev/null || true
