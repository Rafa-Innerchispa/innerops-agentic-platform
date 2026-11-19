# Handoff activo — canario autorización owner (Telegram + Alexa)

**Autor:** Cloud Agent (Composer) · **Para:** cualquier agente en Intel (`ralphi-ia-ver-10`), worker Cursor, o sesión local  
**Estado GitHub:** PR **#283** fusionado en `main` (notify Telegram directo + HA en paralelo).  
**No repetir:** explicación larga en chat; ejecutar el one-shot y leer `var/owner_notify_canary_latest.json`.

## Qué falta certificar (producción Intel)

1. Al crear ops **Cursor/Codex/AG** externas, llega **Telegram** (botones) y/o **HA/Alexa** (registry compartido).
2. Rafael aprueba **una** vía; la otra debe rechazar (`ops_owner_decision_registry`).
3. **Fase 2** (después): claim con `cursor-agent` / `codex` / `agy` en Intel si falla ejecución — no bloquea este canario.

## Comando único (sin preguntas)

```bash
cd ~/innerops-agentic-platform && git pull -q origin main && bash platform/scripts/owner_authorization_notify_canary_one_shot.sh
```

Si el script aún no existe en el host (pull antiguo), misma máquina:

```bash
export GIT_TERMINAL_PROMPT=0 NOTIFY_OPS_TELEGRAM_DIRECT_ON_CREATE=1 NOTIFY_OPS_AUTH_HA=1
cd ~/innerops-agentic-platform && git pull -q --ff-only origin main && bash platform/scripts/owner_authorization_notify_canary_one_shot.sh
```

## Evidencia

| Artefacto | Ruta |
|-----------|------|
| Último run | `~/innerops-agentic-platform/var/owner_notify_canary_latest.json` |
| Workers Cursor | `inneros-amd-5`, `ralphi-ia-ver-10` (account `rlopez@innerchispa.us`) |
| Fix notify | `platform/inneros_core_runtime/notifications/ops_task_alerts.py` |

## Rol humano (solo Rafael)

Tras el one-shot: **un** Confirmar en Telegram o voz/Alexa. No pegar salida de terminal aquí salvo que no llegue nada en 2 minutos.

## Continuidad InnerOS

Leer también `platform/docs/INNEROS_COORDINATION_CONTINUITY_20261012.md` y `AGENTS.md`; este archivo es el **slice P0 notify** vigente hasta cierre del canario.