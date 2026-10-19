# human_task_id (alias humano canónico)

El propietario opera por **`human_task_id`**; el sistema conserva `task_id`, `correlation_id`, `workflow_id`, `run_id`.

## Campos

- `human_task_id` / `task_alias` (espejo) en `ralfia_ops_tasks`
- Herencia: mismo `correlation_id`, `parent_task_id`, `supersedes_task_id`

## Superficies

- WhatsApp: primera línea `[ALIAS]`, OPS actual abajo
- `list_ops_tasks(human_task_id=..., group_by_human=True)`
- Búsqueda WhatsApp: `CONFIRMAR` sigue usando sufijo `ops_`; alias resuelve vía `find_tasks_by_human_task_id`

## Migración

```bash
platform/scripts/backfill_human_task_ids.py --days 45 --apply
```

## Caso AMD-LEAGUE-WRAPUP

- `correlation_id`: `amd-ai-league-umbrella-20261019`
- `ops_8dc1dbe7eddd` (Dev Swarm, histórico)
- `ops_84c81dfcc896` (Antigravity)
