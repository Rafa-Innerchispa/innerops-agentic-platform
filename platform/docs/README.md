# Documentación RaphiIA-OpenAI

**Servidor:** `192.168.1.4` · **Repo:** `/home/rlopez/projects/raphiia-openai`

## Lectura principal

- [`CREDIT_AND_LOCAL_FIRST_POLICY.md`](CREDIT_AND_LOCAL_FIRST_POLICY.md) — regla local-first para ahorrar creditos y usar RalfIA antes que APIs externas.
- [`RALFIA_CONTROL_PLANE.md`](RALFIA_CONTROL_PLANE.md) — vision de RalfIA como centro operativo, MCP gateway, contingencia y reglas de no interferencia.
- [`HANDOFF.md`](HANDOFF.md) — estado actual y decisiones para continuar trabajo.
- [`CONEXION.md`](CONEXION.md) — conexion SSH/Remote SSH y arranque.
- [`MCP_CHATGPT.md`](MCP_CHATGPT.md) — conectar ChatGPT al MCP.
- [`MCP_CURSOR.md`](MCP_CURSOR.md) — conectar **Cursor** y **Codex** (`.cursor/mcp.json` / `.codex/config.toml`).
- [`INTEGRATION.md`](INTEGRATION.md) — MongoDB, colecciones y tools.
- [`BACKUPS.md`](BACKUPS.md) — respaldo y recuperacion.

## Regla de seguridad

No tocar puertos ni servicios existentes sin aprobacion explicita. Los proyectos de hackatones y servicios actuales forman parte del ecosistema y deben mantenerse operativos.

## Orden de lectura

| # | Archivo | Para qué |
|---|---------|----------|
| 1 | [**CONEXION.md**](CONEXION.md) | **Conexión al servidor, arranque, puertos, errores típicos** |
| 2 | [**CURSOR_SSH.md**](CURSOR_SSH.md) | Configurar Cursor Remote SSH (evitar fallos Windows) |
| 3 | [**ARRANQUE_RAPIDO.md**](ARRANQUE_RAPIDO.md) | Copy/paste arranque en terminal del servidor |
| 4 | [**MCP_CHATGPT.md**](MCP_CHATGPT.md) | Conectar ChatGPT Connectors (Developer Mode + ngrok) |
| 5 | [**HANDOFF.md**](HANDOFF.md) | Arquitectura, decisiones, roadmap P0–P3 |
| 6 | [**INTEGRATION.md**](INTEGRATION.md) | MongoDB colecciones DBxx |
| 7 | [**BACKUPS.md**](BACKUPS.md) | Disaster recovery |
| 8 | [**ROADMAP.md**](ROADMAP.md) | Fases v1–v3 |
| 9 | [**VISION.md**](VISION.md) | Visión producto |

## Regla

> Cursor debe abrirse vía **Remote SSH** en `192.168.1.4`.  
> No trabajar desde Windows apuntando a rutas `/home/rlopez/...`.
