# CENSO MAESTRO DE AGENTES INNEROS — CATALOGO COMPLETO v1.0
**Empresas:** PC Doctor S.A. & InnerChispa LLC  
**Fecha de Publicación:** 2026-10-22  
**Autoridad de Gobierno:** InnerOS Core Governance / Antigravity Interactive  
**Repositorio Central:** `inneros_core/platform/raphiia_openai/agents/agent_catalog.py` & `agents_pool/`

---

## 1. Visión y Estado Global del Ecosistema

El ecosistema de InnerOS cuenta con **57 agentes catalogados** distribuidos en 3 capas operativas. Este documento establece la verdad técnica y el semáforo de desarrollo para cada uno de ellos, eliminando cualquier ambigüedad entre lo que está 100% operativo con código propio, lo que está conceptualizado y lo que son esqueletos de configuración (*stubs*).

### Semáforo de Madurez Técnica
* 🟢 **Operativo con Código Propio (Functional / Tested):** Cuenta con directorio `src/`, lógica de ejecución independiente, scripts de prueba y dependencias instaladas.
* 🟡 **Diseñado / Enlace de Plataforma (Specified / Bridge):** Cuenta con contrato formal (`README.md`, `config/`), pero delega su ejecución en scripts de plataforma o herramientas del runtime central.
* 🔴 **Esqueleto de Configuración (Stub / Planned):** Existe como registro en catálogo y carpeta `config/`, pero requiere desarrollo de código y lógica propia.

---

## 2. Resumen Estadístico de la Flota

| Capa Operativa | Total Agentes | 🟢 Código Propio | 🟡 Enlace Plataforma | 🔴 Stub / Config |
| :--- | :---: | :---: | :---: | :---: |
| **I. Séquito de Negocio Core (PC Doctor & InnerChispa)** | 12 | 8 | 2 | 2 |
| **II. Infraestructura, Redes, SRE y Domótica** | 25 | 10 | 9 | 6 |
| **III. Operaciones Especiales, Personales y Sandbox** | 10 | 4 | 2 | 4 |
| **IV. Inteligencia de Oportunidades y Hackathons** | 10 | 0 | 2 | 8 |
| **TOTAL** | **57** | **22** | **15** | **20** |

---

## 3. Catálogo Detallado de los 57 Agentes

### Capa I: Séquito de Negocio Core (Operaciones Comerciales, Facturación, Taller y Campo)

| ID | Nombre Operativo | Semáforo | Rol / Especialidad | Fuentes de Datos / Herramientas |
| :--- | :--- | :---: | :--- | :--- |
| **AG-05** | **Mail Gatekeeper** | 🟢 | Triage, clasificación y archivado inteligente de correo electrónico. | Gmail API, PST Ingestion, IMAP. |
| **AG-06** | **Field Voice Processor** | 🟢 | Procesamiento de notas de voz de técnicos en campo de PC Doctor. | Whisper local, MongoDB `field_inspections`. |
| **AG-10** | **Fiscal Signer** | 🟢 | Consulta y preparación de estado fiscal en Contífico. | Contífico API v1, Firma digital. |
| **AG-11** | **Media Marketing** | 🟢 | Pipeline editorial, build-in-public y living portfolio. | Astro 5, `lab.pcdoctor.ai`, GitHub Commits. |
| **AG-13** | **Voice Inspection Extractor** | 🟢 | Extracción de datos estructurados para reportes `PCD-INF-*`. | Modelos NLP, MongoDB `ops_technical_reports`. |
| **AG-14** | **CRM Client Onboarder** | 🟢 | Alta, validación de RUC/cédula y registro de clientes. | MongoDB `parties`, SRI SRI RUC validator. |
| **AG-15** | **Inventory Cataloger** | 🟢 | Indexación y consulta de existencias y precios de hardware. | MongoDB `inventory_catalog`. |
| **AG-16** | **Quote Calculator** | 🟢 | Motor matemático de cotizaciones con márgenes y retenciones. | FastAPI `:2026`, Python Finance Engine. |
| **AG-17** | **Contifico Billing Bridge** | 🟢 | Conexión directa y emisión fiscal en Contífico SRI. | Contífico REST API (`approved_by=RAFAEL`). |
| **AG-18** | **Collections Tracker** | 🟢 | Seguimiento de cobranzas y cuentas por cobrar. | MongoDB `accounting_receivables`. |
| **AG-19** | **Sales Funnel Scout** | 🟢 | Monitoreo del embudo de ventas y prospectos. | MongoDB `sales_funnel`. |
| **AG-38** | **Vero Commercial Orchestrator** | 🟢 | Orquestadora conversacional de ventas en lenguaje natural. | Qwen 30B, WhatsApp Webhook, Fast-API. |
| **AG-46** | **Quote Agent** | 🔴 | Lane de ejecución para cotizaciones automatizadas. | Wrapper sobre `AG-16` / `AG-38`. |
| **AG-47** | **Report Agent** | 🔴 | Generación documental de informes técnicos de servicio. | Wrapper sobre `AG-13` / `AG-06`. |
| **AG-48** | **Billing Agent** | 🔴 | Orquestación de borradores de facturación para el propietario. | Wrapper sobre `AG-17` / `AG-10`. |

