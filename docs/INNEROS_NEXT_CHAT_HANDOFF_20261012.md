# InnerOS | Traspaso obligatorio al siguiente chat

**Corte:** 2026-10-12, alrededor de 15:25 UTC. **Objetivo:** continuar y terminar sin repetir trabajo ni inventar que GitHub `main` equivale a producción. **Idioma de ejecución:** español. Archivo público, sin claves, tokens ni datos confidenciales.

## INSTRUCCIÓN AL ASISTENTE DEL NUEVO CHAT: EMPEZAR AQUÍ

1. Recupera estado **vivo** de GitHub `Rafa-Innerchispa/innerops-agentic-platform` `main`, PRs, workflows, [inventario de ramas](INNEROS_BRANCH_LEDGER.md) y [atestación de producción](INNEROS_RELEASE_ATTESTATION.json). No uses SHAs antiguos como si fueran HEAD.
2. Lee [AGENTS.md](../AGENTS.md), [continuidad técnica](../platform/docs/INNEROS_COORDINATION_CONTINUITY_20261012.md) y [política universal](INNEROS_UNIVERSAL_DELIVERY_POLICY.md).
3. Comprueba mensajes nuevos de Cursor y estado de tareas existentes en MCP Small/Mongo/Temporal **sin reenviarlas ni crear otras**. Antes de editar, confirmar rama/worktree/lease y propietario de archivos. Cursor y otros agentes continúan trabajando; no sobreescribirlos.
4. **Prioridad inmediata:** verificar si el workflow `InnerOS Branch and Production Ledger` ya creó `docs/INNEROS_BRANCH_LEDGER.md` tras corregir el checkout en PR #151. Si falla, leer el último job log y reparar solo ese bloqueo, en PR acotado. Luego avanzar con versionado/release y deploy a producción con evidencias independientes.
5. No iniciar K3s, Argo CD, Router v2 ni refactorizaciones ajenas al cierre de fase 1. No intentar instalar/desplegar en AMD/Intel con `rsync --delete` sin preflight/snapshot/rollback.

## Lo que el usuario acaba de ordenar y NO se debe olvidar

La conservación de ramas, CI/release, protección de `main`, versiones, Last Known Good, rollback, actualizaciones de estado, evidencias y prevención de trabajo perdido deben aplicar a **TODOS** los desarrollos actuales y futuros en **GitHub, GitLab, servidores AMD/Intel y futuros nodos**, no únicamente a este repositorio. Cada proyecto mantiene su propio `main`; el InnerOS core gobierna la política y la coordinación, no fusiona códigos de productos distintos en un repositorio.

El usuario quiere activar funciones que aporten valor para terminar el problema **sin compras inesperadas**. Recuperación de acuerdos del **10-10-2026**:
- **Fase 1:** (1) **GitHub Actions con pruebas obligatorias**, y (2) **GitHub Releases/versiones oficiales**, Last Known Good, rollback y reglas de protección de rama.
- **Fase 2:** **K3s y Argo CD** se evalúan después. No son dependencia P0.
- Mantener GitHub como remoto de código canónico, GitLab como espejo/repositorio secundario según producto y copias locales/backup. Los servicios previos `inneros-repo-sovereignty`, descubrimiento de repos, backups/mirrors y ContributorOps GitLab deben **consultarse antes de reconstruir nada**; no se confirmó su estado vivo en este turno.
- No volver a pedir al usuario recordar comandos ni abrir manualmente Cursor para que InnerOS funcione.

## Estado real confirmado de GitHub en este corte

**Repositorio:** <https://github.com/Rafa-Innerchispa/innerops-agentic-platform>.

| Qué | Estado verificado | Qué NO implica |
|---|---|---|
| PR #142 | Fusionado: ejecutor release local con alcance limitado | No es deploy universal |
| PR #144 | Fusionado: evidencias de ejecución Cursor y gate | No prueba por sí solo todos los agentes |
| PR #145 | Fusionado: router canónico/fallback bajo CI | No certifica endpoint vLLM vivo |
| PR #147 | Fusionado: registro AMD/Intel y proveedores internos | No completa tasks de producto |
| PR #148 | Fusionado, `5c3605f686e6ddfe7e086f7d1c2d7c056ccd8aec`: receipts veraces y reconciliación Temporal/Mongo | No acredita release host |
| PR #146 | Fusionado, `2526121b16d476d9881dfb6609dcd5c7bb4230f8`: registro del repositorio Ambient Guardian | No implica runtime Ambient Guardian desplegado |
| Cambio posterior | `e1b628e3b89fcedb4102e99f22ce14b06bc522dd`: bloquea falso cierre de operaciones host sin evidencia de despliegue | No ejecuta deploy |
| PR #149 | **Fusionado**, SHA `5ff8a1a615de3e763a6ff2920e9ad3719cc7cfd5`: script/workflow diario para inventario y estado de producción | El primer workflow falló; aún no afirmar que el reporte se publica |
| PR #151 | **Fusionado**, SHA `2e96a08bac1161bcf5f83fea1aff0ef92a8200e1`: arreglo del checkout del inventario | Comprobar nueva corrida y publicación antes de decir operativo |
| Política universal | `docs/INNEROS_UNIVERSAL_DELIVERY_POLICY.md`, commit `bb835c339cc56f3cd41c67ebd0cf3acf0c8ea5b3` | No está instalada todavía en todos los repos |

