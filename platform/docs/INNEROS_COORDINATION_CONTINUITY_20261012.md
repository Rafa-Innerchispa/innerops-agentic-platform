# InnerOS: estado canónico, continuidad y plan de cierre
**Corte verificado:** 2026-10-12 05:00 UTC (00:00 America/Guayaquil).  
**Destino:** documentación persistente en `main` de `Rafa-Innerchispa/innerops-agentic-platform`.  
**IMPORTANTE:** estados en este archivo son una instantánea, no certificación de que la situación seguirá igual. Recuperar telemetría viva antes de actuar. **No contiene credenciales.**

## 1. Objetivo del propietario (no perder)
InnerOS debe tomar una orden en ChatGPT, voz o WhatsApp y **ejecutarla** usando el agente adecuado, interno o externo, sin intervención manual en una laptop, con cambios de código reales, verificación, posibilidad de rollback y cierre durable. No son suficientes mensajes ACK, modelos cargados, servicios activos, IDs `claimed` ni un PR fusionado. El propietario quiere un *único sistema* y no un router v2 ni otra instancia de Temporal.

Política de modelos vigente:
- **Internos/local-first:** AMD ROCm/vLLM (Qwen), Intel/Ollama y futuros nodos para programación frecuente, tests y automatizaciones recurrentes; coste incremental mínimo.
- **Externos especializados:** Cursor/Composer 2.5 Fast, Codex con sus modelos, Antigravity/Gemini con los suyos, mediante créditos ya disponibles cuando sus capacidades aporten valor. No bloquearlos exigiendo Qwen. Ningún cargo nuevo inesperado sin aprobación.
- **Despliegue seguro:** dos nodos AMD `ralfiia-amd` e Intel `ralphi-ia-ver-10` con mirrors comprobados, sin alterar hardware/red/firmware y sin descartar worktrees o commits locales.

## 2. Hechos confirmados en el corte y NO comprobados
- GitHub `main`: `af0ba8d467f1575220fc82dc1152b9cf8b08131a`; HEAD sirve como referencia histórica, no como SHA runtime automáticamente comprobado.
- PR #142 (ejecutor local de releases) fusionado; eso no certifica por sí solo el despliegue.
- **PR #144** <https://github.com/Rafa-Innerchispa/innerops-agentic-platform/pull/144>, draft abierto, no fusionado. Commit candidato `75236f3709f8db4ef3a7be66afee787c75127eb2`, branch `chatgpt/p0-executor-evidence-contract-20261012`. Incorpora `platform/inneros_core_runtime/execution_receipts.py`, tests, modificaciones del wrapper headless de Cursor y CI; no está en `main` ni desplegado. Falta revisión, pruebas y extender contrato a los demás proveedores.
- **`ops_d45afea0028e`**: canario enviado por ChatGPT a Cursor headless AMD, mensaje `msg_15d4ec07906fa8b0`, `claimed`, proceso iniciado `2026-10-12T04:40:34Z`, sin `headless_execution_finished_at` ni evidencia final en corte; no enviar segundo proceso sobre su worktree hasta confirmar PID y lease.
- **`ops_f46a62594c73`**: reparación integral P0 en Cursor headless **Intel**, mensaje `msg_d68c93eb36a5ba97`, correlación `inneros-p0-universal-execution-gates-pr144-20261012`, `in_progress`; inició `2026-10-12T04:51:54Z`, no tiene cierre ni ejecución validada aún. Seguimiento **sin nueva task** enviado por ChatGPT `msg_ae3adaad921fc6a4`: auditar dos routers Qwen, recuperación local y benchmarks.
- Canarios previos **`ops_bb2b8a9eb081` (AMD) y `ops_e0b587b1098e` (Intel)**: reportaron `headless_last_result.ok=true`, `primary=local_sdk`, y archivos/commits en worktree; permanecieron `in_progress` por gate Temporal `Cursor completion prohibited: require commit_sha + objective_paths or test_results.exit_code=0`. No confundir ejecución física SDK con aprobación y cierre.
- Los mensajes de Cursor ahora obtienen ACK automático; el inbox consumer **solo es mensajería**, el autopilot headless y sus workers realizan ejecución real. Contrato probado parcialmente desde ChatGPT: `message -> ACK -> claim -> proceso arrancado`; falta terminal `completed` con evidencia.
- Temporal responde; Mongo `pcdoctor_swarm` es bus y proyección de estado. El scheduler Dev Swarm `enabled`, configuración 4, **last_tick_started=0, last_executor_executed=0, workers=0** al corte, con fallos anteriores `local_model_transport_failure:amd_vllm_unreachable`.
- AMD observado: Qwen `QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ` en contenedor `inneros-vllm-qwen3-coder-30b-awq`; servicio escuchando en `127.0.0.1:8000`, GPU actividad ~3%, VRAM reservada ~95%, RAM disponible ~20 GiB; gobernador actual recomienda **4 coding/inference workers** (no es benchmark probado de 4 peticiones de modelo). Intel con observabilidad por peer tuvo helper RC=126; requiere validación del host por canal permitido.
- AG-60 `ops_5ffa304380cc`: cerrada en coordinación con timers y muestras Mongo registradas; su cierre de Temporal no fue certificado de manera independiente.
- Algunos componentes de A2A/LangGraph/NATS/OTel solo tienen integración parcial/no certificada. Flags vivos vistos: `INNEROS_TEMPORAL_ENABLED=true`, `INNEROS_NATS_ENABLED=false`, `INNEROS_OTEL_ENABLED=false`.

