#!/usr/bin/env bash
# Réplica espejo AMD ↔ Intel: mismo código platform, workers Temporal en ambos nodos, MCP activo en ambos.
# Roles: AMD = GPU + AG-60; Intel = Mongo + cola intel-ops. Cursor headless HA: ambos nodos, 2 carriles/nodo (ampliable).
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
  local me
  me="$(local_host)"
  if [[ "$target" != "localhost" ]] && [[ "$target" != "$me" ]]; then
    node_role=intel
  elif [[ "$me" == *intel* ]]; then
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

install_cursor_headless_autopilot_timer() {
  local target="$1"
  local node_role="$2"
  local machine_name="$3"
  local run_remote
  if [[ "$target" == "localhost" ]] || [[ "$target" == "$(local_host)" ]]; then
    run_remote() { bash -s <<<"$1"; }
  else
    run_remote() { ssh -o BatchMode=yes "$target" "bash -s" <<<"$1"; }
  fi
  local timer_cmd
  timer_cmd=$(cat <<EOF
set -euo pipefail
U=\${XDG_CONFIG_HOME:-\$HOME/.config}/systemd/user
mkdir -p "\$U"
S="\$U/inneros-cursor-headless-autopilot.service"
T="\$U/inneros-cursor-headless-autopilot.timer"
cp -f '${PLATFORM}/systemd/user/inneros-cursor-headless-autopilot.timer' "\$T"
cat > "\$S" <<UNIT
[Unit]
Description=InnerOS Cursor HA headless autopilot (${node_role})
ConditionPathExists=${PLATFORM}/scripts/cursor_ops_headless_autopilot.py

[Service]
Type=oneshot
WorkingDirectory=${PLATFORM}
Environment=PYTHONPATH=${PLATFORM}
Environment=INNEROS_NODE_ROLE=${node_role}
Environment=INNEROS_CURSOR_MACHINE_NAME=${machine_name}
Environment=INNEROS_CURSOR_HA_DUAL=1
Environment=INNEROS_CURSOR_MAX_CONCURRENT=2
Environment=INNEROS_CURSOR_MAX_CONCURRENT_CEILING=8
Environment=INNEROS_CURSOR_AUTO_CLAIM=1
Environment=INNEROS_CURSOR_HEADLESS_EXECUTE=1
Environment=INNEROS_CURSOR_DISPATCH_MODE=auto
EnvironmentFile=-${PLATFORM}/.env
ExecStart=${PLATFORM}/venv/bin/python3 ${PLATFORM}/scripts/cursor_ops_headless_autopilot.py
TimeoutStartSec=180
UNIT
systemctl --user daemon-reload
systemctl --user enable --now inneros-cursor-headless-autopilot.timer
systemctl --user is-active inneros-cursor-headless-autopilot.timer
EOF
)
  echo "== cursor HA autopilot on ${target} role=${node_role} machine=${machine_name}"
  run_remote "$timer_cmd"
}

install_notion_autopilot_timer() {
  if [[ "${INNEROS_INSTALL_NOTION_AUTOPILOT:-0}" != "1" ]]; then
    echo "== skip Notion autopilot (set INNEROS_INSTALL_NOTION_AUTOPILOT=1 to enable)"
    return 0
  fi
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

LOCAL_ROLE=amd
[[ "$ME" == *intel* ]] && LOCAL_ROLE=intel
PEER_ROLE=intel
[[ "$LOCAL_ROLE" == intel ]] && PEER_ROLE=amd

activate_node "localhost"
activate_node "$PEER"

install_cursor_headless_autopilot_timer "localhost" "$LOCAL_ROLE" "$ME"
install_cursor_headless_autopilot_timer "$PEER" "$PEER_ROLE" "$PEER"

install_notion_autopilot_timer "localhost"
install_notion_autopilot_timer "$PEER"

echo "OK mirror HA: código sincronizado y servicios canonical en AMD + Intel."
