# Recuperación ante desastre — 192.168.1.4

## Cuenta Google configurada en el servidor

| Remoto rclone | Estado | Carpetas visibles |
|---------------|--------|-------------------|
| **Ralphi-IA-Gdrive** | Activo (principal) | PC-Doctor Historico, InnerSpark, InnerChispa, Domotika, Google AI Studio... |
| Gdrive | Secundario / no usado por defecto | — |

Los respaldos disaster recovery suben a:
```
Ralphi-IA-Gdrive:RalphiIA_Backups/disaster_recovery/
```

## ¿Qué respaldos existen HOY?

**Verificado 2026-06-18:** backup diario OK local + Google Drive.

| Qué | Dónde | Frecuencia | Cubre Swarm-OS + Hackathon |
|-----|-------|------------|----------------------------|
| **Disaster recovery** | `data/backups/disaster_recovery/` → **Ralphi-IA-Gdrive** | **Diario 1:30 AM** | **SÍ** (código, Mongo, .env, data/docs) |
| Snapshot ligero | `data/backups/snapshots/` | 8:00, 14:00, 22:00 | Parcial (repo sin node_modules) |
| Ralphi operacional | `ralphi_backups/` → Google Drive | 3x/día | NO (legacy Ralphi) |
| Crontab autostart | `@reboot` + cada 10 min | continuo | Relanza servicios + ngrok |

### Verificar ahora

```bash
bash /home/rlopez/projects/innerspark-swarm-os-cursor-local/scripts/verify_backup.sh
```

Estado JSON: `/home/rlopez/data/manifests/swarm-os-estado.json`

## Git — estado real

| Ruta | Git | Problema |
|------|-----|----------|
| `/home/rlopez/` | Sí (repo gigante) | Mezcla todo el home; último commit mayo 2026 |
| `innerspark-swarm-os-cursor-local/` | Repo propio (nuevo) | Aislado, correcto |
| `inneros/` | Init sin commits | Sin historial |

**Recomendación:** usar repo propio en cada proyecto bajo `/home/rlopez/projects/`.

## Ejecutar respaldo ahora

```bash
chmod +x /home/rlopez/projects/backup_disaster_recovery.sh
/home/rlopez/projects/backup_disaster_recovery.sh
```

## Agregar a cron (diario 1:30 AM)

```bash
crontab -e
# añadir:
30 1 * * * /home/rlopez/projects/backup_disaster_recovery.sh >> /home/rlopez/backups/disaster_recovery.log 2>&1
```

## Restaurar desde cero (orden)

1. **OS + Docker** instalados
2. **Restaurar código:**
   ```bash
   tar -xzf disaster_recovery_YYYYMMDD.tar.gz
   tar -xzf projects_code.tar.gz -C /home/rlopez
   tar -xzf infra_compose.tar.gz -C /home/rlopez
   ```
3. **Levantar infra Docker:**
   ```bash
   cd /home/rlopez/ai-server-v2/docker && docker compose up -d
   cd /home/rlopez/whisper-service && docker compose up -d
   cd /home/rlopez/inneros && docker compose up -d
   ```
4. **Restaurar MongoDB:**
   ```bash
   mongorestore --archive=mongo_pcdoctor_swarm.archive --drop
   ```
5. **Swarm-OS:**
   ```bash
   cd /home/rlopez/projects/innerspark-swarm-os-cursor-local
   python3 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   cp envs/swarm-os.env .env   # desde backup
   ./run_api.sh
   ```

## Qué NO está respaldado automáticamente (aún)

- Volúmenes Docker completos (Ollama models, Qdrant) — solo en backup Ralphi semanal parcial
- Windows: Antigravity, swarm-os.zip, Google Drive
- Notion (fuente externa)

## Mapa del proyecto

Ver [`MAPA_PROYECTO.md`](MAPA_PROYECTO.md)
