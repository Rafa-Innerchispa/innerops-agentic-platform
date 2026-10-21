#!/usr/bin/env bash
# ==============================================================================
# install_ralfia_scout_timers.sh — Idempotent installer for RalfIA Scout Timers
# InnerOS / RalfIA Fleet Systemd User Units
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_SRC="/home/rlopez/inneros/inneros_core/platform/systemd/user"
USER_SYSTEMD_DIR="${HOME}/.config/systemd/user"

echo "[*] Initializing RalfIA Scout Timers on $(hostname) ($(whoami))..."

mkdir -p "${USER_SYSTEMD_DIR}"

# 1. Target Scout Timers (Canonical 8 P0 Scouts)
SCOUT_TIMERS=(
  "ralfia-hackathon-scan.timer"
  "ralfia-funding-credits-scan.timer"
  "ralfia-backlog-steward.timer"
  "ralfia-agent-activity-report.timer"
  "ralfia-service-guardian.timer"
  "ralfia-deferred-tasks.timer"
  "ralfia-daily-companion.timer"
  "ralfia-memory-curator-drive.timer"
)

# Optional ecosystem timers if present
OPTIONAL_TIMERS=(
  "ralfia-disk-steward.timer"
  "ralfia-capacity-governor.timer"
  "ralf-astro-editorial-sync.timer"
)

# 2. Sync Unit Files from source repository
echo "[*] Syncing unit files from ${SYSTEMD_SRC} to ${USER_SYSTEMD_DIR}..."
for timer in "${SCOUT_TIMERS[@]}"; do
  service="${timer%.timer}.service"
  
  if [ -f "${SYSTEMD_SRC}/${service}" ]; then
    cp -f "${SYSTEMD_SRC}/${service}" "${USER_SYSTEMD_DIR}/"
  fi
  if [ -f "${SYSTEMD_SRC}/${timer}" ]; then
    cp -f "${SYSTEMD_SRC}/${timer}" "${USER_SYSTEMD_DIR}/"
  fi
done

# 3. Reload systemd daemon
echo "[*] Reloading systemd user daemon..."
systemctl --user daemon-reload

# 4. Enable and start timers
echo "[*] Enabling and activating scout timers..."
for timer in "${SCOUT_TIMERS[@]}"; do
  if [ -f "${USER_SYSTEMD_DIR}/${timer}" ]; then
    echo "  --> Activating ${timer}..."
    systemctl --user enable "${timer}"
    systemctl --user restart "${timer}"
  else
    echo "  [!] Warning: ${timer} not found in ${USER_SYSTEMD_DIR}"
  fi
done

for timer in "${OPTIONAL_TIMERS[@]}"; do
  if [ -f "${USER_SYSTEMD_DIR}/${timer}" ]; then
    echo "  --> Activating optional ${timer}..."
    systemctl --user enable "${timer}" 2>/dev/null || true
    systemctl --user restart "${timer}" 2>/dev/null || true
  fi
done

echo ""
echo "[*] Verification — Active Scout Timers on $(hostname):"
systemctl --user list-timers --all | grep -E "ralfia-|ralf-" || true

echo ""
echo "[+] RalfIA Scout Timers successfully installed and active on $(hostname)."
