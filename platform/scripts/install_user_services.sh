#!/usr/bin/env bash
# Instala servicios systemd USER de Ralphi IA (sin sudo) — 24/7 tras reboot + linger.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DST="${HOME}/.config/systemd/user"
mkdir -p "$DST"
chmod +x "$ROOT/scripts/free_port.sh" "$ROOT/run_ops.sh" "$ROOT/scripts/ralfia_boot_verify.sh" 2>/dev/null || true

for unit in ralfia-portal ralfia-app ralfia-mcp ralfia-boot-verify ralfia-voice-gateway; do
  cp "$ROOT/systemd/user/${unit}.service" "$DST/"
done
CANON_VOICE="${HOME}/.config/systemd/user/ralfia-voice-gateway.service"
CANON_DIR="/home/rlopez/data/ralfia/ecosystem/canonical/systemd/user"
if [[ -f "$ROOT/systemd/user/ralfia-voice-gateway.service" ]]; then
  mkdir -p "$CANON_DIR"
  cp "$ROOT/systemd/user/ralfia-voice-gateway.service" "$CANON_DIR/"
fi
AMD_ROUTER="/home/rlopez/projects/ralfiia-amd-standby/scripts/install_ollama_router.sh"
if [[ -x "$AMD_ROUTER" ]] && [[ "$(hostname -I 2>/dev/null)" == *"192.168.1.5"* ]]; then
  bash "$AMD_ROUTER" || true
fi
if [[ -f "$ROOT/scripts/install_notify_timer.sh" ]]; then
  bash "$ROOT/scripts/install_notify_timer.sh"
fi

# AG-25 + editorial (coordination repo)
COORD="/home/rlopez/data/ai_coordination"
if [[ -f "$COORD/systemd/user/ralfia-coordination-daemon.service" ]]; then
  cp "$COORD/systemd/user/ralfia-coordination-daemon.service" "$DST/"
fi
if [[ -f "$COORD/systemd/user/ralfia-editorial-worker.service" ]]; then
  cp "$COORD/systemd/user/ralfia-editorial-worker.service" "$DST/"
fi

systemctl --user daemon-reload
python3 "$ROOT/scripts/ralphia_project_create.py" --ensure-baseline 2>/dev/null || true
loginctl enable-linger "${USER}" 2>/dev/null || true

for unit in ralfia-coordination-daemon ralfia-app ralfia-mcp ralfia-portal ralfia-editorial-worker ralfia-boot-verify ralfia-voice-gateway; do
  if systemctl --user cat "${unit}.service" &>/dev/null; then
    systemctl --user enable "${unit}.service"
  fi
done

echo "OK — servicios user habilitados. Arrancar: systemctl --user start ralfia-app ralfia-mcp ralfia-portal"
echo "Estado:   systemctl --user status ralfia-app ralfia-mcp ralfia-portal ralfia-coordination-daemon"
