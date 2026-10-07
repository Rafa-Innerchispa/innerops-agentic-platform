# Contífico MCP — configuración y diagnóstico (PC Doctor)

## Variables (sin commitear secretos)

| Variable | Dónde | Uso |
|----------|--------|-----|
| `CONTIFICO_API_KEY` | `platform/.env` (gitignored) | Header `Authorization` en cada request |
| `CONTIFICO_COMPANY_TOKEN` | opcional | Referencia multi-empresa si aplica |
| `CONTIFICO_API_BASE` | default `https://api.contifico.com/sistema/api/v1` | Base URL v1 |
| `CONTIFICO_FISCAL_EMIT_ENABLED` | `0` en dev | Debe ser `1` solo con autorización owner para `FAC` |
| `CONTIFICO_WRITE_ENABLED` | legacy AG-17 | No sustituye gate fiscal |

## Rotación de API key

1. Generar nueva key en Contífico (Siigo) → soporte/portal.
2. Actualizar `CONTIFICO_API_KEY` en `.env` del host MCP (Intel/AMD).
3. Reiniciar servicio MCP router/worker que carga `inneros_core_runtime`.
4. Verificar: `capability_invoke` → `contifico.connection.status.v1`.

## Capabilities MCP

- Read: `contifico.connection.status.v1`, `customer.search/get`, `item.search`, `invoice.get/status`, `payment.query`
- Medium: `customer.create`, `invoice.draft` (COT no fiscal)
- High: `invoice.create` (FAC) — requiere `owner_approved` + `CONTIFICO_FISCAL_EMIT_ENABLED`

## Borrador vs fiscal

- **Borrador:** `invoice.draft` crea **COT** (`electronico=false`) — cotización, no factura SRI.
- **Fiscal:** `invoice.create` → **FAC** bloqueado sin aprobación explícita.

## Diagnóstico rápido

```bash
cd platform && PYTHONPATH=. ./venv/bin/python3 -m unittest tests.test_contifico_mcp_capabilities -q
PYTHONPATH=. ./venv/bin/python3 scripts/contifico_p1_mcp_smoke.py
```

## Idempotencia

Claves en Mongo `contifico_idempotency` evitan doble emisión con la misma `idempotency_key`.
