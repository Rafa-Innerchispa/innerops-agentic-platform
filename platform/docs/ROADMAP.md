# Roadmap — MCP first + RalfIA Control Plane

## v0 — Plan y esqueleto (HECHO)

- [x] Repo + docs HANDOFF / MCP_CHATGPT
- [x] Mongo store (`mongo_store.py`)
- [x] FastAPI `:8101` status/health
- [x] Decisión: MCP sí, OpenAI API / Custom GPT no

## v1 — MCP funcional (SIGUIENTE CHAT)

- [x] `raphiia_openai/mcp_server.py` (FastMCP)
- [x] Tools: `save_message`, `save_idea`, `search`, `fetch`, `get_context_summary`
- [x] `run_mcp.sh` puerto 8102
- [ ] ngrok / gateway ruta pública `/mcp`
- [ ] Conectar ChatGPT Developer Mode
- [ ] Smoke: guardar idea desde chat → ver en Mongo

## v1.5 — Control plane seguro

- [x] Documentar RalfIA como AI control plane / integration fabric
- [x] Marcar puertos reservados y regla de no interferencia
- [x] Corregir referencias legacy `8099` -> `8101` donde aplique
- [ ] Definir tools MCP por dominio de negocio
- [ ] Definir auditoria uniforme en `raphiia_openai_sync_log`
- [ ] Preparar conector para Cursor/Gemini/Notion usando la misma fuente MCP

## v2 — Editorial

- [ ] `save_pipeline_draft`, `list_pipeline`
- [ ] Aprobar → `editorial_posts` (DB15)
- [ ] Cola `social_destinations` (DB16)

## v3 — Redes + ops

- [ ] APIs LinkedIn / Meta / X (prioridad Rafael)
- [ ] Backup DR verificado para este repo
- [ ] GitHub privado
- [ ] Eliminar código legacy REST OpenAI/Actions si obsoleto

## v4 — Continuidad y venta como producto

- [ ] Nodo AMD standby con MCP minimo + datos restaurables
- [ ] Backups cifrados a Google Cloud Storage
- [ ] Runbook de failover RalfIA → AMD → Google Cloud
- [ ] Plantilla Docker/Compose para vender servidores CRM adaptables
- [ ] Separacion multi-tenant para clientes futuros