**Fallo técnico del primer workflow:** ejecución `38269250249`, job `114879118039`, 2026-10-12 ~15:18 UTC. `actions/checkout@v4` falló en `git submodule foreach`: `fatal: No url found for submodule path 'workspaces/innerops-agentic-platform' in .gitmodules`. Causa: gitlink huérfano + `persist-credentials:false` del checkout, **NO falla de red de AMD/Intel**. PR #151 cambia `persist-credentials:true` y mantiene `submodules:false` exclusivamente para main-only workflow; no elimina workspaces. Nueva ejecución esperada `38269793085` (consultar status en vivo). Si reaparece, inspeccionar antes de borrar gitlink o cambiar .gitmodules; no reset de otras ramas.

**Ramas/PR:** antes del inventario automático había **263 ramas** y 9 PR abiertos; tras fusiones #146/#149/#151, los conteos cambiaron. Últimos PR antiguos relevantes: #127 MCP profiles (988 líneas eliminadas), #119 GitLab resource fabric (216.026 líneas eliminadas), #126 política GitLab runner, #118 Bellini Device Fabric, #99 Router MCP shadow, #42 runtime clean gate, #28 TaskEnvelope, #23 hackathon index. No fusionar #119 ni #127 masivamente; auditarlos por equivalencia de contenido y riesgo. Ramas sin PR con commits exclusivos incluyen AG-60, Contífico, global coordination guards, HA failover, observabilidad AG41, etc. Muchas ramas antiguas pueden tener commits equivalentes ya integrados, no asumir 263 desarrollos pendientes. Conserva todas las referencias hasta triage.

## Funciones de GitHub: verificación de configuración

- API del repositorio confirmó `has_issues=false` (**Issues DESACTIVADO**). No se pueden crear tickets/incidencias mediante GitHub Issues mientras esté desactivado; no implica que se hayan perdido commits/PRs y los issues antiguos reaparecen si se reactiva.
- `has_projects=true`: **Projects ya está habilitado**, distinto de Issues. El uso de Projects como tablero aún requiere configuración.
- `allow_auto_merge=false`: auto-merge desactivado. **No activarlo a ciegas** antes de reglas y gates confiables.
- API `/releases`: **0 GitHub Releases oficiales**. No marcar fase 1 como versionada solo porque existan commits.
- Conector GitHub reportó permisos `admin=true` pero **no expone una mutación aprobada de Settings/Issues/Rulesets/Releases**. No afirmar activación. Acción administrativa UI: repo > **Settings > General > Features > Issues**: marcar. En **Settings > Rules > Rulesets**: PR y checks obligatorios, no force pushes, no borrado; revisar que los checks existan y el bot del inventario pueda publicar conforme a las reglas.
- Nota de arquitectura: el auditor actual hace commit del ledger directamente a `main`. ANTES de proteger `main` sin bypass hay que cambiar ese update a PR de bot o bypass extremadamente limitado; jamás permitir bypass universal a los agentes.

## Estado de producción y autonomía: NO confundir con GitHub

**AMD e Intel siguen `NO_CERTIFICADO` respecto a `main`** en `docs/INNEROS_RELEASE_ATTESTATION.json`. Checkouts locales registrados pueden diferir de los módulos importados por procesos; AMD LEP anteriormente `bf43c6a5`, Cursor reportó runtime distinto. Intel workspace sin `.venv` en ruta registrada y helper observabilidad RC126 no prueban el entorno productivo.

El release executor protegido `scripts/inneros_local_release_executor.py` despliega **solo tres archivos** del gateway/AG41. El script espejo `platform/scripts/deploy_platform_mirror_ha.sh` usa `rsync --delete`; no usar indiscriminadamente. Cerrar con preflight/procesos/worktrees/rollback, SHA/hashes importados, pruebas en ambos nodos y comprobación Temporal/Mongo.

