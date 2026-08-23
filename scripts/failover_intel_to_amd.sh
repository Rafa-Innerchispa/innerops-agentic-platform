#!/usr/bin/env bash
# Failover Intel (.4) → AMD (.5) — borrador
# Uso:
#   ./failover_intel_to_amd.sh              # dry-run (default)
#   ./failover_intel_to_amd.sh --execute    # activa servicios en .5
#   ./failover_intel_to_amd.sh --execute --with-quoteops
#
# NO reinicia producción en .4 sin confirmación explícita de Rafael.

set -euo pipefail

INTEL="${RALFIA_INTEL_HOST:-192.168.1.4}"
AMD="${RALFIA_AMD_HOST:-192.168.1.5}"
SSH_USER="${RALFIA_SSH_USER:-rlopez}"
EXECUTE=false
WITH_QUOTEOPS=false

for arg in "$@"; do
  case "$arg" in
    --execute) EXECUTE=true ;;
    --with-quoteops) WITH_QUOTEOPS=true ;;
    -h|--help)
      sed -n '2,8p' "$0"
      exit 0
      ;;
    *) echo "Opción desconocida: $arg" >&2; exit 2 ;;
  esac
done

log() { printf '[failover] %s\n' "$*"; }

check_intel_health() {
  local ok=true
  log "Verificando salud Intel (.4) @ $INTEL ..."

  if ! ping -c1 -W3 "$INTEL" &>/dev/null; then
    log "  FAIL: ping a $INTEL"
    ok=false
  else
    log "  OK: ping"
  fi

  local mcp_code
  mcp_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "http://${INTEL}:8102/health" 2>/dev/null || echo '000')
  if [[ "$mcp_code" != "200" ]]; then
    log "  FAIL: MCP :8102/health → HTTP $mcp_code"
    ok=false
  else
    log "  OK: MCP :8102"
  fi

  local app_code
  app_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "http://${INTEL}:8101/status" 2>/dev/null || echo '000')
  if [[ "$app_code" != "200" ]]; then
    log "  WARN: ralfia-app :8101/status → HTTP $app_code"
    ok=false
  else
    log "  OK: ralfia-app :8101"
  fi

  local portal_code
  portal_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "http://${INTEL}:8800/" 2>/dev/null || echo '000')
  if [[ "$portal_code" =~ ^(000|000000)$ ]]; then
    log "  WARN: portal :8800 → HTTP $portal_code"
  else
    log "  OK: portal :8800 → HTTP $portal_code"
  fi

  if $ok; then
    return 0
  fi
  return 1
}

activate_amd() {
  log "Activando servicios en AMD (.5) @ $AMD ..."

  local remote_script
  remote_script=$(cat <<'REMOTE'
set -euo pipefail
UNITS=(ralfia-mcp ralfia-app ralfia-portal ralfia-coordination-daemon)
for u in "${UNITS[@]}"; do
  if systemctl --user cat "${u}.service" &>/dev/null; then
    systemctl --user enable "${u}.service" 2>/dev/null || true
    systemctl --user start "${u}.service" 2>/dev/null || echo "WARN: start ${u} falló"
    printf '  %-30s %s\n' "$u" "$(systemctl --user is-active ${u} 2>/dev/null || echo '?')"
  else
    echo "  SKIP: ${u}.service no instalado"
  fi
done

# WhatsApp Innerchispa — Evolution API (verificar instancia)
if curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8082/ 2>/dev/null | grep -qE '^(200|301|302|404)'; then
  echo "  OK: Evolution/Innerchispa responde :8082"
else
  echo "  WARN: Evolution :8082 no responde — revisar docker/systemd innerchispa"
fi

# Webhook debe apuntar a nodo activo (manual si .4 caído)
echo "  NOTA: verificar webhook Innerchispa → nodo activo (ver INBOX msg WhatsApp dual-nodo)"

REMOTE
)

  if $WITH_QUOTEOPS; then
    remote_script+=$(cat <<'QOPS'

# QuoteOps (opcional)
if systemctl --user cat ralfia-mcp-profile@quoteops.service &>/dev/null; then
  systemctl --user enable --now ralfia-mcp-profile@quoteops.service 2>/dev/null || true
  printf '  quoteops-mcp-profile     %s\n' "$(systemctl --user is-active ralfia-mcp-profile@quoteops.service 2>/dev/null || echo '?')"
fi
for port in 8765 8773; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:${port}/health" 2>/dev/null || echo '000')
  printf '  quoteops :%-5s         HTTP %s\n' "$port" "$code"
done
QOPS
)
  fi

  if $EXECUTE; then
    ssh -o BatchMode=yes -o ConnectTimeout=10 "${SSH_USER}@${AMD}" bash -s <<< "$remote_script"
  else
    log "[DRY-RUN] Se ejecutaría en $AMD:"
    echo "$remote_script" | sed 's/^/    /'
  fi
}

print_manual_steps() {
  cat <<'MANUAL'

=== Pasos manuales restantes (no automatizados) ===

1. DNS / ngrok: actualizar túnel público si apunta a .4 caído
   - Gateway :5188 en Intel (systemd swarm-public-gateway)
   - ngrok: https://sworn-profusely-alongside.ngrok-free.dev/

2. WhatsApp Innerchispa:
   - Cambiar webhook Evolution → http://192.168.1.5:2002/api/whatsapp/evolution/webhook
   - O mantener proxy si .4 vuelve parcialmente
   - Ver msg_5c6acfd961a5ec18 (WhatsApp dual-nodo)

3. MongoDB:
   - Si Mongo vive en .4, AMD necesita acceso de red o réplica local
   - Verificar: mongosh --eval "db.runCommand({ping:1})"

4. Qdrant / Ollama:
   - AMD tiene Ollama local; verificar modelos cargados
   - Qdrant: puerto 6333 en nodo con datos

5. Notificar agentes:
   create_agent_message(from_agent='CURSOR', target_agent='chatgpt',
     title='Failover activo AMD .5', priority='critical', ...)

6. Rollback cuando .4 vuelva:
   - NO detener AMD hasta confirmar .4 estable
   - Revertir webhook WhatsApp a .4
   - ack mensajes de failover en Mongo

MANUAL
}

# --- Main ---
log "Modo: $($EXECUTE && echo EXECUTE || echo DRY-RUN) | QuoteOps: $WITH_QUOTEOPS"
log "Nodo local: $(hostname) ($(hostname -I 2>/dev/null | awk '{print $1}'))"

if check_intel_health; then
  log "Intel (.4) SALUDABLE — failover NO necesario."
  log "Para forzar activación AMD: $0 --execute"
  exit 0
fi

log "Intel (.4) DEGRADADO o INALCANZABLE — proceder con failover."
activate_amd
print_manual_steps

if $EXECUTE; then
  log "Failover ejecutado. Verificar portal http://${AMD}:8800/ y MCP http://${AMD}:8102/health"
else
  log "Dry-run completado. Usar --execute para activar."
fi
