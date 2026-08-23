# Daily Life Memory MCP

## Objetivo

Memoria de vida diaria versionada y respaldada por evidencia, dentro de la base existente `pcdoctor_swarm`. Mantiene separadas las conversaciones, memorias históricas, estado actual, entidades, pendientes y timeline.

## Pipeline de `finalize_conversation`

`Conversation → Session Summary → Entity Extraction → Emotion Analysis → Decision/Intention Extraction → Context Rule Learning → Pending Detection → Duplicate Search → Memory Builder → Current State Update → Timeline Update`

El pipeline acepta análisis estructurado generado por ChatGPT. Si no se proporciona, usa un extractor determinista y conservador; no llama APIs externas ni incurre en costos.

## Colecciones

| Colección | Función |
|---|---|
| `raphiia_openai_messages` | Mensajes fuente idempotentes |
| `daily_life_conversations` | Sesiones y resultado de finalización |
| `ralfia_memory_items` | Memorias activas; amplía la colección existente |
| `ralfia_memory_versions` | Snapshots antes de cada actualización/corrección |
| `daily_life_current_state` | Estado actual por owner + state key |
| `daily_life_entities` | Personas, proyectos y lugares |
| `daily_life_pending_items` | Pendientes abiertos/resueltos |
| `daily_life_timeline` | Eventos históricos |
| `daily_life_memory_audit` | Auditoría de cambios |

## Memoria

Cada memoria incluye `memory_id`, `owner_id`, `kind`, `title`, `body`, `privacy_scope`, `project`, `entities`, `source_conversation_id(s)`, `source_message_ids`, `fingerprint`, `version`, `status`, timestamps y calibración epistémica: `confidence`, `confidence_label`, `confidence_basis`, `owner_validated` y `epistemic_status`.

Tipos independientes: `fact`, `opinion`, `hypothesis`, `interpretation`, `decision`, `emotion`, `intention`, `context_rule`, `pattern` y `summary`.

### Interpretación segura y patrones

- Una frase ambigua sin marcador verificable no se promueve automáticamente a `fact`: se guarda como `interpretation` de baja confianza y queda marcada para revisión.
- Las correcciones explícitas del owner pueden crear `context_rule`, por ejemplo una regla de humor o lenguaje compartido dentro de una relación. Estas reglas se recuperan con prioridad antes de interpretar conversaciones futuras.
- `intention` (lo que Rafael quiere o planea) se mantiene separada de `decision` (algo que ya decidió o acordó).
- Un `pattern` requiere evidencia de al menos dos conversaciones distintas o confirmación explícita del owner. Una sola conversación produce como máximo un `pattern_candidate` revisable.
- Emociones y patrones son observaciones personales, no diagnósticos clínicos. La IA no debe afirmar que conoce objetivamente la mente, intención de terceros o causa interna de una conducta.
- `correct_memory` conserva la versión anterior, registra historial estructurado de corrección y puede añadir una regla contextual aprendida a la misma colección de memorias; no crea un sistema paralelo.

### Reutilización de arquitectura

| Capacidad | Decisión |
|---|---|
| Conversaciones, evidencia, deduplicación y versiones | KEEP: se conservan sin colecciones nuevas |
| Personas, proyectos, lugares, estado actual y timeline | ADAPT: se añade contexto relacional e intenciones |
| Hechos, opiniones, hipótesis, interpretaciones y emociones | ADAPT: se añade confianza explícita y clasificación conservadora |
| Reglas de contexto y patrones longitudinales | ADD dentro de `ralfia_memory_items` mediante nuevos `kind` |

La deduplicación usa fingerprint exacto y similitud Jaccard conservadora. Una coincidencia exacta agrega evidencia sin crear otro registro; una memoria suficientemente similar se actualiza y versiona.

## Privacidad

Scopes obligatorios:

- `PRIVATE_PERSONAL`
- `PRIVATE_HEALTH`
- `PRIVATE_RELATIONSHIPS`
- `PRIVATE_FAMILY`
- `PRIVATE_FINANCIAL`
- `INTERNAL_WORK`
- `PROJECT`
- `PUBLIC`

Reglas:

