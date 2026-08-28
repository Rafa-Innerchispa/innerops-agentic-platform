# Arquitectura objetivo — PC Doctor OS (nivel producción)

**Visión:** mini-ERP modular para MSP/PIME técnica (Ecuador), local en 192.168.1.4, sin depender de créditos cloud.

---

## 1. RAG — qué es y qué hace AnythingLLM

**RAG** = Retrieval Augmented Generation:

1. Subes un **bucket de documentos** (PDFs, SOPs, manuales, contratos, histórico)
2. El sistema los **trocea**, genera **embeddings** (vectores) y los guarda
3. Cuando preguntas, **busca** los fragmentos relevantes y se los pasa al LLM
4. El LLM responde **citando** ese contexto (menos alucinación)

### En tu servidor hay VARIOS sistemas RAG (no uno solo)

| Sistema | Puerto | Qué hace | ¿Es RAG? |
|---------|--------|----------|----------|
| **AnythingLLM** | 3001 | UI para workspaces, subir docs, chat sobre ellos | **Sí — RAG listo para humanos** |
| **Qdrant** | 6333 | Base de vectores (motor) | Infra RAG, no UI |
| **inneros / Ralphi** | 4000, 6333 | Pipelines RAG hackathon | Sí, otro stack |
| **Open WebUI** | 3000 | Chat + puede tener RAG con documentos | Parcial |
| **Swarm-OS MongoDB** | 27017 | **NO es RAG** — datos estructurados | Operativo ERP |

### Rol correcto de AnythingLLM

- **Sí:** "¿Qué dice el manual sobre retención de 30 días en NVR Hikvision?"
- **Sí:** "Resume el SOP de negociación de margen"
- **No:** "¿Cuánto cobramos a ASOPAR?" → eso es **MongoDB**
- **No:** "Crea cotización PCD-COT-26-0042" → eso es **Swarm-OS API**

### Arquitectura RAG unificada (objetivo)

Un solo **servicio RAG** (AnythingLLM o Qdrant+API propia) con workspaces:

| Workspace | Contenido |
|-----------|-----------|
| `pcd-sops` | Playbook, SOPs, políticas |
| `pcd-manuales` | Manuales técnicos fabricantes |
| `pcd-historico` | Informes/cotizaciones archivadas (PDF) |

Los **agentes** Swarm-OS llaman RAG como **tool** (`search_knowledge`), no mezclan con precios.

### Upload colgado en AnythingLLM

Causa típica: embedding model en Ollama lento/fallando. No es el ERP; es el pipeline de vectorización del PDF.

---

## 2. Admin Panel — mini-ERP (diseño definitivo, sin migrar después)

### Recomendación: **Refine** + React + tu API FastAPI

- GitHub: https://github.com/refinedev/refine (20k+ stars, MIT)
- **No es ERP completo empaquetado** — es framework admin **profesional** que consume TU API
- Listas, formularios, filtros, relaciones, auth — sin atarte a Supabase/Firebase
- UI premium con **Ant Design** o **MUI** o **shadcn/ui**

**Por qué no ERPNext / Odoo desde cero:**

| Opción | Problema |
|--------|----------|
| ERPNext | Stack propio (Frappe/MariaDB), migrar DBxx = dolor |
| Odoo | Python propio, módulos pesados |
| Appsmith/Budibase | Low-code rápido pero techo bajo para lógica DB38/gates |
| **Refine + FastAPI + Mongo** | **Tu modelo DBxx intacto**, UI de nivel producto |

### Módulos del admin (mini-ERP)

| Módulo | Colecciones | Pantallas |
|--------|-------------|-----------|
| CRM | clients, contacts, client_hubs | Lista clientes, ficha, hub |
| Campo | sop_visits, technical_reports, media_assets | Visitas, reportes |
| Comercial | quotes, quote_lines, catalog_products, inventory_items | Cotizaciones, catálogo, stock |
| Taller | equipment_tickets | Recepción equipos |
| Operación | works | Trabajos día a día |
| Finanzas | invoices, transactions, accounts, expenses | Facturas, cobros |
| Proveedores | suppliers, purchase_prices | Compras, márgenes |
| Calidad | verification_rules, validation_results | Reglas y auditoría |
| Conocimiento | link a AnythingLLM :3001 | Embeds o nueva pestaña |

### App móvil campo (fase 2)

- PWA o React Native simple: voz + foto → misma API 8100
- Admin Refine para oficina; PWA para técnico

---

## 3. GitHub — estado actual

| Item | Estado |
|------|--------|
| Git local | ✅ 3 commits en `/home/rlopez/projects/innerspark-swarm-os-cursor-local` |
| Remote GitHub | ❌ **No configurado** (`git remote` vacío) |
| `gh` CLI | ❌ No instalado en servidor |
| `.env` en git | ✅ Ignorado (.gitignore) |

