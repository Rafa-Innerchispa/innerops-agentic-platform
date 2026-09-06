# MCP `project_runtime_bootstrap` contract sync

Fecha: 2026-09-06  
Tarea: `ops_526a216683ba`  
Rama: `chatgpt/project-runtime-bootstrap-contract-sync-20260906`

## Problema reproducido

El runtime desplegado ya soportaba `base_ref` y `expected_sha`, pero el `main` del repositorio y la firma FastMCP de `project_runtime_bootstrap` seguían exponiendo el contrato antiguo. Como FastMCP genera el schema que consume el conector a partir de la firma del wrapper, ChatGPT no podía enviar esos campos aunque el backend supiera procesarlos.

La primera prueba de regresión reprodujo 19 fallos. No eran 19 bugs independientes: eran síntomas de cuatro capas desfasadas: runtime de `main`, wrapper FastMCP, catálogo de tools y validación/ref-SHA.

## Corrección estructural

1. `project_runtime_registry.bootstrap_runtime()` acepta `base_ref` y `expected_sha`.
2. `base_ref` se valida con un allowlist de caracteres y rechaza refs ambiguos (`..`, `@{`, `.lock`, backslash, etc.).
3. `expected_sha` acepta únicamente hexadecimal Git de 7 a 64 caracteres y se normaliza a minúsculas.
4. El helper de nodo recibe ambos campos explícitamente.
5. Si `expected_sha` no coincide con `observed_sha`, el bootstrap falla cerrado con `expected_sha_mismatch`; no marca el runtime como válido.
6. En una materialización real exitosa se registra `last_bootstrap` con nodo, ref, SHA esperado/observado, task/correlation y actor.
7. El wrapper FastMCP expone y reenvía ambos argumentos.
8. El catálogo ya no mantiene una lista específica independiente para este tool: consume `project_runtime_registry.BOOTSTRAP_INPUT_SCHEMA` como contrato canónico.

## Prevención de una nueva desincronización

`platform/tests/test_project_runtime_bootstrap_contract_sync.py` compara **igualdad exacta** entre:

- parámetros de `project_runtime_registry.bootstrap_runtime`;
- parámetros públicos del wrapper `mcp_server.project_runtime_bootstrap`;
- keywords reenviados al runtime;
- `project_runtime_registry.BOOTSTRAP_INPUT_SCHEMA`;
- schema publicado por `tool_catalog.describe_tool("project_runtime_bootstrap")`.

Agregar o quitar un campo en una sola de estas capas hace fallar la suite. Por eso este cambio no depende de que una persona recuerde editar tres listas manuales.

Esto reduce el riesgo de recurrencia, pero no convierte los tests en una ley física: la protección depende de que esta suite forme parte de los checks antes de integrar/desplegar cambios al MCP.

## Compatibilidad

Las llamadas antiguas sin `base_ref` ni `expected_sha` siguen siendo válidas; ambos defaults son cadena vacía. No se amplían roots confiables, owners permitidos ni URLs remotas. No se reduce ningún approval/guard existente.

## Pruebas

### Reproducción inicial

`python3 -m pytest platform/tests/test_project_runtime_bootstrap_contract_sync.py -q --tb=short`

Antes del fix: **19 failed**.

### Después del fix

La misma suite: **19 passed**.

Cubre además:

- refs válidos y maliciosos/ambiguos;
- SHA válido, corto y no hexadecimal;
- propagación al helper del nodo;
- mismatch de SHA fail-closed;
- compatibilidad sin ref/SHA;
- igualdad exacta runtime ↔ FastMCP ↔ catálogo.

### Regresión no relacionada detectada

La suite ampliada detectó un fallo existente en:

`platform/tests/test_dev_swarm_repo_inference.py::DevSwarmRepoInferenceTests::test_workforce_devswarm_task_resolves_to_workforce_repo_not_platform`

Se reprodujo en un worktree limpio de `main` (`e543f5f4`), por lo que **no fue causado por este cambio**. Se registró como anomalía Dev Swarm independiente, fingerprint `22f8adb709da1093ab5e439813f6962950c0ede88485efaa36893a852b893768`, repair task `ops_watchdog_22f8adb709da`.

## Verificación de despliegue requerida

Un commit verde no basta. Después de integrar/desplegar:

1. `describe_tool("project_runtime_bootstrap")` debe mostrar `base_ref` y `expected_sha`.
2. El schema visible al cliente/connector debe mostrar ambos parámetros.
3. Un `dry_run` con `base_ref` + `expected_sha` debe ser aceptado por el contrato.
4. La aceptación final de Hyperloom exige materializar el ref/SHA en AMD y comprobar `observed_sha` desde ese nodo antes de ejecutar.

No declarar el incidente cerrado si únicamente el catálogo interno está correcto pero el schema FastMCP/cliente sigue antiguo.

## Rollback

Revertir el commit de esta rama restaura el contrato previo. No requiere migración de datos. `last_bootstrap` es metadata adicional y las llamadas legacy siguen siendo compatibles durante rollback.
