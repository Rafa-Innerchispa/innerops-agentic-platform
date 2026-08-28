#!/usr/bin/env bash
# Verifica respaldos local + nube — ejecutar cuando quieras confirmar.
set -euo pipefail

DATA="/home/rlopez/data/backups/disaster_recovery"
SNAP="/home/rlopez/data/backups/snapshots"
REMOTE="Ralphi-IA-Gdrive:RalphiIA_Backups/disaster_recovery"
LOG="/home/rlopez/data/backups/disaster_recovery.log"

echo "=== Verificación backup $(date -Iseconds) ==="
echo ""

echo "## Cron backup"
crontab -l 2>/dev/null | grep -E 'backup_disaster|backup_snapshot|inneros-autostart' || echo "(sin entradas backup en crontab)"
echo ""

echo "## Último disaster recovery LOCAL"
ls -lt "$DATA"/disaster_recovery_*.tar.gz 2>/dev/null | head -3 || echo "NO hay tar.gz local"
echo ""

echo "## Último snapshot ligero"
ls -lt "$SNAP"/snapshot_*.tar.gz 2>/dev/null | head -3 || echo "NO hay snapshots"
echo ""

echo "## Log backup (últimas 5 líneas útiles)"
grep -E 'COMPLETADO|OK nube|AVISO|ERROR' "$LOG" 2>/dev/null | tail -5 || echo "(sin log)"
echo ""

echo "## Nube Google Drive"
if command -v rclone >/dev/null 2>&1; then
  rclone lsf "$REMOTE/" 2>/dev/null | tail -5 || echo "rclone: no se pudo listar $REMOTE"
else
  echo "rclone no instalado"
fi
echo ""

echo "## MongoDB en Docker"
docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^mongodb$' && echo "mongodb: UP" || echo "mongodb: DOWN"
echo ""

echo "=== Fin ==="
