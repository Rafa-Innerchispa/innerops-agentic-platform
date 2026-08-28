# RalfIA Copilot — qué puede hacer desde Open WebUI

**Modelo:** RalfIA Copilot (qwen 14B) · MCP LAN :8102 · preset permanente

---

## Hoy (activado en preset)

| Acción | Cómo | Tool MCP |
|--------|------|----------|
| Ver mapa de proyectos/servicios | Pregunta natural | `get_project_map`, `bootstrap_context` |
| Leer coordinación (ESTADO, TASKS…) | Por nombre de doc | `read_coordination_file`, `search_coordination_docs` |
| Leer buzones agentes (Cursor, ChatGPT…) | «¿Qué hay en INBOX de Codex?» | `get_agent_mailboxes` |
| Buscar clientes / ideas / pipeline | Texto libre | `search`, `get_context_summary` |
| Guardar preferencias y metas | «Recuerda que…» | `save_memory`, `search_memory` |
| Guardar hecho operativo clasificado | Tras clasificar | `save_knowledge_seed` |
| Contactos ops | Listar / crear | `list_ops_contacts`, `save_ops_contact` |
| WhatsApp (borrador) | Redacta; Rafael confirma | `send_whatsapp_draft` |
| Estado WhatsApp/Evolution | Diagnóstico | `get_whatsapp_status` |
| Registrar hito | Sesión importante | `log_coordination_event` |
| Shell / scripts / curl APIs | Terminal integrado | Open Terminal :8010 |
| Docs estáticos runbook | RAG | Knowledge «RalfIA Offline» |
| Web | DuckDuckGo | web_search (ON) |

**Memoria Open WebUI (UI):** capability ON + `memories.system_context` ON — complementa MCP `save_memory` (Mongo).

---

## Parcial / con fricción

| Acción | Estado | Camino actual |
|--------|--------|---------------|
| **Cliente nuevo (RUC)** | Lookup auto-registra en Mongo | API `:8101/api/v1/clients/lookup/{ruc}` vía Terminal, o Smart Quoter :2026 |
| **WhatsApp enviado** | Borrador OK; envío real necesita contacto en `ops_contacts` | `send_whatsapp_draft` + confirmación; `ops_contacts` estaba vacío (jul-2026) |
| **Informe técnico** | API Swarm, **sin tool MCP** | POST `:8100` `/technical-reports` (requiere `visit_id`) vía Terminal |
| **Correo IMAP** | No en MCP | Panel http://192.168.1.4:5173/email · Mongo vía Swarm |
| **Cotización PDF** | Smart Quoter :2026 | UI dedicada; WhatsApp real pendiente Antigravity |

---

## No disponible aún desde Open WebUI

- Tool MCP `create_client` / `create_technical_report` (P1 — wrapper sobre :8100/:8101)
- Leer bandeja IMAP por chat
- Publicar LinkedIn / pipeline editorial (sí en ChatGPT MCP completo)
- Recovery drill / watchdog (tools admin — solo ChatGPT)

---

## ChatGPT vs Open WebUI

| | ChatGPT + MCP ngrok | Open WebUI Copilot |
|--|---------------------|---------------------|
| Tools MCP | ~82 (catálogo completo) | **17 filtradas** (qwen 14B) |
| Tool use | Muy fluido | Variable; a veces alucina |
| Voz / LAN / terminal | Limitado | Fuerte |
| Memoria | MCP + ChatGPT | MCP + Open WebUI Memory |

**Recomendación:** operaciones delicadas (publicar, recovery, envío WhatsApp final) → ChatGPT o confirmación manual. Consultas LAN, voz, terminal → Open WebUI.

---

## Re-tuning permanente

```bash
python3 /home/rlopez/projects/innerspark-swarm-os-cursor-local/scripts/tune_openwebui_copilot.py
```

Tras cualquier upgrade Open WebUI: `upgrade_openwebui_ralfia.sh` (incluye tune).
