#!/usr/bin/env bash
# Install InnerOS coordination systemd user units from git and enable timers.
# Run after: git fetch && git reset --hard origin/main && scripts/sync_platform_runtime_from_git.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$DEST"

UNITS=(
  inneros-ha-liveness.service
  inneros-ha-liveness.timer
  inneros-cursor-headless-autopilot.service
  inneros-cursor-headless-autopilot.timer
  inneros-interactive-provider-autopilot.service
  inneros-interactive-provider-autopilot.timer
  inneros-cursor-inbox-consumer.service
  inneros-cursor-inbox-consumer.timer
  inneros-ag25-project-cycle.service
  inneros-ag25-project-cycle.timer
  ralfia-external-repair-agent.service
)

for u in "${UNITS[@]}"; do
  src="$ROOT/systemd/user/$u"
  if [[ ! -f "$src" ]]; then
    echo "missing unit in git: $src" >&2
    exit 1
  fi
  install -m 0644 "$src" "$DEST/$u"
  echo "installed $DEST/$u"
done

systemctl --user daemon-reload

TIMERS=(
  inneros-ha-liveness.timer
  inneros-cursor-headless-autopilot.timer
  inneros-interactive-provider-autopilot.timer
  inneros-cursor-inbox-consumer.timer
)

# Dev Swarm AG-25 cycle: primary on AMD; optional on Intel via INNEROS_ENABLE_AG25_TIMER=1
if [[ "${INNEROS_ENABLE_AG25_TIMER:-auto}" == "1" ]]; then
  TIMERS+=(inneros-ag25-project-cycle.timer)
elif [[ "${INNEROS_ENABLE_AG25_TIMER:-auto}" == "0" ]]; then
  :
elif hostname | grep -qi amd; then
  TIMERS+=(inneros-ag25-project-cycle.timer)
fi

for t in "${TIMERS[@]}"; do
  systemctl --user enable --now "$t"
  systemctl --user restart "$t" 2>/dev/null || true
  echo "enabled $t"
done

if systemctl --user cat ralfia-external-repair-agent.service >/dev/null 2>&1; then
  systemctl --user enable --now ralfia-external-repair-agent.service || true
  systemctl --user restart ralfia-external-repair-agent.service || true
  echo "enabled ralfia-external-repair-agent.service"
fi

systemctl --user list-timers "${TIMERS[@]}" --no-pager || true
echo "coordination timers installed from $ROOT"
