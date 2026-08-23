# MCP en Cursor (y Codex) — Ralphi IA

> ChatGPT = conector gráfico + ngrok. **Cursor/Codex en el servidor** = archivo de config + `127.0.0.1:8102` (sin ngrok).

---

## ¿Qué es un «drill»?

**Drill** = prueba controlada: reinicia servicios Ralphi, verifica que todo volvió, y manda WhatsApp (🔴 caída / 🟢 recuperado / ✅ OK). Lo ejecuta **AG-31**, no tú.

---

## Ventajas de conectar MCP en Cursor

| Sin MCP | Con MCP RalfIA en Cursor |
|---------|---------------------------|
| Yo leo archivos a mano | Tools: `get_project_map`, `search`, `fetch`, `list_ralphia_agents` |
| Contexto desactualizado | Misma Mongo + `ai_coordination/` que ChatGPT |
| Tú copias tokens/URLs | Leo config vía tools (secretos enmascarados en panel) |
| Reinicios a ciegas | `run_service_watchdog`, AG-31, estado registry |
| ChatGPT y Cursor separados | **Un solo cerebro** — mapa, agentes AG-xx, editorial |

El agente de Cursor **deja de adivinar** estructura: usa el mapa canónico y las reglas AG-31/AG-25/AG-30.

---

## Mapa de referencia (todos los agentes)

| Archivo | Para qué |
|---------|----------|
| `MAPA_CENTRAL.md` | Estado vivo humano |
| `raphiia_openai/agents/registry.py` | AG-xx en código |
| `docs/AGENTS_REGISTRY.md` | Tabla rápida repo |
| MCP `get_project_map()` | ChatGPT/Cursor al abrir sesión |
| MCP `list_ralphia_agents()` | Numeración + entrypoints |

---

## Opción A — Cursor IDE (recomendado, Remote SSH)

Trabajas en `192.168.1.4` → el MCP es **local**, no hace falta ngrok.

### 1. Generar config (automático)

```bash
cd /home/rlopez/projects/raphiia-openai
./scripts/setup_cursor_mcp.sh
```

Crea `.cursor/mcp.json` leyendo `MCP_API_KEY` del `.env` (no va a git).

### 2. O manual — `.cursor/mcp.json` en el repo

```json
{
  "mcpServers": {
    "ralfia": {
      "url": "http://127.0.0.1:8102/mcp",
      "headers": {
        "X-API-Key": "TU_MCP_API_KEY_DEL_ENV"
      }
    }
  }
}
```

### 3. Activar en Cursor

1. Remote SSH → carpeta `raphiia-openai`
2. **Command Palette** (`Ctrl+Shift+P`) → **Developer: Reload Window**
3. **Cursor Settings** (icono engranaje) → **Tools & MCP** — debe aparecer **ralfia** (verde si `:8102` activo)
4. En Composer/Agent, las tools RalfIA quedan disponibles

> **Si no ves nada:** suele ser porque `~/.cursor/mcp.json` estaba vacío. Ejecuta `./scripts/setup_mcp_all.sh` (sincroniza proyecto + home).

### Script todo-en-uno (recomendado)

```bash
cd /home/rlopez/projects/raphiia-openai
./scripts/setup_mcp_all.sh
```

Configura **Cursor** (`.cursor/mcp.json` + `~/.cursor/mcp.json`) y **Codex** (`~/.codex/config.toml`) en un solo paso.

### Requisitos

- `ralfia-mcp.service` activo
- `MCP_API_KEY` en `.env` = mismo valor en `mcp.json`

---

## Opción B — Codex CLI / extensión Codex (`.codex/config.toml`)

Codex **no** usa JSON como ChatGPT: usa **TOML**.

| Alcance | Ruta |
|---------|------|
| Global (usuario) | `~/.codex/config.toml` |
| Proyecto | `.codex/config.toml` en la raíz del repo (**solo si el proyecto es trusted**) |

### Ejemplo proyecto — `.codex/config.toml`

Copia desde `.codex/config.toml.example` y pon tu clave, o:

```bash
./scripts/setup_codex_mcp.sh
```

Contenido tipo:

```toml
[projects."/home/rlopez/projects/raphiia-openai"]
trust_level = "trusted"

[mcp_servers.ralfia]
url = "http://127.0.0.1:8102/mcp"
http_headers = { "X-API-Key" = "TU_MCP_API_KEY" }
startup_timeout_sec = 20
tool_timeout_sec = 120
enabled = true
```

### Confiar el proyecto (si Codex ignora el config local)

```bash
cd /home/rlopez/projects/raphiia-openai
codex trust
```

### Verificar en Codex

- CLI: `codex mcp list` → debe mostrar **ralfia** `enabled`
- TUI: `cd /home/rlopez/projects/raphiia-openai && codex` → comando **`/mcp`**

> Codex lee **`~/.codex/config.toml` global**, no solo el del proyecto. `setup_mcp_all.sh` hace el merge automático.

---

## ChatGPT vs Cursor vs Codex

| Cliente | Config | URL MCP |
|---------|--------|---------|
| ChatGPT | Clic en Connectors | HTTPS ngrok + OAuth o API Key |
| **Cursor** | `.cursor/mcp.json` | `http://127.0.0.1:8102/mcp` |
| **Codex** | `~/.codex/config.toml` o `.codex/config.toml` | Igual, local |

---

## Tools útiles al conectar

```
get_project_map()
list_ralphia_agents()
run_service_watchdog()      # admin
list_service_registry()
search / fetch              # obligatorios conector
get_chatgpt_workspace()
log_coordination_event()
```

---

## Problemas frecuentes

| Síntoma | Solución |
|---------|----------|
| MCP no aparece en Cursor | `./scripts/setup_mcp_all.sh` + **Reload Window** + **Cursor Settings → Tools & MCP** |
| Cursor: config existe pero UI vacía | Revisar `~/.cursor/mcp.json` (debe tener `ralfia`, no `{}`) |
| Codex: «No MCP servers configured» | Merge en `~/.codex/config.toml` vía `setup_mcp_all.sh`; `codex mcp list` |
| 401 Unauthorized | Igualar `MCP_API_KEY` en `.env` y config |
| Connection refused | `systemctl --user start ralfia-mcp` |

---

## Referencias

- [`MCP_CHATGPT.md`](MCP_CHATGPT.md) — conector ChatGPT (ngrok)
- [`CURSOR_SSH.md`](CURSOR_SSH.md) — Remote SSH
- [`AGENTS_REGISTRY.md`](AGENTS_REGISTRY.md) — AG-xx
- OpenAI: [Codex MCP](https://developers.openai.com/codex/mcp)
