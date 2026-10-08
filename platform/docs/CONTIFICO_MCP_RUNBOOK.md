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


## Contabilidad dual (Mongo + ledger)

Capabilities:
- `contifico.accounting.status.v1` — conteos por entidad (`contifico_documents`, `contifico_personas`, `ralfia_ledger_documents`).
- `contifico.accounting.sync.v1` — import por `entity_id` o todas; valida **RUC vs API key** antes de escribir.

Colecciones etiquetadas con `contifico_entity_id`, `issuer_ruc`, `issuer_trade_name`.

**Validación RUC:** si `connected_company_ruc` ≠ RUC de la entidad, la sync se omite (`api_key_ruc_mismatch`). Cada empresa Contifico/Siigo tiene su propia API key ([guía API](https://contifico.portaldeclientes.siigo.ec/basedeconocimiento/consultar-guia-de-uso-api/)).

Ledger unificado: `ralfia_ledger_documents` con `ledger_id` = `contifico:{entity_id}:{contifico_id}`.

## Escritura API v1 (facturación PC Doctor)

Contífico exige el **token POS en el cuerpo JSON** (`"pos": "UUID"`), no solo header `Pos` v2.

- `CONTIFICO_PCDOCTOR_POS_TOKEN` o `CONTIFICO_COMPANY_TOKEN` (UUID del POS, p. ej. punto 001-001).
- COT/FAC vía MCP usan **API v1** `/documento/` con totales `subtotal_0`, `subtotal_12`, `documento` (secuencia).

## Domotika / RUP personal — stand-by

`CONTIFICO_DOMOTIKA_STANDBY=1` → sin API; no sync ni facturación. Migración futura: export manual / CSV / cierre de cuenta.
