#!/usr/bin/env python3
"""Broadcast COT + limpieza INBOX + bump ESTADO_VIVO."""

from __future__ import annotations

from raphiia_openai import mongo_store
from raphiia_openai.coordination_live import bump_revision, refresh_estado_vivo
from raphiia_openai.memory.agent_messages import (
    compact_agent_mailbox,
    create_agent_message,
    update_agent_message_status,
)
from raphiia_openai.settings import COL_AGENT_MESSAGES

COT_BODY = """## Prioridad Rafael — Cotizaciones (COT)

**Contifico:** import **completo** (5.867 docs en Mongo).

### Nuevo módulo COT (MCP 2.29.0)
- `generate_quote_intro` — intro comercial (NO informe técnico completo)
- `render_quote_document` — HTML con cabecera cliente/fechas
- `send_quote_delivery` — ticket `PCD-COT-*` + WhatsApp + email cola
- `get_quote_tracking` — estado por referencia

**Perfil MCP:** `list_mcp_tool_profiles()` → **`quoter`**

**Spec:** `docs/COT_QUOTER_SPEC.md`

### ChatGPT
Rafael cotiza **en tiempo real desde ChatGPT**. Lee `chatgpt/COTIZACIONES_MCP.md`.

### Contifico → Codex
Import terminado — puedes cerrar `ops_66f2f78fd0a6` con spec reconciliación.

_Mongo: ops_quote_deliveries · ops_quote_drafts · quote_opportunities_
"""


def close_stale_messages() -> int:
    db = mongo_store.get_db()
    closed = 0
    # Verificación Notion ya completed
    for doc in db[COL_AGENT_MESSAGES].find(
        {"status": "open", "body": {"$regex": "ops_989a19a24ea7|notion-audit-2026-07-11"}},
        {"message_id": 1},
    ):
        update_agent_message_status(doc["message_id"], "done")
        closed += 1
    # Duplicados PROTOCOLO — dejar solo el más reciente por agente
    for agent in ("cursor", "codex", "antigravity", "chatgpt", "notion", "gemini"):
        msgs = list(
            db[COL_AGENT_MESSAGES]
            .find(
                {"target_agent": agent, "status": "open", "title": {"$regex": "PROTOCOLO", "$options": "i"}},
                {"message_id": 1, "created_at": 1},
            )
            .sort("created_at", -1)
        )
        for old in msgs[1:]:
            update_agent_message_status(old["message_id"], "superseded")
            closed += 1
    return closed


def main() -> None:
    closed = close_stale_messages()
    targets = ("chatgpt", "codex", "antigravity", "notion", "gemini")
    sent = []
    for t in targets:
        res = create_agent_message(
            from_agent="CURSOR",
            target_agent=t,
            title="P0 Cotizaciones COT — MCP 2.29 + ticket WhatsApp",
            body=COT_BODY,
            priority="high",
            tags=["cot", "quoter", "p0"],
        )
        sent.append(res.get("message_id"))
    bump_revision(
        reason="COT quoter live — Contifico complete — MCP 2.29",
        source="cursor",
        current_priority={
            "title": "Cotizaciones (COT) desde ChatGPT",
            "summary": (
                "Rafael cotiza en tiempo real vía ChatGPT. Intro comercial + HTML + ticket WhatsApp PCD-COT-*. "
                "No enviar informe técnico completo al cliente."
            ),
            "tools": [
                "create_quote_draft",
                "generate_quote_intro",
                "render_quote_document",
                "send_quote_delivery",
                "get_quote_tracking",
            ],
            "doc": "docs/COT_QUOTER_SPEC.md",
        },
    )
    refresh_estado_vivo()
    for agent in ("cursor", "chatgpt", "codex", "antigravity", "notion", "gemini"):
        compact_agent_mailbox(agent, max_open=12)
    print({"ok": True, "closed_messages": closed, "broadcast_ids": sent})


if __name__ == "__main__":
    main()
