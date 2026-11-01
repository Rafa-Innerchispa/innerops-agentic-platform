# InnerOS — Carriles dual-nodo, agentes externos/internos y coordinación HA

**Fecha:** 2026-10-31  
**Estado:** Documento canónico de arquitectura + operación (persiste en `main` / runtime)  
**Audiencia:** Owner (Rafael), Cursor, ChatGPT, Codex, Antigravity  
**Motivo:** El chat se pierde; las tareas en Notion no “bajan” solas. Este archivo es la fuente recuperable junto a Mongo `ralfia_ops_tasks` y el HUB de coordinación.

---

## 1. Resumen ejecutivo

InnerOS **no es una configuración de producto empaquetado**, pero **sí es una composición estándar de la industria** (Temporal + cola Mongo + human-in-the-loop + rate limits + workers por nodo). Lo **poco común** es tener **tres proveedores IDE de pago** (Cursor, Codex, Antigravity), **dos servidores activos** (Intel + AMD), **MCP Small** como puerta, **Home Assistant Companion** como autorización móvil, y **modelos locales Qwen/vLLM** en paralelo.

**Hoy:** casi todo el código relevante está en **`main`** y desplegado en runtime Intel; AMD debe tener **paridad funcional** (mismas CLIs, mismos timers, mismos límites por env). La coordinación **autónoma** (correo → propuesta → HA → ejecución local/pagada) **no termina de cerrar el circuito**: el owner sigue empujando manualmente porque faltan gates unificados, notify HA en todos los eventos, y schedulers que consuman trabajo **local-first** sin desbordar créditos.

**Meta:** Rafael solo **orquesta decisiones** (aprobar/rechazar/límites en HA). Agentes internos (Qwen, Dev Swarm, email intelligence) **proponen y preparan**; agentes externos **ejecutan solo con grant** y techo duro de intentos/tiempo.

---

## 2. ¿Existe “una solución ya hecha”?

| Pieza | Qué aporta | En InnerOS |
|-------|------------|------------|
| **Temporal** | Timeouts, cancel, señales humanas, no loops infinitos en workflow | `inneros-temporal-worker`, ops workflows |
| **Mongo ops tasks** | Proyección de cola, claims, leases, receipts | `ralfia_ops_tasks` |
| **Human-in-the-loop** | Aprobar antes de gasto/deploy | HA Companion + `owner_authorized_at` |
| **Lanes / semáforos** | Máx. concurrentes por proveedor y host | `interactive_provider_lanes`, `cursor_headless_lanes` |
| **Presupuesto headless** | Máx. re-dispatches | `MAX_AUTOMATIC_DISPATCHES = 3`, SIGALRM 900s default |
| **Local-first** | Qwen/Ollama antes de APIs | `local_model_router`, Dev Swarm, `CREDIT_AND_LOCAL_FIRST_POLICY.md` |

**No hay un solo producto** que implemente “Cursor+Codex+Antigravity+HA+dual node”. La implementación correcta es **seguir componiendo** estos bloques con **un contrato único por tarea** (ver §6).

---

## 3. Mapa de infraestructura (dos nodos)

| Nodo | LAN | Rol típico | GPU / modelos locales |
|------|-----|------------|------------------------|
| **Intel** | `192.168.1.4` | Coordinación, Mongo primario, HA push, MCP routers, Temporal worker | Qwen / cargas en **~32 GB** (según despliegue actual) |
| **AMD** | `192.168.1.5` | vLLM, media, workers secundarios, tunnel GPU | **~12 GB VRAM** NVIDIA — modelos locales sirviendo |

**Regla de red (runtime):** peer a peer en **LAN** (`192.168.1.4` / `.5`). Tailscale solo laptop/Cursor SSH.

**Paridad obligatoria:** todo script/systemd/env que se active en Intel para OPS IDE debe existir en AMD con `INNEROS_NODE_ROLE=amd` (Intel: `intel`). Los tres carriles externos (Cursor, Codex, Antigravity) deben poder ejecutarse en **cualquier nodo** si la tarea lleva `preferred_execution_host` / steering y el peer está vivo (`should_this_node_run_task`).

---

## 4. Matriz de carriles (capacidad teórica)

Los números son **por host** salvo Dev Swarm (scheduler global). Valores por defecto en `.env` Intel (2026-10-31); AMD debe **replicar** (verificar en deploy).

### 4.1 Agentes externos (de pago / IDE)

| Proveedor | Env | Default nodo | Techo nodo | Máx. flota (Intel+AMD activos) |
|-----------|-----|--------------|------------|--------------------------------|
| **Cursor** headless | `INNEROS_CURSOR_MAX_CONCURRENT` | 2 | 8 (`CEILING`) | **4** (2+2) si ambos nodos ejecutan |
| **Codex** | `INNEROS_CODEX_MAX_CONCURRENT` | 1 | 2 | **2** (1+1) |
| **Antigravity** | `INNEROS_ANTIGRAVITY_MAX_CONCURRENT` | 1 | 2 | **2** (1+1) |

