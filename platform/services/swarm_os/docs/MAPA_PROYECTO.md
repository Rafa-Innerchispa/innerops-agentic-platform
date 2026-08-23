# MAPA MAESTRO — InnerSpark Swarm-OS Cursor Local

**Última actualización:** 2026-06-09 (esquema v2 + docs onboarding modelo IA)  
**Servidor:** `ralphi-ia-ver-10` / **`192.168.1.4`** (MongoDB y API viven aquí, no en tu Windows)  
**Acceso red:** `docs/ACCESO_RED.md`  
**Proyecto activo:** desarrollo local con Cursor (NO mezclar con Google AI Studio hackathon)

---

## 1. Visión (qué estamos construyendo)

**Cerebro operativo local** para PC Doctor S.A.: autonomía real en el servidor, sin depender de créditos cloud.

Flujo de campo que duele hoy:

```
Técnico en urbanización → dictado/fotos/audio
  → RUC o cédula → consulta SRI (API Intuito)
  → crear/actualizar cliente en MongoDB
  → bitácora de hallazgos + pendientes
  → informe técnico (PDF-first)
  → cotización (inventario + DB38 matemática)
  → revisión (gates Playbook V2)
  → enviar correo / aviso WhatsApp (n8n)
```

**Dolor principal (prioridad 1):** inspección + recopilar info + cliente + informe + cotizar.  
**Hackathon (11):** lo llevas en Google AI Studio por separado.  
**Este proyecto:** independencia total, MongoDB real, agentes locales.

---

## 2. Dónde vive cada cosa (no perder el mapa)

### Proyecto ACTIVO (programar aquí)

```
/home/rlopez/projects/innerspark-swarm-os-cursor-local/
├── AGENTS.md                     ← LEER PRIMERO (cualquier modelo IA)
├── docs/
│   ├── INSTRUCCIONES_AGENTE.md   ← Onboarding sin chat anterior
│   ├── ESQUEMA_MONGODB_DBxx.md  ← DB01–DB52 → colecciones Mongo
│   ├── CANON_CORRECCIONES_DBxx.md
│   ├── SOPS_LOGICA_OPERATIVA.md   ← SOPs Master (Playbook)
│   ├── RELACIONES_Y_FLUJOS.md   ← Relaciones + gates para código
│   ├── ACCESO_RED.md            ← 192.168.1.4 vs 127.0.0.1
│   ├── MAPA_PROYECTO.md          ← ESTE ARCHIVO
│   ├── RECUPERACION_DESASTRE.md
│   └── GITHUB_SEGURO.md
├── scripts/
│   └── migrate_v1_to_v2.py       ← Legacy inspections → v2
├── api/main.py                   ← FastAPI puerto 8100
├── agents/
│   ├── crew.py                   ← orquestación CrewAI
│   └── roles.py                  ← 8 agentes definidos
├── tools/
│   ├── ruc_api.py                ← SRI vía Intuito (cédula/RUC)
│   ├── transcribe.py             ← Whisper :9001
│   ├── file_reader.py            ← PDF + fotos (llava)
│   ├── mongo.py                  ← base de datos (legacy + v2)
│   ├── schema.py                 ← índices, secuenciales DB40
│   ├── crew_tools.py             ← tools para agentes
│   └── pdf_generator.py          ← exportables .md (→ PDF después)
├── .env                          ← credenciales (RUC, Ollama, etc.)
└── README.md                     ← guía rápida
```

### Otros proyectos en el servidor (NO mezclar)

| Ruta | Herramienta / origen | Para qué |
|------|----------------------|----------|
| `/home/rlopez/inneros/` | Antigravity / hackathon | Band of Agents, LiteLLM, Qdrant |
| `/home/rlopez/agentes/` | Cursor (prototipo) | DevOps bash simple |
| `/home/rlopez/ai-server-v2/` | Ralphi | Docker: Ollama, Qdrant, n8n, Postgres |
| `/home/rlopez/whisper-service/` | Docker | Transcripción audio :9001 |
| Windows `swarm-os.zip` | Google AI Studio | Referencia; NO copiar lógica rota |
| Windows `antigravity_workspace/inneros-swarm` | Antigravity | Archivo / importar plantillas |

