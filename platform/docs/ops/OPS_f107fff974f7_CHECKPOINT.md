# OPS ops_f107fff974f7 — checkpoint integrador (2026-10-28/29)

## Fase 0 — baseline
- [x] Cherry-pick PR #231 (spawn Python/systemd, canarios idempotentes, audit readonly) sobre `cursor/ops-f107fff974f7`
- [x] CI PR #231: fallo `test_spawn_uses_persistent_systemd_unit` → corregido (mock `systemd_run_transient`)
- [ ] PR #220 retry budgets: revisión selectiva pendiente (draft, no merge)
- [ ] AMD/Intel runtime SHA: script `ops_runtime_deploy_audit_readonly.py` (read-only; SSH puede fallar)

## Fase 1 — tareas en curso / adenda
- [x] Semántica explícita inbox: `delivery_semantics` en `cursor_ops_inbox_consumer.py`
- [x] Módulo `ops_task_requirements.py` (pending→accepted→applied→verified, idempotency_key)
- [x] Replies sin cabecera P0 → adenda, no OPS duplicada (`coordination_ingest.py`)
- [x] Barrera cierre: `complete_ops_task` bloquea si hay adendas pending/accepted/applied
- [x] Tests: `test_ops_task_requirements.py`

## Fase 2 — ejecución real vs canario
- [x] `is_innocuous_canary_task` solo con `payload.execution_mode=SYNTHETIC_CANARY`
- [x] `execution_verification_class`: SYNTHETIC_CANARY_PASS vs PROVIDER_REAL_EXECUTION_VERIFIED
- [x] Canario script: auth vía `authorize_ops_task` + env `INNEROS_OPS_SYNTHETIC_CANARY_AUTH`

## Fase 3 — aprobaciones / créditos (parcial en código existente)
- [x] Vista HA local `ops_owner_approval_ha.py` (NL budget, grant, observed vs estimate) — continuación ops_2dae642f4ebf
- [ ] Push live Companion / MCP wiring producción — pendiente aprobación scoped
- [x] FMEA 12 invariantes offline — `test_ops_fmea_invariants.py` (issue #8 no copiado al público)

## Reanudación
- `task_id`: ops_f107fff974f7
- Rama: `cursor/ops-f107fff974f7`
- Checkpoint durable: este archivo + Mongo `ops_task_requirement_events` + revision en ops_tasks