- Solo el actor `RAFAEL` puede recuperar scopes `PRIVATE_*`.
- Otros agentes quedan limitados a `INTERNAL_WORK`, `PROJECT` y `PUBLIC`, aun si solicitan scopes privados.
- Las tools de memoria personal usan scopes OAuth de mínimo privilegio: lectura (`ralfia:memory:read`), escritura (`ralfia:memory:write`), finalización (`ralfia:memory:finalize`) y acceso privado (`ralfia:private_memory`). Las operaciones administrativas (corrección, olvido, revisión y migración) conservan `ralfia:admin`. `actor` es una etiqueta de auditoría, no la frontera de autorización.
- Un guard determinista rechaza contenido con indicios de salud, relaciones, familia o finanzas si se intenta guardar como `PUBLIC` o `PROJECT`.
- El panel no incrusta datos. Su API exige `X-RalfIA-Memory-Review`, comparado con `DAILY_MEMORY_REVIEW_TOKEN` o, como fallback interno, `MCP_API_KEY`.
- Ningún endpoint público, demo, hackathon o fixture recibe memorias privadas. Las pruebas usan datos sintéticos y scope privado.

El acceso mediante `X-API-Key` se considera principal administrativo interno y debe mantenerse fuera de agentes o clientes no confiables. Antes de exponer el módulo fuera del control interno, usar OAuth administrativo individual y rotación del API key compartido.

### OAuth de ChatGPT

Después de cambiar scopes, el token anterior conserva únicamente sus permisos originales. El cliente ChatGPT registrado solicita ahora `ralfia:memory:read`, `ralfia:memory:write`, `ralfia:memory:finalize` y `ralfia:private_memory`; Rafael debe reautorizar una vez el conector para emitir un token nuevo. No se deben ampliar tokens existentes directamente.

## Tools

1. `save_conversation_batch`
2. `finalize_conversation`
3. `save_memory`
4. `update_memory`
5. `search_memory`
6. `get_current_state`
7. `update_current_state`
8. `get_person_context`
9. `correct_memory`
10. `forget_memory`
11. `resolve_pending_item`
12. `timeline`
13. `get_memory_review_queue`
14. `migrate_daily_memory`

## Corrección, olvido y pendientes

- `correct_memory` conserva la versión anterior, registra historial estructurado y puede guardar una `context_rule` validada para evitar repetir la interpretación errónea.
- `forget_memory` exige owner, reemplaza contenido por `[FORGOTTEN]`, purga versiones y opcionalmente borra mensajes fuente vinculados.
- `resolve_pending_item` cambia el estado y agrega la resolución al timeline.

## Panel

Ruta interna: `/daily-memory` en `ralfia-ops-panel`. Permite revisar, filtrar, corregir, olvidar y resolver pendientes. El shell HTML es público dentro del panel, pero la API de contenido siempre requiere token.

## Migración

1. Ejecutar `migrate_daily_memory(dry_run=true)`.
2. Respaldar `ralfia_memory_items` con `scripts/backup_daily_memory.py`.
3. Ejecutar `migrate_daily_memory(dry_run=false)`.
4. Verificar índices y conteos.
5. Ejecutar E2E con datos sintéticos.

La migración es aditiva: asigna IDs, privacy scope, kind, versión, estado, evidencia vacía y fingerprint. No cambia el texto ni reclasifica contenido legacy.

## Rollback

- Restaurar archivos desde el backup de release.
- Reiniciar `ralfia-mcp.service` y `ralfia-ops-panel.service`.
- Los campos/colecciones Mongo nuevos son compatibles con el código anterior y pueden conservarse.
- Si se requiere rollback de datos, restaurar el dump previo de `ralfia_memory_items`; no borrar conversaciones ni mensajes sin aprobación.

## E2E canónico 2026-07-17

- MCP: `127.0.0.1:8102/mcp`
- Run: `20260717T222941Z`
- Conversation: `dlm-e2e-20260717T222941Z`
- Mensajes: 4 insertados
- Memorias independientes: 6
- Entidades: 3 (PERSON, PROJECT, PLACE)
- Versión después de update + correction: 3
- Current State: versión 1
- Timeline: 2 eventos
- Pendiente: `pending_07d048c7533f4988`, resuelto
- Búsqueda owner privada: 1 resultado
- Búsqueda agente no autorizado: 0 resultados
- Intento `PRIVATE_HEALTH → PUBLIC`: rechazado
- Resultado: PASS
- Migración legacy aplicada: 2 documentos; verificación posterior: 0 pendientes de migrar.
- Backup de datos: `/home/rlopez/backups/raphiia-openai/20260717T2230Z-daily-memory/ralfia_memory_items.pre-migration.json` (14 documentos antes de migrar).
