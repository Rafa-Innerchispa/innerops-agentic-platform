# AG-32 Home Assistant Bridge

**Numeración:** AG-32 · **ID:** `AG-32_home_assistant_bridge`

Puente domótico local entre RalfIA (MCP/voz) y Home Assistant en `:8123`.

## Capacidades

- Listar / leer entidades (`light`, `switch`, `climate`, `scene`)
- Encender/apagar luces por nombre natural
- Snapshot cache → `/home/rlopez/data/ralfia/ha_state.json`
- Integrado en `home_ops_daemon.py` (poll + digest Ollama local)

## MCP tools

- `ha_ping`, `ha_list_entities`, `ha_get_entity`
- `ha_turn_on_light`, `ha_turn_off_light`, `ha_call_service`
- `run_home_ops_cycle`

## Configuración

```bash
export HOME_ASSISTANT_URL=http://192.168.1.4:8123
export HOME_ASSISTANT_TOKEN=...   # ver setup_home_assistant_token.sh
```

Runtime: `raphiia_openai/homeassistant_client.py`
