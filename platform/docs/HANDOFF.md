# HANDOFF — RaphiIA-OpenAI (leer en chat nuevo)

**Actualizado:** 2026-06-30  
**Autor:** Rafael López / InnerChispa  
**Carpeta:** `/home/rlopez/projects/raphiia-openai`  
**Estado:** MCP implementado en :8102 — convertir en RalfIA Control Plane sin tocar servicios existentes

---

## Decisión final (no desviar)

| Tema | Decisión |
|------|----------|
| Integración ChatGPT | **MCP (Model Context Protocol)** — como Notion, no Custom GPT |
| Coste API OpenAI (`sk-`) | **NO usar en el servidor** — el LLM es el chat de ChatGPT (tu suscripción) |
| Custom GPT + Actions | **Descartado** como camino principal (demasiado rígido) |
| `/api/v1/chat` con OpenAI API | **Descartado** — no implementar salvo debug explícito |
| MongoDB | **Compartida** `pcdoctor_swarm` (datos reales + conversaciones nuevas) |
| Puerto HTTP status | **8101** |
| Puerto MCP (Streamable HTTP) | **8102** → URL pública `…/mcp` vía ngrok |
| Respaldos | Disaster recovery Ralphi IA (Mongo incluye colecciones bridge) |

---

## Qué quiere Rafael

1. Chatear en **ChatGPT normal** (todas las funciones del plan).
2. **Conexión transparente** tipo Notion: guardar y consultar su base.
3. **Sin coste extra** de API OpenAI en el backend — solo Mongo + tools MCP.
4. Alimentar `ideas`, `editorial_pipeline`, conversaciones `raphiia_openai_*`.
5. Proyecto aislado de hackathons (`:8097`, `:8098`).
6. RalfIA como **control plane** central para ChatGPT, Cursor, Gemini, Perplexity, Notion, n8n y futuros servicios.
7. No interferir con puertos/proyectos existentes: los hackatones deben seguir operativos.

---

## Arquitectura objetivo

```
ChatGPT (chat normal + Developer Mode Connector)
        │  HTTPS
        ▼
ngrok / gateway  →  MCP :8102/mcp  (FastMCP, Streamable HTTP)
        │
        ▼
MongoDB pcdoctor_swarm
  ├── raphiia_openai_messages      (conversaciones bridge)
  ├── raphiia_openai_conversations
  ├── ideas (DB11)
  ├── editorial_pipeline (DB48)
  └── clients, … (lectura contexto real)

FastAPI :8101  →  solo /status, /health (ops, smoke tests)
```

---

## Ecosistema

```
/home/rlopez/projects/innerspark-swarm-os-cursor-local/  ← Swarm :8100, Ralphi assistant
/home/rlopez/projects/raphiia-openai/                     ← ESTE PROYECTO :8101 + MCP :8102
/home/rlopez/projects/chutes-deposit-agent/               ← :8098 (no tocar)
/home/rlopez/projects/uipath-copilot/                     ← :8097 (no tocar)
```

Servidor: `192.168.1.4` (`ralphi-ia-ver-10`)

Documento de control plane: [`RALFIA_CONTROL_PLANE.md`](RALFIA_CONTROL_PLANE.md).

Operación segura y alertas de los servidores `.4` y `.5` por WhatsApp:
[`WHATSAPP_SAFE_OPS.md`](WHATSAPP_SAFE_OPS.md).

---

## Próximos pasos (orden para el chat nuevo)

### P0 — MCP servidor
- [x] `pip install fastmcp` — `raphiia_openai/mcp_server.py` implementado
- [x] Tools: `save_message`, `save_idea`, `search`, `fetch`, `get_context_summary`, `save_pipeline_draft`, `list_pipeline`
- [x] Tools `search` + `fetch` incluidos
- [x] `./run_mcp.sh` en `:8102`

### P1 — Conectar ChatGPT (una vez)
- [x] HTTPS vía gateway `:5188/raphiia-mcp` → `:8102/mcp` (ngrok compartido)
- [ ] ChatGPT → Settings → Connectors → **Developer Mode** ON
- [ ] Add custom connector → URL MCP + auth (API key header)
- [ ] Probar: “Guarda esta idea…” / “¿Qué ideas tengo?”

### P2 — Editorial
- [ ] Tool `create_pipeline_draft` → DB48 (texto que trae ChatGPT, sin LLM en servidor)
- [ ] Tool `list_pipeline` / approve → DB15 (fase 2)

### P3 — Ops
- [ ] Confirmar `raphiia-openai` en `backup_disaster_recovery.sh`
- [ ] Repo GitHub privado
- [ ] Limpiar `routes.py` legacy (Actions/OpenAI chat) si ya no se usan

### P4 — RalfIA Control Plane
- [x] Documentar arquitectura central y reglas de no interferencia
- [ ] Exponer MCP por HTTPS estable sin mover puertos existentes
- [ ] Agregar tools de negocio por dominio: clientes, proyectos, oportunidades, hackatones, tareas
- [ ] Definir auditoria obligatoria para escrituras de agentes
- [ ] Preparar contingencia AMD + Google Cloud

---

## Prompt para chat nuevo

```
Workspace: /home/rlopez/projects/raphiia-openai (SSH 192.168.1.4)
Lee docs/CONEXION.md, docs/HANDOFF.md, docs/MCP_CHATGPT.md.
Trabaja SOLO en el servidor — no SSH desde Windows.
MCP :8102 implementado — conectar ChatGPT Connectors vía ngrok.
Sin OPENAI sk- en servidor. Mongo pcdoctor_swarm.
No tocar puertos ni proyectos de hackaton sin aprobacion explicita.
```

---

## Historial

- v0 inicial tenía OpenAI API + Custom GPT Actions → **reemplazado por MCP**.
- Rafael prefiere chat normal ChatGPT + conexión tipo Notion, versátil y sin API de pago en backend.
- 2026-07-19 P0 WhatsApp: health canónico con evidencia, ledger anti-loop,
  conversación owner compartida entre líneas, botones de confirmación tipados y SSH
  peer-ops restringido entre `.4` y `.5`. Ver `docs/WHATSAPP_SAFE_OPS.md`.
- AG31/dual-node monitor queda como adaptador temporal. `systemd` es el supervisor;
  n8n podrá normalizar incidentes cuando exista contrato de eventos. No duplicar
  diagnóstico o remediación con un LLM.
