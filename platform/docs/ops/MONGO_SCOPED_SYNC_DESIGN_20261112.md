# Sync acotado Mongo AMD↔Intel — diseño para revisión (2026-11-12)

Estado: DISEÑO + CÓDIGO LISTOS, SIN EJECUTAR. `platform/scripts/sync_mongo_scoped.py`
implementa dry-run (defecto) y apply (`--apply --yes`, kill-switch, presupuestos,
divergencias bloquean). Requiere OK owner explícito para la primera ejecución
con `--apply` (escribe en ambas BDs). Veredicto dry-run vivo 2026-11-12T09:56Z:
push 427 / pull 55 / 0 conflictos / 0 terminal-mismatch.

## 0. Problema probado (no teoría)

- AMD `ralfia_ops_tasks`: 6722 docs; Intel: 6705. Contenidos distintos:
  cola viva Antigravity solo en Intel; backlog `pending_human_review`/
  `waiting_for_binding`/`awaiting_ide_claim` solo en AMD.
- `get_db()` prefiere Intel cuando responde: escrituras AMD caen en Intel;
  la proyección AMD envejece en silencio (dual-monitor AMD: 15 días viejo).
- Visión owner: degradación elegante —si cae un nodo, el otro sigue con
  lo suyo—. Sin sync, el sobreviviente NO ve la cola viva del caído.

## 1. Objetivo y no-objetivos

- SÍ: que la **cola viva de coordinación** sobreviva a la caída de un nodo.
- NO: espejo total, multi-master de todo, sync de telemetría/logs anchos,
  borrados cruzados (el sync jamás borra; solo upserta).

## 2. Alcance (colecciones y campos)

- `ralfia_ops_tasks`: no-terminales + contrapartes terminales del otro
  lado (para que vivo-vs-terminal se marque, jamás se resucite por
  overwrite). Campos: todo el doc menos `_id`. Límite 1MB/doc.
- `ralfia_agent_messages`: solo `open`/`sending` (INBOX vivo).
- `ralfia_task_heartbeats`: solo últimos 30 min por task (liveness).
- Fuera: métricas (`productivity_*`, `self_heal_*`), auditoría ancha,
  colecciones de notingestía, `var/` y filesystem (no es Mongo).

## 3. Precedencia y conflictos

- Clave natural: `task_id` / `message_id` (+ `task_id+ts` heartbeats).
- Regla: **LWW por `updated_at`**; empate → mayor `revision`; empate →
  prefiere Intel (proyección viva actual) y registra `sync_conflict_log`.
- Terminal sobre no-terminal: solo si el terminal es MÁS NUEVO
  (evita resurrecciones y cierres fantasma).
- `claim_token`/leases viajan como campos normales (el CAS de claim
  sigue siendo el árbitro real de doble-claim, no el sync).

## 4. Transporte y cadencia

- Poller unidireccional por sentido, cada 60s, ventana `updated_at` de
  10 min con solape (idempotente por upsert). Sin change-streams
  (topología simple, reanudable).
- Dónde corre: UN poller por sentido, cada uno en su nodo origen
  (lee local, escribe remoto). Si un nodo cae, su sentido se detiene
  solo; el otro sigue.
- Verificar antes de implementar: Intel→AMD `mongod` accesible
  (AMD→Intel probado OK; el reverso NO está probado desde aquí).

## 5. Rieles de seguridad

- Solo upserts (`update_one` + `$set` + `upsert=True`). Jamás `delete`,
  jamás `drop`, jamás `$unset` masivo. Dry-run obligatorio primero
  (contar candidatos por sentido, mostrar muestra, sin escribir).
- Kill-switch: documento `sync_control{_id:"ops_live", enabled:false}`
  detiene ambos pollers sin deploy.
- Budget: máx 500 docs/sentido/minuto; exceso ⇒ alerta, no bestia.
- Todo sync escribe `synced_at` + `synced_from` (auditable, filtrable).

## 6. Bootstrap (convergencia inicial, una vez)

1. Dry-run completo: contar divergencia por colección/estado.
2. Owner revisa el conteo + muestra.
3. Backfill por ventanas (no-terminal primero, luego ventana 6h),
   con `synced_from: bootstrap`.
4. Activar pollers. Verificar lag < 2 min en `sync_health`.

## 7. Monitoreo (`sync_health`, una doc por sentido)

`last_run`, `lag_seconds` (max updated_at remoto − espejado),
`docs_upserted_total`, `conflicts_total`, `errors_total`, `enabled`.
Alarma si `lag_seconds > 300` o `errors_total` crece 3 ciclos seguidos.

## 8. Modos de fallo

- Cae Intel: AMD sirve su proyección + lo espejado; reintentos con
  backoff; al volver, LWW converge (revisar `sync_conflict_log`).
- Cae AMD: simétrico.
- Relojes torcidos: LWW se degrada —prerrequisito NTP en ambos
  (verificar `timedatectl` en Intel al instalar).
- Split-brain con writes en ambos: LWW + log; terminal-nuevo-gana;
  revisión manual solo de `sync_conflict_log`.

## 9. Decisiones owner (bloquean implementación)

1. OK a writes cruzados recurrentes (upserts acotados, §2–§5).
2. Intel accesible: shell o sesión para instalar el poller Intel→AMD
   (+ verificar mongod AMD desde Intel + NTP).
3. Ventana (propuesta 6h) y budget (propuesta 500/min).
4. ¿El par Kiro + 7770 entran al primer backfill? (Son awaiting viejos;
   propuesta: sí, son no-terminales.)
