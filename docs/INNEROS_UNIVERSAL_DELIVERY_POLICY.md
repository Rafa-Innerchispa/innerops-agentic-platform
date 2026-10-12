# InnerOS: política de entrega universal (GitHub, GitLab y servidores)

**Vigente desde:** 2026-10-12. **Estado:** estándar canónico acordado; adopción efectiva aún debe certificarse repositorio por repositorio y servicio por servicio.

## Objetivo innegociable

Ningún cambio útil queda olvidado en una rama, worktree, fork o servidor; ningún cambio se declara terminado solo por existir en `main`; ninguna automatización pisa el trabajo de otro agente. Aplica a **todos los desarrollos actuales y futuros**, incluidos proyectos externos a `innerops-agentic-platform`, GitHub, GitLab, AMD, Intel y futuros servidores.

### Unidad de verdad de cada proyecto

Cada proyecto conserva su propio repositorio y su propio `main` o rama predeterminada protegida. **No** trasladar el código de múltiples proyectos al `main` de InnerOS. InnerOS contiene la política, el índice cruzado y los contratos de ejecución; no reemplaza el repositorio fuente de cada producto.

Cada proyecto debe registrar: URL/ID GitHub o GitLab, owner, main SHA, ramas y PR/MR, CI real, último release semántico, SHA desplegado por entorno/nodo, evidencia de pruebas funcionales, rollback/LKG y tareas pendientes. No almacenar tokens ni secretos en repositorios públicos.

## Fase 1: lo acordado el 10 de octubre

1. **CI obligatorio**: GitHub Actions o GitLab CI, análisis de seguridad y pruebas que ejecuten el código afectado. Habilitar Rulesets/branch protection para exigir PR/MR y checks que ya existan, bloquear borrado y force push de ramas canónicas, e impedir direct pushes no excepcionados. No activar gate inexistente que impida todos los merges.
2. **Versiones/releases oficiales**: GitHub Releases y tags/versiones equivalentes de GitLab. Publicar solo tras revisión, CI, SHA pinneado y evidencia de despliegue. Registrar **Last Known Good (LKG)**, manifiestos de archivos/hash, backup y rollback. Si falta evidencia de host, estado `NO_CERTIFICADO`, no `RELEASED`.
3. **Auditoría continua de deuda de ramas**: inventario diario, paginado, compara contra main, identifica commits únicos, PR/MR abiertos, cambios potencialmente destructivos y ramas que requieren equivalencia semántica. **Nunca** merge/borrado/rebase/reset automáticos de ramas sin revisión. Los commits adelantados pueden ya estar integrados mediante squash/cherry-pick.
4. **Cierre durable de tareas**: entrega/ACK ≠ ejecución; `claimed` ≠ trabajo terminado; `Temporal RPC COMPLETED` ≠ resultado funcional. Exigir evidencia según clase de tarea, gate Temporal/Mongo terminal e idempotencia por `task_id`/`correlation_id`. Tareas read-only no requieren diff ficticio.
5. **Despliegue controlado en host**: preflight de git/status/worktrees, relación origen→código importado→servicio/PID, backup, paso gradual y rollback, hash de archivos cargados, smoke real y registro por nodo. `rsync --delete` o reinicios indiscriminados quedan prohibidos como procedimiento general.

**Fase 2 excluida del P0 actual:** piloto de K3s/Kubernetes y Argo CD tras una entrega estable. No usarlos como condición retroactiva para terminar el flujo actual.

## GitHub: adopción por repositorio

- [ ] Auditoría de ramas/PR mediante `scripts/inneros_branch_ledger.py --repo owner/repo` (desplegar workflow local a cada repo o una ejecución central con permisos mínimos).
- [ ] `Settings > General > Features > Issues`: habilitar si se quieren tickets y trazabilidad de errores. GitHub Projects es complementario, no reemplaza automáticamente Issues.
- [ ] `Settings > Rules > Rulesets` (o Branch protection): rama principal, PR obligatorio, `critical-runtime-contracts` u otros checks **realmente presentes** como obligatorios, impedir force push/eliminación.
- [ ] GitHub Actions y seguridad habilitadas sin secretos visibles en logs; jobs con permisos mínimos.
- [ ] GitHub Release/tag `vMAJOR.MINOR.PATCH`, notas, SHA, evidencia CI, manifest y LKG; no declarar producción hasta recibir evidencia de servidores.
- [ ] Inventario y LKG disponibles desde `README`/`AGENTS.md` y registrador corporativo.

