#!/usr/bin/env bash
set -euo pipefail

ROOT="${RALFIA_ROOT:-/home/rlopez/projects/raphiia-openai}"
PROFILE="${1:-quoteops}"
PORT="${2:-8110}"
MODE="${3:---plan}"
UNIT_SOURCE="$ROOT/deploy/systemd/ralfia-mcp-profile@.service"
UNIT_TARGET="$HOME/.config/systemd/user/ralfia-mcp-profile@.service"
ENV_DIR="$HOME/.config/ralphiia/mcp-profiles"
ENV_TARGET="$ENV_DIR/$PROFILE.env"

if [[ ! "$PROFILE" =~ ^[a-z0-9_]+$ ]]; then
  echo "Invalid profile name: $PROFILE" >&2
  exit 2
fi
if [[ ! "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1024 || PORT > 65535 )); then
  echo "Invalid profile port: $PORT" >&2
  exit 2
fi
if [[ ! -f "$UNIT_SOURCE" ]]; then
  echo "Missing unit template: $UNIT_SOURCE" >&2
  exit 1
fi

(
  cd "$ROOT"
  PYTHONPATH="$ROOT" "$ROOT/venv/bin/python" -c \
    "from raphiia_openai.mcp_profiles import get_profile; p=get_profile('$PROFILE'); assert p.get('ok'), p"
)

echo "Profile: $PROFILE"
echo "Port: $PORT"
echo "Unit: $UNIT_TARGET"
echo "Environment: $ENV_TARGET"
if [[ "$MODE" == "--plan" ]]; then
  exit 0
fi
if [[ "$MODE" != "--apply" ]]; then
  echo "Apply requires third argument --apply" >&2
  exit 2
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$HOME/backups/raphiia-openai/mcp-profile-$PROFILE-$timestamp"
mkdir -p "$backup" "$(dirname "$UNIT_TARGET")" "$ENV_DIR"
[[ -f "$UNIT_TARGET" ]] && cp -p "$UNIT_TARGET" "$backup/" || true
[[ -f "$ENV_TARGET" ]] && cp -p "$ENV_TARGET" "$backup/" || true

install -m 0644 "$UNIT_SOURCE" "$UNIT_TARGET"
{
  printf 'MCP_TOOL_PROFILE=%s\n' "$PROFILE"
  printf 'MCP_PORT=%s\n' "$PORT"
  printf 'MCP_DISPLAY_NAME=RalfIA MCP - %s\n' "$PROFILE"
} > "$ENV_TARGET"
chmod 0600 "$ENV_TARGET"

systemctl --user daemon-reload
systemctl --user enable --now "ralfia-mcp-profile@$PROFILE.service"
systemctl --user is-active --quiet "ralfia-mcp-profile@$PROFILE.service"

for _ in $(seq 1 30); do
  status="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/mcp" || true)"
  if [[ "$status" == "200" || "$status" == "401" || "$status" == "406" ]]; then
    echo "Profile service PASS: $PROFILE on port $PORT (HTTP $status)"
    echo "Backup: $backup"
    exit 0
  fi
  sleep 1
done

echo "Profile service did not become ready: $PROFILE on port $PORT" >&2
exit 1
