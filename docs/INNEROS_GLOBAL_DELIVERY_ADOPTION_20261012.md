# InnerOS | Gobierno universal de desarrollo y entrega

**Vigencia:** 2026-10-12. **Ámbito:** todos los proyectos actuales y futuros de InnerChispa/PC Doctor en GitHub, GitLab, AMD, Intel, worktrees de agentes y futuros servidores.

## Norma operativa

1. **Preservación primero.** Cada rama/worktree/fork tiene responsable, respaldo, SHA, estado y trazabilidad. Antes de cualquier limpieza, conocer commits exclusivos y cambios sin commit. Mantener backups Git locales restaurables y espejo GitLab cuando corresponda. No hacer `reset --hard`, `clean -fd`, `rsync --delete`, force-push, cambios globales de visibilidad ni eliminación automática de ramas.
2. **Una rama principal por proyecto.** Cada producto conserva su repositorio y rama principal real (`main`, `master` u otra). InnerOS centraliza políticas, inventario y evidencias; **no importa todos los códigos a su propio `main`**.
3. **Promoción de mejoras útiles.** Agente entrega commit y pruebas verificables en worktree aislado, se abre PR/MR acotado, CI compatible con ese lenguaje pasa, se revisan equivalencias/rebases y se integra a la rama principal del proyecto. Un commit sólo local no equivale a entrega; tampoco un PR sin merge.
4. **Producción no es GitHub.** Si el proyecto tiene servicio vivo, la promoción exige SHA pinneado de su rama principal, comprobación de rutas efectivamente importadas, backup/LKG, rollout gradual, smoke E2E y registro por servicio/nodo. El éxito de CI, un puerto abierto o el estado `claimed` **no certifican producción**. Proyectos experimentales o sin servicio no se fuerzan a producción.
5. **No duplicar trabajo.** Antes de tocar código: comprobar tareas Mongo/Temporal, propietario y lease, mensajes Cursor/Codex/Antigravity, PR/MR existentes y ramas/worktrees. Un solo escritor por alcance; reaprovechar la tarea original.
6. **Sin perder desarrollos viejos.** Inventariar rama por rama; diferenciar historia Git separada, cambios exclusivos y cambios ya integrados semánticamente. Rescate selectivo mediante PR y tests. No borrado masivo ni merge de cientos de ramas.
7. **Ejecución local primero.** Modelos Qwen/vLLM AMD y Ollama Intel son preferentes; Cursor/Codex/Antigravity usan sus capacidades autorizadas sólo cuando están asignados. Ningún gasto externo inesperado ni cambio de arquitectura Kubernetes/K3s/Argo CD en fase 1.

## Piezas existentes que se REUTILIZAN

- `platform/scripts/repo_taxonomy_reconcile.py` y `repository_taxonomy.json`: clasificación activa/experimental/legacy.
- `platform/scripts/repo_sovereignty_discover.py`: inventario y mirrors locales/GitLab; tiene operaciones mutadoras y de visibilidad. **NO ejecutarlo para una auditoría read-only**.
- `platform/scripts/repo_sovereignty_gitlab_sync.py`: sincronización GitLab con preservación de divergencias; jamás reimplementarlo como force-push.
- `platform/scripts/repo_sovereignty_health_check.py`: chequeo del catálogo y respaldos.
- `scripts/inneros_branch_ledger.py`: comparador profundo para el repositorio core. El workflow existente de main sigue vigente hasta que el PR #152 y los permisos administrativos estén comprobados.
- `scripts/inneros_local_release_executor.py`: rollout ya existente limitado a tres archivos, NO liberación universal.
- `scripts/inneros_release_gate.py`: validador de metadatos host del core, mantiene LKG en `UNSET` sin evidencia real.
- `platform/scripts/repo_delivery_guardian.py`: **nuevo auditor de SOLO LECTURA** sobre todos los repositorios GitHub visibles. Consume salidas de soberanía existentes; consulta ramas, PRs, rama principal, estado CI, releases, GitLab sincronizado y recibos de hosts. No crea PR, no fusiona, no modifica visibilidad, no despliega.

## Cobertura progresiva y evidencia

| Perímetro | Evidencia existente | Certificación requerida |
|---|---|---|
| GitHub cuenta Rafa-Innerchispa | 60 repositorios visibles en la lectura 2026-10-12 | Auditoría real paginada de todos, incluidos privados; después PR, branch rules e Issues por repo |
| GitLab namespace rafagye y otros autorizados | Conector local `local_gitlab_plane.py` y scripts de soberanía | Confirmar inventario nativo, MRs, pipelines, ramas que no estén en GitHub, sincronización sin force |
| Código local no publicado | Worktrees de agentes, repos de desarrollo y mirrors | Probar que no hay cambios uncommitted olvidados y que el backup permite recuperar |
| Servidor AMD | Peer observability disponible | SHA efectivo y hash de módulo importado, tests y rollback por servicio |
| Servidor Intel | Observabilidad Peer Ops reportó RC126 | Reparar helper, ver procesos/imports/hashes y canarios reales |
| Cursor/Codex/Antigravity/Dev Swarm | Tareas Mongo, mensajes y Temporal disponibles | Claim → ejecución real → commit → CI → merge → runtime y resultado terminal sin falsos positivos |

**No confundir** 60 repositorios identificados con 60 repositorios gobernados; el auditor dice explícitamente `universal_coverage_certified=false` mientras falte inventario nativo GitLab o cobertura de worktrees locales. No manipular su reporte para ocultar pendientes.

## Instalación del observador central

Los archivos `platform/systemd/user/inneros-universal-delivery-guardian.service` y `.timer` son candidatos **opt-in**, deshabilitados hasta validar host y credenciales. Se instalarán únicamente en el nodo líder, no simultáneamente en AMD e Intel; incluyen `flock` para no competir. Se requiere la utilidad `gh` autenticada a todos los repos permitidos; no guardar tokens en Git.

El reporte detallado se guarda sólo en `/home/rlopez/inneros/inneros_core/var/repo_sovereignty/universal-delivery-health.json` con permisos locales restrictivos. Se publica a la coordinación únicamente un resumen sin nombres privados, secretos o rutas sensibles. El auditor no tiene permisos de escritura en GitHub/GitLab y no se ejecuta dentro de PRs de terceros.

## Política para cerrar cada proyecto

`DISCOVERED` → `BACKUP_VERIFIED` → `BRANCHES_TRIAGED` → `PR_CI_PASS` → `MERGED_TO_DEFAULT` → `RELEASE_CANDIDATE` → `HOST_E2E_VERIFIED` → `PRODUCTION_CERTIFIED`.

No avanzar automáticamente de `PR_CI_PASS` a producción: confirmar qué nodos/servicios realmente dependen del repositorio. Etiquetas de release sólo después de la certificación pertinente, LKG y rollback probados. El despliegue repetitivo se ejecutará por adaptadores aprobados, no por un script remoto genérico que ejecute comandos arbitrarios.

## Bloqueos actuales

La API GitHub muestra el core `main.protected=false`, `has_issues=false` y `releases=[]`. El conector de esta sesión no expone Settings/Rulesets/Issues ni creación de Releases. Hasta completar esos pasos administrativos, **no anunciar una protección universal activa**. No desactivar el ledger existente del core antes de comprobar su reemplazo PR (#152) bajo las reglas deseadas.

Esta política es la especificación transversal; **la adopción por repo, CI/PR, respaldo, host y service receipt se prueba individualmente**. La fase 1 permanece abierta mientras falten tales comprobaciones.
