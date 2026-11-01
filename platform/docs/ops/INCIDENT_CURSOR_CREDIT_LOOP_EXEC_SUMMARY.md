# Incidente P0: bucle Cursor / créditos (~80% cuota) — resumen ejecutivo

**Fecha incidente:** 2026-10-29 (America/Guayaquil)  
**Tarea emblemática:** `ops_7039e9cc4f11` (certificación E2E / deploy Intel+AMD)  
**Estado código (2026-11-01):** mitigaciones integradas en `main`; **despliegue runtime obligatorio** en Intel y AMD al mismo SHA.

---

## Qué pasó (cadena causal)

1. **Varias OPS P0** autorizadas vía Home Assistant → `ops_post_owner_autopilot` → **Cursor headless** (`Agent.prompt` / `composer-2.5`, facturación Cursor, no inferencia local).
2. Objetivos mezclaban **código + deploy en producción**. El gate de completitud exigía **evidencia de mutación en host**; la tarea no podía cerrarse como `COMPLETED`.
3. **Antes de PR #238**, autopilot, Dev Swarm scheduler y recuperación Temporal **seguían reclamando / re-spawneando** headless aunque el mensaje del gate fuera “falta deploy / receipt”. Cada tick (~2 min) podía volver a pagar SDK.
4. **Runtime desalineado de GitHub `main`:** Intel llevaba código **sin** `ops_deploy_execution_pause.py` ni regresión CI (#238). Los receipts del integrador documentaban merge en git pero **`ops_runtime_deploy_audit_readonly` → ok: false** (AMD/Intel ≠ SHA main).
5. **Duplicación systemd:** logs con `worker_spawn_failed` / “unit already loaded” → riesgo de **workers paralelos** sobre la misma OPS.
6. **Efecto créditos:** cientos de ejecuciones SDK (evidencia ~265 resultados “success” en logs headless en Intel); el owner cortó red para detener agentes. Totales de factura no estaban en el servidor (ver doc Codex).

Documentación detallada de contención (Codex): `platform/docs/CURSOR_RETRY_CREDIT_INCIDENT_20261029.md`.  
Checkpoint operativo: `platform/docs/ops/OPS_7039e9cc4f11_CHECKPOINT.md`.

---

## Controles que deben permanecer en `main` + runtime

| Capa | Mecanismo | Archivo / PR |
|------|-----------|--------------|
| Deploy pause | `execution_automation_frozen`, `awaiting_deploy_approval`, sin respawn headless ni reopen Temporal | PR **#238** → `ops_deploy_execution_pause.py` |
| Admission Cursor | Política única resume/dispatch/worker; terminal, superseded, stopped, manual, lanes interactivos | PR **#249** → `cursor_headless_policy.py` |
| Presupuesto dispatch | Máx. **3** reservas automáticas por tarea (atómico) | `cursor_headless_policy` + dispatch |
| Fleet budget | Guard + auditoría periódica de recursos de ejecución | PR **#250** → `execution_resource_guard.py`, timer audit |
| Retry fences | Grants DevSwarm / fences acumulativos | PR **#233** |
| Regresión CI | `test_ops_deploy_scheduler_loop_regression.py` en runtime gates | commit `2d0028af` |
| Dual-node HA | Failover inferencia + monitor lease | ADR_018 + cherry-pick rama `chatgpt/inneros-dual-node-ha-20261010` |

**Notion → cola OPS:** `poll_pending_coordination_orders` (no estaba en `main`; añadido en commit de coordinación 2026-10-31).

---

## Por qué ChatGPT no pudo “romper” el bucle

El freno operativo era **en el nodo** (timers systemd, Mongo estado de tarea, unidades `inneros-cursor-headless-ops_*`), no en el chat. Sin MCP de ejecución local o SSH, el canal remoto no deshabilitaba autopilot ni enmascaraba units. Orden correcta: **owner stop** en Mongo + **stop/mask timer** + **network kill** (último recurso).

---

## Despliegue post-incidente (obligatorio)

1. Publicar `main` a **Intel y AMD** con el mismo SHA (`deploy_platform_mirror_ha.sh` o rsync equivalente).
2. Instalar timer **`inneros-execution-resource-audit.timer`** si no existe.
3. Verificar: `test -f .../ops_deploy_execution_pause.py` en ambos nodos.
4. Reconciliar OPS abiertas: `do_not_auto_dispatch`, `execution_stop`, `superseded` en canarios muertos (`ops_queue_hygiene_zero_pending.py --apply` con cuidado).
5. **No reactivar** Cursor headless autopilot hasta orden explícita del owner y SHA auditado.

---

## Higiene de ramas (política)

- **Canónico:** GitHub `Rafa-Innerchispa/innerops-agentic-platform` → rama `main`.
- **~587** ramas remotas sin merge vs **~3888** merged (oct 2026); no borrar masivo: usar `scripts/inneros_branch_ledger.py` + etiqueta `archived/YYYY-MM` en ramas ya cherry-picked.
- Ramas **preservadas en main** (2026-11-01): `#238`, Codex `#249`/`#250`, dual-node HA 20261010, Notion poll.
- PRs **DRAFT** `#249`/`#250`: cerrar tras merge local; integrador `#248` ya **MERGED**.
- GitLab `main` diverge de GitHub: tratar GitLab como espejo secundario hasta sync explícito.

---

## Acciones pendientes owner

- Aprobar deploy canario Intel+AMD al SHA actual de `main`.
- Evolution WhatsApp / IMAP (alertas HA) — independiente del bucle Cursor pero bloquea coordinación visible.
- Revisar PRs OPEN antiguos (#231, #219, …) y archivar o rebase contra `main` reciente.