## 3. Router local CANÓNICO: rectificación del diagnóstico (12 oct ~05:35 UTC)
El scheduler usa `from raphiia_openai import local_model_router`; **eso NO implica que cargue el archivo legado** `platform/raphiia_openai/local_model_router.py`. El `platform/raphiia_openai/__init__.py` es un shim de compatibilidad que define `__path__ = inneros_core_runtime.__path__`, por lo que la importación normal de `raphiia_openai.local_model_router` resuelve el código de **`platform/inneros_core_runtime/local_model_router.py`**. El router canónico ya implementa `_intel_ollama_fallback`.

La hipótesis anterior, según la cual Dev Swarm utilizaba una copia sin fallback, fue **refutada al inspeccionar el shim**. Se conserva como antecedente histórico, NO como tarea para modificar el router legado. La verdadera causa de errores `amd_vllm_unreachable` sigue **sin comprobarse en el proceso productivo**: verificar en AMD e Intel el `module.__file__`, URL activa, túneles/env, `GET /v1/models`, modelos disponibles Ollama `/api/tags`, logs de llamadas y el resultado real del fallback.

En GitHub **PR #145** se convirtió deliberadamente en cobertura de tests y CI (sin alterar módulos productivos): exige que Dev Swarm use el módulo canónico y prueba fallbacks exitosos y negativos. CI `critical-runtime-contracts` PASS **71/71**, GitGuardian PASS, merge SHA `7f6c52aca61d1e243de62cf5de38ba8b3849f49f`. CI NO sustituye el canario de proceso vivo.

## 4. Distinción necesaria: ROCm 10/ROCm.AI/AMD Skills vs InnerOS
**AMD ROCm 10** mejora la plataforma de cómputo GPU. **ROCm.AI** integra ROCm CLI, Hyperloom y **AMD Skills**, con procedimientos validados para agentes de programación (Cursor/Codex/etc). El catálogo oficial de AMD: <https://github.com/amd/skills> y documentación: <https://rocm.docs.amd.com/projects/amd-skills/en/latest/>. Instalar una skill AMD pone instrucciones/herramientas a disposición de un agente que la admita; **no** instala automáticamente todo el contrato de dispatch de InnerOS (task admission, autorización, secretos, worktrees, ciclo Temporal, reintentos, evidencias, release AMD/Intel, failover). Algunas skills pueden necesitar configuración específica de servidor/proveedor y confirmación de compatibilidad del hardware.
**Capas distintas a conectar**, por adaptador concreto:
1. GPU/ROCm/vLLM/Ollama: servir modelos, health, concurrencia, fallback.
2. Skill AMD + herramientas/CLI: que un ejecutor válido pueda descubrir/usar operaciones concretas, solo si instaladas/compatibles, con sandbox/permiso adecuados.
3. MCP Small y Capability Broker: operaciones allowlisted y permisos de conexión; comprobar herramientas realmente disponibles (no asumir equivalencia skill=tool).
4. Mongo + Temporal: admisión durable, owner gate, mensaje, lease/claim, workflow, retries y cierre independiente.
5. Ejecutores: Dev Swarm local, Cursor Headless, Codex, Antigravity y próximos agentes; cada uno necesita transporte real, contrato de ejecución y receipt. No todos tienen headless.
6. GitHub/main + deployment manifest: merge/CI/release y ejecución real de hashes/versiones en cada nodo.

## 5. Criterio universal de aceptación para cualquier agente
`orden -> autorización/policy -> binding concreto -> mensaje -> ACK (solo entrega) -> claim único con lease -> proceso ejecutor vivo -> acción real -> evidence_receipt -> validación independiente Temporal -> proyección Mongo terminal -> CI y despliegue si aplica`.

