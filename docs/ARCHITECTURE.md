# Arquitectura Ralfi IA Platform — MCP, conectores, agentes

**Fecha:** 2026-08-05 · **Estado:** Fase 1 (estructura + migración gradual desde `raphiia-openai`)

---

## Respuesta corta

| Pregunta | Respuesta |
|----------|-----------|
| ¿El MCP es código? | **Sí.** Es un servidor Python (FastAPI) que expone *tools* vía protocolo MCP. Hoy vive en `raphiia-openai/raphiia_openai/mcp_server.py`. |
| ¿Hay una carpeta MCP? | **Objetivo:** `packages/ralfi_ia/kernel/mcp/`. Hoy todo está mezclado en un solo paquete de ~146 archivos. |
| ¿Dónde van los conectores? | **Dentro de la plataforma:** `packages/ralfi_ia/connectors/` — librerías reutilizables (Notion, Contifico, WhatsApp…). |
| ¿Dónde van los agentes? | **Fuera de la plataforma**, en pool compartido: `~/inneros_core/agents_pool/` (o futuro repo `ralfi-ia-agents`). Cualquier servicio los lee por YAML. |
| ¿Qué va en `ralfi-ia-platform`? | Todo **código importable** que usa el ecosistema ops: kernel MCP, conectores, módulos de negocio, entrypoints de servicios. |
| ¿Qué queda fuera? | Servicios systemd (solo units en `infra/`), datos (`~/data/`), personal, ISKCON, hackathons, Docker base. |

---

## Tres capas (regla de oro)

```
┌─────────────────────────────────────────────────────────────┐
│  CAPA 3 — SERVICIOS (procesos systemd, puertos)             │
│  infra/systemd/*.service  →  services/*/main.py (delgado)   │
└───────────────────────────────┬─────────────────────────────┘
                                │ importa
┌───────────────────────────────▼─────────────────────────────┐
│  CAPA 2 — PLATAFORMA (ralfi-ia-platform, código Python)     │
│  kernel/ · connectors/ · modules/ · coordination/             │
└───────────────────────────────┬─────────────────────────────┘
                                │ lee config
┌───────────────────────────────▼─────────────────────────────┐
│  CAPA 1 — AGENTES (pool externo, YAML + lógica opcional)    │
│  ~/inneros_core/agents_pool/AG-XX_*/config/agent.yaml       │
└─────────────────────────────────────────────────────────────┘
```

**Servicio ≠ código.** Un servicio (`ralfia-mcp.service`) solo arranca un entrypoint; la lógica vive en la Capa 2.

---

## Árbol objetivo `ralfi-ia-platform/`

```
ralfi-ia-platform/
├── companies/                    # Multi-tenant (entity.yaml, branding)
│   └── ENTITIES_CANONICAL.yaml
│
├── packages/
│   └── ralfi_ia/                 # Paquete Python único (hoy: raphiia_openai)
│       ├── kernel/               # Núcleo plataforma
│       │   ├── mcp/              # ← AQUÍ EL MCP
│       │   │   ├── server.py     # (hoy mcp_server.py)
│       │   │   ├── catalog/      # tool_catalog, params
│       │   │   ├── profiles.py   # perfiles acotados (quoter, contifico…)
│       │   │   ├── fleet.py      # dual-nodo .4/.5
│       │   │   └── diagnostics.py
│       │   ├── portal/           # portal_bridge, ops_routes
│       │   ├── auth/             # OAuth, middleware
│       │   ├── settings.py
│       │   └── mongo_store.py
│       │
│       ├── connectors/           # ← AQUÍ LOS CONECTORES (APIs externas)
│       │   ├── contifico/        # bridge, normalize, ledger
│       │   ├── notion/           # bridge, webhook, coordination
│       │   ├── whatsapp/         # evolution_client, conversational
│       │   ├── google_drive/     # ingest → Qdrant
│       │   ├── email/            # IMAP/SMTP, monitor
│       │   ├── home_assistant/   # ha_client
│       │   └── linkedin/         # editorial social
│       │
│       ├── modules/              # ← LÓGICA DE NEGOCIO (MOD-*)
│       │   ├── accounting/       # accounting_store, AP/AR
│       │   ├── quoting/          # document_engine, quoteops bridge
│       │   ├── inventory/
│       │   ├── pcdoctor_ops/     # clientes, sitios, visitas
│       │   └── editorial/        # hub LinkedIn/imágenes
│       │
│       └── coordination/         # Runtime coordinación (NO definiciones AG-xx)
│           ├── live.py           # mandatory reads, estado vivo
│           ├── agent_messages.py # buzones Mongo inter-IA
│           ├── racb/             # locks, protocolo
│           └── registry.py       # lee agents_pool externo
│
├── services/                     # Entrypoints DELGADOS (solo arrancan apps)
│   ├── mcp/                      # python -m → :8102
│   ├── app/                      # health + editorial → :8101
│   ├── portal/                   # ops panel → :2002
│   ├── voice/                    # PWA voz → :8200
│   └── auth/                     # OAuth → :8103
│
├── infra/
│   └── systemd/                  # Solo .service / .timer (sin lógica)
│
├── scripts/                      # Mantenimiento (sync, ingest, verify)
└── docs/
```

