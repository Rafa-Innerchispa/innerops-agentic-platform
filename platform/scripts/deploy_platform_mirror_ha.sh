#!/usr/bin/env bash
# Réplica espejo AMD ↔ Intel: mismo código platform, workers Temporal en ambos nodos, MCP activo en ambos.
# Un nodo caído → el otro sigue sirviendo MCP + drenando colas Temporal compartidas.
set -euo pipefail

PLATFORM="${INNEROS_PLATFORM_ROOT:-/home/rlopez/inneros/inneros_core/platform}"
PEERS=(ralfiia-amd ralfiia-intel)
RSYNC_EXCLUDES=(
  --exclude 'venv/'
  --exclude '__pycache__/'
  --exclude '*.pyc'
  --exclude '.git/'
  --exclude 'data/'
  --exclude '.env'
)

local_host() {
  hostname -s 2>/dev/null || hostname
}

peer_for() {
  local me="$1"
  if [[ "$me" == *intel* ]]; then
    echo ralfiia-amd
  else
    echo ralfiia-intel
  fi
}

sync_to_peer() {
  local peer="$1"
  echo "== rsync platform → ${peer}:${PLATFORM}"
  rsync -az --delete "${RSYNC_EXCLUDES[@]}" "${PLATFORM}/" "${peer}:${PLATFORM}/"
}

activate_node() {
  local target="$1"
  local run_remote
  if [[ "$target" == "localhost" ]] || [[ "$target" == "$(local_host)" ]]; then
    run_remote() { bash -s <<<"$1"; }
  else
    run_remote() { ssh -o BatchMode=yes "$target" "bash -s" <<<"$1"; }
  fi

  local node_role=amd
  if [[ "$target" != "localhost" ]]; then
    node_role=intel
  fi
  echo "== activate ${target} (INNEROS_NODE_ROLE=${node_role})"
  local cmd
  cmd=$(cat <<EOF
set -euo pipefail
export INNEROS_NODE_ROLE=${node_role}
cd '${PLATFORM}'
./scripts/apply_canonical_temporal_worker.sh
systemctl --user restart ralfia-mcp-profile@chatgpt_compact.service || true
systemctl --user restart ralfia-mcp.service || true
systemctl --user is-active inneros-temporal-worker.service
systemctl --user is-active ralfia-mcp-profile@chatgpt_compact.service || systemctl --user is-active ralfia-mcp.service
EOF
)
  run_remote "$cmd"
}

install_notion_autopilot_timer() {
  local target="$1"
  local run_remote
  if [[ "$target" == "localhost" ]] || [[ "$target" == "$(local_host)" ]]; then
    run_remote() { bash -s <<<"$1"; }
  else
    run_remote() { ssh -o BatchMode=yes "$target" "bash -s" <<<"$1"; }
  fi
  local timer_cmd
  timer_cmd=$(cat <<EOF
set -euo pipefail
PLATFORM='${PLATFORM}'
U=\${XDG_CONFIG_HOME:-\$HOME/.config}/systemd/user
mkdir -p "\$U"
S="\$U/inneros-notion-coordination-autopilot.service"
T="\$U/inneros-notion-coordination-autopilot.timer"
printf '%s\n' '[Unit]' 'Description=InnerOS Notion coordination autopilot tick' '' '[Service]' 'Type=oneshot' "WorkingDirectory=\${PLATFORM}" "Environment=PYTHONPATH=\${PLATFORM}" "ExecStart=\${PLATFORM}/venv/bin/python3 \${PLATFORM}/scripts/notion_coordination_autopilot_tick.py" '' '[Install]' 'WantedBy=default.target' > "\$S"
printf '%s\n' '[Unit]' 'Description=Notion coordination autopilot every 3 minutes' '' '[Timer]' 'OnBootSec=2min' 'OnUnitActiveSec=3min' 'Persistent=true' '' '[Install]' 'WantedBy=timers.target' > "\$T"
systemctl --user daemon-reload
systemctl --user enable --now inneros-notion-coordination-autopilot.timer
systemctl --user is-active inneros-notion-coordination-autopilot.timer
EOF
)
  run_remote "$timer_cmd"
}

ME="$(local_host)"
PEER="$(peer_for "$ME")"

echo "Local: $ME  Peer: $PEER  Platform: $PLATFORM"

sync_to_peer "$PEER"

activate_node "localhost"
activate_node "$PEER"

install_notion_autopilot_timer "localhost"
install_notion_autopilot_timer "$PEER"

echo "OK mirror HA: código sincronizado y servicios canonical en AMD + Intel."
