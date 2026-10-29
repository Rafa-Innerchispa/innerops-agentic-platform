# OPS ops_2dae642f4ebf — checkpoint integración (2026-10-29)

Continuación de ops_f107fff974f7 (inmutable). Rama integración: `cursor/ops-f107fff974f7` / PR [#232](https://github.com/Rafa-Innerchispa/innerops-agentic-platform/pull/232).

## Entregables (verdad operativa)

| # | Entregable | Estado | Evidencia |
|---|------------|--------|-----------|
| 1 | CI critical-runtime + lane A verde | **PASS** | GitHub PR232 checks SUCCESS (40816397733); local `237 passed` suite inneros-runtime-gates |
| 2 | Adendas durables en checkpoint worker | **PASS** | `process_checkpoint_amendments`, claim hooks cursor/generic; tests `test_ops_task_requirements_e2e.py`; fix `requirements_version_at_register==0` |
| 3 | Owner approval HA view/push presupuesto | **PASS (local)** | `ops_owner_approval_ha.py` + tests; live HA deploy **BLOCKED** (requiere aprobación scoped owner) |
| 4 | Codex/Antigravity real vs synthetic | **PASS (offline)** | Trust boundary tests; Codex CLI presente en host (`~/.local/bin/codex`); ejecución real con spend **BLOCKED** sin `record_owner_grant` + env allow |
| 5 | FMEA 12 invariantes + chaos acotado | **PASS** | `test_ops_fmea_invariants.py` |
| 6 | Runtime AMD/Intel SHA audit | **BLOCKED** | SSH/DNS Intel sin resolver; script readonly no ejecutado en esta sesión |
| 7 | PR #220 retry/fencing selectivo | **BLOCKED** | Draft; no merge; pendiente cherry-pick con tests legacy 80/51 worktrees |
| 8 | PR #231 cierre | **PENDING** | Reconciliar tras merge PR232 (no duplicar trabajo) |
| 9 | Deploy producción runtime | **BLOCKED** | Sin despliegue; CI-only manifest |

## Commits
- Base HEAD integración: `da387005` (padre)
- Continuación ops_2dae642f4ebf: ver `git log -1` tras push

## Acción owner (blockers externos)
1. **Intel runtime SSH/DNS**: restaurar resolución/host key para audit SHA readonly.
2. **Gasto real Codex/Antigravity**: `record_owner_grant` + límites USD/tokens + env explícito; Companion receipt si aplica.
3. **HA deploy push**: aprobación scoped separada (no incluida en autorización chat Cursor).

## Criterio COMPLETED
Task **no** COMPLETED hasta: merge PR232 verificado, runtime SHA audit Intel, PR220 tests fencing, despliegue explícito aprobado.
