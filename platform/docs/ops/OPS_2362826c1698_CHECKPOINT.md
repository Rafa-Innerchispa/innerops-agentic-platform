# OPS ops_2362826c1698 — cierre operativo multi-agente post PR #238

Baseline GitHub **main**: `430c13ff10f1c8a44422226f6b98326ad6b336c9` (merge PR #238, CI run `40973627165`).  
Estado Mongo task: **`awaiting_deploy_approval`** (coding entregado; deploy no autorizado por esta orden).

## Fase 1 — Preparación read-only

| Host | Rol | Evidencia |
|------|-----|-----------|
| Intel `.4` | Auditor local `ralphi-ia-ver-10` | Worktree HEAD = main SHA **PASS**; runtime import `/home/rlopez/inneros/inneros_core/platform` **sin** `ops_deploy_execution_pause.py` (**drift**); servicios headless activos vía transient units |
| AMD `.5` | Peer SSH | Workspace SHA `f3a4ecdd…` ≠ main (**drift**); peer AG-41 matrix **operative** |
| SSH Intel loopback | — | `Permission denied (publickey)` → usar peer/local, no contraseña |

**Systemd relevante (Intel, read-only):**

- `inneros-cursor-headless-ops_2362826c1698-*` — tarea actual
- `inneros-cursor-headless-ops_7039e9cc4f11-*` — relaunch legacy (runtime pre-PR238)
- `inneros-cursor-headless-autopilot.service` — **inactive**
- `inneros-interactive-provider-autopilot.service` — **inactive**
- `inneros-ops-ha-approval-worker.service` — **active**
- `inneros-temporal-worker.service` — **active**

**Python / proyecto:** registry `…/workspaces/innerops-agentic-platform` en ambos nodos (peer status OK). Intel 3.12 sin `.venv` en workspace; AMD 3.14 con `.venv` (confirmar en deploy).

**Evidencia JSON:** `var/evidence/ops_2362826c1698_runtime_deploy_audit.json`

## Fase 2 — Autorizaciones HA deploy (pendiente owner)

Notificación HA **dry-run** preparada: `platform/docs/ops/OPS_2362826c1698_HA_DEPLOY_NOTIFICATION.json`  
Push owner checkpoint emitido (`owner_approval_ha`, idempotency `owner_checkpoint:ops_2362826c1698:owner_approval_ha:r11`).

**Acción owner requerida (una sola):** emitir grant HA **separado** por host (`peer.service.action.v1` + `host.approval.issue.v1`, `dry_run=false`) para canario Intel → verificar SHA/servicios → AMD. Sin auto-grant.

## Fase 3 — Codex (`ops_d7ac9d1e90ec`)

| Campo | Valor |
|-------|--------|
| status | `blocked` |
| blocked_reason | `codex_canary_pass_ha_resume_requires_owner_reauth` |
| paid gate | `owner_budget_grant_required` |
| exec gate | `INNEROS_CODEX_OPS_ALLOW_MODEL_EXEC` unset → `blocked_execution_not_wired` |
| CLI | `codex-cli 0.144.5` presente |

**No duplicar #227.** Reanudar con push owner + `record_owner_grant` + env allow model exec.

## Fase 4 — Antigravity

`ops_64d4bf6d941e` **completed** histórico; política actual rechaza text-only (`test_ops_antigravity_false_completion_regression.py`). E2E IDE/Gemini requiere grant + `INNEROS_ANTIGRAVITY_OPS_ALLOW_MODEL_EXEC` (misma bounded executor).

## Fase 5 — FMEA / tests offline

- `test_ops_deploy_scheduler_loop_regression.py` + `test_ops_fmea_invariants.py` + `test_ops_global_completion_gate.py`: **23 passed** (venv runtime).
- Matriz: `platform/docs/ops/OPS_2362826c1698_FMEA_MATRIX.yaml`

## Acciones Mongo (dispatch, no systemd)

- `ops_7039e9cc4f11` → **`superseded`** por `ops_2362826c1698` (fencing dispatch; unidad en curso puede terminar sola).
- `ops_97310078a555` permanece **completed** (coding); E2E deploy no certificado.

## Criterio COMPLETED global

**NO OPERATIVO E2E** hasta:

1. Deploy canario PR238 en runtime Intel + AMD con recibo HA firmado  
2. Cursor + Codex + Antigravity con prueba real, commit/tests y receipt Temporal verificable  
3. Sin relaunch `ops_7039e9cc4f11` tras import SHA  

**Riesgos:** runtime vivo ejecuta autopilot **anterior** a PR238; AMD varios commits detrás de main; gasto Codex bloqueado fail-closed (correcto).
