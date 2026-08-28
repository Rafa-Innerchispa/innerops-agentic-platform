# Esquema MongoDB — OS Central DBxx

**Base de datos:** `pcdoctor_swarm`  
**Implementación:** `tools/schema.py` (índices + secuenciales)  
**Correcciones vs Notion:** `docs/CANON_CORRECCIONES_DBxx.md`

Última actualización: 2026-06-09

---

## Reglas de diseño (replicadas del Playbook)

1. Una colección por concepto DBxx; vistas = consultas, no colecciones duplicadas.
2. IDs/códigos permanentes — nunca reciclar (`serials` DB40).
3. Cabecera ≠ líneas: `quotes` (DB27) + `quote_lines` (DB38).
4. PDF-first en `documents`, separado de operación.
5. Hub-first: `client_id` + `hub_id` en entregables.
6. Gates DB41 → `validation_results` antes de enviar cotización.

---

## Fases de implementación

| Fase | DBxx | Estado código |
|------|------|---------------|
| **A** Campo + comercial | 04,05,08*, 13,25,26,28,27,38,40,41,42,45,29*, 52, HUB, DOC, VAL, MED | Índices + migración; crew pendiente |
| **B** Taller + cobro | 43, 32, 46, 30, 31 | Esquema definido |
| **C** Editorial | 47–50, 15–24 | Esquema definido |
| **D** Finanzas plenas | 12, 33–36, 44, 51 | Esquema definido |
| **E** Organización | 01–03, 06–07, 09–11, 14, 17–20, 39 | Esquema definido |

\* DB08/DB29 mínimo en Fase A (referencia opcional).

---

## Mapa colección ↔ DBxx

| DB | Colección | Título / propósito |
|----|-----------|-------------------|
| DB01 | `entities` | Entidades (PC Doctor, InnerSpark…) |
| DB02 | `divisions` | Divisiones |
| DB03 | `buyer_personas` | Buyer personas |
| DB04 | `clients` | Instituciones y clientes |
| DB05 | `contacts` | Contactos |
| DB06 | `offers` | Ofertas y soluciones |
| DB07 | `stacks` | Stacks validados |
| DB08 | `projects` | Proyectos (columna vertebral) |
| DB09 | `assets` | Inventario y activos instalados |
| DB10 | `research_lines` | Líneas de research |
| DB11 | `ideas` | Ideas y viabilidad |
| DB12 | `grants` | Grants & Funding (pipeline) |
| DB13 | `catalog_products` | Catálogo maestro productos/servicios |
| DB14 | `automations` | OS Automation Registry |
| DB15 | `editorial_posts` | OS Editorial Social |
| DB16 | `social_destinations` | Destinos sociales |
| DB17 | `avatars` | Avatares InnerSpark |
| DB18 | `digital_assets_channels` | Activos digitales y canales |
| DB19 | `ecosystem_metrics` | Métricas salud ecosistema |
| DB20 | `incidents` | Incidentes y decisiones |
| DB21 | `media_library` | Biblioteca assets media |
| DB22 | `utm_links` | UTM y links |
| DB23 | `campaigns` | Campañas |
| DB24 | `experiments` | A/B tests |
| DB25 | `suppliers` | Proveedores |
| DB26 | `inventory_items` | Inventario hardware PC Doctor |
| DB27 | `quotes` | Cotizaciones (cabecera) |
| DB28 | `purchase_prices` | Compras / historial precios |
| DB29 | `works` | Trabajos día a día |
| DB30 | `accounts` | Cuentas financieras |
| DB31 | `transactions` | Transacciones |
| DB32 | `invoices` | Facturas |
| DB33 | `expenses` | Gastos operativos |
| DB34 | `payment_processors` | Procesadores de pago |
| DB35 | `grant_financials` | Grants tracking financiero |
| DB36 | `cashflow_budgets` | Cash flow y budget |
| DB37 | `productivity_metrics` | Productivity metrics |
| DB38 | `quote_lines` | Líneas de cotización |
| DB39 | `manuals` | Manuales InnerSpark |
| DB40 | `serials` | Secuenciales |
| DB41 | `verification_rules` | Reglas verificación cotización |
| DB42 | `sop_visits` | Soporte / visitas SOP |
| DB43 | `equipment_tickets` | Recepciones equipos |
| DB44 | `domains_hosting` | Dominios y hosting |
| DB45 | `technical_reports` | Reportes técnicos |
| DB46 | `contracts` | Contratos |
| DB47 | `field_captures` | Capturas campo editorial |
| DB48 | `editorial_pipeline` | Pipeline editorial multicanal |
| DB49 | `editorial_campaigns` | Campañas editoriales |
| DB50 | `visual_prompts` | Biblioteca prompts visuales |
| DB51 | `domain_emails` | Correos por dominio |
| DB52 | `ai_provenance` | AI provenance log |
| — | `client_hubs` | Hub cliente (Playbook) |
| — | `documents` | PDF-first unificado |
| — | `validation_results` | Resultado gates DB41 |
| — | `media_assets` | Fotos/audio por visita |

