# PANORAMA COMPLETO InnerOS — sesión Windows 2026-11-12 (para AMD)

Todo lo hablado y hecho en las últimas 3 horas, sin recortes. Lo que está en
GitHub viaja con `git pull`. Lo marcado [SOLO-LOCAL] vive en la laptop y se
pierde si no se respalda: va al final cómo cubrirlo.

## 0. Cadena de custodia

- En GitHub (`origin/main`): commit `688e76b` checkpoint + `39b43ac` guardrails.
  El fix P0 de hoy (6 archivos) sigue SIN commit en la laptop.
- [SOLO-LOCAL] Notas de memoria, logs de sesión, llave SSH dedicada generada
  (inútil, ver §8), tokens OAuth del navegador, keys del usuario.

## 1. El chat perdido y lo recuperado

Se cerró la ventana de PowerShell en VS Code y se perdió el chat. Se recuperó
la sesión anterior `01a1cd6c` (2887 eventos, 5.5 MB, 11-nov 20:46). Prompts
clave: recuperar chat, proyectos en Windows vs GitHub, que TODOS los agentes
externos (incluido Muse) tomen tareas de cualquier mensaje en coordinación sin
copiar-pegar, mandar un canario con Antigravity y revisar claim vs receipt.
Última conclusión de esa sesión: CONFIRMAR de WhatsApp sí llegaban
(`owner_authorized`), pero el claim fallaba o quedaba quieto.

## 2. Prueba de coordinación y cola Antigravity (P0, abierta)

Objetivo: agentes externos toman tareas de la cola sin copiar-pegar.
Estado real (auditorías rev 54334 + 22:40 Ecuador, solo lectura):

- `ops_7770edd4b494` (QA GhostBridge): `awaiting_antigravity_claim`,
  `owner_authorized`, `claim_error=worktree_create_failed`. Sin lease.
- `ops_7e7edb50afb3` (Devpost): `claimed` por antigravity, lease vigente
  entonces, solo `cursor_handoff`, sin receipt terminal.
- `ops_8ce2a638961b` (Kiro vieja): `claimed`, CANCELAR llegó con lease activo
  y no la desalojó. Sin evento cancelled.
- `ops_345e9ea4c645` (Kiro nueva): `claimed`, doble claim rechazado
  (`not claimable`), sin ejecución probada.

Hallazgos que no se negocian: `claimed` no es ejecutado. INBOX `open` sin ACK
en los 4 (autorización, ACK y claim son eventos distintos). `cursor_handoff`
no es receipt. Leases vencieron 23:06 Ecuador sin receipts. Regla vigente:
un solo canario, no autorizar ni cancelar hasta relectura post-lease.

## 3. Decisiones del propietario (vigentes)

- WhatsApp/Evolution DESCARTADO (2026-11-12). Solo Telegram + notificaciones HA.
- Borrados: solo con inventario previo mostrado + OK explícito por ruta.
- Nada de push, deploys, fleet-sync, gasto externo ni revocar nada sin su OK.
- Fuente de verdad: main en GitHub. Runtime solo vía fleet-sync manual.
- Libertad con barandas para el agente: leer/investigar/editar código y tests
  sin pedir; lo grave lo decide Rafael.

## 4. Repo y tests (laptop Windows)

- `main` == `origin/main` en `39b43ac`, solo `?? debug.log` sin seguimiento.
- Guardrails Meta 5/5 por vía directa
  (`python platform/.../test_meta_provider_guardrails.py`).
  `pytest` da 5 errores de colección por el paquete local `platform/` que tapa
  al módulo estándar: es colisión de nombre, no fallo de tests.
- Push al día. Key LLM_ revocada. CLI reiniciado (sesión nueva).
  OAuth MCP: tokens presentes en `.mcp-auth`. Falta: login GitHub para pushes
  futuros, definir alcance MR GitHub, fiscal AG-17, ContributorOps, Living Lab.

## 5. Intel: disco y veredicto NO BORRAR

- `~/worktrees` 451M (julio) + `inneros_core/worktrees` 971M en 173 entradas
  (septiembre, canarios `temporal-*`). Eso prueba que antes SÍ generaba.
- El peso real: `workspaces` 41G + `var` 13G + `data` 108G
  (`media` 76G, `pst_archive` 26G = datos y correos del usuario).
  Workspaces grandes activos oct-nov (liga AI, guardian, voiceops, innerops).
  `var/local_execution` con movimiento del 11-nov. DF: 383G usado, 458G libre.
- Veredicto: NADA es basura. No borrar. Lo único podable son canarios viejos
  (<1.5G) y no vale el riesgo sin OK por ruta.

## 6. Notion

- `NOTION_VERSION` es solo el pin de API (`2022-06-28`), no un secreto.
- Token viejo inválido (`token_invalid`, largo 100). Token nuevo válido:
  `users/me` devuelve bot `InnerOS` en el workspace de Pc Doctor.
- Falta: verificar body con IDs de bases/páginas compartidas con la
  integración (paso: search API, luego bloques children).