---

### Capa II: Infraestructura, Redes, SRE, Domótica e Integración Física

| ID | Nombre Operativo | Semáforo | Rol / Especialidad | Fuentes de Datos / Herramientas |
| :--- | :--- | :---: | :--- | :--- |
| **AG-01** | **Network Router** | 🟢 | Análisis de topología de red, switches, ping y conectividad. | UniFi Controller, SSH, SNMP. |
| **AG-02** | **Context Memory** | 🟢 | Memoria organizacional persistente en MongoDB. | `pcdoctor_swarm`, vector store local. |
| **AG-03** | **Telemetry Analyst** | 🟢 | Análisis de consumo de tokens, uso de IA y telemetría de nodos. | Logs de inferencia, métricas ROCm/Intel. |
| **AG-04** | **Doc Maker** | 🟢 | Generador de documentación técnica Markdown y reportes. | Python FPDF2, templates Jinja. |
| **AG-07** | **Notion Cosmos** | 🟢 | Sincronización bidireccional con bases de datos de Notion. | Notion API v1, `notion_bridge.py`. |
| **AG-08** | **Financial Consolidator**| 🟢 | Consolidación contable multi-cuenta (Ecuador / US Mercury). | Extractos PDF, MongoDB `accounting_ledger`. |
| **AG-09** | **Catalyst RAG Bridge** | 🟢 | Búsqueda semántica híbrida sobre manuales y base histórica. | ChromaDB / Vector Search local. |
| **AG-12** | **Project Provisioner** | 🟢 | Bindings de proyectos, clonado de repos y configuración. | Git, GitHub CLI, Linux FS. |
| **AG-20** | **Hub Dashboard Generator** | 🟢 | Generación de vistas para el dashboard operativo HUB. | Next.js / Vite / Astro endpoints. |
| **AG-25** | **RalfIA Orchestrator** | 🟡 | Orquestador maestro de la plataforma (visión global de tareas). | MCP Canonical, `ralfia_ops_tasks`. |
| **AG-26** | **Discord Bridge** | 🟢 | Canal de telemetría y SRE interactivo en servidor Discord. | Discord Bot API, WebSocket. |
| **AG-27** | **Security Health** | 🔴 | Auditoría de puertos expuestos, claves y certificados SSL. | UFW, Cloudflare Zero Trust. |
| **AG-28** | **Backup Sync** | 🔴 | Respaldo programado de MongoDB y archivos a Cloud Storage. | Rclone, Google Cloud Storage, Cron. |
| **AG-29** | **Log Ops** | 🔴 | Monitoreo y rotación de logs de systemd y contenedores. | Journalctl, rsyslog. |
| **AG-30** | **WhatsApp Agent** | 🟢 | Envío y recepción de mensajes vía Evolution API v2. | Evolution API `:8080`, Webhooks. |
| **AG-31** | **Service Recovery Watchdog**| 🟡 | Monitoreo de salud y autoreinicio de demonios fallidos. | Systemd D-Bus, `systemctl --user`. |
| **AG-32** | **Home Assistant & Devices**| 🟡 | Domótica integral: Home Assistant, Intelbras, UniFi, Broadlink. | Home Assistant REST/WS, LAN. |
| **AG-33** | **Sync Sentinel** | 🟡 | Centinela de sincronización de documentos entre nodos. | Rsync, SSH entre `.4` y `.5`. |
| **AG-34** | **KB Ingest Sentinel** | 🟡 | Ingesta automática de nuevos documentos a la base de RAG. | Inotify, watchdog filesystem. |
| **AG-35** | **Ecosystem Pulse** | 🟡 | Pulso y disponibilidad de servicios MCP en el clúster. | MCP Router, Sondas HTTP internas. |
| **AG-36** | **Deferred Tasks** | 🟡 | Ejecutor de tareas programadas en cola de espera. | `ralfia-deferred-tasks.timer`. |
| **AG-37** | **Disk Steward** | 🟡 | Prevención de saturación de disco y limpieza de cachés. | `ralfia-disk-steward.timer`. |
| **AG-40** | **Runtime Reconciler** | 🔴 | Reconciliación de dependencias entre nodo Intel y AMD. | Script de comparación de paquetes. |
| **AG-41** | **Peer Ops Executor** | 🟡 | Ejecución remota segura entre servidores físicos. | SSH keys internas, Ansible local. |
| **AG-42** | **Service Guardian** | 🔴 | Guardián preventivo contra degradación de memoria/swap. | `ralfia-service-guardian.timer`. |
| **AG-43** | **Platform Sync** | 🟡 | Replicación de repositorios de código entre máquinas. | Git remotes locales. |
| **AG-44** | **Cloud Deployer** | 🟡 | Despliegue seguro a Cloudflare Pages y Cloud Run. | Cloudflare API, gcloud SDK. |
| **AG-45** | **Local Exec** | 🔴 | Caja de arena para ejecución segura de código local. | Bubblewrap / cgroups sandbox. |
| **AG-49** | **Local Dispatcher** | 🔴 | Punto de entrada unificado para solicitudes locales. | Fast-API local router. |
| **AG-55** | **Browser Ops** | 🔴 | Automatización de navegador para scraping e inspección. | Playwright Chromium Headless. |
| **AG-59** | **DMX Orchestrator** | 🟡 | Control de iluminación física por protocolo Art-Net/DMX. | Subordinado a `AG-32` Home Assistant. |
| **AG-60** | **Universal Device Fabric**| 🟡 | Capa de abstracción para hardware IoT y sensores. | MQTT / Modbus / HTTP. |