**Siguiente paso GitHub:**

1. Crear repo privado `innerspark-swarm-os-cursor-local` en github.com (cuenta rafagye@gmail.com)
2. SSH key o token en servidor
3. `git remote add origin` + `git push`
4. Admin frontend puede ser **monorepo** (`/admin`) o repo hijo

---

## 4. Agentes — mapa completo MSP/PIME

### Hoy: 8 agentes (solo flujo campo → cotización)

Cubre ~15% del negocio total.

### Objetivo: 3 capas de agentes

#### Capa A — Orquestación (1)

| Agente | Rol |
|--------|-----|
| **Director OS** | Detecta intención, elige squad, aplica gates |

#### Capa B — Squads operativos (por dominio)

| Squad | Agentes | Flujo DB |
|-------|---------|----------|
| **Onboarding** | Cliente, Contacto, Hub | DB04, DB05, Hub |
| **Campo** | Campo, Bitácora, Informes | DB42, DB45 |
| **Comercial** | Cotizador, Revisor margen, Negociación | DB27, DB38, DB41 |
| **Taller** | Recepción, Diagnóstico, Presupuesto taller | DB43 |
| **Ejecución** | Trabajo, Cierre | DB29 |
| **Finanzas** | Facturador, Cobranza, Contabilidad | DB32, DB31, DB30 |
| **Comunicaciones** | Email, WhatsApp | n8n |
| **Conocimiento** | Bibliotecario RAG | AnythingLLM tool |
| **Editorial** | Captura, Pipeline | DB47-49 (opcional) |

**Total agentes especializados: ~16-18**, no 8 forever.

#### Capa C — Servicios (no son agentes LLM)

| Servicio | Función |
|----------|---------|
| `gates.py` | Reglas duras (no negociables) |
| `workflow_v2.py` | Máquinas de estado |
| RAG API | Búsqueda documentos |
| n8n | Tubos correo/WhatsApp/sync |

**Principio:** LLM para razonamiento; **código** para matemática DB38 y dinero DB31.

---

## 5. Flujo total MSP (no necesitas explicarlo desde cero)

Es el estándar de toda PIME técnica — tu DBxx ya lo modela:

```
LEAD → CLIENTE → HUB
  → VISITA/INSPECCIÓN → REPORTE
  → COTIZACIÓN → APROBACIÓN
  → TRABAJO → ENTREGA
  → FACTURA → COBRO (DB31)
  → SOPORTE/TICKET (post-venta)
  → INVENTARIO/COMPRAS (replenish)
```

| Fase | % cubierto hoy | Prioridad |
|------|----------------|-----------|
| Cliente + visita + reporte + cotización | ~60% código | ✅ Fase A |
| Admin UI | 0% | 🔥 Fase B |
| Import Notion datos | 0% | 🔥 Fase B |
| Factura + cobro | 0% | Fase C |
| Taller DB43 | 0% | Fase C |
| RAG integrado en agentes | 0% | Fase C |
| Editorial | 0% | Fase D |

**No hace falta que expliques cada procedimiento** — son variantes del mismo patrón. Lo que pulimos es fiscal Ecuador, urbanizaciones, nomenclatura PCD-*, gates Playbook.

---

## 6. Roadmap "lo mejor" (sin atajos mediocres)

### Fase B — Plataforma (4-6 semanas)

1. GitHub privado + CI básico
2. **Refine admin** conectado a FastAPI (CRUD clients, quotes, inventory)
3. Import masivo Notion CSV → Mongo
4. Auth (login técnico/admin)
5. API versionada `/api/v1/`

### Fase C — Negocio completo

6. Módulo finanzas (DB31/32)
7. Módulo taller (DB43)
8. PWA campo (voz + foto)
9. RAG tool en agentes
10. PDF real (WeasyPrint/plantillas)

### Fase D — Producto modular

11. Multi-tenant (otras PIMEs)
12. Paquetes módulos on/off
13. Sync Notion API bidireccional opcional

---

## 7. Respuesta directa a tus preguntas

| Pregunta | Respuesta |
|----------|-----------|
| ¿RAG = AnythingLLM? | AnythingLLM es **una app RAG lista**. Qdrant/inneros son otros. MongoDB **no es RAG**. |
| ¿Admin panel complejo? | **Refine** en GitHub — no desde cero. 2-3 semanas con API existente. |
| ¿GitHub conectado? | **No.** Solo git local. Falta remote + push. |
| ¿Cuántos agentes? | **8 hoy**, **~16-18** en diseño final + servicios código. |
| ¿Explicar todos los flujos? | **No** — son estándar MSP; tu DBxx ya los tiene. |
| ¿Lo mejor? | Refine + FastAPI + Mongo + AnythingLLM RAG + n8n — **sin ERP genérico que obligue a migrar**.