---

## Dónde está hoy vs dónde va

| Componente | Hoy (legacy) | Objetivo |
|------------|--------------|----------|
| MCP server | `raphiia_openai/mcp_server.py` | `packages/ralfi_ia/kernel/mcp/server.py` |
| Tool catalog | `raphiia_openai/mcp_catalog/` | `kernel/mcp/catalog/` |
| Contifico | `contifico_bridge.py` (raíz paquete) | `connectors/contifico/` |
| Notion | `notion_bridge.py` | `connectors/notion/` |
| WhatsApp | `notifications/evolution_client.py` | `connectors/whatsapp/` |
| Accounting | `operational/accounting_store.py` | `modules/accounting/` |
| PC Doctor ops | `operational/pcdoctor_store.py` | `modules/pcdoctor_ops/` |
| Agentes AG-xx | `~/inneros_core/agents_pool/` | **Sin mover** — pool externo |
| Agent registry | `raphiia_openai/agents/registry.py` | `coordination/registry.py` |
| QuoteOps app | repo `ralphiia-quoteops/` | `modules/quoting/quoteops/` (sub-app :8765) |
| Portal UI | `innerspark-swarm-os-cursor-local/portal/` | Fase 2: mover UI o submodule |

---

## Agentes: ¿dentro o fuera?

**Recomendación: FUERA de la plataforma**, en pool compartido.

```
/home/rlopez/inneros_core/agents_pool/     ← canónico hoy (AG-01…AG-36)
    AG-07_notion_cosmos_orchestrator/
        config/agent.yaml                  # identidad, tools permitidas, entity_id
        config/tasks.yaml
        src/logic.py                       # opcional: código del agente
        README.md
```

**Por qué externo:**

1. **Un agente lo usa cualquier cosa** — MCP, hackathon, script shell, n8n, QuoteOps.
2. **No acoplar agentes al deploy MCP** — cambiar AG-17 no requiere reiniciar MCP si solo es YAML.
3. **Ya funciona así** — `agents/registry.py` lee `INNEROS_AGENTS_POOL` (default `~/inneros_core/agents_pool`).

**Futuro opcional:** repo Git `ralfi-ia-agents` con el mismo árbol, clonable en cualquier nodo.

**Qué SÍ va en plataforma sobre agentes:**

- `coordination/registry.py` — descubre y valida agentes del pool
- `coordination/agent_messages.py` — buzón Mongo
- `agents/whatsapp_agent.py` — runtime embebido en MCP (excepción: agente siempre activo)

---

## MCP: qué es y qué contiene

El **MCP (Model Context Protocol)** en Ralfi IA tiene dos partes:

### 1. Servidor MCP (`ralfia-mcp.service`, :8102)

- Archivo principal: `mcp_server.py` (~1800 líneas)
- Registra **117+ tools** desde catálogo
- Enruta llamadas a conectores y módulos
- Perfiles acotados (`mcp_profiles.py`): `quoter`, `contifico`, `msp_core`…

### 2. Tools (dispersas hoy, agrupadas mañana)

| Origen tool | Carpeta objetivo |
|-------------|------------------|
| Contifico queries | `connectors/contifico/` |
| Notion sync | `connectors/notion/` |
| WhatsApp send | `connectors/whatsapp/` |
| Accounting AP/AR | `modules/accounting/` |
| PC Doctor clients | `modules/pcdoctor_ops/` |
| QuoteOps proxy | `modules/quoting/quoteops_bridge.py` |
| HA domótica | `connectors/home_assistant/` |

