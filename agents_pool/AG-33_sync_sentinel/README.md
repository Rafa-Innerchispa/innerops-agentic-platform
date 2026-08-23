# AG-33 Sync Sentinel

**Numeración:** AG-33 · **ID:** `AG-33_SYNC_SENTINEL`

Vigilante de sincronización dual-nodo Intel (.4) ↔ AMD (.5).

- Detecta sync stale (>8h sin pull OK) o push roto (cron Intel→AMD con `Permission denied`)
- Intenta `sync_from_primary_on_amd.sh` automáticamente
- Alerta WhatsApp vía `evolution_client.send_alert_whatsapp()`
- Timer: `ralfia-sync-sentinel.timer` (cada 1h)
- Script: `ralfiia-amd-standby/scripts/ag33_sync_sentinel.sh`
- Instalador: `install_sync_sentinel.sh`
