# RaphiIA-OpenAI — instrucciones Cursor

**Proyecto:** puente **MCP** ChatGPT ↔ MongoDB RalfyIA (contenido + conversaciones)  
**Servidor:** `192.168.1.4` (`ralphi-ia-ver-10`) — **workspace remoto obligatorio**  
**Ruta:** `/home/rlopez/projects/raphiia-openai`  
**Puertos:** status `:8101` · MCP `:8102` — **NO tocar** `:8100` Swarm, `:8098` Chutes, `:8097` UiPath, `:8099` Funding Hub

## Conexión (LEER PRIMERO)

> **Coordinación (Cursor + Codex):** [`/home/rlopez/data/ai_coordination/00_LEER_PRIMERO.md`](/home/rlopez/data/ai_coordination/00_LEER_PRIMERO.md)

> **NO trabajar desde Windows local.** Abrir Cursor vía **Remote SSH** → `rlopez@192.168.1.4` → carpeta del repo.

1. [`docs/CONEXION.md`](docs/CONEXION.md) ← **conexión servidor + arranque**
2. [`docs/CURSOR_SSH.md`](docs/CURSOR_SSH.md) ← **configurar Cursor Remote SSH**
3. [`docs/ARRANQUE_RAPIDO.md`](docs/ARRANQUE_RAPIDO.md) ← copy/paste arranque
4. [`docs/HANDOFF.md`](docs/HANDOFF.md) — arquitectura y decisiones
5. [`docs/MCP_CHATGPT.md`](docs/MCP_CHATGPT.md) — ChatGPT Connectors
6. [`docs/INTEGRATION.md`](docs/INTEGRATION.md) — Mongo DBxx
7. [`docs/BACKUPS.md`](docs/BACKUPS.md)

## Reglas duras (agentes)

- **Coordinación:** leer y actualizar `/home/rlopez/data/ai_coordination/` cada sesión; registrar en Mongo vía `scripts/log_coordination.py`.
- **Workspace = servidor** `/home/rlopez/projects/raphiia-openai` vía SSH remoto. **No** levantar SSH desde Windows en cada comando.
- **Integración ChatGPT = MCP Connectors** (tipo Notion). No Custom GPT como camino principal.
- **NO usar `OPENAI_API_KEY`** en el servidor — evita coste API; el LLM es ChatGPT del usuario.
- **MongoDB** `pcdoctor_swarm` compartida — no crear DB nueva.
- Colecciones bridge: `raphiia_openai_*` — no borrar `chat_messages` de Swarm.
- Tools MCP: **`search`** y **`fetch`** obligatorios (ChatGPT Connectors).
- `.env` nunca a git. Español en docs.

## Arranque (terminal del servidor)

```bash
cd /home/rlopez/projects/raphiia-openai
source venv/bin/activate
cp -n .env.example .env   # MCP_API_KEY + Mongo
./run.sh          # :8101 status
./run_mcp.sh      # :8102 /mcp
./scripts/setup_ngrok.sh   # otra terminal → ChatGPT HTTPS
```

## Código clave

| Archivo | Rol |
|---------|-----|
| `raphiia_openai/mcp_server.py` | FastMCP tools → Mongo |
| `raphiia_openai/mongo_store.py` | Persistencia |
| `raphiia_openai/auth_middleware.py` | Auth `X-API-Key` |
| `raphiia_openai/app.py` | Health `:8101` |
| `raphiia_openai/routes.py` | Legacy REST — deprecar |

## Prompt chat nuevo

```
Workspace: /home/rlopez/projects/raphiia-openai (SSH 192.168.1.4)
Lee docs/CONEXION.md, docs/HANDOFF.md, docs/MCP_CHATGPT.md.
Trabaja SOLO en el servidor — no SSH desde Windows.
Implementa/mantén MCP :8102 + Mongo pcdoctor_swarm. Sin OPENAI sk-.
```


## Autonomía operativa obligatoria (Codex / Cursor / AntiGravity / Gemini)

Para tareas owner-approved dentro del scope asignado, el agente debe **avanzar sin pedir permiso por decisiones reversibles**. Esta regla existe para evitar pausas artificiales y preguntas de rutina durante trabajo técnico.

- `question_budget = 0` para decisiones reversibles.
- Leer/inspeccionar, crear o usar worktrees aislados, ejecutar tests, reintentar comandos, corregir fallos normales, elegir defaults seguros, preservar diffs, commit y push de la rama propia están preautorizados cuando forman parte de la tarea.
- Ante un fallo recuperable: registrar intento, diagnosticar, aplicar corrección reversible, reintentar automáticamente y probar al menos un fallback seguro antes de declarar `BLOCKED`.
- Reportar progreso por heartbeat/status. Un reporte de progreso no es una solicitud de permiso.
- `ACK` significa únicamente lectura. Después del ACK, reclamar/iniciar la tarea y continuar hasta estado terminal o bloqueo real.
- Si hay ambigüedad, elegir la alternativa reversible más segura que preserve trabajo existente y continuar.
- Interrumpir al owner sólo por: acción destructiva/irreversible; secreto o credencial inaccesible; gasto externo no preautorizado; aprobación a nivel de cuenta; o mutación hardware/red/firmware fuera del scope aprobado.
- Un bloqueo real debe incluir evidencia, intentos realizados, al menos un fallback seguro probado y la acción humana concreta requerida.
- Nunca usar `reset --hard`, `clean`, force-push, borrado de trabajo ajeno ni cruces de lanes como forma de “resolver” una ambigüedad.

Override excepcional: una tarea puede declarar explícitamente `allow_owner_questions=true` o `interaction_mode=interactive`; sin ese override, rige el modo autónomo anterior.
