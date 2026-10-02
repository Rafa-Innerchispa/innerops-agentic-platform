# Dual-node MCP — AMD primary (2026-10-02)

## Objetivo
- **Entrada pública única:** `https://mcp.pcdoctor.ai/router/mcp` (router en Intel `:8250`).
- **Ejecución MCP compact primaria:** AMD `.5` (`inneros_compact_amd` → Tailscale `100.72.153.124:8112`).
- **Fallback degradado:** Intel `.4` (`inneros_compact` → `127.0.0.1:8112`).
- **Qwen residente:** vLLM en AMD `127.0.0.1:8000`; túnel Tailscale `100.72.153.124:8001` para Intel.

## Router
- Config: `services/mcp-router-gateway/profiles.json`
- Health probe: `services/mcp-router-gateway/src/mcp_router_gateway/backend_health.py`
- `/router/health` expone `mode`: `normal_amd_primary` | `degraded_intel_only` | `degraded_no_compact_backend`

## Capacity governor (AMD)
- Grace de arranque vLLM: 900s (`startup_grace_observe`).
- Stop + fallback Intel solo tras fallos sostenidos (`VLLM_MAX_RESTARTS_BEFORE_STOP=8`).
- Unidad: `inneros-vllm-qwen3-coder-30b-awq.service` — recomendado `gpu-memory-utilization 0.68` en R9700 32GB con carga compartida.

## Despliegue
```bash
# Intel
systemctl --user restart inneros-mcp-router-gateway.service

# AMD — sync platform + restart compact/vllm según unidades user
```

## Verificación
```bash
curl -s http://127.0.0.1:8250/router/health | jq .mode,.primary_backend,.backends_healthy
curl -s http://100.72.153.124:8001/v1/models | head
```
