# AG-34 KB Ingest Sentinel

**Responsable:** vigilancia ingesta única Notion + Google Drive + PST → Qdrant.

- **Timer:** `ralfia-kb-ingest-sentinel.timer` cada 30 min
- **WhatsApp:** milestones 25/50/75/90/100% + alerta al completar todo
- **Auto-heal:** relanza GDrive ingest si muere; lanza PST ingest AMD cuando Intel termina
- **Estado:** `get_kb_ingest_status` (MCP) o `raphiia_openai/kb_ingest_status.py`
- **Log:** `~/data/ralfia/kb_ingest_sentinel.log`

Instalar: `bash ralfiia-amd-standby/scripts/install_kb_ingest_sentinel.sh`
