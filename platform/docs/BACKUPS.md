# Respaldos — alineado con Ralphi IA

Este proyecto **no tiene backup propio separado**. Depende del **disaster recovery** del servidor Ralphi IA, que ya cubre MongoDB + proyectos bajo `/home/rlopez/projects/`.

Las conversaciones guardadas vía **MCP** (`raphiia_openai_*`, `ideas`, `editorial_pipeline`) viven en Mongo → **respaldadas con el DR diario** automáticamente.

## Fuentes oficiales (Swarm-OS)

Documentación canónica:

- `innerspark-swarm-os-cursor-local/docs/RECUPERACION_DESASTRE.md`
- `innerspark-swarm-os-cursor-local/docs/CONTINUIDAD_IA.md`
- `innerspark-swarm-os-cursor-local/docs/RALPHI_IA_PRESERVACION.md`

## Qué se respalda

| Qué | Dónde | Frecuencia |
|-----|-------|------------|
| **MongoDB completa** (incl. `raphiia_openai_*`) | `data/backups/disaster_recovery/` | Diario 1:30 AM |
| **Nube Google Drive** | `Ralphi-IA-Gdrive:RalphiIA_Backups/disaster_recovery/` | Diario |
| **Código proyectos** | `/home/rlopez/projects/*` en tar.gz DR | Diario |
| **`.env`** | Incluido en DR (no git) | Diario |
| Snapshots ligeros | `data/backups/snapshots/` | 3x/día |

## Verificar backups

```bash
bash /home/rlopez/projects/innerspark-swarm-os-cursor-local/scripts/verify_backup.sh
ls -lt /home/rlopez/data/backups/disaster_recovery/*.tar.gz | head -3
```

## Restaurar

```bash
restaura-a-ralphia
# o
BACKUP_FROM_CLOUD=1 restaura-a-ralphia
```

## Backup manual ahora

```bash
/home/rlopez/projects/backup_disaster_recovery.sh
```

## TODO para este repo

- [ ] Confirmar que `backup_disaster_recovery.sh` incluye `/home/rlopez/projects/raphiia-openai`
- [ ] Crear repo Git privado y push inicial
- [ ] Tras primer `.env` productivo, verificar que DR incluye el `.env` de este proyecto
- [ ] Definir nodo AMD standby para Mongo/Postgres/Qdrant snapshots y MCP minimo
- [ ] Definir bucket Google Cloud Storage cifrado para copias fuera del servidor
- [ ] Crear runbook de failover: RalfIA principal → AMD → Google Cloud

## Regla

**Conversaciones en Mongo = respaldadas** con el DR diario. No confiar solo en memoria de ChatGPT.