**Receipt para modificación de código:** task_id, correlation_id, provider, node/host, started/finished timestamps, branch/worktree, baseline SHA, nuevo SHA, rutas objetivo realmente presentes en diff nuevo, exit codes de tests y logs sin secretos. SHA sin cambios, output de LLM o ACK jamás son prueba. **Tareas de lectura:** pruebas de consulta/evidencia real verificable, sin fingir commit de producto. **Fallo/timeout:** estado FAILED/BLOCKED seguro, watchdog/lease recolección, idempotencia y recuperación, sin procesos duplicados. Cloud async request ≠ completion.

## 6. Prioridades técnicas en UNA SOLA línea de ejecución
**P0-A: recuperar tareas existentes** `ops_d45afea0028e`, `ops_f46a62594c73`: inspeccionar PID real, logs, lease, worktrees; no relanzarlas ni declararlas exitosas ciegamente. Detectar por qué `headless_execution_finished_at` y el cierre Temporal faltan; si todavía corren, esperar su estado hasta condición terminal, sin abrir duplicados.
**P0-B: corregir gate y ejecutar tests** revisar PR #144, cubrir timeouts, child/process reaping, ejecución sin commit, fallos de señal Temporal, receipt Git, no-op, reinicios y credenciales no expuestas; conectar `interactive_ops_runner` (Codex/Antigravity) y Dev Swarm al mismo esquema de evidencias, respetando diferentes clases de tareas.
**P0-C: reparar local Qwen** unificar routers, verificar rutas y fallback Intel. Scheduler: contar tareas `proposed` elegibles con `execution_lane=local_dev_swarm`; zero workers puede ser falta de candidatas elegibles o transporte modelo fallido; no asumir solo timer.
**P0-D: certificar canarios reales** Cursor en AMD e Intel, Dev Swarm y agentes externos cuando estén realmente conectados (sin inventar HEADLESS), ambos sentidos de failover, Temporal y Mongo estados terminales y sin duplicados.
**P0-E: integrar y desplegar** PR revisado y pruebas PASS a GitHub `main`; release controlado con backup/rollback, SHA y hash runtime real de los procesos AMD/Intel, health y e2e posterior.
**P1/P2:** inventario por conector/skill de adaptadores realmente existentes, disponibles pero no conectados, pendientes de implementación y objetivos para fase siguiente; no bloquear P0 por funcionalidades futuras.

## 7. Procedimiento de recuperación desde otro chat
1. Leer **este archivo en `main`**, sin considerar sus timestamps estado vivo.
2. Con MCP Small: `get_coordination_live`, `list_ops_tasks(task_id=ops_d45afea0028e)`, `list_ops_tasks(task_id=ops_f46a62594c73)`, `dev_swarm_scheduler_status`, `mcp_version`; consultar mensajes correlacionados.
3. GitHub: revisar HEAD `main`, PR #144, CI y si ya están integrados los cambios; diferenciar worktrees de runtime instalado.
4. Inspección read-only de AMD e Intel, timers, procesos de workers y vLLM/Ollama health sin imprimir secretos.
5. Actualizar este archivo **solo con fecha, resultado y evidencias comprobadas**; no sobrescribir errores históricos ni proclamar entregado por un ACK.
6. No pedir al propietario repetir estos datos: usar estos IDs, ruta y correlaciones.

