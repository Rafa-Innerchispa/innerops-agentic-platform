# AGENT ROSTER v1.0 — Flota Operativa Canónica InnerOS
**Empresas:** PC Doctor S.A. & InnerChispa LLC  
**Fecha de Publicación:** 2026-10-21  
**Autoridad de Gobierno:** InnerOS Core Governance / Antigravity Interactive  
**Mapeo de Referencia:** Notion `16-innerspark innerOS (PC Doctor Stage)` (Page ID: `372cb2de-eb0f-807f-bb46-eafb5ee03aa8`) & `HUB/AGENT_FLEET_LOCAL.md`

---

## 1. Visión y Propósito de la Flota

La Flota de Agentes de Negocio de InnerOS conforma un séquito operativo autónomo, coordinado y local-first, diseñado para asumir la carga operativa recurrente de **PC Doctor** (servicios de hardware, CCTV, redes, soporte en Guayaquil) e **InnerChispa** (inteligencia artificial, automatización supervisada, living portfolio y hackathons).

### Principios Inquebrantables de Ejecución
1. **Local-First (Zero Cloud Spend):** Los agentes ejecutan en los servidores físicos locales `.4` (Intel) y `.5` (AMD ROCm / Ollama local). No consumen créditos en la nube de Cursor, OpenAI ni Anthropic salvo autorización explícita (`owner_approved=True`).
2. **Gobernanza y Puertas de Aprobación (Gates):** Operaciones críticas (emisión de facturas fiscales SRI en Contífico, gastos bancarios, mutaciones de firmware/red o borrado destructivo) requieren confirmación humana explícita del propietario (`approved_by=RAFAEL`).
3. **Auditabilidad Canónica:** Cada acción, mensaje, cotización o reporte genera evidencia estructurada en MongoDB (`pcdoctor_swarm`), trazabilidad con hash y estado verificable.

---

## 2. El Elenco Operativo de los 6 Agentes de Negocio

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       ORQUESTACIÓN HUMANO-AGENTE                            │
│                      Rafael (Owner) / WhatsApp / MCP                        │
└──────────────┬───────────────────────────────┬──────────────────────────────┘
               │                               │
    ┌──────────▼──────────┐         ┌──────────▼──────────┐
    │     AG-38 VERO      │         │   AG-05 GATEKEEPER  │
    │  Orquestadora Negocio│        │  Filtro Comunicaciones│
    └──────────┬──────────┘         └──────────┬──────────┘
               │                               │
 ┌─────────────┼───────────────┬───────────────┼───────────────┐
 │             │               │               │               │
 ▼             ▼               ▼               ▼               ▼