**Conteo real:** cada nodo cuenta lanes con `provider_execution_started_at` / `headless_execution_*` **en ese host** (`interactive_provider_lanes.active_lane_count`, `cursor_headless_lanes.active_lane_count`). Tras limpieza 2026-10-31: `verification` ya no bloquea slot Antigravity/Codex; reconcile periódico libera PIDs muertos.

**Cursor adicional:** máximo **3** dispatches automáticos por tarea (`cursor_headless_policy.MAX_AUTOMATIC_DISPATCHES`); timeout SDK **900 s** (`INNEROS_CURSOR_SDK_TIMEOUT_SECONDS`).

**Importante:** “tres carriles externos” en Intel = **tres tipos de proveedor**, no “tres tareas totales”. En el peor caso teórico por nodo: hasta **4** ejecuciones pagadas concurrentes (2 Cursor + 1 Codex + 1 Antigravity). Flota: hasta **~8** pagadas si ambos servidores saturan (raro; requiere grants y HA por tarea).

### 4.2 Agentes internos (local / sin IDE cloud)

| Carril | Control | Default / notas |
|--------|---------|-------------------|
| **Dev Swarm** | `DEV_SWARM_MAX_CONCURRENT` | 8 workers lógicos; tick/executor en `inneros_coordination_cycle` |
| **Dev Swarm executor** | `DEV_SWARM_EXECUTOR_LIMIT` | 2 por ciclo |
| **Local model router** | Política por tarea | Qwen 7B/14B/coder en AMD/Intel según `local_model_router.py` |
| **Email intelligence** | `email_ops_alignment`, digest | Clasificar, proponer ops; cancelar ruido |
| **Inbox agents** | `poll_agent_inbox`, AG-25 | Codex/Cursor/Antigravity/ChatGPT — **no sustituye** ops Mongo |

**Gap de producto:** los modelos en AMD (12 GB) e Intel (32 GB) **están infraestructura listos** pero **no hay un autopilot cerrado** que: lea correo → resuma → cree propuesta → **push HA** → al aprobar enrute a Qwen (local) o escale a IDE (grant). Piezas existen; falta **un solo scheduler de “trabajo proactivo”** con techo global.

### 4.3 Techo global deseado (diseño owner)

Propuesta de gobernanza (implementación parcial en main; completar en `capacity_governor` + HA):

