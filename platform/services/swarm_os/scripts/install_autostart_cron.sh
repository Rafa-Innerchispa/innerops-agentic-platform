#!/usr/bin/env bash
# Registra arranque automático en crontab (sin sudo) — InnerOS + Hackathon + ngrok dual.
set -euo pipefail

PROJECT="/home/rlopez/projects/innerspark-swarm-os-cursor-local"
MARKER="# inneros-autostart"
REBOOT_LINE="@reboot sleep 60 && $PROJECT/scripts/start_on_boot.sh"
WATCH_LINE="*/10 * * * * $PROJECT/scripts/ensure_stack_running.sh >>$PROJECT/data/ensure_stack.log 2>&1"

chmod +x "$PROJECT/scripts/start_on_boot.sh"
chmod +x "$PROJECT/scripts/ensure_stack_running.sh"
chmod +x "$PROJECT/scripts/bootstrap_on_boot.sh"
chmod +x "$PROJECT/run_ngrok.sh" "$PROJECT/run_ngrok_all.sh"
chmod +x "$PROJECT/run_hackathon_api.sh" "$PROJECT/run_hackathon_ui.sh"
chmod +x "$PROJECT/run_public_gateway.sh"

(crontab -l 2>/dev/null | grep -v "$MARKER" | grep -v "start_on_boot.sh" | grep -v "ensure_stack_running.sh"; \
  echo "$MARKER"; echo "$REBOOT_LINE"; echo "$WATCH_LINE") | crontab -

echo "Crontab @reboot instalado (InnerOS + Hackathon + ngrok dual)."
echo "Tras reinicio:"
echo "  cat $PROJECT/data/public_demo_url.txt"
echo "  cat $PROJECT/data/hackathon_public_url.txt"
echo ""
echo "Para systemd completo (recomendado, requiere sudo una vez):"
echo "  bash $PROJECT/scripts/install_services.sh"
