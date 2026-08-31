# AG-37 Disk Steward — inventario discos + alertas + movimientos con aprobación WhatsApp

**Responsable:** espacio en todos los discos (/, data, projects, HDD adicionales), backups, coordinación con AG-36.

## Umbrales

| Nivel | Condición |
|-------|-----------|
| **CRÍTICO** | ≤ **20% libre** en cualquier disco monitoreado |
| **AVISO** | ≤ 30% libre en cualquier disco monitoreado |

## Política de ubicación

Los respaldos y archivos grandes no deben vivir en el filesystem raíz si existe
un disco de datos separado.

| Servidor | Destino persistente esperado |
|----------|------------------------------|
| Intel `.4` | `/mnt/datos_agentes/backups` |
| AMD `.5` | `/home/rlopez/data/backups` |

El instalador detecta el primer disco de datos que no esté en el mismo filesystem
que `/` y lo fija en el timer como `DISK_ARCHIVE_BASE`,
`DISK_ARCHIVE_ROOT` y `DISK_MIGRATION_ROOT`.

## Qué hace

1. Escanea **todos** los montajes (`df`) — incluye discos adicionales (`/mnt/...`).
2. Inventaria carpetas de **backups** conocidas (tamaño GB).
3. Lee estado **AG-36** (tareas diferidas PST/GDrive).
4. Si crítico/aviso → WhatsApp alerta inmediata por Evolution API con failover.
5. Si hay candidatos seguros (snapshots/DR antiguos) → propuesta con botones **Sí, mover** / **No mover**.
6. Registra cada alerta en Mongo aunque WhatsApp falle, para que MCP/ChatGPT la vean.
7. **Nunca** formatea discos. **Nunca** mueve Mongo, Docker, InnerOS platform sin propuesta explícita.

## Aprobación Rafael

WhatsApp:
- Botones interactivos, o
- `confirmar movimiento dm_abc123`
- `cancelar movimiento dm_abc123`

## Instalar

```bash
bash ~/inneros/inneros_core/scripts/install_disk_steward.sh
```

## MCP

Tool: `get_disk_steward_status`

## Estado JSON

`~/data/ralfia/disk_steward_<hostname>.json`

## Relación con otros agentes

| Agente | Rol |
|--------|-----|
| **AG-35** Ecosystem Pulse | Pulso general 2×/día |
| **AG-36** Deferred Tasks | Archivar PST/GDrive cuando ingesta termina |
| **AG-37** (este) | Discos + backups + propuesta mover con OK WhatsApp |
| **disk_guard.sh** | Limpieza automática menor (tmp, docker prune) — sin mover datos grandes |