AG-46         AG-47           AG-48           AG-11           AG-54
VENTAS        TÉCNICO         CONTABLE        EDITORIAL       SCOUTS
Cotizaciones  Informes        Cashflow & FAC  Living Story    Hackathons &
Smart Quoter  Voz & FieldOps  Contífico SRI   Web & Redes     Financiamiento
```

---

### Agente 1: El Filtro de Entrada / Mail Gatekeeper
* **ID Interno:** `AG-05` (`AG-05_email_gatekeeper`) / `ralfia-email-triage`
* **Nombre Operativo:** Mail Gatekeeper & Communication Dispatcher
* **Rol Principal:** Puerto de control de todas las comunicaciones entrantes (Gmail, Outlook/PST, buzones de soporte y clientes). Clasifica correos, filtra spam/ruido, extrae leads calificados y detecta incidentes urgentes.
* **Límites y Gobernanza:**
  - **Permitido:** Lectura de bandejas IMAP/Gmail, clasificación automática, asignación de etiquetas, generación de resúmenes estructurados.
  - **Prohibido:** Responder correos a clientes o proveedores sin borrador aprobado; marcar correos como leídos/archivados si contienen requerimientos comerciales abiertos.
* **Fuentes de Datos:**
  - Gmail API / PST Ingest (`run_local_ingest_fleet.py`)
  - MongoDB: `pcdoctor_swarm.email_triage`, `parties`
* **Bandeja / Mailbox Asignada:** `mailbox_gatekeeper@pcdoctor.ai` / `inbox_triage`
* **Execution Lane:** `email_intelligence` / `email_triage`
* **Timer y Cadencia:** Timer continuo / cada 15 min (`ralfia-email-owner-digest.timer`, `ralfia-ingest-vkr@.service`)
* **Modelo / Runner Local:** Ollama `gemma:2b` / `qwen2.5:3b` en nodo Intel (.4).

---

### Agente 2: El Escudo Financiero / Cashflow & Contable
* **ID Interno:** `AG-48` (`AG-48_billing_agent`) / `AG-17` (`AG-17_contifico_billing_bridge`) / `AG-08` (`AG-08_financial_consolidator`)
* **Nombre Operativo:** Cashflow Matrix & Fiscal Bridge
* **Rol Principal:** Control predictivo de liquidez de PC Doctor e InnerChispa LLC, cuentas por cobrar/pagar, pasarela Stripe US (Mercury), emisión de facturas fiscales Contífico / SRI con autorización `approved_by=RAFAEL`, regla de los 7 días (alertas predictivas de cortes SRI, IESS, cheques y tarjetas).
* **Límites y Gobernanza:**
  - **Permitido:** Calcular balances, leer facturas de compra, sincronizar catálogo Contífico en modo lectura, emitir alertas de liquidez y proyecciones.
  - **Gate Estricto (SRI / Contífico):** Emisión real de facturas electrónicas hacia el SRI bloqueada por defecto (`dry_run=True`); requiere confirmación `approved_by=RAFAEL` vía WhatsApp o MCP.
* **Fuentes de Datos:**
  - Contífico API v1 (lectura de clientes, productos, comprobantes)
  - MongoDB: `accounting_ledger`, `accounting_receivables`, `credits_store`
  - Estados de cuenta bancarios PDF (Mercury, Banco Guayaquil/Pichincha)
* **Bandeja / Mailbox Asignada:** `finanzas@pcdoctor.ai` / `billing_mailbox`
* **Execution Lane:** `local_dev_swarm` / `internal_bounded_local`
* **Timer y Cadencia:** Diario 06:15 UTC (`ralfia-daily-contifico-sync.timer`) + semanal.
* **Modelo / Runner Local:** Qwen 2.5 Coder 32B / Python deterministic finance ledger.

---

### Agente 3: El Copiloto de Campo / Voice Supervisor & Operaciones PC Doctor
* **ID Interno:** `AG-47` (`AG-47_report_agent`) / `AG-13` (`AG-13_voice_inspection_extractor`) / `AG-06` (`AG-06_field_voice_processor`)
* **Nombre Operativo:** The Voice Supervisor & Technical Operations Copilot
* **Rol Principal:** Sustitución definitiva de hojas de cálculo manuales. Asistencia técnica y supervisión de campo para trabajos en exteriores y taller en Guayaquil (Torres del Río, La Ensenada, Torres Bellidia). Transcribe notas de voz de técnicos, actualiza órdenes de trabajo (`PCD-ORD-*`), genera informes técnicos de inspección (`PCD-INF-*`), y provee pinouts/manuales históricos.
* **Límites y Gobernanza:**
  - **Permitido:** Transcribir audio con Whisper local, mapear notas de campo a partidas de trabajo, redactar informes técnicos en PDF y Markdown.
  - **Prohibido:** Modificar el estado de un ticket a "entregado" sin evidencia fotográfica o firma de recepción de cliente.
* **Fuentes de Datos:**
  - Whisper local (nodo AMD ROCm / Intel)
  - MongoDB: `ops_technical_reports`, `pcdoctor_store`, `field_inspections`
  - Base histórica indexada de manuales y procedimientos (18,404 documentos)
* **Bandeja / Mailbox Asignada:** `soporte@pcdoctor.ai` / `fieldops_mailbox`
* **Execution Lane:** `agent_ops` / `local_dev_swarm`
* **Timer y Cadencia:** Reactivo por Webhook de Audio / PWA + consolidación diaria 18:00 GYT.
* **Modelo / Runner Local:** Whisper Large v3 local + Qwen local en AMD (.5).

---

### Agente 4: El Creador de Tracción / Build-In-Public & Editorial
* **ID Interno:** `AG-11` (`AG-11_media_marketing_agent`) / `astro_editorial_publisher`
* **Nombre Operativo:** Living Story & Growth Engine (Build-In-Public)
* **Rol Principal:** Transforma el trabajo técnico diario, commits y victorias operativas en historias públicas observables. Publica automáticamente en el living portfolio de Astro (`https://lab.pcdoctor.ai/historia-en-vivo`), alimenta las colas de LinkedIn e Instagram, y audita copies para conectar con los dolores de los clientes.
* **Límites y Gobernanza:**
  - **Límite de Privacidad Estricto (Publication Boundary):** Nunca publica razonamiento interno de agentes, prompts, credenciales, tokens, IPs privadas, balances bancarios confidenciales ni datos de clientes (PII).
  - **Permitido:** Publicar fichas verificadas, métricas públicas, historias de builds y evidencias de commits en repositorios autorizados.
