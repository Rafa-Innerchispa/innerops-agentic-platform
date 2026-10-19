#!/usr/bin/env bash
set -euo pipefail
WS="${INNEROS_PLATFORM_GIT:-/home/rlopez/inneros/inneros_core/workspaces/innerops-agentic-platform/platform}"
RT="${INNEROS_PLATFORM_RUNTIME:-/home/rlopez/inneros/inneros_core/platform}"
rsync -a --exclude=venv/ --exclude=var/ --exclude=.env --exclude=__pycache__/ --exclude="*.pyc" \
  "$WS/inneros_core_runtime/" "$RT/inneros_core_runtime/"
rsync -a --exclude=venv --exclude=__pycache__ "$WS/scripts/" "$RT/scripts/"
rsync -a "$WS/systemd/" "$RT/systemd/"
echo "synced git workspace platform -> runtime $RT"