## 8. Regla permanente para el proyecto
**Trabajo terminado = cambios reales en repositorio correcto + CI o test específico + release al runtime que ejecuta + evidencia de acción real + Temporal estado terminal confirmado.** Si algo falta, registrar qué exactamente. Que el contenedor, Temporal o una skill de AMD estén instalados **no equivale** a tener un agente autónomo conectado.
## 9. Verificación adicional posterior al corte (2026-10-12 ~05:02 UTC)
- [PR #144](https://github.com/Rafa-Innerchispa/innerops-agentic-platform/pull/144): GitHub Check Runs **critical-runtime-contracts=success** y **GitGuardian Security Checks=success** para commit `75236f3709f8db4ef3a7be66afee787c75127eb2`. Esto valida los tests presentes en CI, **no** las pruebas host, ni el cierre universal de agentes. Sigue draft/unmerged al comprobarlo.
- `ops_d45afea0028e` sigue `claimed` y `ops_f46a62594c73` sigue `in_progress` sin `headless_execution_finished_at` en la última consulta; no repetir ejecución hasta inspección de PID, lease, Temporal y logs.
- Búsqueda en árbol GitHub `main`: no se encontraron carpetas versionadas `.cursor/skills/`, `.agents/skills/`, `amd/skills` ni referencias directas a `rocm-doctor` / `lemonade-router-builder`. Esto **no demuestra** que las skills no estén instaladas en HOME de AMD/Intel; inspeccionar ambas máquinas con herramientas aprobadas antes de concluir. Tampoco confirma que ROCm 10 esté instalado.
- Documentación previa `platform/docs/INNEROS_LOCAL_AGENT_FABRIC.md` y `platform/docs/AI_COORDINATION.md` conserva antecedentes útiles pero referencias de agosto y políticas ya superadas; **este archivo prevalece para el handoff del 12 de octubre**, mientras los procesos, Mongo/Temporal y GitHub aportan el estado vivo.

## 10. Cierre operativo verificado (2026-10-12 ~05:25 UTC)
- **GitHub `main`:** incluye PR #144 fusionado, fix inbox (`poll_agent_inbox` + estados visibles), proyección Mongo Temporal vía `mongo_store`, fallback vLLM→Ollama en el router CANÓNICO `inneros_core_runtime/local_model_router.py` (importado por shim de `raphiia_openai`); no se modificó el legado, helper `completion_evidence_from_worktree`.
- **Mensajería:** `poll_agent_inbox(agent=cursor)` vuelve a listar mensajes `acknowledged` con tareas activas; consumer sigue ACK solo `open`.
- **Ops canario E2E:** `ops_bb2b8a9eb081` → Mongo `failed` (gate anterior); `ops_e0b587b1098e` continúa `in_progress` según última lectura pese a registrar sincronización temporal; verificar historial de workflow y NO declarar cierre Intel. `ops_d45afea0028e` → `failed` (claim stale).
- **Runtime:** Cursor reporta haber ejecutado el espejo HA y autopilot headless en ambos nodos; los runtimes productivos y hashes requieren comprobación independiente. AMD peer observability responde, Intel peer helper observability RC126; el workspace registrado en Intel informó `venv_exists=false`, que NO prueba estado del venv productivo. Tests de receipts reportados PASS en AMD.
- **Pendiente certificación final:** cierre terminal **`ops_f46a62594c73`** con evidencia Git + señal Temporal + Dev Swarm dispatch medido (4 carriles).

## 11. Decisión sobre Kubernetes / K3s (2026-10-12)
- Ver [ADR_20261012_KUBERNETES_VS_INNEROS_COORDINATION.md](ADR_20261012_KUBERNETES_VS_INNEROS_COORDINATION.md): **Kubernetes NO es prerrequisito de cierre P0**, no sustituye InnerOS/Temporal/Mongo/receipts ni requiere migración inmediata. K3s se evalúa posteriormente por supervisión, despliegues y escalado; con 2 nodos no se presume HA de control plane con etcd embebido. No introducir dependencias ocultas: exigir bloqueo real reproducible y autorización antes de cambiar el alcance.

## 12. Punto vivo verificado por ChatGPT (12 oct, ~05:36 UTC)
- GitHub PR #144 y PR #145 **fusionados**. PR #145 fue `test/CI`, con 71 pruebas aprobadas, sin despliegue ni reparación de endpoints productivos por sí mismo.
- `ops_f46a62594c73` permanecía **`verification`** con `candidate_evidence.commit_sha=80b03a54` y `objective_paths=[platform/docs/P0_F46_CLOSURE_EVIDENCE.md]`; señal Temporal recibida, pero **no se confirmó Mongo terminal**. Es un marcador documental, no evidencia de que Codex, Antigravity y Dev Swarm estén todos operativos.
- `ops_d45afea0028e` y `ops_bb2b8a9eb081` estaban `failed`; `ops_e0b587b1098e` seguía `in_progress`, con error de gate anterior. Mantener historial sin repetir efectos.
- Dev Swarm `enabled`, `max_concurrent=4`, **0 workers y 0 lanzamientos en última iteración**. La GPU AMD tiene vLLM/Qwen cargado; falta certificar health + fallback en tarea local real.
- `AGENTS.md` root, README y reglas Cursor apuntan a esta continuidad; **todos los agentes** deben usarla como entrada y verificar estado vivo.
- Existe adaptador `interactive_ops_runner.py` para Codex/Antigravity, pero no hay prueba compartida todavía de ejecución autónoma headless y cierre final en esos proveedores. Las tarjetas de agentes A2A registradas NO son canarios reales.
- Pendiente: canario local Dev Swarm coding real, Cursor AMD/Intel terminal, pruebas Codex/Antigravity según runner disponible, rutas read-only con evidence, recuperación de PID/lease y versión SHA de código importado en AMD e Intel; coordinar por la MISMA línea P0 y evitar tareas duplicadas.