---

## Fase A — campos mínimos por colección

### `clients` (DB04)

```json
{
  "client_id": "cli_abc123",
  "ruc": "0991386866001",
  "cedula": null,
  "name": "ASOPAR",
  "trade_name": "",
  "tipo": "Comunidad",
  "estado": "Cliente",
  "pais": "ecu",
  "ciudad": "",
  "direccion": "",
  "phone": "",
  "email": "",
  "email_documentos": "",
  "hub_id": "hub_xyz",
  "hub_ready": true,
  "primary_contact_id": null,
  "notas": "",
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```

### `contacts` (DB05)

```json
{
  "contact_id": "con_abc",
  "client_id": "cli_abc123",
  "nombre": "",
  "tipo_contacto": ["Cliente"],
  "email": "",
  "phone": "",
  "perfil": "Técnico"
}
```

### `client_hubs` (Hub)

```json
{
  "hub_id": "hub_xyz",
  "client_id": "cli_abc123",
  "name": "Hub ASOPAR",
  "ready": true
}
```

### `sop_visits` (DB42)

```json
{
  "visit_id": "vis_abc",
  "legacy_inspection_id": "INS-...",
  "code": "PCD-SOP-26000001",
  "entity": "PCD",
  "client_id": "cli_abc123",
  "contact_id": null,
  "project_id": null,
  "fecha": "2026-06-09",
  "estado": "En ejecución",
  "raw_input": "",
  "notas": ""
}
```

### `technical_reports` (DB45)

```json
{
  "report_id": "rpt_abc",
  "code": "PCD-RPT-260001",
  "visit_id": "vis_abc",
  "client_id": "cli_abc123",
  "estado": "Borrador",
  "tipo_reporte": "Visita técnica / Avance",
  "resumen_ejecutivo": "",
  "hallazgos_clave": "",
  "pendientes": "",
  "bitacora": "",
  "findings": [],
  "pdf_first_url": null,
  "listo_exportar_pdf": false
}
```

### `media_assets` (MED)

```json
{
  "asset_id": "med_abc",
  "visit_id": "vis_abc",
  "tipo": "audio|foto|pdf",
  "path": "/data/media/...",
  "transcripcion": "",
  "created_at": "ISO8601"
}
```

### `quotes` (DB27)

```json
{
  "quote_id": "qot_abc",
  "code": "PCD-COT-260001",
  "client_id": "cli_abc123",
  "visit_id": "vis_abc",
  "report_id": "rpt_abc",
  "estado": "Borrador",
  "moneda": "USD",
  "iva_15": true,
  "subtotal": 0,
  "monto_iva": 0,
  "total": 0,
  "subtotal_calculado": 0,
  "alerta_descuadre": null,
  "legacy_inspection_id": null
}
```

### `quote_lines` (DB38) — fuente matemática