* **Fuentes de Datos:**
  - MongoDB: `innerchispa_web_content`, `editorial_publish_logs`
  - Git Commits & Tags de proyectos aprobados
  - Feed canónico `public/data/build-story.json`
* **Bandeja / Mailbox Asignada:** `editorial@innerchispa.us` / `editorial_mailbox`
* **Execution Lane:** `local_dev_swarm` / `antigravity_interactive`
* **Timer y Cadencia:** Cada 10 minutos (`ralf-astro-editorial-sync.timer`) y cola de redes (`ralfia-editorial-worker.service`).
* **Modelo / Runner Local:** Astro 5 SSG + Python Publisher / Node 20.

---

### Agente 5: El Cerrador Automatizado / Conversational Closer & Ventas
* **ID Interno:** `AG-46` (`AG-46_quote_agent`) / `AG-16` (`AG-16_quote_calculator`) / `AG-38` (`AG-38_vero_commercial_orchestrator`)
* **Nombre Operativo:** Vero Conversational Closer & Smart Quoter
* **Rol Principal:** Orquestación y embudo comercial inteligente. Escucha solicitudes en lenguaje natural ("dile a Vero que cotice a FEMAR cámaras"), consulta el stock real de inventario (`search_inventory_catalog`), revisa cotizaciones históricas, formula preguntas clave sobre necesidades y genera cotizaciones formales numeradas (`PCD-COT-YYYY-MM-###`) listas para enviar por WhatsApp o PDF.
* **Límites y Gobernanza:**
  - **Permitido:** Consultar catálogo de precios, aplicar márgenes de contribución preconfigurados, duplicar cotizaciones anteriores, generar borradores de cotización en PDF.
  - **Prohibido:** Otorgar descuentos superiores al 10% sin aprobación explícita de Rafael; prometer tiempos de entrega sin validación de stock físico.
* **Fuentes de Datos:**
  - MongoDB: `ops_quote_drafts`, `inventory_catalog`, `parties`
  - WhatsApp Business Webhook / voz.pcdoctor.ai
* **Bandeja / Mailbox Asignada:** `ventas@pcdoctor.ai` / `commercial_mailbox`
* **Execution Lane:** `agent_ops` / `local_dev_swarm`
* **Timer y Cadencia:** Reactivo por mensaje (WhatsApp/Voz) + Recordatorio diario de seguimiento a las 08:00 GYT (`ralfia-backlog-steward.timer`).
* **Modelo / Runner Local:** Qwen 30B en AMD (.5) + Smart Quoter FastAPI (:2026).

