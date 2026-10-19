# Estado coordinación — 2026-10-19 (post-recovery)

## Git / runtime

- **main:** `6672f33d` (tras `e4d41643` #194)
- Intel y AMD: `git reset --hard origin/main` + `sync_platform_runtime_from_git.sh` + `install_inneros_coordination_timers.sh`

## Causa de la regresión

Timers systemd en **not-found** (units borradas de `~/.config/systemd/user/`). El ciclo **AG-25** (Dev Swarm) no corría desde ~2026-10-14.

## Timers activos

| Nodo | AG-25 Dev Swarm | Cursor headless | HA liveness | Interactive providers |
|------|-----------------|-----------------|-------------|------------------------|
| AMD | sí (5 min) | sí | sí | sí |
| Intel | no (por diseño) | sí | sí | sí |

## HA Cursor

Peer Intel ↔ AMD **alive** (`touch_ha_node_liveness`, 2026-10-19T06:46Z).

## Dev Swarm (AMD)

- Scheduler **enabled**, max_concurrent 4
- Workers activos: `ops_4ccf470eff0e`, `ops_6113b4f0abf7` (running)
- `ops_8dc1dbe7eddd`: en cola (`capacity_full` hasta liberar slot)

## Externos (Cursor/Codex/Antigravity)

Idle si Evolution/WhatsApp no conectada (gate #194). Cursor ops en `awaiting_cursor_claim` con `manual_dispatch_only` donde aplique.

## Mantener

No parchear solo `/home/rlopez/inneros/inneros_core/platform/` — siempre PR → `main` → sync en ambos nodos. Ver `COORDINATION_RUNTIME_DEPLOY.md`.
