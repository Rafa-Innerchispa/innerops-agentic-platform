# Coordinación Cursor ↔ Codex

> **Nota de vigencia (2026-10-12):** documento histórico. Para el estado operativo, ID de tareas, política actual de modelos, ROCm 10/AMD Skills y criterios de entrega consultar [INNEROS_COORDINATION_CONTINUITY_20261012.md](INNEROS_COORDINATION_CONTINUITY_20261012.md). Las rutas, versiones, políticas y estados debajo pueden haber cambiado. Corroborar con Mongo/Temporal/GitHub y runtime antes de intervenir.


**Carpeta canónica (fuera del repo):**

```
/home/rlopez/data/ai_coordination/
```

**Entrada única:** [`00_LEER_PRIMERO.md`](/home/rlopez/data/ai_coordination/00_LEER_PRIMERO.md)

Rafael solo dice: *«Lee la carpeta de coordinación»*.

## Registrar trabajo

```bash
cd /home/rlopez/projects/raphiia-openai
source venv/bin/activate
python scripts/log_coordination.py --agent CURSOR --summary "..." --project raphiia-openai
```

## MCP (ChatGPT)

Tools: `get_coordination_summary`, `log_coordination_event`, `search`, `fetch`, …