---

### Capa III: Inteligencia de Oportunidades, Hackathons y Grants

| ID | Nombre Operativo | Semáforo | Rol / Especialidad | Fuentes de Datos / Herramientas |
| :--- | :--- | :---: | :--- | :--- |
| **AG-21** | **Hackathon Docs Harvester**| 🟡 | Extractor de reglas, rúbricas y fechas de hackathons. | Web Scraper, Markdown Parser. |
| **AG-22** | **Opportunity Collector** | 🟡 | Rastreador de grants y financiamiento para startups. | Feeds RSS, Venture Capital alerts. |
| **AG-23** | **Opportunity Analyst** | 🟡 | Evaluación de viabilidad técnica y encaje de requisitos. | Modelos LLM, Rúbricas oficiales. |
| **AG-24** | **Application Drafter** | 🟡 | Redacción de propuestas, pitches y borradores de postulación.| Plantillas de postulación, Git docs. |
| **AG-53** | **Hackathon Agent** | 🔴 | Orquestador integral de ciclo de vida de hackathón. | `ralfia-hackathon-scan.timer`. |
| **AG-54** | **Funding Credits** | 🔴 | Auditoría de consumo y vencimiento de créditos de nube. | `ralfia-funding-credits-scan.timer`. |

---

### Capa IV: Operaciones Personales, Salud y Sandbox

| ID | Nombre Operativo | Semáforo | Rol / Especialidad | Fuentes de Datos / Herramientas |
| :--- | :--- | :---: | :--- | :--- |
| **AG-39** | **Raúl (Atlas Catalog)** | 🟡 | Asistente de búsqueda de catálogo local. | SQLite, Catálogos PDF. |
| **AG-50** | **Daily Companion** | 🔴 | Resumen ejecutivo matutino para Rafael. | `ralfia-daily-companion.timer`. |
| **AG-51** | **Health Memory** | 🔴 | Registro y recordatorios de salud y bienestar. | Base de datos privada encriptada. |
| **AG-52** | **ISKCON Ops** | 🟡 | Automatización y apoyo documental para templo y comunidad.| Base documental ISKCON. |
| **AG-56** | **Sandbox Fleet** | 🔴 | Entorno de pruebas para modelos de código abierto sin filtro.| Ollama local en AMD ROCm. |

---

## 4. Prioridades de Desarrollo para Completar la Flota

1. **Paso Inmediato:** Mantener la estabilidad de los 22 agentes operativos (Capa I y redes) que sostienen la operación diaria de PC Doctor.
2. **Paso Secundario:** Dotar de lógica en Python a los esqueletos de facturación y cotizaciones (`AG-46`, `AG-47`, `AG-48`) para que dejen de ser simples wrappers y tengan autonomía total bajo supervisión humana.
3. **Paso Terciario:** Conectar los scouts de hackatones y créditos (`AG-53`, `AG-54`) para que reporten hallazgos estructurados directamente por WhatsApp al amanecer.
