#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="${INNEROS_WORKSPACE:-/home/rlopez/inneros/inneros_core/workspaces/innerops-agentic-platform}"
RUNTIME="${INNEROS_RUNTIME:-/home/rlopez/inneros/inneros_core/platform}"
PYTHON_BIN="${INNEROS_PYTHON:-$RUNTIME/venv/bin/python3}"
AMD_HOST="${INNEROS_AMD_HOST:-rlopez@192.168.1.5}"
PUBLIC_HOST="infralens.creatorcore.ai"
PUBLIC_URL="https://$PUBLIC_HOST/"
UI_ORIGIN="http://192.168.1.5:18501"
UI_HEALTH="$UI_ORIGIN/_stcore/health"
OCR_HEALTH="http://127.0.0.1:18765/health"
EXPECTED_IMAGE="sha256:dbfcaf89fc2d47823406c1ceeefef464a98a7e4328226511ab1625c3d721868f"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_ROOT="/home/rlopez/inneros/inneros_core/var/recovery/infralens-publication-$STAMP"

FILES=(
  "platform/inneros_core_runtime/coordination_live.py"
  "platform/inneros_core_runtime/agents/ag44_cloud_deployer.py"
  "platform/inneros_core_runtime/mcp_server.py"
)

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
die() { log "ERROR: $*"; exit 1; }

[[ -d "$WORKSPACE/.git" ]] || die "workspace is not a git checkout: $WORKSPACE"
[[ -x "$PYTHON_BIN" ]] || die "runtime python missing: $PYTHON_BIN"
command -v git >/dev/null || die "git missing"
command -v curl >/dev/null || die "curl missing"
command -v systemctl >/dev/null || die "systemctl missing"
command -v ssh >/dev/null || die "ssh missing"

mkdir -p "$BACKUP_ROOT"

restore_runtime() {
  log "Restoring runtime files from $BACKUP_ROOT"
  local rel dst bak
  for rel in "${FILES[@]}"; do
    dst="$RUNTIME/${rel#platform/}"
    bak="$BACKUP_ROOT/${rel#platform/}"
    if [[ -f "$bak" ]]; then
      install -D -m 0644 "$bak" "$dst"
    fi
  done
  systemctl --user restart ralfia-mcp || true
}

log "Refreshing canonical main without changing the workspace checkout"
git -C "$WORKSPACE" fetch --prune origin main
SOURCE_SHA="$(git -C "$WORKSPACE" rev-parse origin/main)"
log "Source SHA: $SOURCE_SHA"

for rel in "${FILES[@]}"; do
  dst="$RUNTIME/${rel#platform/}"
  bak="$BACKUP_ROOT/${rel#platform/}"
  tmp="$(mktemp)"
  [[ -f "$dst" ]] || { rm -f "$tmp"; die "runtime file missing: $dst"; }
  install -D -m 0644 "$dst" "$bak"
  git -C "$WORKSPACE" show "$SOURCE_SHA:$rel" > "$tmp"
  install -m 0644 "$tmp" "$dst"
  rm -f "$tmp"
done

log "Compiling patched runtime modules"
if ! "$PYTHON_BIN" -m py_compile   "$RUNTIME/inneros_core_runtime/coordination_live.py"   "$RUNTIME/inneros_core_runtime/agents/ag44_cloud_deployer.py"   "$RUNTIME/inneros_core_runtime/mcp_server.py"; then
  restore_runtime
  die "runtime compile failed; rollback applied"
fi

log "Restarting only ralfia-mcp"
if ! systemctl --user restart ralfia-mcp; then
  restore_runtime
  die "ralfia-mcp restart failed; rollback applied"
fi

MCP_OK=0
for _ in 1 2 3 4 5 6; do
  if curl -fsS --max-time 4 http://127.0.0.1:8102/health >/tmp/infralens-mcp-health.json; then
    MCP_OK=1
    break
  fi
  sleep 2
done
if [[ "$MCP_OK" -ne 1 ]]; then
  restore_runtime
  die "MCP did not recover after restart; runtime rollback applied"
fi
log "MCP health PASS"

log "Checking AMD Streamlit origin before publishing"
curl -fsS --max-time 8 "$UI_HEALTH" >/tmp/infralens-ui-health.txt
grep -qi "ok" /tmp/infralens-ui-health.txt || die "Streamlit health did not return ok"
log "Streamlit origin PASS"

log "Checking private OCR and immutable image on AMD node"
OCR_JSON="$(ssh -o BatchMode=yes -o ConnectTimeout=8 "$AMD_HOST" "curl -fsS --max-time 8 '$OCR_HEALTH'")"
printf '%s\n' "$OCR_JSON" | grep -q "AMD Radeon AI PRO R9700" || die "OCR health does not prove R9700"
RUNNING_IMAGE="$(ssh -o BatchMode=yes -o ConnectTimeout=8 "$AMD_HOST" "docker inspect infralens-track2-ocr --format '{{.Image}}'")"
[[ "$RUNNING_IMAGE" == "$EXPECTED_IMAGE" ]] || die "final-512 image changed: $RUNNING_IMAGE"
log "OCR/R9700 PASS; final-512 digest unchanged"

log "Applying the single Cloudflare ingress entry"
PYTHONPATH="$RUNTIME" "$PYTHON_BIN" - <<'PY'
import json
from inneros_core_runtime.agents import ag44_cloud_deployer as ag44

result = ag44.cloudflare_tunnel_ingress_upsert(
    "infralens.creatorcore.ai",
    "http://192.168.1.5:18501",
    dry_run=False,
)
print(json.dumps(result, sort_keys=True))
if not result.get("ok"):
    raise SystemExit(2)
PY

log "Verifying public HTTPS"
PUBLIC_OK=0
for _ in 1 2 3 4 5 6 7 8; do
  if PYTHONPATH="$RUNTIME" "$PYTHON_BIN" - <<'PY'
from inneros_core_runtime.agents import ag44_cloud_deployer as ag44
result = ag44.cloudflare_hostname_health_check("infralens.creatorcore.ai", path="/", timeout=8)
print(result)
raise SystemExit(0 if result.get("ok") and result.get("status") == 200 and not result.get("cf_mitigated") else 1)
PY
  then
    PUBLIC_OK=1
    break
  fi
  sleep 3
done
[[ "$PUBLIC_OK" -eq 1 ]] || die "public HTTPS did not reach clean HTTP 200"

log "FINAL PASS"
printf 'source_sha=%s\n' "$SOURCE_SHA"
printf 'public_url=%s\n' "$PUBLIC_URL"
printf 'ui_origin=%s\n' "$UI_ORIGIN"
printf 'ocr_visibility=private_loopback_only\n'
printf 'final512=%s\n' "$RUNNING_IMAGE"
printf 'backup=%s\n' "$BACKUP_ROOT"