- `ops_f46a62594c73` figura `completed` en Mongo pero conservó error anterior de verificación; **no** extrapolar que todos los proveedores están certificados.
- `ops_ba6e885a1cf3`: canario Qwen registró creación de archivo y gate passed, pero faltaba commit y prueba específica del nuevo archivo. No rehacer tareas viejas para simular éxito.
- `ops_1369791f60a0` AMD y `ops_cb8cafe5c2f4` Intel: canarios Cursor read-only; no prueba Composer coding headless autónomo.
- Codex y Antigravity tienen contratos de claim/receipt, pero hace falta canario coding end-to-end por runner efectivo. Agent Cards registradas no equivalen a workers reales.
- Faltan certificación de Dev Swarm local AMD Qwen/Intel Ollama, GitLab ContributorOps y otros conectores, con pruebas reales.
- Acceso al backend GitLab mediante conector directo **no demostrado en este chat**: puede existir bridge local/MCP/ContributorOps en servidores. No decir que GitLab está vacío o desactivado; leer primero su estado vivo.

## Orden de trabajo para el nuevo chat, sin redundancias

**1. Rescatar el ciclo ya empezado.** Leer resultado del run diario GitHub Actions posterior al PR #151, confirmar generación de `docs/INNEROS_BRANCH_LEDGER.md` (o reparar con un PR mínimo). Clasificar resultados, sin otra importación masiva.

**2. Conservar TODO el código útil.** Priorizar branches adelantadas con PR viejo y alto impacto. Distinguir patch-id/equivalencia semántica; actualizar o cherry-pick SELECTIVO con CI y revisión; no borrar ramas ni force push. Mantener `main` fuente de versiones, y mirror/backup GitLab verificables.

**3. Completar lo acordado en fase 1.** GitHub Actions obligatorio + protección de main, Issues y Projects para trazabilidad, GitHub Releases con tag `vX.Y.Z`, LKG y rollback. No inventar Release productivo sin hash importado AMD/Intel. No habilitar auto-merge que suprima la revisión.

**4. Extender la política a TODOS los repos.** Descubrir los proyectos GitHub y GitLab reales con owner/permiso, matriz por repo, reglas y pipelines por plataforma, último release y nodos. Implementar auditor en cada repo o proceso central con permisos acotados; certificar adopción una por una; preservación de mirror GitLab y backups.

**5. Certificar producción dual.** Controlar cambios en AMD e Intel, tareas activas, procesos y leases; desplegar solo SHA revisado y mediante métodos no destructivos con backup/rollback; probar Qwen, fallback Intel y proveedores externos mediante canarios reales. No concluir solo por git HEAD/CI.

**6. Cierre universal.** Lista de tareas ops/Mongo/Temporal con sus dependencias; claims reconciliados con leases; read-only/coding/deploy bajo criterios de evidencia diferentes; no reintentar tareas terminadas ni cerrar operaciones incompletas.

## Prohibiciones explícitas de repetición

- NO crear un nuevo MCP Router, Temporal paralelo, scheduler v2 ni Kubernetes para resolver este P0.
- NO volver a crear PRs #142/#144/#145/#147/#148/#149/#151, ni reimplementar código ya fusionado.
- NO cambiar políticas de modelos: local AMD Qwen/vLLM, Intel Ollama fallback; Cursor Composer propio, Codex y Antigravity modelos propios autorizados, sin cargos externos inesperados.
- NO usar Notion como coordinador activo; mantener GitHub como código/release, Mongo + Temporal como tareas, GitLab mirror/MRs según proyecto.
- NO sobreescribir worktrees, borrar ramas, normalizar `main` con `reset --hard`, activar servicios que no corresponden, ni usar un `rsync --delete` sin evidencia y snapshot.
- NO dejar `production=success` sin prueba de host ni `test_results.exit_code=0` inventado.
- NO hacer más preguntas al usuario sobre decisiones ya tomadas. Usar estas rutas y estado vivo.

## Fuente operativa para el siguiente chat

Repositorio central: <https://github.com/Rafa-Innerchispa/innerops-agentic-platform>

- [Este handoff](INNEROS_NEXT_CHAT_HANDOFF_20261012.md)
- [Política universal](INNEROS_UNIVERSAL_DELIVERY_POLICY.md)
- [Ramas y producción, automatizado](INNEROS_BRANCH_LEDGER.md) (**puede faltar hasta que el workflow sea exitoso**)
- [Atestaciones de producción](INNEROS_RELEASE_ATTESTATION.json)
- [Continuidad técnica](../platform/docs/INNEROS_COORDINATION_CONTINUITY_20261012.md)
- [Reglas de agentes](../AGENTS.md)
- [GitHub Actions](../.github/workflows/inneros-branch-ledger.yml)
- [GitHub PRs](https://github.com/Rafa-Innerchispa/innerops-agentic-platform/pulls)

**Frase de retomada:** «Continúa InnerOS desde `docs/INNEROS_NEXT_CHAT_HANDOFF_20261012.md`; verifica el estado vivo, no repitas tareas ni PRs integrados, arregla el inventario diario si sigue fallando, habilita fase 1 de CI/release y certifícalo por GitHub/GitLab/servidor».
