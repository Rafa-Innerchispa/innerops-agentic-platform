# Mapa de `/home/rlopez` — servidor Ralphi-IA

**Servidor:** ralphi-ia-ver-10 · 192.168.1.4  
**Última actualización:** 2026-06-12

## Vista general

```
/home/rlopez/
├── data/                              ← DATOS COMPARTIDOS (ver README ahí)
│   ├── notion_export/                 ← CSV Notion → import MongoDB
│   ├── gdrive_sync/                   ← rclone Google Drive empresa
│   ├── media/                         ← fotos, PDFs campo
│   ├── docs/                          ← informes descargables
│   ├── backups/disaster_recovery/     ← backup completo diario
│   ├── backups/snapshots/             ← Mongo+.env 3×/día
│   └── scripts/                       ← sync_gdrive, migrate_notion, setup
│
├── projects/
│   ├── innerspark-swarm-os-cursor-local/   ← SwarmOS + InnerOS (REPO PRINCIPAL)
│   └── swarm-os-google_ai_studio/          ← prototipo AI Studio
│
├── ai-server-v2/                      ← Docker stack principal (~34 GB)
│   └── docker/                        ← compose, servicios
│
├── inneros/                           ← legacy RAG (~4.9 GB) — no borrar aún
├── agentes/                           ← experimento viejo — no es producción
├── datos_agentes/ → /mnt/datos_agentes/   ← disco 2 (880 GB archivo)
└── backups/                           ← backups históricos (archivar tras migración)
```

## Servicios Docker (referencia)

| Puerto | Servicio |
|--------|----------|
| 5173 | PC Doctor Admin / InnerOS UI |
| 8100 | Swarm API |
| 3000 | Open WebUI |
| 3001 | AnythingLLM |
| 8081 | FileBrowser |
| 8082 | Evolution (WhatsApp) |
| 9001 | Whisper (voz→texto) |
| 6333 | Qdrant |
| 5678 | n8n |

## Backups activos

| Script | Frecuencia |
|--------|------------|
| `projects/backup_disaster_recovery.sh` | 01:30 diario → GDrive |
| `projects/backup_snapshot_ligero.sh` | 08:00, 14:00, 22:00 |

Instalar cron: `bash projects/scripts/install_backup_cron.sh`

## Informe completo descargable

`/home/rlopez/data/docs/RALPHI_IA_INFORME_PLATAFORMA_2026.md`

FileBrowser: http://192.168.1.4:8081 → `data/docs`

## Acceso Cursor

- **Raíz código:** `~/projects/innerspark-swarm-os-cursor-local`
- **Raíz datos:** `~/data` (añadir como carpeta al workspace si hace falta)