### Infra compartida (Docker en 192.168.1.4)

| Servicio | Puerto | Estado |
|----------|--------|--------|
| MongoDB | 27017 | OK |
| Ollama | 11434 | OK |
| Whisper | 9001 | OK |
| n8n | 5678 | OK (correo/WhatsApp pendiente conectar) |
| Qdrant | 6333 | OK (Ralphi/inneros) |
| LiteLLM | 4000 | OK (inneros) |
| Swarm-OS API | 8100 | OK |

---

## 3. Los 8 agentes (roles)

| Agente | Responsabilidad | Estado |
|--------|-----------------|--------|
| Director | Orquesta el flujo | Esqueleto OK |
| Campo | Estructura visita, hallazgos | Esqueleto OK |
| Cliente | RUC/cédula → SRI → MongoDB | **API RUC OK** |
| Bitácora | Pendientes, evidencia | Esqueleto OK |
| Informes | Informe técnico Playbook | Esqueleto OK |
| Cotizador | Inventario → líneas → totales | Esqueleto OK |
| Revisor | Gates anti-placeholders | Básico |
| Comunicaciones | Borrador correo/WhatsApp | Sin n8n aún |

---

## 4. Qué YA funciona (verificado)

- [x] MongoDB `pcdoctor_swarm` con colecciones base
- [x] API FastAPI `:8100`
- [x] Consulta RUC/cédula API Intuito (credenciales públicas guía)
  - ASOPAR `0991386866001` → OK
  - Cédula `0914832423` → LOPEZ GUTIERREZ HECTOR RAFAEL / DOMOTIKA
- [x] Transcripción audio (Whisper local)
- [x] Lectura PDF + descripción imágenes (llava)
- [x] CrewAI + Ollama `neural-chat:7b`
- [x] Export informe/cotización en Markdown
- [x] Inventario demo sembrado (DB26 equivalente)

---

## 5. Qué FALTA (orden de programación)

### Fase A — Flujo de campo usable (siguiente)

- [x] Esquema MongoDB v2 documentado (`docs/ESQUEMA_MONGODB_DBxx.md`)
- [x] Correcciones canónicas DB41/DB12 (`docs/CANON_CORRECCIONES_DBxx.md`)
- [x] `tools/schema.py` — índices + `next_serial()` DB40
- [x] `scripts/migrate_v1_to_v2.py` — migración idempotente
- [x] Onboarding modelo IA (`AGENTS.md`, `docs/INSTRUCCIONES_AGENTE.md`)
- [x] Estructura MongoDB creada (`python scripts/init_mongodb_schema.py`) — 62 colecciones
- [ ] Migración opcional solo si hay datos legacy en `inspections`
- [x] Conectar `crew.py` a flujo v2 (`workflow_v2.py`: DB42→45→27/38→documents→gates)
- [ ] Probar flujo end-to-end ASOPAR o DOMOTIKA
- [ ] Gates DB41 en agente Revisor
- [ ] PDF real (HTML → PDF, no solo .md)

### Fase B — Operación diaria

5. **Inventario real** en MongoDB (importar DB26 / CSV → `inventory_items`)
6. ~~Hub cliente~~ — `client_hubs` en v2 (al crear cliente)
7. ~~Secuenciales~~ — `next_serial()` en schema.py
8. **n8n webhook** correo + WhatsApp (Evolution API :8082 ya existe)

### Fase C — Pulido

9. Pegar **Playbook V2** en `docs/playbook-v2.md`
10. Importar **plantillas** desde Antigravity / swarm-os.zip (solo templates)
11. UI simple o integración Cursor/MCP para llamar API
12. Credenciales RUC propias cuando las tengas

### NO hacer ahora

- Copiar lógica rota de Google AI Studio
- Portar todas las validaciones Notion DBxx
- Mezclar con `inneros` hackathon

---

## 6. Reglas de negocio (Playbook V2 — resumen)

