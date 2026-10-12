# GitHub: activaciones administrativas pendientes, sin perderlas

Corte verificado: 2026-10-12. Responsable administrativo: cuenta Rafa-Innerchispa. Estado es OBSERVADO, no una declaración de activación.

| Acción | Estado verificado | Puerta de cierre |
|---|---|---|
| Issues core | has_issues=false | Settings > General > Features > Issues; GET repo has_issues=true |
| Protección core main | protected=false, rulesets=[] | Antes de activar, comprobar PR #152 y checks. Crear Ruleset require PR / status checks existentes; GET branch protected=true o ruleset active |
| GitHub Actions PR bot | PR #152 abierto y draft | Settings > Actions > General > Workflow permissions > Allow GitHub Actions to create and approve pull requests. Revalidar funcionamiento de create-pull-request y dispatch de CI, luego merge #152 |
| Releases/LKG | 0 GitHub Releases, LKG=UNSET | Primero evidencia SHA runtime importado AMD e Intel, snapshot y canarios; después crear Release vX.Y.Z y LKG certificado |
| Auto-merge | allow_auto_merge=false | No activarlo automáticamente hasta que exista gobierno fiable; no es requisito de fase 1 |
| Projects | has_projects=true | Ya disponible, tablero/automatizaciones por proyecto pendientes de verificar |
| Portafolio completo | ~60 repos GitHub visibles | Activación por cada repo, con recibo. GitLab solo y worktrees sin commit requieren auditoría independiente |
| AMD / Intel | NO_CERTIFICADO; Intel helper RC126 | Corregir binding/helper y obtener receipts por proceso, PID, import SHA y smoke |
| Dev Swarm | scheduler enabled, workers 0 | Demostrar tareas reales en carriles y cierre Temporal/Mongo sin falsos PASS |

## Activación por el propietario, sin tokens en chat

1. [Ajustes core](https://github.com/Rafa-Innerchispa/innerops-agentic-platform/settings): habilitar Issues. Volver a consultar API para verificar.
2. [Permisos Actions](https://github.com/Rafa-Innerchispa/innerops-agentic-platform/settings/actions): habilitar creación de PRs por GitHub Actions si aparece la opción. No cambiar permisos predeterminados a escritura general.
3. Revisar [PR #152](https://github.com/Rafa-Innerchispa/innerops-agentic-platform/pull/152). Es requisito para que el inventario diario deje de escribir directamente a main. No activar Ruleset estricto antes de validar este reemplazo, y tampoco cerrar/borrar la rama vieja.
4. [Reglas](https://github.com/Rafa-Innerchispa/innerops-agentic-platform/settings/rules): exigir PR, status check **critical-runtime-contracts** ya existente, prohibir force push y deletion, sin bypass general.
5. Repetir configuración y sus comprobaciones por repositorio con nombre de check propio, por ejemplo **serviceops-quality** en innerops-service-ops. No imponer checks de InnerOS a otros productos.
6. No emitir un GitHub Release ni declarar LKG productivo antes de verificar AMD/Intel y rollback. Un tag no certifica hosts.

## Limitación real de herramientas

La conexión GitHub en ChatGPT permite leer el repositorio y gestionar código/PR, pero no ofrece endpoints de escritura para Settings, Rulesets o Releases. La consulta branch protection devolvió HTTP 403 `Resource not accessible by integration`. Aunque el usuario tiene permiso admin, la instalación usada aquí no adquiere automáticamente esos permisos.

## Corrección ya preparada en código

En `platform/inneros_core_runtime/local_github_plane.py`, la creación por gh **ya no pasa --disable-issues**, y la creación por API incluye `has_issues=true`, con diferenciación cuenta personal/organización. No modifica repos existentes. Pasar CI antes de integrar. No duplicar trabajos de Codex relacionados con editoriales/perfil.

## Regla de seguimiento

Actualizar este documento tras cada modificación y registrar recibo con fecha UTC, repo, configuración previa/posterior, identidad, SHA y enlace de evidencia. Mientras no haya GET confirmatorio, marcar PENDIENTE. Revisar también el handoff y `AGENTS.md`, las tareas Mongo/Temporal y mensajes de agentes. No crear issues ficticios para simular cierre.
