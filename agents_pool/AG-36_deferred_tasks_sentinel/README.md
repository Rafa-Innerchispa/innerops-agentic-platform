# AG-36 Deferred Tasks Sentinel

**Responsable:** ejecutar tareas de almacenamiento diferidas cuando la ingesta KB lo permite — sin olvidar nada.

## Tareas automáticas

| ID | Cuándo | Acción |
|----|--------|--------|
| `cleanup_hdd2tb` | Inmediato | Elimina `/home/rlopez/data/hdd2tb` (symlink circular) |
| `pst_archive_intel` | PST extract ≥100% + ingest AMD terminado | rsync Intel → `/mnt/datos_agentes/backups/pst_archive/` |
| `pst_archive_amd` | PST ingest terminado + `.pst` en projects | rsync → `/home/rlopez/data/pst_archive/` |
| `gdrive_archive_amd` | GDrive ingest 100% | rsync incremental → `google_drive_archive/` |
| `post_gdrive_verify` | Tras rsync GDrive | Log Qdrant; borrar origen solo tras `gdrive_archive_verified=true` o 24h |

## Infraestructura

- **Script:** `ralfiia-amd-standby/scripts/ag36_deferred_tasks_sentinel.sh`
- **Timer:** `ralfia-deferred-tasks.timer` cada 30 min
- **State:** `~/data/ralfia/.ag36_deferred_state.json`
- **Manifest:** `~/data/ralfia/deferred_tasks_manifest.json`
- **Log:** `~/data/ralfia/ag36_deferred.log`
- **MCP:** `get_deferred_tasks_status`
- **WhatsApp:** milestones vía `send_alert_whatsapp` (593999059000, RALFIA_ALERTS_VIA_NODE=primary)

## Instalar

```bash
bash ~/projects/ralfiia-amd-standby/scripts/install_deferred_tasks_sentinel.sh
```

## Verificar manualmente

```bash
systemctl --user status ralfia-deferred-tasks.timer
cat ~/data/ralfia/deferred_tasks_manifest.json | jq .
PYTHONPATH=~/projects/raphiia-openai ~/projects/raphiia-openai/venv/bin/python3 -c \
  "from raphiia_openai.deferred_tasks_status import get_deferred_tasks_status; import json; print(json.dumps(get_deferred_tasks_status(), indent=2))"
```

## Marcar verificación GDrive manual

Editar `~/.ag36_deferred_state.json` → `gdrive_archive_amd.gdrive_archive_verified: true` cuando hayas probado búsqueda en voz/MCP.
