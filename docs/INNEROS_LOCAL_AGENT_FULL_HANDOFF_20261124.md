# Handoff completo — agente local Intel/AMD (nov 2025)

**Para:** chat/agente con SSH o Cursor My Machines en `ralphi-ia-ver-10` / `ralfiia-amd`  
**No usar:** Cloud Agent sin acceso LAN (no puede reiniciar systemd, ni Mongo productivo, ni validar Telegram en vivo).  
**Cuenta Cursor workers:** `rlopez@innerchispa.us` — workers `ralphi-ia-ver-10`, `inneros-amd-5` (My Machines, ya configurados).  
**Repo Git canónico:** `~/innerops-agentic-platform` (`Rafa-Innerchispa/innerops-agentic-platform`, `main` @ ≥ `e89f1770`).  
**Leer primero:** `AGENTS.md`, `platform/docs/INNEROS_COORDINATION_CONTINUITY_20261012.md`, `docs/INNEROS_BRANCH_LEDGER.md`.

---

## 1. Objetivo inmediato (P0)

1. **Coordinación owner notify:** crear ops IDE (Cursor/Codex/**Antigravity**) → **Telegram + HA + Alexa registry** en paralelo; Rafael aprueba **una** vía (`ops_owner_decision_registry`).
2. **Parar spam Telegram** de tareas/canarios viejos que siguen en Mongo como activas.
3. **Unificar runtime:** el código que corre en producción **no** es el mismo árbol que Rafael actualizó con el canario manual (ver §4).
4. **Fase 2** (después de P0): CLIs `cursor-agent`, `codex`, `agy` + worktrees en Intel para claim tras autorizar.

---

## 2. Lo que YA está probado (evidencia)

| Hecho | Detalle |
|-------|---------|
| PR **#283** | Fusionado — `notify_ops_owner_authorization_request` envía Telegram directo si `NOTIFY_OPS_TELEGRAM_DIRECT_ON_CREATE=1` (default **1** en código). |
| Canario one-shot | `bash platform/scripts/owner_authorization_notify_canary_one_shot.sh` en Intel **2026-11-20** → `ok: true`, Telegram msg **2165** + HA Infinix + registry. |
| Tarea canario | `ops_f31d48cab238`, correlación `owner-notify-canary-20261120T045420Z-7da140`, JSON en `var/owner_notify_canary_latest.json`. |
| Bugs corregidos en `main` | SyntaxError `_internal_brief_enabled`; shadow stdlib `platform` en one-shot script (`INNEROS_REPO` + limpiar `sys.path`). |

**Rafael aún debe confirmar** en Telegram/Alexa ese canario si no lo hizo (o cancelar/supersede para no dejar ruido).

---

## 3. Síntomas nuevos (reportados 24 nov)

### 3.1 Antigravity vía coordinación: Alexa sí, Telegram no

**Hipótesis ordenadas (verificar en este orden):**

1. **Doble árbol de código (más probable):** servicios systemd y MCP usan  
   `/home/rlopez/inneros/inneros_core/platform`  
   mientras Rafael hace `git pull` en  
   `~/innerops-agentic-platform`.  
   El canario manual corrió código **nuevo** en el clone GitHub; las tareas reales por MCP/Temporal pueden correr código **viejo** (`telegram_via_atlas_observer`, early return solo registry → Alexa habla, Telegram no).

2. **Variables de entorno solo en shell:** `NOTIFY_OPS_TELEGRAM_DIRECT_ON_CREATE=1` aplicó en one-shot export; **no** está en `platform/.env.ops-notify` ni en unidades systemd → worker Temporal/MCP sin direct Telegram.

3. **`registry_only_ok`:** si `direct_tg` false o `tg.send_message` falla, el flujo marca `ok: true` con solo `alexa_shared_registry` (`ops_task_alerts.py` ~409–424). Alexa anuncia; Telegram no.

4. **Dedupe/cooldown:** `_can_send("owner_auth", human_task_id)` bloquea reenvío si alias repetido; HA/Alexa pueden haber disparado por otro carril.

5. **`notify_cursor_awaiting_claim`:** tras transición a `awaiting_antigravity_claim`, segunda notificación va por **HA/email**, no el mismo path Telegram con botones (`temporal_activities.py`).

**Archivos clave:**

- `platform/inneros_core_runtime/notifications/ops_task_alerts.py` — `notify_ops_owner_authorization_request`, `_owner_auth_telegram_direct_enabled`
- `platform/inneros_core_runtime/coordination_live.py` — `create_ops_task` llama notify al crear
- `platform/inneros_core_runtime/ops_alexa_owner_auth.py` — primera decisión gana
- `platform/inneros_core_runtime/ops_owner_decision_registry.py`
- `platform/inneros_core_runtime/temporal_activities.py` — `notify_cursor_awaiting_claim`

### 3.2 Telegram pide actualización de tareas viejas / pruebas

**Hipótesis:**

1. **Mongo:** muchas `ralfia_ops_tasks` en estados no terminales (`queued`, `awaiting_*_claim`, `verification`) — títulos canary/smoke.

2. **`inneros-coordination-owner-summary`:** timer ejecuta `coordination_owner_summary.py` → `notify_owner` → **Telegram fanout** con lista de OPS activas (incluye viejas).

3. **`inneros-coordination-cycle`:** hygiene con `INNEROS_COORDINATION_HYGIENE_APPLY=1` debería archivar/fence; puede no clasificar todos los títulos de prueba (ver regex en `ops_queue_hygiene_zero_pending.py`).

4. **Poll Telegram:** botones viejos siguen en el chat; si el poll re-procesa updates, puede reactivar lógica sobre `task_id` antiguos.

**Herramientas:**

- `platform/scripts/ops_queue_hygiene_zero_pending.py` (dry-run luego apply)
- `platform/scripts/reconcile_ops_mongo_temporal.py`
- Mongo query: tasks `status` not in terminal, `created_at` > 7d, title ~ canary|quad|notify-canary

---

## 4. Infraestructura (recordatorio)

| Nodo | IP / host | Rol |
|------|-----------|-----|
| Intel | `192.168.1.4`, `ralphi-ia-ver-10` | Coordinación, Temporal worker, Mongo, MCP :8102, Telegram poll, HA push |
| AMD | `192.168.1.5`, `ralfiia-amd` | vLLM :8000, Dev Swarm, Cursor worker |
| Mongo | `pcdoctor_swarm`, colección **`ralfia_ops_tasks`** (confirmar nombre en `coordination_live.OPS_TASKS_COL`) | |

**Rutas que confunden (arreglar P0):**

| Uso | Ruta |
|-----|------|
| Clone Git (Rafael, workers, CI) | `/home/rlopez/innerops-agentic-platform` |
| Runtime systemd histórico | `/home/rlopez/inneros/inneros_core/platform` |
| Bridge RaphiIA MCP docs | `/home/rlopez/projects/raphiia-openai` |

**Unidades user systemd relevantes** (rutas en unit files apuntan a `inneros/inneros_core`):

- `inneros-coordination-cycle.timer` / `.service`
- `inneros-coordination-owner-summary.timer`
- `inneros-telegram-ops-poll.service`
- `inneros-interactive-provider-autopilot.timer`
- `inneros-temporal-worker.service` (verificar nombre real en host)
- `cursor-worker.service` (My Machines)

**Env obligatorios (persistir en `.env.ops-notify` + drop-ins):**

```bash
NOTIFY_OPS_TELEGRAM=1
NOTIFY_OPS_TELEGRAM_DIRECT_ON_CREATE=1
NOTIFY_OPS_AUTH_HA=1
NOTIFY_OPS_CREATE_AUTHORIZATION=1
NOTIFY_OPS_TASKS=1
```

Template repo: `platform/.env.ops-notify` (añadir línea DIRECT si falta en host).

---

## 5. Plan de trabajo para el agente local (orden estricto)

### Fase A — Diagnóstico read-only (15 min)

```bash
export INNEROS_REPO=~/innerops-agentic-platform
cd "$INNEROS_REPO" && git fetch origin main && git log -1 --oneline origin/main
# Comparar SHA runtime vs Git
for D in "$INNEROS_REPO/platform" /home/rlopez/inneros/inneros_core/platform; do
  echo "=== $D ==="
  git -C "$(dirname "$D")/.." rev-parse HEAD 2>/dev/null || true
  rg -n "telegram_via_atlas_observer|_owner_auth_telegram_direct" "$D/inneros_core_runtime/notifications/ops_task_alerts.py" 2>/dev/null | head -5
done
systemctl --user list-timers 'inneros-*' --no-pager
systemctl --user is-active inneros-telegram-ops-poll.service
```

### Fase B — Unificar código en runtime productivo

**Opción recomendada:** script de promoción existente o:

```bash
cd ~/innerops-agentic-platform && git pull origin main
# Ajustar según runbook del host (NO force-push):
# rsync o git worktree hacia inneros_core, o cambiar systemd WorkingDirectory al clone GitHub
```

Documentar SHA desplegado en `/home/rlopez/inneros/inneros_core/var/deployed_main_sha.txt`.

Añadir a **ambos** `.env.ops-notify` (clone + inneros_core):

`NOTIFY_OPS_TELEGRAM_DIRECT_ON_CREATE=1`

```bash
systemctl --user daemon-reload
systemctl --user restart inneros-telegram-ops-poll.service
systemctl --user start inneros-coordination-cycle.service
# Reiniciar temporal-worker / mcp según unit names reales en el host
```

### Fase C — Repro Antigravity

Crear ops Antigravity como lo hace coordinación (MCP `create_ops_task` o script), capturar JSON de notify:

```bash
export NOTIFY_OPS_TELEGRAM_DIRECT_ON_CREATE=1 NOTIFY_OPS_AUTH_HA=1
cd ~/innerops-agentic-platform
PYTHONPATH=platform python3 <<'PY'
import json, sys, uuid
from pathlib import Path
_root = Path.home() / "innerops-agentic-platform"
sys.path = [p for p in sys.path if Path(p).resolve() != _root]
sys.path.insert(0, str(_root / "platform"))
from inneros_core_runtime import coordination_live as cl
from inneros_core_runtime.notifications import ops_task_alerts as alerts
from inneros_core_runtime import execution_binding as eb
cid = "ag-notify-canary-" + uuid.uuid4().hex[:8]
out = cl.create_ops_task(
    assignee="antigravity",
    title="[CANARIO] AG notify Telegram+Alexa",
    objective="Solo prueba notify. No ejecutar.",
    preferred_provider="antigravity",
    execution_lane="antigravity_interactive",
    correlation_id=cid,
    do_not_auto_dispatch=True,
    from_agent="local_handoff_ag_canary",
)
tid = out.get("task_id")
print("create", json.dumps(out, indent=2, default=str)[:4000])
if tid:
    from raphiia_openai import mongo_store
    from inneros_core_runtime.coordination_live import OPS_TASKS_COL
    t = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or {}
    n = alerts.notify_ops_owner_authorization_request(t, binding=eb.resolve_execution_binding(t), force=True)
    print("notify", json.dumps(n, indent=2, default=str)[:4000])
PY
```

Rafael confirma si llegó Telegram. Si no: inspeccionar `delivery_mode` y `telegram.skipped` en salida.

### Fase D — Hygiene spam Telegram

```bash
cd ~/innerops-agentic-platform
PYTHONPATH=platform python3 platform/scripts/ops_queue_hygiene_zero_pending.py --dry-run 2>/dev/null | tail -80
# Si el output es razonable:
PYTHONPATH=platform python3 platform/scripts/ops_queue_hygiene_zero_pending.py --apply 2>/dev/null | tail -80
```

Incluir en fence/supersede: `owner-notify-canary`, `quad-canary`, `cursor-ha-e2e`, tareas sin `owner_authorized_at` > 3 días.

Opcional: desactivar temporalmente `inneros-coordination-owner-summary.timer` si sigue spameando hasta limpiar Mongo.

### Fase E — Autorización Rafael + verificación

- Rafael **Confirmar** una vía; segunda debe duplicar-rechazar.
- Verificar Mongo: `owner_authorized_at`, `owner_authorization_channel`.
- Si claim falla → `external_repair_agent.detect_provider` para `antigravity`, `cursor`, `codex` en Intel.

---

## 6. Scripts y artefactos

| Script | Uso |
|--------|-----|
| `platform/scripts/owner_authorization_notify_canary_one_shot.sh` | Canario Cursor notify |
| `platform/scripts/coordination_p0_deploy_intel.sh` | Pull + flags (mejorar para merge no-ff) |
| `platform/scripts/ops_queue_hygiene_zero_pending.py` | Limpiar cola ruido |
| `platform/scripts/verify_cursor_auto_claim_pipeline.py` | Timers, admission |
| `docs/CURSOR_OWNER_NOTIFY_CANARY_HANDOFF_20261120.md` | Slice canario anterior |

---

## 7. CLIs fase 2 (no bloquean notify)

En Intel, `PATH` debe incluir `~/.local/bin`:

- `cursor-agent` + `cursor-agent whoami` o `CURSOR_API_KEY`
- `codex` + `~/.codex/auth.json`
- `agy` / `antigravity` + auth Gemini/AG

---

## 8. Coordinación entre chats (para Rafael)

1. **Abrir chat nuevo** en Cursor con worker **Intel** o SSH local.
2. Primer mensaje del chat: pegar el párrafo de la §9.
3. Agente debe leer **este archivo** y ejecutar Fases A→D sin pedir comandos intermedios a Rafael.
4. Este archivo vive en Git: siempre `git pull` y leer versión actual.

**No marcar DONE** hasta: (a) AG + Cursor notify Telegram con mismo SHA runtime, (b) hygiene reduce OPS activas ruido, (c) evidencia JSON guardada en `var/`.

---

## 9. Párrafo único (copiar al otro chat)

Lee y ejecuta `~/innerops-agentic-platform/docs/INNEROS_LOCAL_AGENT_FULL_HANDOFF_20261124.md` (tras `git pull origin main`): el Cloud Agent no tiene LAN; PR #283 está en main y el canario Cursor `ops_f31d48cab238` probó Telegram+HA el 20-nov, pero producción probablemente sigue en `/home/rlopez/inneros/inneros_core/platform` sin `NOTIFY_OPS_TELEGRAM_DIRECT_ON_CREATE` persistente, lo que explica Antigravity con Alexa sí y Telegram no; además hay spam de ops viejas vía timers/hygiene. Haz Fase A–D del handoff (unificar SHA runtime con `innerops-agentic-platform`, fijar `.env.ops-notify`, reiniciar `inneros-telegram-ops-poll` y ciclo coordinación, canario Antigravity con notify JSON, `ops_queue_hygiene_zero_pending.py` apply). Rafael solo confirma botones Telegram/Alexa; tú entregas evidencia en `var/` y no pidas comandos paso a paso.

---

## 10. Historial fixes (cloud, no repetir)

- Diverging `main` en Intel → `git merge --no-edit origin/main`
- Python `platform` shadow → `INNEROS_REPO` en one-shot
- SyntaxError línea 179 `ops_task_alerts.py` — commit `e89f1770`