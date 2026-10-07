# Contífico MCP — dual entidad (PC Doctor + Domotika/InnerChispa)

## Variables (sin commitear secretos)

| Variable | Dónde | Uso |
|----------|--------|-----|
| `CONTIFICO_API_KEY` | `platform/.env` (gitignored) | Legacy → entidad **pcdoctor** |
| `CONTIFICO_PCDOCTOR_API_KEY` | opcional | Si vacío, usa `CONTIFICO_API_KEY` (legacy) |
| `CONTIFICO_DOMOTIKA_API_KEY` | **requerida para RUP personal** | RUC `0914832423001` (nombre fantasía Domotika → InnerChispa) |
| `CONTIFICO_PCDOCTOR_POS_TOKEN` / `CONTIFICO_DOMOTIKA_POS_TOKEN` | opcional | Header `Pos` por entidad |
| `CONTIFICO_DEFAULT_ENTITY` | default `pcdoctor` | Entidad por defecto si invoke omite `entity_id` |

### Entidades (`entity_id`)

| entity_id | RUC | Uso |
|-----------|-----|-----|
| `pcdoctor` | `0992418575001` | PC Doctor S.A. — facturación corporativa |
| `domotika` / `innerchispa` | `0914832423001` | RUP Héctor Rafael López Gutiérrez — marca Domotika (pronto InnerChispa) |

Todas las capabilities aceptan parámetro opcional `entity_id`. `connection.status` sin `entity_id` devuelve **ambas** cuentas.

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
