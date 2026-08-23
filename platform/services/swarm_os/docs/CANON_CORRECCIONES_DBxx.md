# Canon local — correcciones DBxx (este proyecto manda)

**Fuente de verdad operativa:** MongoDB `pcdoctor_swarm` + documentos en este repo.  
**Notion:** referencia humana; Rafael corrige allí cuando pueda. **Aquí no replicamos errores de Notion.**

Última actualización: 2026-06-09

---

## Correcciones adoptadas

### DB41 — nombre y rol

| Sistema | Qué dice | Acción |
|---------|----------|--------|
| Notion (algunas vistas) | "DB41 Informes Técnicos" | **Incorrecto / legacy** |
| Especificación técnica + este repo | **DB41 = Reglas de Verificación (Cotizaciones)** | **Canónico** |
| Informe técnico formal | Tipo/plantilla en **DB45 Reportes Técnicos** | No es DB41 |

**Colección Mongo:** `verification_rules` (DB41)  
**Colección Mongo:** `technical_reports` (DB45) — incluye plantillas de informe

### DB12 — hueco en índice Notion

- DB35 referencia `DB12 Grants & Funding` pero el índice Notion salta DB11→DB13.
- **Aquí:** DB12 existe como `grants` (pipeline de grants).
- DB35 = `grant_financials` (dinero recibido, reportes).

### DB28 — no está libre

- **DB28 = Compras / Historial de Precios** (`purchase_prices`).
- Alimenta validación de costos en DB38 y reglas DB41.

### Tres capas de campo (no una sola)

| DB | Colección Mongo | Qué es |
|----|-----------------|--------|
| DB42 | `sop_visits` | Ticket visita PCD-SOP-26-NNNNNN |
| DB45 | `technical_reports` | Reporte técnico, bitácora, PDF-first |
| DB29 | `works` | Trabajo operativo, cobro, margen |

**Legacy `inspections`:** mezcla las tres. Migrar a v2; no crear datos nuevos solo en `inspections`.

### Inventario — tres bases, un propósito cada una

| DB | Colección | Uso |
|----|-----------|-----|
| DB13 | `catalog_products` | Catálogo comercial, servicios, bundles |
| DB26 | `inventory_items` | Stock hardware cotizable |
| DB09 | `assets` | Activos instalados en cliente/proyecto |

No unificar en una sola colección `inventory` (legacy aceptado hasta migrar).

### DB43 — cliente como texto

- Notion tiene `Cliente (text)` en recepción rápida.
- **Mongo:** `client_id` obligatorio cuando exista; campos texto como snapshot de recepción.

### DB50–DB52 — completar en Notion

Incluidos en `ESQUEMA_MONGODB_DBxx.md` aunque el paste del usuario cortó en DB49:

- **DB50** → `visual_prompts`
- **DB51** → `domain_emails`
- **DB52** → `ai_provenance` (reemplaza/ampliará `audit_log`)

### Hub Cliente

No es DBxx numerada pero es **obligatoria** (Playbook Hub-first).

- Colección: `client_hubs`
- Todo `quote`, `technical_report`, `document` lleva `client_id` + `hub_id`.

---

## Nomenclatura de códigos (DB40)

| Tipo | Formato | Ejemplo |
|------|---------|---------|
| Cotización | `{ENT}-COT-{AA}{NNNN}` | `PCD-COT-260001` |
| Trabajo | `{ENT}-TRB-{AA}{NNNN}` | `PCD-TRB-260042` |
| Reporte | `{ENT}-RPT-{AA}{NNNN}` | `PCD-RPT-260007` |
| SOP visita | `{ENT}-SOP-{AA}{NNNNNN}` | `PCD-SOP-26000001` |
| Factura | `{ENT}-INV-{AA}{NNNN}` | `PCD-INV-260003` |

Generación: **solo** `tools/schema.py` → `next_serial(entity, doc_type)`.

---

## Compatibilidad legacy

| Legacy v1 | Destino v2 |
|-----------|------------|
| `inspections` | `sop_visits` + `technical_reports` |
| `reports` | `technical_reports` |
| `quote_headers` | `quotes` |
| `quote_lines` | `quote_lines` (misma colección, nuevos campos) |
| `clients` | `clients` (campos ampliados) |
| `inventory` | `inventory_items` |
| `audit_log` | `ai_provenance` (+ opcional seguir escribiendo audit_log) |

Script: `python scripts/migrate_v1_to_v2.py`