```json
{
  "quote_id": "qot_abc",
  "line_no": 1,
  "tipo": "Hardware|Servicio|Material|Otro",
  "inventory_item_id": null,
  "catalog_product_id": null,
  "descripcion": "",
  "cantidad": 1,
  "costo_unitario": 0,
  "precio_unitario": 0,
  "subtotal_linea": 0,
  "margen_pct": 0,
  "supplier_id": null
}
```

### `inventory_items` (DB26)

```json
{
  "item_code": "PCD-ITM-CAM-0001",
  "sku": "CAM-IP-2MP",
  "nombre": "Cámara IP 2MP",
  "categoria": ["Cámaras"],
  "costo_proveedor": 0,
  "precio_sugerido": 85,
  "stock_actual": 0,
  "disponible_cotizar": true,
  "supplier_id": null
}
```

### `catalog_products` (DB13)

```json
{
  "code": "PCD-SRV-RACK-001",
  "nombre": "Ordenamiento de rack",
  "marca": "PC Doctor",
  "tipo": "Servicio",
  "precio_sugerido": 120,
  "costo_base": 0,
  "margen_objetivo_pct": 40
}
```

### `verification_rules` (DB41)

```json
{
  "rule_id": "rule_abc",
  "activa": true,
  "severidad": "Bloqueante (no enviar)",
  "aplica_a": ["DB38 (líneas)", "PDF-first"],
  "condicion": "",
  "verificar": "",
  "accion_si_falta": ""
}
```

### `validation_results` (VAL)

```json
{
  "target_type": "quote",
  "target_id": "qot_abc",
  "rule_id": "rule_abc",
  "passed": false,
  "mensaje": "",
  "at": "ISO8601"
}
```

### `documents` (DOC) — PDF-first

```json
{
  "document_id": "doc_abc",
  "target_type": "quote|technical_report|sop_visit",
  "target_id": "qot_abc",
  "client_id": "cli_abc123",
  "formato": "pdf|md",
  "path": "/data/exports/...",
  "sha256": "",
  "version": 1
}
```

### `serials` (DB40)

```json
{
  "entity": "PCD",
  "doc_type": "COT",
  "year": 26,
  "last_seq": 1,
  "prefix": "PCD"
}
```

### `ai_provenance` (DB52)

```json
{
  "actor": "agente:revisor",
  "modelo": "neural-chat:7b",
  "fuente": "ollama",
  "accion": "validate_quote",
  "target_type": "quote",
  "target_id": "qot_abc",
  "input_hash": "",
  "payload": {},
  "at": "ISO8601"
}
```

### `works` (DB29)

```json
{
  "work_id": "wrk_abc",
  "code": "PCD-TRB-260001",
  "client_id": "cli_abc123",
  "visit_id": "vis_abc",
  "quote_id": "qot_abc",
  "estado_facturacion": "Pendiente facturar",
  "precio_cobrado": 0,
  "costo_proveedor": 0
}
```

---

## Legacy v1 (convivencia)

| Colección legacy | Migración |
|------------------|-----------|
| `inspections` | → `sop_visits` + `technical_reports` |
| `reports` | → `technical_reports` |
| `quote_headers` | → `quotes` |
| `inventory` | → `inventory_items` |
| `audit_log` | → también `ai_provenance` |

Ejecutar: `python scripts/migrate_v1_to_v2.py`

---

## Relaciones troncales

```
entities → divisions → projects
clients ↔ contacts
clients → client_hubs (1:1)
clients → sop_visits → technical_reports → quotes → quote_lines
quote_lines → inventory_items | catalog_products
quotes → validation_results ← verification_rules
quotes | technical_reports → documents
serials → codes en quotes, reports, works, sop_visits
```

---

## Referencia Notion

Los campos completos 1:1 de cada DBxx están en la **Especificación Técnica OS Central** (pegada por Rafael en chat). Este documento es la **proyección Mongo** operativa; ante duda de negocio consultar Playbook V2 en Notion.
