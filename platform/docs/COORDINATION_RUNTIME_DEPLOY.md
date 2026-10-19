# Coordinación InnerOS — despliegue persistente (Intel + AMD)

## Problema que esto evita

El runtime vivo en `/home/rlopez/inneros/inneros_core/platform/` **no es un clon git**. Si se parchea solo ahí, un rsync, reinicio o copia desde un workspace desactualizado **revierte** los arreglos. La fuente de verdad es **`main`** en `Rafa-Innerchispa/innerops-agentic-platform` (carpeta `platform/`).

## Procedimiento canónico (cada nodo)

```bash
cd /home/rlopez/inneros/inneros_core/workspaces/innerops-agentic-platform
git fetch origin main && git reset --hard origin/main
platform/scripts/sync_platform_runtime_from_git.sh
platform/scripts/install_inneros_coordination_timers.sh
```

En Intel (sin Dev Swarm AG-25 por defecto):

```bash
INNEROS_ENABLE_AG25_TIMER=0 platform/scripts/install_inneros_coordination_timers.sh
```

## Qué hace cada pieza

| Pieza | Rol |
|--------|-----|
| `sync_platform_runtime_from_git.sh` | Copia `inneros_core_runtime/`, `scripts/`, `systemd/` del workspace git → runtime |
| `install_inneros_coordination_timers.sh` | Instala units en `~/.config/systemd/user/` y activa timers |
| `inneros-ag25-project-cycle.timer` | Ciclo Dev Swarm + guardian (AMD, cada 5 min) |
| `inneros-ha-liveness.timer` | Liveness HA Cursor Intel/AMD |
| `inneros-cursor-headless-autopilot.timer` | Claim/ejecución Cursor headless |
| `inneros-interactive-provider-autopilot.timer` | Codex/Antigravity (requiere SI WhatsApp si Evolution caída) |

## Carriles

- **Dev Swarm (`local_dev_swarm`)**: sin WhatsApp; paralelo en AMD (~4 slots).
- **Cursor / Codex / Antigravity**: con gate de owner WhatsApp si Evolution no conectada (#194).

## Verificación rápida

```bash
systemctl --user list-timers 'inneros-*' --all
cat /home/rlopez/inneros/inneros_core/var/inneros_autopilot/last-ag25-cycle.json | head
```

Merge de referencia: PR #194 (`e4d41643`).
