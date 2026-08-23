# Auditoría definitiva de Coordinación MCP — 2026-07-17

## Veredicto

**PASS después de corrección.** El estado anterior de `ops_137a01d27f94` era **FAIL de proceso**: fue cerrado por `system` directamente desde `proposed`, sin ACK, aceptación, heartbeat, verificación ni E2E registrada.

## Causa raíz

1. `create_agent_message` solo persistía en `ralfia_agent_messages` y `codex/INBOX.md`; no normalizaba instrucciones P0/P1/OPS a `ralfia_ops_tasks`.
2. El conector autenticado ocultaba parámetros que el runtime ya soportaba (`correlation_id`, `message_type`, `payload`, `reply_to`, `idempotency_key`). Cuando faltaba `correlation_id`, se reemplazaba por `message_id`.
3. `search()` no indexaba `ralfia_ops_tasks`, `ralfia_agent_messages`, `ralfia_coordination_log` ni `ralfia_memory_items`.
4. Existía `ack_agent_message`, pero no un poll que registrara automáticamente el ACK al leer el INBOX.
5. Existía transición RACB, pero no una tool de heartbeat explícita.

## Prueba que reprodujo el fallo

- Timestamp: `2026-07-17T21:51:31.952961Z`
- Mensaje: `msg_fc12f671f2f8bbc9`
- Correlación solicitada en cuerpo: `coord-e2e-20260717-chatgpt-codex-01`
- Resultado: mensaje en Mongo + `codex/INBOX.md`; cero `ops_task`; correlación estructurada reemplazada por el message ID; búsqueda por correlación = 0.

## Corrección

- Normalización automática por `message_type=task`, `payload.auto_create_ops_task=true` o marcadores explícitos `[OPS]`, `[P0..P3]`, `[E2E P0..P3]`.
- Vínculos persistentes: `source_message_id`, `task_id`, `correlation_id`, `conversation_ref`, `related_project`.
- Mensaje canónico de tarea en INBOX conserva la misma correlación.
- `poll_agent_inbox(auto_ack=true)` separa entrega de lectura y registra ACK al poll.
- `heartbeat_ops_task` registra `last_heartbeat_at`, próximo paso, bloqueo y archivos.
- `search` recupera tareas/mensajes por ID, correlación, proyecto y términos semánticos aproximados.
- `in_progress` crea el primer heartbeat automáticamente.
- Se restauró `list_monitored_emails`, que había perdido su decorador MCP; el guard final no reporta pérdida de tools.

## E2E aislado

- MCP: `127.0.0.1:18112/mcp`
- Run: `20260717T220629Z`
- Mensaje: `msg_d7b68346b11b2b17`
- Tarea: `ops_ed44368f80da`
- Correlación: `coord-e2e-20260717T220629Z`
- HUB al distribuir: revisión `85`
- Resultado: PASS.

## E2E canónico

- MCP: `127.0.0.1:8102/mcp`
- Run: `20260717T220709Z`
- Mensaje origen: `msg_f4f3599755b5d1b7`
- Tarea: `ops_a89c26ff2927`
- Correlación: `coord-e2e-20260717T220709Z`
- Proyecto: `coordination-mcp-audit`
- Conversación: `chatgpt-daily-life-memory-20260717T220709Z`
- Creación: `2026-07-17T22:07:09.546171Z`
- HUB al distribuir: revisión `90`
- ACK automático: sí (`poll_agent_inbox`, 10 mensajes incluidos en el poll)
- `accepted`: revisión 2
- `in_progress`: revisión 3
- Heartbeat: `2026-07-17T22:07:09.686475Z`
- `verification`: revisión 4
- `completed`: revisión 5
- Recuperación: task ID = 1, correlation ID = 1, proyecto = 2, términos semánticos = 4.

## Ruta completa

`ChatGPT → MCP create_agent_message → ralfia_agent_messages → normalizador → ralfia_ops_tasks → codex/INBOX.md → bump_revision/HUB → poll+ACK → RACB states+heartbeat → search/fetch`

## Rollback

Respaldo previo al despliegue: `/home/rlopez/backups/raphiia-openai/20260717T2207Z-coordination-e2e`.

Para volver atrás: detener `ralfia-mcp.service`, restaurar los archivos respaldados, eliminar únicamente el archivo nuevo `raphiia_openai/coordination_ingest.py`, reiniciar el servicio y ejecutar el smoke test. Los registros E2E completados se conservan como auditoría; no se borran.