El repositorio `Rafa-Innerchispa/innerops-agentic-platform` tenía `has_issues=false`, `has_projects=true` y **0 releases** al auditarlo el 12-10. El conector GitHub actual no expone la mutación de `has_issues`/Rulesets ni creación de Releases; no afirmar que están activados. Requiere ajuste administrativo o herramienta aprobada que permita esas acciones.

**Compatibilidad del libro diario con Rulesets:** el workflow de inventario queda configurado para preparar cambios en `automation/inneros-branch-ledger` y proponerlos mediante PR, sin publicar directamente en `main`. Para que funcione debe estar habilitado **Settings > Actions > General > Workflow permissions > Allow GitHub Actions to create and approve pull requests**; el workflow solicita permisos mínimos por capacidad `contents: write`, `pull-requests: write` y `actions: write` (este último exclusivamente para el dispatch explícito). Los PR creados con `GITHUB_TOKEN` pueden dejar los checks de PR pendientes de aprobación; por eso se despacha explícitamente el workflow existente `inneros-runtime-gates.yml` por `workflow_dispatch` para ejecutar `critical-runtime-contracts` sobre la rama de propuesta. **No activar un Ruleset estricto hasta comprobar el PR automatizado y su CI en vivo.** No existe bypass universal para agentes ni auto-merge.

## GitLab: adopción equivalente

- [ ] Enumerar todos los proyectos reales y MRs/ramas (incluir forks/remotos) con API del GitLab correspondiente.
- [ ] Habilitar `Branch rules` de la rama predeterminada: sin push directo ni force push, merge solo con MR revisada; verificar permisos actuales.
- [ ] CI de Merge Request, preferiblemente resultado combinado cuando corresponda; no aprobar MR si falla pipeline o faltan artefactos.
- [ ] Crear tag y GitLab Release con SHA, CI, evidencia del host, LKG y rollback.
- [ ] Conservar ramas viejas hasta clasificar equivalencia, impacto y dependencias, sin fusionar stacks enteros de versiones divergentes.
- [ ] Publicar un índice de deuda de ramas y despliegues, enlazado desde InnerOS.
- [ ] Activar/usar los readers de pipelines/MRs/jobs de Capability Gateway con MCP Small cuando estén verificables.

**Estado de acceso:** no se confirmó en esta conversación un conector GitLab directo con permisos para consultar o mutar todos los proyectos. No suponer el despliegue de esta política a GitLab hasta verificar y obtener evidencias.

## Servidores AMD/Intel y futuros nodos

Cada despliegue registra: `project_id`, servicio, nodo, repositorio remoto, `main_sha` esperado, `runtime_import_sha` real o hashes SHA256 de módulos ejecutados, PID/servicio, tests reales, resultado canario, timestamp UTC, backup, rollback y resultado Temporal/Mongo. Separar checkout de LEP, checkout del repositorio y código realmente importado por el proceso.

No ejecutar un rsync destructivo sobre directorios con código local/worktrees, no resetear ramas divergentes sin snapshots, no borrar datos o carpetas de otros agentes, no reiniciar servicios ajenos al release. Un nodo sin evidencia **NO_CERTIFICADO** aunque GitHub diga PASS.

## Reglas de coordinación de editores y proveedores

- Un escritor autorizado por rama/archivo/trabajo, leases/fencing, y no abrir otra `ops_task` por el mismo objetivo.
- Modelos internos: Qwen/vLLM AMD y Ollama Intel, local-first; Cursor usa su Composer, Codex sus modelos y Antigravity los suyos cuando asignados/autorizados.
- Conectores y skills deben certificar cuatro capas: presente, integrado, ejecutable y E2E verificado; una Agent Card no equivale a un worker autónomo.
- La decisión de integración se documenta con riesgos, pruebas y alternativa/rollback; código o tareas incompletas permanecen explícitamente `BLOCKED`/`NOT_RELEASED`.

## Registro de adopción y seguimiento

**Implementado inicialmente solo en InnerOS core:** workflow `.github/workflows/inneros-branch-ledger.yml`, script `scripts/inneros_branch_ledger.py`, atestación `docs/INNEROS_RELEASE_ATTESTATION.json`. Esto **no equivale** a todos los repos GitHub/GitLab ni a despliegue AMD/Intel. Aplicar en etapas, un repositorio por vez y con recibo de adopción.

**Continuidad transversal:** [Handoff del próximo chat](INNEROS_NEXT_CHAT_HANDOFF_20261012.md). Comprobar telemetría viva antes de continuar; este documento es política, no un estado de producción en tiempo real.