**Regla:** un conector expone funciones; el MCP las registra como `@mcp.tool()`. El conector **no** es un servicio aparte (salvo QuoteOps que tiene su propio :8765).

---

## Qué va DENTRO vs FUERA del repo plataforma

### DENTRO `ralfi-ia-platform`

| Qué | Por qué |
|-----|---------|
| Paquete Python (`ralfi_ia`) | Importado por todos los servicios |
| Conectores | APIs reutilizables |
| Módulos MOD-* | Lógica multi-empresa |
| Entrypoints `services/` | Arranque uvicorn |
| Units systemd | Referencia deploy |
| `companies/` | Config tenant |
| Scripts ops | verify_entities, sync contifico |

### FUERA (otros repos / rutas)

| Qué | Dónde | Por qué |
|-----|-------|---------|
| **Agent pool YAML** | `~/inneros_core/agents_pool/` | Compartido por MCP, hackathons, scripts |
| **Datos runtime** | `~/data/`, Mongo, Qdrant | No versionar |
| **Coordinación docs** | `~/data/ai_coordination/` | Memoria humana/IAs, no código |
| **Personal Rafael** | `ralfi-ia-personal/` | Universo B separado |
| **ISKCON** | `iskcon/` | Vertical espiritual |
| **Hackathons** | `hackathons/*` | Pilotos aislados, reutilizan MCP vía HTTP |
| **Infra dual-nodo** | `ralfi-ia-infra/` | rsync, sync, sentinels shell — no lógica negocio |
| **Docker base** | compose en infra | Mongo, Qdrant, Evolution, Ollama |
| **Portal UI legacy** | `innerspark-swarm-os-cursor-local/` | Fase 2 — UI separada del backend |

---

## Servicios systemd (Capa 3)

Los servicios **no contienen lógica**. Solo definen:

```ini
# infra/systemd/ralfia-mcp.service
ExecStart=%h/projects/ralfi-ia-platform/.venv/bin/python -m ralfi_ia.services.mcp
WorkingDirectory=%h/projects/ralfi-ia-platform
Environment=INNEROS_AGENTS_POOL=%h/inneros_core/agents_pool
```

| Servicio | Entrypoint | Puerto |
|----------|------------|--------|
| `ralfia-mcp` | `services/mcp` | 8102 |
| `ralfia-app` | `services/app` | 8101 |
| `ralfia-portal` | `services/portal` | 2002 |
| `ralfia-voice-gateway` | `services/voice` | 8200 |
| `ralfia-quoteops` | `modules/quoting/quoteops` | 8765 |
| `ralfia-smart-quoter` | submodule smart-quoter | 2026 |

---

## Plan migración (sin romper producción)

### Fase 1 — Esta semana (estructura)
- [x] Repo GitHub `ralfi-ia-platform`
- [x] `companies/` + entidades canónicas
- [x] Este documento + skeleton carpetas
- [ ] Symlinks desde skeleton → código legacy (imports siguen funcionando)

### Fase 2 — Próximas 2 semanas (mover código)
- Renombrar `raphiia_openai` → `ralfi_ia` con shims de compatibilidad
- Mover conectores a subcarpetas (un PR por conector)
- Extraer entrypoints a `services/`

### Fase 3 — Consolidación
- Absorber `ralphiia-quoteops` en `modules/quoting/`
- Portal UI unificado
- Repo opcional `ralfi-ia-agents` desde `inneros_core/agents_pool`

---

## Variables de entorno clave

| Variable | Default | Uso |
|----------|---------|-----|
| `INNEROS_AGENTS_POOL` | `~/inneros_core/agents_pool` | Ruta pool agentes |
| `MCP_DISPLAY_NAME` | `Ralphi-IA-MCP` | Nombre técnico conector (legacy OK) |
| `RALFI_IA_COMPANIES_DIR` | `companies/` | Config multi-tenant |

---

*Ver también:* [NOMENCLATURA.md](nomenclatura/NOMENCLATURA.md) · [SERVICIOS.md](nomenclatura/SERVICIOS.md) · [ECOSYSTEM.md](ECOSYSTEM.md)
