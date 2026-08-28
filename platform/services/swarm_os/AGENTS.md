# Instrucciones para agentes IA (Cursor / cualquier modelo)

**Proyecto:** InnerSpark Swarm-OS — PC Doctor S.A. (local, MongoDB, sin créditos cloud).

## Lee esto PRIMERO (orden obligatorio)

0. [`/home/rlopez/data/ai_coordination/00_LEER_PRIMERO.md`](/home/rlopez/data/ai_coordination/00_LEER_PRIMERO.md) — coordinación RalfIA, puertos, logs (todos los proyectos)
0b. [`/home/rlopez/data/ai_coordination/CHATS_Y_MEMORIA.md`](/home/rlopez/data/ai_coordination/CHATS_Y_MEMORIA.md) — chats vs Mongo

1. [`docs/CONTINUIDAD_IA.md`](docs/CONTINUIDAD_IA.md) — guía maestra, backups, hackathon, continuidad
2. [`docs/INSTRUCCIONES_AGENTE.md`](docs/INSTRUCCIONES_AGENTE.md) — cómo retomar sin romper nada
3. [`docs/MAPA_PROYECTO.md`](docs/MAPA_PROYECTO.md) — visión, qué funciona, qué falta, decisiones tomadas
3. [`docs/ESQUEMA_MONGODB_DBxx.md`](docs/ESQUEMA_MONGODB_DBxx.md) — esquema canónico DB01–DB52
4. [`docs/CANON_CORRECCIONES_DBxx.md`](docs/CANON_CORRECCIONES_DBxx.md) — errores corregidos vs Notion
5. [`docs/SOPS_LOGICA_OPERATIVA.md`](docs/SOPS_LOGICA_OPERATIVA.md) — SOPs + invariantes Playbook
6. [`docs/RELACIONES_Y_FLUJOS.md`](docs/RELACIONES_Y_FLUJOS.md) — relaciones DB → Mongo + gates
7. [`docs/ARQUITECTURA_FLUJOS.md`](docs/ARQUITECTURA_FLUJOS.md) — por qué no las 52 DB en cada flujo
8. [`docs/ACCESO_RED.md`](docs/ACCESO_RED.md) — Windows usa 192.168.1.4, no localhost
9. [`docs/RECUPERACION_DESASTRE.md`](docs/RECUPERACION_DESASTRE.md) — backups (`scripts/verify_backup.sh`)

## Reglas al programar

- **Servidor:** desarrollo solo en **`192.168.1.4`** vía Remote SSH — ver `docs/ACCESO_RED.md`
- Al terminar sesión: `python /home/rlopez/projects/raphiia-openai/scripts/log_coordination.py --agent CURSOR --summary "..." --project innerspark-swarm-os`
- **No mezclar** con `/home/rlopez/inneros/` (hackathon) ni `/home/rlopez/agentes/`.
- **No copiar** lógica rota de Google AI Studio; solo plantillas/reglas.
- **Cabecera ≠ líneas:** cotización = `quotes` + `quote_lines` (DB27/DB38).
- **No fusionar** visita + reporte + cotización en un solo documento (`inspections` es legacy).
- **Hub-first:** todo entregable lleva `client_id`.
- **Secuenciales:** usar `tools/schema.py` → `next_serial()` (DB40), nunca inventar códigos.
- **`.env` nunca a git.** Credenciales solo en `.env`.
- **Cambios mínimos:** no refactorizar fuera del alcance pedido.
- **Español** en documentación y respuestas al usuario (Rafael).

## Código clave

| Archivo | Rol |
|---------|-----|
| `api/main.py` | FastAPI :8100 |
| `agents/crew.py` | Flujo multi-agente |
| `tools/mongo.py` | Acceso BD (legacy + v2) |
| `tools/schema.py` | Colecciones, índices, secuenciales |
| `tools/workflow_v2.py` | Flujo campo DB42→45→27/38 |
| `tools/gates.py` | Gates Playbook (hub, DB38, PDF-first, duplicados) |
| `scripts/migrate_v1_to_v2.py` | Migrar `inspections` → modelo v2 |

## Arranque

```bash
cd /home/rlopez/projects/innerspark-swarm-os-cursor-local
source venv/bin/activate
./run_api.sh
curl http://192.168.1.4:8100/status
```

## Fase actual

**Fase A:** flujo campo end-to-end con esquema v2 (DB04→DB45→DB27/38→DB40→DB41→DB52).

Ver checklist en `docs/MAPA_PROYECTO.md` sección 5.