Fuente de verdad futura: `docs/playbook-v2.md` (pendiente pegar desde Notion).

Reglas críticas ya acordadas:

- **Hub-first:** no documentos sueltos sin cliente
- **DB38 manda:** matemática de cotización
- **PDF-first:** entregable limpio al cliente
- **Gate anti-placeholders:** no @today, no N/A inventado
- **Cliente:** DB04 → contacto DB05 → Hub → trabajos DB29 → informe DB45 → cotización DB27/DB38

---

## 7. Endpoints API (referencia rápida)

```
GET  /status
POST /ruc/lookup                    {"id": "0914832423"}
POST /inspection/quick              {"input": "visita..."}
POST /inspection/{id}/upload        multipart file
POST /inspection/{id}/upload-audio  multipart audio → Whisper
POST /inspection/{id}/analyze-file {"path": "...", "question": "..."}
POST /inspection/start              {"input": "...", "inspection_id": "..."}
POST /inspection/{id}/notify        correo/WhatsApp vía n8n
GET  /schema/registry               mapa DBxx → colecciones
GET  /schema/flows                  flujos SOP + gates
POST /gates/client/duplicate-check  anti-duplicación DB04
POST /gates/quote/{id}/ready-to-send   gate Listo para enviar
POST /gates/quote/{id}/validate-rules  reglas DB41
```

**Desde Windows:** reemplazar host por `http://192.168.1.4:8100`

---

## 8. Credenciales (.env)

```
RUC_API_USER=          # ver .env (Intuito) — NUNCA pegar contraseña en docs
RUC_API_PASS=          # solo en .env local, ignorado por git
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=neural-chat:7b
WHISPER_URL=http://127.0.0.1:9001
MONGO_URI=mongodb://127.0.0.1:27017/
MONGO_DB=pcdoctor_swarm
```

---

## 9. Decisiones tomadas (no re-debatir)

| Decisión | Razón |
|----------|-------|
| Proyecto nuevo limpio, no extender `agentes/` | Evitar sopa de carpetas |
| MongoDB = verdad operativa | Independencia de Notion |
| Código fuera de Docker | Ollama/Mongo en Docker; app en host |
| No copiar Google AI Studio | Lógica con fallas; solo plantillas |
| API Intuito para RUC | Ya probada con cédula y RUC reales |
| CrewAI para agentes | Roles + tools + razonamiento |
| n8n para correo/WhatsApp | No reinventar tuberías |

---

## 10. Git y respaldos (desastre)

**Documento completo:** [`docs/RECUPERACION_DESASTRE.md`](RECUPERACION_DESASTRE.md)

| Mecanismo | Cubre Swarm-OS | Notas |
|-----------|----------------|-------|
| Git repo propio en este proyecto | Código (sin commit aún) | `git init` hecho aquí |
| `backup_disaster_recovery.sh` | **SÍ** | `/home/rlopez/projects/backup_disaster_recovery.sh` |
| Ralphi → Google Drive 3x/día | NO | Solo gateway/postgres/n8n |
| `backup_system.sh` diario | NO | Solo AnythingLLM + inneros .env |

Ejecutar respaldo: `/home/rlopez/projects/backup_disaster_recovery.sh`

---

## 11. Cómo no perder contexto (cambio de modelo IA)

1. **`AGENTS.md`** + **`docs/INSTRUCCIONES_AGENTE.md`** — prompt de arranque para modelo nuevo
2. **Este archivo** — visión y fases
3. **`docs/ESQUEMA_MONGODB_DBxx.md`** — datos y relaciones
4. **MongoDB** — persiste aunque cambies de modelo
5. **`.env`** — credenciales en disco (no en git)
6. **Chats Cursor** — efímeros; decisiones van a los docs anteriores

---

## 12. Próximo paso inmediato (cuando digas "programa")

**Fase A.1:** Ejecutar y depurar flujo completo con:

```
Cédula 0914832423 + notas de inspección de campo (cámaras, cables, switches)
→ cliente en Mongo
→ informe técnico
→ cotización 3 ítems
→ archivos exportados
```
