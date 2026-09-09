# AG-37 Disk Steward — inventario discos + alertas + movimientos con aprobación WhatsApp

**Responsable:** espacio en todos los discos (/, data, projects, HDD adicionales), backups, coordinación con AG-36.

## Umbrales

| Nivel | Condición |
|-------|-----------|
| **CRÍTICO** | ≤ **20% libre** en `/`, `/home/rlopez/data` o `/home/rlopez/projects` |
| **AVISO** | ≤ 30% libre |
| **REVISIÓN** | backup grande (>50GB por defecto) en mount primario que no sea archive root |

## Qué hace

1. Escanea **todos** los montajes (`df`) — incluye discos adicionales (`/mnt/...`).
2. Inventaria carpetas de **backups** conocidas (tamaño GB).
3. Detecta backups grandes en discos primarios, por ejemplo `/mnt/datos_agentes/backups/off-root`, y los marca como `second_gate_review_before_move_or_delete`.
4. Lee estado **AG-36** (tareas diferidas PST/GDrive).
5. Si crítico/aviso → WhatsApp alerta inmediata con deduplicación/histéresis para no spamear cada timer.
6. Si hay candidatos seguros (snapshots/DR antiguos) → propuesta con botones **Sí, mover** / **No mover**.
7. **Nunca** formatea discos. **Nunca** mueve Mongo, Docker, InnerOS platform ni árboles grandes sin segunda compuerta explícita.

## Restore Points

Los restore points son checkpoints de release/configuración con manifiesto, hashes y archivos pequeños copiados de forma acotada. No son backups completos ni snapshots de disco. Una restauración debe pasar por aprobación explícita del owner y plan de acciones antes de escribir sobre archivos vivos.

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
