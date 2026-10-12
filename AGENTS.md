# InnerOS - entrada obligatoria de continuidad para agentes

**Migración y continuidad 12-10-2026:** [docs/INNEROS_NEXT_CHAT_HANDOFF_20261012.md](docs/INNEROS_NEXT_CHAT_HANDOFF_20261012.md). Leer ANTES de proponer nuevas tareas o reparar ramas; contiene estado de GitHub/GitLab/AMD/Intel, PRs fusionados, fases 1/2, evidencia pendiente y regla de no repetición.


> Vigente desde el 12 de octubre de 2026. Aplica a Cursor, Codex, Antigravity y agentes locales que trabajen en este repositorio.

**Inventario vivo de ramas y producción:** leer [docs/INNEROS_BRANCH_LEDGER.md](docs/INNEROS_BRANCH_LEDGER.md) (actualizado diariamente por GitHub Actions) y [docs/INNEROS_RELEASE_ATTESTATION.json](docs/INNEROS_RELEASE_ATTESTATION.json). Nunca considerar que main o CI implica despliegue. El auditor conserva ramas y NO las fusiona ni borra.

## Al iniciar una sesión o reclamar trabajo

1. Leer **[platform/docs/INNEROS_COORDINATION_CONTINUITY_20261012.md](platform/docs/INNEROS_COORDINATION_CONTINUITY_20261012.md)**. Es el handoff actual; referencias de septiembre y manuales antiguos siguen como material histórico, no como autoridad de estado vivo.
2. Consultar el estado **vivo** de MCP Small / Mongo / Temporal: `get_coordination_live`, `list_ops_tasks`, mensajes pertinentes e historial real del workflow. Confirmar HEAD de GitHub `main`, PRs, ramas y runtime efectivo de AMD/Intel. No inferir ejecución por ACK, PID, claim, commit en rama o tests de CI.
3. Si hay una tarea existente, **reutilizar su ID/correlación y comprobar lease, proceso y worktree**. No crear duplicados ni lanzar dos ejecutores sobre el mismo trabajo. Preservar worktrees y cambios locales de otras sesiones.
4. Cada resultado debe incluir prueba adecuada a su clase: cambios y tests reales para coding, consulta/observación para read-only; Temporal debe aceptar cierre y Mongo reflejar estado terminal. No fingir cambios para obtener un gate positivo.
5. Evitar cambios destructivos y de red/hardware/firmware; usar backups, revisión, CI, release controlado y hashes runtime AMD/Intel con rollback.
6. Modelos: local-first con AMD Qwen/vLLM e Intel Ollama para carriles internos; Cursor, Codex y Antigravity pueden usar sus modelos propios con créditos existentes cuando estén asignados/autorizados, sin compras o cargos inesperados.

## Arquitectura de ejecución, no confundir capas

ROCm y AMD Skills habilitan cómputo y procedimientos, pero **no sustituyen** binding de tareas, autenticación, MCP, Temporal, Mongo, ejecución real, heartbeat/lease, verificación, ni release a producción.

**Contrato objetivo:** orden → autorización/policy → asignación → entrega/ACK → claim con lease → trabajo real → receipt de evidencia → gate Temporal → Mongo terminal → release certificada si corresponde.

**Handoff activo:** [platform/docs/INNEROS_COORDINATION_CONTINUITY_20261012.md](platform/docs/INNEROS_COORDINATION_CONTINUITY_20261012.md). Confirmar siempre con las fuentes vivas; el documento guarda historia, no una garantía de actualidad.
