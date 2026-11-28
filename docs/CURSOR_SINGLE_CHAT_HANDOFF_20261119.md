# Handoff — un solo hilo de trabajo InnerOS (2026-11-19)

**Para cualquier agente nuevo (worker Intel/AMD, IDE SSH, o cloud): leer esto primero.**

## Decisión del owner

- Cuenta: **rlopez@innerchispa.us** (InnerChispa).
- **Workers permanentes** (systemd `cursor-worker.service`):
  - Intel: **`ralphi-ia-ver-10`** → `/home/rlopez/innerops-agentic-platform`
  - AMD: **`inneros-amd-5`** → mismo repo
- Visibility confirmada: **2 workers** en tailnet/Cursor.
- **No** volver a chats Gmail viejos; GitHub + Notion + Mongo son memoria.

## Qué NO mezclar

| Grok (X) | Cursor worker/IDE |
|----------|-------------------|
| Marketing, hilos, tendencias | Código, coordinación, servidores |

## Coordinación P0 (pendiente real)

1. Notify al crear ops de pago: Telegram/HA; Atlas observer o fallback directo (`ops_task_alerts.py`).
2. Externos: `detect_provider` — CLI + auth + `worktree_create_failed` en Intel/AMD.
3. Contrato: `INNEROS_DUAL_NODE_LANES_HA_COORDINATION_20261031.md`.
4. Estado canónico: `platform/docs/INNEROS_COORDINATION_CONTINUITY_20261012.md`.
5. **DONE** solo con smoke: crear ops → notify → approve → claim → receipt → cierre.

## Archivos tocados en sesión cloud

- PR #281 (workers doc + scripts): rama `cursor/dual-node-mobile-workers-3999`.
- Este handoff: `docs/CURSOR_SINGLE_CHAT_HANDOFF_20261119.md`.

## Próximo trabajo del agente (sin pedir comandos a Rafael)

Auditoría en **Intel** (`ralphi-ia-ver-10`), PRs mínimos, luego paridad AMD si aplica.