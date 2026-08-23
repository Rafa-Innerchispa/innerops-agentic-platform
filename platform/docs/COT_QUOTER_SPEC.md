# Cotizaciones (COT) — prioridad y formato visual

**Estado:** implementación base en servidor (jul 2026)  
**Prioridad:** COT > FAC — las cotizaciones son el documento comercial principal.

## Principio

| Documento | Contenido | Uso |
|-----------|-----------|-----|
| **Informe técnico** | Hallazgos de campo, equipos, procedimientos | Interno / post-visita |
| **Cotización (COT)** | Introducción narrativa + detalle comercial | Cliente — propuesta de venta |
| **Factura (FAC)** | Contable / SRI | Después de aprobación |

Al cotizar **no** se adjunta el informe técnico completo. Sí una **introducción** (`intro_md`) que explique qué se propone y por qué, en lenguaje claro.

## Formato visual

Plantilla HTML alineada a la estética PC Doctor / InnerSpark:

- Cabecera con gradiente, logo textual y tipo **COTIZACIÓN**
- Meta grid: número, fecha emisión, validez, estado
- Banda cliente: nombre, RUC, contacto, proyecto, dirección
- Sección **01 — Contexto de la propuesta** (intro, no informe)
- Sección **02 — Detalle comercial** (tabla + totales)
- Pie con ticket de seguimiento si fue enviada

**Vista previa:** `GET /api/v1/quotes/{quote_ref}/document`

Fuentes: Inter + Outfit (misma familia que Smart Quoter).

## Fuentes de datos

| Origen | Colección | ID |
|--------|-----------|-----|
| MCP / PC Doctor | `ops_quote_drafts` | `quote_id` |
| Smart Quoter UI | `quote_opportunities` | `quote_number` (ej. SQ-2026-0001) |
| Contifico histórico | `contifico_documents` | `ralfia_number` (ej. COT-202607000184) |

Campos nuevos en borrador ops:

- `intro_md` — introducción narrativa
- `scope_summary` — resumen corto
- `display_number` — número visible al cliente
- `entity_id` — `ent_pcdoctor` | `ent_innerspark`
- `valid_until`, `ticket_id`, `sent_at`

## Entrega al cliente — ticket moderno

No es un “ticket clásico” de mesa de ayuda. Es **seguimiento de propuesta** visible por WhatsApp.

### Flujo

1. `generate_quote_intro(quote_ref)` — IA genera intro comercial breve
2. `render_quote_document(quote_ref)` — HTML listo para imprimir/PDF
3. `send_quote_delivery(quote_ref, channels=['whatsapp','email'])`:
   - Crea ticket `PCD-COT-YYYYMM-XXXX`
   - WhatsApp (Evolution API): mensaje con número, total, enlaces
   - Email: cola de registro (`email_payload.status=queued`) — SMTP pendiente
   - Persiste en `ops_quote_deliveries`

### Seguimiento

| Canal | Rol |
|-------|-----|
| **WhatsApp** | Primario — cliente responde citando `PCD-COT-…` |
| **Email** | Registro formal / archivo |
| **Web** | `GET /api/v1/quotes/track/{ticket_id}` — página oscura moderna |

### Tools MCP

- `render_quote_document`
- `generate_quote_intro`
- `send_quote_delivery`
- `get_quote_tracking`

### Smart Quoter

`POST /api/quotes/deliver` en `:2026` → proxy a RalfIA `:8099`.

Centro de Envíos deja de simular; llama API real.

## Relación con informes técnicos

```
Visita de campo → generate_supervisor_report → ops_technical_reports (Markdown)
                        ↓
              generate_quote_intro (resume para cliente, ~180 palabras)
                        ↓
              render_quote_document + send_quote_delivery
```

El informe sigue existiendo para el equipo. La cotización solo **hereda la estética** y un resumen comercial.

## Pendiente (siguiente iteración)

- [x] PDF server-side (fpdf2) desde datos cotización
- [x] Adjuntar PDF en WhatsApp (`sendMedia` Evolution)
- [x] SMTP real para email (env o email_accounts Mongo)
- [x] Sync `quote_opportunities` / Contifico ↔ `ops_quote_drafts` (`sync_quote_sources`)
- [x] Webhook WhatsApp: respuesta cliente → `update_delivery_status`
- [ ] Panel RalfIA: lista entregas por ticket

## URLs públicas (ngrok)

Sustituir base por `MCP_PUBLIC_URL`:

- Documento: `{MCP_PUBLIC_URL}/api/v1/quotes/{quote_ref}/document`
- Seguimiento: `{MCP_PUBLIC_URL}/api/v1/quotes/track/{ticket_id}`