- Ya existía puente directo (`notion_bridge.py`) + export local de 3685 docs.

## 7. SSH y conexión (historia completa)

- Sandbox Windows (usuario `muse-sbx-r1`) sin TCP directo a ningún lado:
  LAN `.4:22`, Tailscale `.12`/`.124` e internet público, todo REFUSED.
  No es Tailscale ni el firewall: es la jaula. SSH-desde-Windows DESCARTADO.
- Se generó llave dedicada (fingerprint `Y9zvytQT...`, ACL restringida) pero
  quedó inútil sin ruta. No autorizarla.
- Doble vía anotada para donde sí hay red: oficina LAN `.4`/`.5`,
  fuera Tailscale `.12`/`.124`.
- Vías reales: Muse corriendo en Intel (Remote-SSH conserva el editor) o
  conector MCP como el de ChatGPT (Streamable HTTP :8102 + API key).

## 8. Muse por servidor

- AMD (192.168.1.5): Muse 1.4.15 en `/home/rlopez/.local/bin/muse`, repo en
  `/home/rlopez/innerops-agentic-platform` HEAD `39b43ac`, python3 3.14,
  Mongo local OK. LISTO. Arranque: `cd` al repo + `muse`.
- Intel (192.168.1.4): Muse MISSING. Su comando `muse` es otro programa
  (MusE, secuenciador de audio: config `MusE`, temas, JACK/VST). Evidencia de
  colisión de nombres, nada roto. Instalar el verdadero Muse Code:
  opción limpia = copiar el binario bueno de AMD por scp (mismo x86_64);
  opción con descarga = launcher con OK de Rafael + revisar antes de correr.
  Cuidado PATH: `~/.local/bin` debe ganar a `/usr/bin/muse`.

## 9. KPI: auditoría terminada (read-only, 4 agentes + síntesis)

- Vivo y reutilizable: `productivity_metrics` (clases
  MEASURED/ESTIMATED/INFERRED/MANUAL, HTR verificado solo MEASURED),
  `self_heal_metrics` (ROI gate), `audit_fabric` (dry_run, prod OFF).
- Muertos: DB37 swarm_os solo esquema; OTel collector en debug sin
  instrumentación (cero `get_tracer`/`start_span` en todo platform);
  duraciones/costos/intervenciones no se computan; sin dashboard unificado,
  sin resumen semanal, sin canal reply Telegram.
- Fórmulas desde código: `saved=max(0,base-assist)`, HTR horas, reducción%,
  speedup, `verified_HTR`, `returned=base-assisted-rework` con negative gate,
  recovery_rate, mttr, T_queue/run/verify/resolution derivados.
- Reglas honestas: nada estimado en total medido, sin negativos, la espera
  nunca cuenta como ahorro, valor económico prohibido sin horas medidas.
- Tests T1-T5 con harness existente, sin framework nuevo.
- Orden: P0 estabilizar coordinación, P1 instrumentar en Intel, P2 dashboard.

## 10. Fix P0 implementado hoy (SIN commit, tests NO corridos aquí)

- `_release_claim(..., details)` + `_compact_claim_details` (≤2000 chars)
  en `cursor_ops_runner.py`; codex/cursor/interactive mandan su `wt`.
  Success-paths limpian `claim_error_detail`. Diagnóstico visible en
  `list_ops_tasks` sin acceso al servidor.
- Reconciliador: `_proposed_superseded` (claimed + lease vencido + sibling
  vivo con `supersedes_task_id`) → `superseded` con motivo y autor,
  conservando historial. Sin sibling vivo no toca nada (liveness decide).
  Report path por env `INNEROS_RECONCILE_EVIDENCE_DIR`. Dry-run por defecto.
- 5 tests en `test_reconcile_ops_mongo_temporal.py` + 2 en
  `test_ops_interactive_claim_release.py`. NO corridos: este sandbox no tiene
  Python (verificado exhaustivamente). Correr en Intel/AMD:
  `python3 platform/tests/test_reconcile_ops_mongo_temporal.py -v` y con
  `PYTHONPATH=platform` el `pytest` del otro archivo.

## 11. Sesiones y puente anti-pérdida

- AMD viva con brief de arranque (tests + lectura post-lease).
- Esta sesión Windows: continuidad + dev local + automatizar Windows.
- Puente: este archivo + checkpoint en GitHub (`git pull` en AMD lo trae
  todo). Memoria local y logs de sesión NO viajan solos.
- [SOLO-LOCAL] aún sin respaldar: notas de memoria del proyecto, logs en
  `.local/share/muse/sessions/`, tokens OAuth del navegador.

## 12. Pendientes ordenados

Usuario: Sync/commit de este panorama + fix (comandos abajo) → decirle al
chat AMD `git pull` + leer este archivo → relectura post-lease 4 tareas →
decidir alcance MR GitHub, fiscal AG-17, ContributorOps, Living Lab →
tarjeta Muse → login GitHub.
Agente (aquí): nada ejecutable pendiente; siguiente paso depende de AMD
(tests + lectura post-lease) o de órdenes nuevas.