---

### Agente 6: El Cazador de Capital & Scouts Continuos
* **ID Interno:** `AG-54` (`AG-54_funding_credits`) / `AG-53` (`AG-53_hackathon_agent`) / `AG-22` (`AG-22_opportunity_collector`)
* **Nombre Operativo:** Capital Hunter & Continuous Scout Fleet
* **Rol Principal:** Monitoreo continuo de oportunidades externas: convocatorias de hackatones internacionales (Devpost, Lablab, AMD AI League, XPRIZE), grants de aceleración, créditos de computación en la nube (AWS, Google Cloud, OpenAI, Anthropic) y fechas límite de postulación.
* **Límites y Gobernanza:**
  - **Permitido:** Web scraping pasivo de convocatorias públicas, monitoreo de correos de confirmación de créditos, actualización del registro de oportunidades (`reward_accounts`, `funding_opportunities`).
  - **Prohibido:** Enviar aplicaciones o firmar términos legales sin autorización previa del propietario.
* **Fuentes de Datos:**
  - Feeds de Devpost, Lablab, GitHub Hackathons
  - Correos de adjudicación de créditos (AWS Activate, Google Cloud for Startups)
  - MongoDB: `reward_accounts`, `hackathon_portfolio`
* **Bandeja / Mailbox Asignada:** `scouts@innerchispa.us` / `scouts_mailbox`
* **Execution Lane:** `local_dev_swarm` / `internal_bounded_local`
* **Timer y Cadencia:** Diario 08:30 UTC (`ralfia-hackathon-scan.timer`) y 09:00 UTC (`ralfia-funding-credits-scan.timer`).
* **Modelo / Runner Local:** Python Crawlers locales + Ollama.

---

## 3. Matriz Resumen de Configuración Técnica

| Agente | Nombre | Mailbox | Timer / Trigger | Lane | Modelo Local Principal |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AG-05** | Mail Gatekeeper | `mailbox_gatekeeper@pcdoctor.ai` | `ralfia-email-owner-digest.timer` (cada 15m) | `email_intelligence` | Ollama `gemma:2b` (Intel) |
| **AG-48** | Cashflow Matrix & Billing | `finanzas@pcdoctor.ai` | `ralfia-daily-contifico-sync.timer` (06:15 UTC) | `local_dev_swarm` | Python Ledger / Qwen |
| **AG-47** | Voice Supervisor / Campo | `soporte@pcdoctor.ai` | Webhook Audio PWA / Continuo | `agent_ops` | Whisper Large + Qwen (AMD) |
| **AG-11** | Living Story / Growth | `editorial@innerchispa.us` | `ralf-astro-editorial-sync.timer` (cada 10m) | `local_dev_swarm` | Astro 5 + Node 20 / Intel |
| **AG-46** | Vero Conversational Closer | `ventas@pcdoctor.ai` | Reactivo WhatsApp + `ralfia-backlog-steward` | `agent_ops` | Qwen 30B / FastAPI (:2026) |
| **AG-54** | Capital Hunter & Scouts | `scouts@innerchispa.us` | `ralfia-hackathon-scan` (08:30) / `funding` (09:00) | `local_dev_swarm` | Python Crawlers / Ollama |

---

## 4. Próximos Pasos para Despliegue Operativo
1. **Canalización WhatsApp:** Asociar cada agente al router de mensajes de WhatsApp mediante prefijos y palabras clave de activación.
2. **Requeue Local de Tareas:** Activar el despachador de Dev Swarm en nodo AMD (.5) para procesar las tareas pendientes de código sin consumir saldo cloud.
3. **Página de Handoff en Notion:** Publicar este Roster en el espacio central de Notion vinculado con `16-innerspark innerOS (PC Doctor Stage)`.
