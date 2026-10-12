# InnerOS fase 1 | Releases, Last Known Good y rollback

**Corte de trabajo:** 2026-10-12. **Estado real:** AMD e Intel NO_CERTIFICADO, sin GitHub Release oficial en el repositorio core. Este documento no autoriza deploys.

## Capacidades existentes que NO se deben duplicar

- `scripts/inneros_local_release_executor.py`: release limitado a **tres archivos** de Gateway/AG41. Preflight, snapshot previo, hashes y rollback **automático si el apply falla**. No es deploy universal ni permite actualmente rollback manual de una versión ya confirmada.
- `.github/workflows/inneros-local-release.yml`: dispatch manual para runner confiable AMD. Confirmar que existe, sus permisos y el ambiente protegido antes de ejecutar. No prueba un rollout Intel.
- `docs/INNEROS_RELEASE_ATTESTATION.json`: ambos hosts `verified=false`. Modificar solo con recibos de ejecución observados en esos hosts.
- `docs/INNEROS_LAST_KNOWN_GOOD.json`: `status=UNSET` hasta la primera versión realmente validada.
- `scripts/inneros_release_gate.py`: evaluación de metadatos sin cambios de estado. Si faltan recibos de ambos hosts, `BLOCKED`. Incluso con metadatos completos informa `HOST_METADATA_PRESENT_RECHECK_REQUIRED`, nunca emite una autorización de Release.
- `.github/workflows/inneros-release-readiness.yml`: disparo manual sobre `main`, produce un artefacto con motivos de bloqueo. No hace tag, restart, push, merge, release ni despliegue.

## Secuencia obligatoria de cierre

1. Seleccionar SHA de 40 caracteres que está en `main` tras PR y pruebas PASS; congelar la referencia para esa entrega.
2. Verificar sin escritura los worktrees y leases de Cursor/Codex/Antigravity, procesos y módulos Python realmente importados, PID y hashes en AMD e Intel. HEAD de checkout y puerto LISTEN no sirven como prueba de versión runtime.
3. Asegurar backup, snapshot, plan de rollback y prueba de restauración por host. Está prohibido `rsync --delete`, `git reset --hard` y reinicios amplios de servicios.
4. Desplegar sólo el alcance aprobado, un nodo por vez, con evidencia de archivos y servicio. El release executor de tres archivos no despliega el conjunto completo de InnerOS.
5. Canarios con acciones reales: AMD Qwen/vLLM, Intel Ollama, failover AMD→Intel e Intel→AMD, Cursor, Codex, Antigravity, Dev Swarm, persistencia Temporal/Mongo terminal sin duplicados ni falso `completed`.
6. Registrar recibos independientes por nodo: `runtime_git_sha`, `runtime_import_sha256`, `runtime_pid`, `tests_exit_code`, `smoke_exit_code`, `rollback_snapshot`, `evidence_path`, `verified_at_utc`. **Estos campos nunca se rellenan por supuesto**.
7. Revisar el reporte del workflow de preflight y hacer una segunda comprobación **en vivo** de los procesos. Sólo entonces aprobar el tag/versionado y publicar `vMAJOR.MINOR.PATCH` con permisos adecuados y evidencia asociada.
8. Registrar LKG en PR revisado: tag oficial, SHA, hash de módulos efectivos de ambos hosts, recibos por nodo y referencias verificadas de rollback. No falsificar LKG desde CI o `git rev-parse`.
9. Si una actualización falla, detener tareas nuevas sobre el host específico, restaurar desde snapshot validado con autorización, reiniciar sólo el servicio afectado, repetir E2E y registrar la reversión. No usar un cambio de `main` como rollback de procesos.

## Administración pendiente

En el core GitHub `Issues=false`, `main.protected=false`, `Releases=0` al corte. La conexión GitHub no ofrece activación administrativa de Issues/Rulesets ni creación de Releases. Antes de habilitar protección estricta de `main`, verificar que PR #152 permita al auditor abrir PRs sin publicar en `main`, y que `critical-runtime-contracts` se ejecute sobre los cambios del bot. Sin excepciones universales.

**Extensión transversal:** adoptar esta política en cada repositorio GitHub/GitLab y host correspondiente, preservando su propia rama principal y registros de despliegue. El hecho de que la cuenta GitHub muestre 60 repositorios no demuestra que los 60 hayan recibido esta automatización.
