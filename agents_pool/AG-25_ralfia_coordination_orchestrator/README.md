# AG-25: RalfIA Coordination Orchestrator (Orquestador de coordinación)

**Nombre corto:** `ralfia_coordination_orchestrator`  
**Rol:** Agente **siempre activo** en el servidor — no sustituye Cursor/Codex/Antigravity.

## Qué hace (automático)

| Ciclo (~2 min) | Acción |
|----------------|--------|
| Watcher | Detecta cambios mailboxes → `HUB/feed.md` |
| Mapa | Actualiza timestamp `MAPA_CENTRAL.md` |
| Health | Comprueba módulos InnerOS (:8101, :8099, :8800) |
| Mongo | Heartbeat `ralfia_coordination_log` agent=`AG-25` |
| Ollama (opcional) | Router local si `COORD_OLLAMA_ROUTER=1` |

## Qué NO hace

- No escribe código en repos
- No abre Cursor/Codex/Antigravity
- No mergea PRs ni reinicia ngrok sin humano

## Arranque

```bash
# Foreground (prueba)
bash /home/rlopez/data/ai_coordination/scripts/run_coordination_daemon.sh

# Permanente (systemd — Rafael)
sudo cp /home/rlopez/data/ai_coordination/systemd/ralfia-coordination-daemon.service /etc/systemd/system/
sudo systemctl enable --now ralfia-coordination-daemon
```

## Variables

| Var | Default | Descripción |
|-----|---------|-------------|
| `COORD_DAEMON_INTERVAL` | 120 | Segundos entre ticks |
| `COORD_OLLAMA_ROUTER` | 0 | 1 = router Ollama en cambios |
| `OLLAMA_ORCHESTRATOR_MODEL` | qwen2.5:14b-instruct | Modelo router |

## Integración modular InnerOS (Mongo `pcdoctor_swarm`)

| Módulo | Puerto | Owner humano | Conexión AG-25 |
|--------|--------|--------------|----------------|
| raphiia-openai | 8101/8102 | Cursor/Codex | health check |
| hackathon-funding-hub | 8099 | Antigravity | health + `opportunities` |
| portal InnerSpark | 8800 | Codex | health |
| AG-22/23/24 | — | Antigravity | vía funding-hub API |
| AG-21 hackathon harvester | — | Cursor | hook futuro T-025 |
| AG-12 project provisioner | — | Cursor | hook futuro T-025 |

## Spec completa

`/home/rlopez/data/ai_coordination/AG-25_ORCHESTRATOR_SPEC.md`

## Output

- `HUB/feed.md` / `feed.jsonl`
- `HUB/router_decision.md` (si Ollama)
- Mongo `ralfia_coordination_log`
