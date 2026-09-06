# MCP `project_runtime_bootstrap` contract sync

Fecha: 2026-09-06
Tarea: `ops_526a216683ba`
Rama de integración: `chatgpt/project-runtime-bootstrap-contract-sync-post-durable-20260906`
Base integrada: Codex durable spine `d4926dd7d04fd8b1749d4104209411fee6338374`.

## Problema reproducido

La capacidad quedó desincronizada entre varias superficies. El runtime desplegado en los nodos ya había recibido soporte para `base_ref` y `expected_sha`, mientras que el schema visible al cliente de ChatGPT todavía mostraba el contrato antiguo. Además, al auditar el commit durable spine publicado por Codex (`d4926dd7`), se encontró una divergencia adicional: su wrapper FastMCP y ambos catálogos ya exponen `base_ref`/`expected_sha`, pero `project_runtime_registry.bootstrap_runtime()` en ese mismo commit todavía conserva la firma vieja. Invocar esa ruta desde el código publicado habría producido una incompatibilidad de argumentos.

La causa estructural es mantener manualmente el mismo contrato en más de una capa.

## Corrección estructural

1. `project_runtime_registry.bootstrap_runtime()` acepta `base_ref` y `expected_sha`.
2. `base_ref` se valida con un conjunto acotado de caracteres y se rechazan refs ambiguos (`..`, `@{`, `.lock`, backslash, etc.).
3. `expected_sha` acepta únicamente hexadecimal Git de 7 a 64 caracteres y se normaliza a minúsculas.
4. El helper de nodo recibe ambos campos explícitamente.
5. Si `expected_sha` no coincide con `observed_sha`, el bootstrap falla cerrado con `expected_sha_mismatch`.
6. En materialización real exitosa se registra `last_bootstrap` con nodo, ref, SHA esperado/observado, task/correlation y actor.
7. `BOOTSTRAP_INPUT_SCHEMA` vive en `project_runtime_registry.py` como contrato canónico.
8. Los dos catálogos (`inneros_core_runtime/mcp_catalog/tool_catalog.py` y el catálogo legacy `inneros_core_runtime/tool_catalog.py`) consumen esa misma constante para `project_runtime_bootstrap`.
9. El wrapper FastMCP ya presente en `d4926dd7` mantiene exactamente los mismos campos y los reenvía al runtime.

## Prevención de nueva desincronización

`platform/tests/test_project_runtime_bootstrap_contract_sync.py` compara igualdad exacta entre:

- parámetros de `project_runtime_registry.bootstrap_runtime`;
- parámetros públicos del wrapper `mcp_server.project_runtime_bootstrap`;
- keywords reenviados al runtime;
- `project_runtime_registry.BOOTSTRAP_INPUT_SCHEMA`;
- schema publicado por `mcp_catalog.tool_catalog.describe_tool("project_runtime_bootstrap")`;
- uso de la misma fuente canónica en el catálogo legacy.

Agregar o quitar un campo en una sola capa rompe la suite. El cambio deja de depender de que una persona recuerde editar varias listas a mano.

Esto reduce la probabilidad de recurrencia, pero la garantía operativa depende de ejecutar esta suite antes de integrar/desplegar cambios MCP.

## Compatibilidad y seguridad

Las llamadas antiguas sin `base_ref` ni `expected_sha` siguen válidas; ambos defaults son cadena vacía. No se amplían roots confiables, owners permitidos, remotos, shell ni approvals. La materialización continúa delegada al helper tipado y acotado del nodo.

## Integración con el trabajo de Codex

Codex reportó PASS del durable spine en `d4926dd7`, con Temporal, NATS JetStream y OpenTelemetry, y lo promovió a Intel/AMD. Ese commit es la base de esta rama para evitar revertir o sobreescribir su trabajo. Esta corrección no toca Temporal/NATS/OTel, scheduler, A2A ni provider execution fabric salvo las pruebas que se ejecuten para detectar regresiones.

Durante la revisión independiente se confirmó que ambos nodos MCP están activos y `runtime_consistent=true` para el conjunto que monitorea `get_mcp_fleet_status`. También se observó Memory Curator procesando lotes reales. Esa evidencia no sustituye las pruebas específicas de este contrato.

## Pruebas requeridas antes del cierre

1. Suite anti-drift `test_project_runtime_bootstrap_contract_sync.py` PASS.
2. Suite durable spine / provider execution / scheduler relevante PASS.
3. `compileall` PASS.
4. `git diff --check` PASS.
5. Commit y push de la rama de integración.
6. Despliegue controlado a Intel y AMD con backup/rollback.
7. `describe_tool("project_runtime_bootstrap")` debe mostrar `base_ref` y `expected_sha`.
8. El schema realmente visible al cliente/connector debe mostrar ambos parámetros. No basta con el catálogo interno.
9. Dry-run de bootstrap con `base_ref` + `expected_sha` aceptado.
10. Luego, aceptación física Hyperloom: materializar el SHA exacto en AMD, comprobar `observed_sha` desde el nodo y ejecutar allí.

## Regresión no relacionada detectada

La suite ampliada de la rama anterior detectó un fallo preexistente en:

`platform/tests/test_dev_swarm_repo_inference.py::DevSwarmRepoInferenceTests::test_workforce_devswarm_task_resolves_to_workforce_repo_not_platform`

También falla sobre `main` limpio `e543f5f4`, por lo que no fue causado por este cambio. Está registrado como anomalía independiente con fingerprint `22f8adb709da1093ab5e439813f6962950c0ede88485efaa36893a852b893768` y repair task `ops_watchdog_22f8adb709da` asignada a Codex. No se mezcla su reparación con este parche de contrato.

## Rollback

Revertir el commit de esta rama restaura el contrato previo. No requiere migración de datos. `last_bootstrap` es metadata adicional y las llamadas legacy siguen siendo compatibles durante rollback.
