#!/usr/bin/env bash
# Deprecated wrapper — use install_amd_skills.sh (official AMD catalog).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$ROOT/install_amd_skills.sh"