1. **`MAX_OPS_IN_FLIGHT_TOTAL`** — límite fleet-wide de ops no terminales con ejecución activa.
2. **`MAX_PAID_IN_FLIGHT`** — Cursor+Codex+Antigravity sumados.
3. **`MAX_LOCAL_IN_FLIGHT`** — Dev Swarm + colas Ollama/vLLM.
4. **HA muestra** cola, presupuesto restante, y botones approve/deny por tarea (Companion Activity #227 Codex).

---

## 5. Home Assistant como freno (no solo campana)

**Implementado (main / Intel runtime):**

- `NOTIFY_OPS_AUTH_HA=1`, servicio `inneros-ops-ha-approval-worker` (systemd user).
- Push al crear autorización (`ops_ha_owner_auth`, `coordination_live`).
- Post-aprobación: `ops_post_owner_autopilot` → claim + headless Cursor/Codex/Antigravity.
- Parche 2026-10-31: **`notify_ops_transition`** también envía outcome a Companion (cierre/fallo/verification).

**Fallos reales observados:**

- HA caído → `ConnectError` → **email fallback** (correo sí, móvil no).
- Transiciones sin HA antes del parche → sensación “Antigravity por email”.
- Autopilot spawn systemd duplicado (`unit already loaded`) → riesgo de créditos + confusión (incidente `ops_7039e9cc4f11` y cadena P0).

**Worker HA está activo** cuando HA responde; el cuello suele ser **notify incompleto** o **HA down**, no “servicio apagado”.

---

## 6. Contrato único por tarea (anti-desborde)

Una ops task **COMPLETED_VERIFIED** solo si:

1. `owner_authorized_at` + grant acotado (task_id, proveedor, límites).
2. Claim + lease válidos; **no** respawn si `failed` / `superseded` / `execution_stop` / `do_not_auto_dispatch`.
3. Headless: ≤3 dispatches, timeout SDK, receipt + tests reales (no synthetic-canary como “real”).
4. Temporal concordante con Mongo.
5. **Notify HA** de cierre con coste observado (cuando exista telemetría).

Incidente créditos Cursor: **varias tareas P0** + **requeue/autopilot** + **unidades systemd huérfanas** — no un solo bug, sino **bordes del contrato** sin fencing global.

---

## 7. Estado operativo 2026-10-31

| Área | Estado |
|------|--------|
| Código coordinación HA → OPS | En **main**, desplegado Intel |
| Limpieza cola IDE | 12 tareas superseded; conservada `ops_d7ac9d1e90ec` (Codex #227) |
| Codex web (Nebius/Cloudflare) | **Inbox P0** — no mezclar con ops Cursor |
| Autonomía correo/inbox | **Parcial** — requiere empuje manual |
| Paridad AMD | **Pendiente verificación** (SSH LAN desde este entorno falló; usar Peer Ops o consola AMD) |
| Notion | **Sincronizado** — DB RalfIA Coordination (MCP 2026-10-31), URL en §11 |

**Timers relevantes (Intel user systemd):** `inneros-coordination-cycle.timer`, `inneros-interactive-provider-autopilot.timer`, `inneros-antigravity-headless-autopilot.timer`, `inneros-ops-ha-approval-worker.service`. Cursor headless autopilot timer puede estar **disabled** (menos auto-loop).

---

## 8. Por qué “nadie hace nada” hasta que empujas

1. **Cola sucia / tareas zombie** bloqueaban lanes (mitigado con hygiene + reconcile).
2. **Inbox ≠ ops:** Codex trabaja mensajes; Mongo ops es otro carril — sin dispatcher unificado no “baja” a Notion sola.
3. **Local-first no está en autopilot diario:** email → acción requiere ciclo explícito (`email_owner_digest`, alignment).
4. **Grants/deploy separados:** autorizar coding ≠ autorizar deploy ≠ autorizar créditos — tareas quedan `AWAITING_*` sin mensaje claro en HA.
5. **Dependencia del owner en chat** en lugar de **push + una cola visible** (Companion Activity / dashboard).

---

## 9. Roadmap de implementación (sin cruzar Codex web)

### Fase A — Paridad AMD (P0 infra)

- [ ] Mismo `.env` de lanes en AMD (`INNEROS_*_MAX_CONCURRENT`, `NODE_ROLE=amd`).
- [ ] Timers: coordination-cycle, interactive-provider-autopilot, ha-approval-worker (si AMD ejecuta IDE).
- [ ] CLIs: Cursor/Codex/Antigravity verificadas en PATH/vault en **ambos** nodos.
- [ ] Smoke: `lane_status()` Intel vs AMD vía Peer Ops.

### Fase B — Gobernanza fleet (P0 créditos)

- [ ] Techo global paid + local en governor; deny spawn si HA no ack reciente para paid.
- [ ] Limpiar unidades `inneros-cursor-headless-ops_*` huérfanas al fallar spawn.
- [ ] Alert HA si headless > N minutos o dispatch attempts ≥ 3.

### Fase C — Autonomía interna (P1)

- [ ] Cron/cycle: email intelligence → propuesta → **create_ops_task local** o mensaje inbox → **push HA**.
- [ ] Enrutar implementación a Qwen (AMD 12G / Intel 32G) por `local_model_router`; IDE solo con grant.

### Fase D — Notion / discoverability

- [x] Importar doc a DB **RalfIA Coordination** (MCP Cursor 2026-10-31).
- [ ] Enlazar desde wiki OS Central / índice de arquitectura InnerOS.

---

## 10. Referencias en repo

- `inneros_core_runtime/interactive_provider_lanes.py` — Codex/Antigravity por host  
- `inneros_core_runtime/cursor_headless_lanes.py` — Cursor dual-node  
- `inneros_core_runtime/cursor_headless_policy.py` — techo 3 dispatches  
- `scripts/inneros_coordination_cycle.py` — hygiene + reconcile lanes  
- `scripts/ops_queue_hygiene_zero_pending.py` — limpieza IDE (`--apply`)  
- `docs/CREDIT_AND_LOCAL_FIRST_POLICY.md`  
- `docs/INNEROS_LOCAL_AGENT_FABRIC.md` (histórico; contrastar con continuidad 20261012)

---

## 11. Notion (registro)

**Página en DB RalfIA Coordination (2026-10-31):**  
https://app.notion.com/p/40acb2deeb0f8177a8abda7d3ec0e3d5

**Verdad canónica (orden):** Git `main` → este path → Mongo ops/events → Notion (espejo humano).

**Título:** `InnerOS — Carriles dual-nodo y coordinación HA (2026-10-31)`

**Tags:** `inneros`, `coordination`, `ha-companion`, `lanes`, `cursor`, `codex`, `antigravity`, `local-first`

---

*Documento generado desde sesión Cursor coordinación 2026-10-31. Actualizar al cambiar `.env` de lanes o política de grants.*
