# Recuperación sistémica de coordinación (2026-10-19)

## Por qué parecía “retroceso”

Mucha lógica **ya estaba en git** (`coordination_backlog_hygiene`, reclaim de workers, auto-claim IDE) pero:

1. **Timers systemd** se borraron de `~/.config/systemd/user/` → autopilot dejó de correr.
2. **`coordination_backlog_hygiene`** existía como tool MCP con **`dry_run=True` por defecto** → nunca reclasificaba filas en Mongo.
3. **Quality gate Dev Swarm** trataba mal repos con `package_roots: ["."]` (`src/…` no contaba como producto).
4. **Admisión** no enrutaba lecturas Device Fabric → `coding` sin repo → `bounded_runner_requires_repo`.

## Correcciones generales (no parche por tarea)

| Pieza | Efecto |
|-------|--------|
| `ops_task_admission.py` | Clasifica lecturas Device Fabric al crear |
| `execution_binding.py` | Runner `device_fabric_capability` sin repo |
| `dev_swarm_scheduler` | Hygiene aplica bucket `needs_device_fabric_lane`; `requeue_retryable_blocked_ops` |
| `inneros_coordination_cycle.py` + timer 5m | Hygiene **apply** + requeue + Dev Swarm tick + autopilots IDE |
| `inneros_ag25_project_cycle.py` | Hygiene apply al inicio de cada ciclo AG-25 |
| `install_inneros_coordination_timers.sh` | Instala ciclo + restaura units |

## Operación

```bash
platform/scripts/sync_platform_runtime_from_git.sh
platform/scripts/install_inneros_coordination_timers.sh
systemctl --user list-timers 'inneros-*'
```

Reporte: `var/inneros_autopilot/last-coordination-cycle.json`
