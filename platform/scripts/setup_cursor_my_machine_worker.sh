#!/usr/bin/env bash
# Install Cursor CLI (if missing) and optional systemd user unit for My Machines worker.
# Run ON the target host (Intel or AMD), not from a generic Cloud Agent VM.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLATFORM_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROLE="${INNEROS_NODE_ROLE:-intel}"
WORKER_NAME="${CURSOR_WORKER_NAME:-}"
DIRS_RAW="${CURSOR_WORKER_DIRS:-}"
INSTALL_CLI="${CURSOR_INSTALL_CLI:-1}"
INSTALL_SYSTEMD="${CURSOR_INSTALL_SYSTEMD:-1}"

if [[ -z "$WORKER_NAME" ]]; then
  if [[ "$ROLE" == "amd" ]]; then
    WORKER_NAME="inneros-amd-5"
  else
    WORKER_NAME="inneros-intel-4"
  fi
fi

if [[ -z "$DIRS_RAW" ]]; then
  if [[ "$ROLE" == "amd" ]]; then
    DIRS_RAW="$HOME/innerops-agentic-platform"
  else
    DIRS_RAW="$HOME/innerops-agentic-platform:$HOME/projects/raphiia-openai"
  fi
fi

echo "==> InnerOS Cursor worker setup: role=$ROLE name=$WORKER_NAME"
echo "    dirs=$DIRS_RAW"

if [[ "$INSTALL_CLI" == "1" ]] && ! command -v agent >/dev/null 2>&1; then
  echo "==> Installing Cursor agent CLI..."
  curl https://cursor.com/install -fsS | bash
fi

if ! command -v agent >/dev/null 2>&1; then
  echo "ERROR: 'agent' CLI not in PATH. Add ~/.local/bin to PATH or re-login."
  exit 1
fi

agent --version 2>/dev/null || true
chmod +x "$SCRIPT_DIR/inneros_cursor_worker_start.sh"

if [[ "$INSTALL_SYSTEMD" == "1" ]]; then
  UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  mkdir -p "$UNIT_DIR"
  cat >"$UNIT_DIR/cursor-inneros-worker.service" <<EOF
[Unit]
Description=Cursor My Machines worker (InnerOS $WORKER_NAME)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Restart=on-failure
RestartSec=15
Environment=CURSOR_WORKER_NAME=$WORKER_NAME
Environment=CURSOR_WORKER_DIRS=$DIRS_RAW
Environment=INNEROS_NODE_ROLE=$ROLE
ExecStart=$SCRIPT_DIR/inneros_cursor_worker_start.sh

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  echo "==> systemd user unit: $UNIT_DIR/cursor-inneros-worker.service"
fi

cat <<EOF

Next steps (once per server, account InnerChispa):
  1. agent login
     # or: export agent worker start --api-key-file ~/.config/cursor/agent-api-key
  2. Test foreground:
       export CURSOR_WORKER_NAME=$WORKER_NAME
       export CURSOR_WORKER_DIRS='$DIRS_RAW'
       $SCRIPT_DIR/inneros_cursor_worker_start.sh
  3. Background (optional):
       loginctl enable-linger \$(whoami)
       systemctl --user enable --now cursor-inneros-worker.service
  4. Phone: cursor.com/agents → My Machines → $WORKER_NAME
  5. agent worker debug

EOF