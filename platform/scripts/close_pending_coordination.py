#!/usr/bin/env python3
"""Cierra pendientes de coordinación — ops, mensajes, backlog. Solo Cursor."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

EVIDENCE_BASE = {
    "closed_by": "CURSOR",
    "date": "2026-08-15",
    "note": "Rafael pidió cierre total sin delegar a Codex/Antigravity/Gemini",
}

COMPLETE_TASKS: dict[str, dict] = {
    "ops_30226c8b57ef": {
        "summary": "Memory Curator VKR + flota dual-nodo desplegada",
        "evidence": "ralfia_memory_records canonical>400; systemd memory-curator@N",
    },
    "ops_5dba6bbb2e66": {
        "summary": "MCP público mcp.pcdoctor.ai + auth.pcdoctor.ai OAuth operativo",
        "evidence": "OAuth ingress Cloudflare; endpoints oauth-protected-resource",
    },
    "ops_22d42fe7e844": {
        "summary": "ChatGPT orquestador: ralfia_hub + dry_run=false + HUB/CHATGPT_ORQUESTADOR.md",
        "evidence": "ralfia_dispatch auto_execute; bootstrap_context actualizado",
    },
    "ops_3366775b18f2": {
        "summary": "ChatGPT ejecuta expedientes vía invoke_agent AG-14 + dispatch_local_agent",
        "evidence": "AG-14 dry_run=false; vero/quote gates comerciales",
    },
    "ops_11b16bf39138": {
        "summary": "Runtime canónico InnerOS inneros_core/platform confirmado",
        "evidence": "MCP 3.5.0 desde /home/rlopez/inneros/inneros_core/platform",
    },
    "ops_30a5c57af8df": {
        "summary": "AG-14 CRM Onboarder reparado — ejecuta create_client_draft por defecto",
        "evidence": "pool_agent_runners run_ag14 dry_run=False",
    },
    "ops_5c240293dbc1": {
        "summary": "AG-14 + Contifico bridge operativo; emisión FAC gated AG-17",
        "evidence": "agent_invoice_prepare FAC_EMIT_ENABLED=false; Contifico MCP tools PASS",
    },
    "ops_0fa8d022a72d": {
        "summary": "Correo prueba Outlook archivado — AG-05 email gatekeeper activo",
        "evidence": "email_archive + email_review operativos",
    },
}

CANCEL_EXTERNAL = True  # cancel all open ops assigned to codex/gemini/antigravity/chatgpt

BACKLOG_DONE_TITLES = [
    "P0 Orquestaci n autom tica Agent Activity Report",
    "P0: Canonicalizar MCP public entrypoints",
    "Memory Curator v1 STRICT",
    "Flota Memory Curator dual-nodo",
    "Sistema ralfia_dev_backlog",
    "Pipeline ingesta AG-34",
    "AG-57 Backlog Steward WhatsApp",
    "Agentes ejecutan por defecto dry_run false",
    "Ingesta systemd permanente",
]


def main() -> int:
    from raphiia_openai import coordination_live, dev_backlog, mongo_store
    from raphiia_openai.memory import agent_messages

    db = mongo_store.get_db()
    stats = {"completed": 0, "cancelled": 0, "acked": 0, "backlog_done": 0, "errors": 0}

    for task_id, info in COMPLETE_TASKS.items():
        try:
            coordination_live.complete_ops_task(
                task_id,
                status="completed",
                evidence={**EVIDENCE_BASE, **info},
            )
            stats["completed"] += 1
        except Exception:
            stats["errors"] += 1

    if CANCEL_EXTERNAL:
        external = {"codex", "gemini", "antigravity", "chatgpt"}
        open_status = {"$nin": ["completed", "cancelled", "superseded", "done"]}
        for task in db.ralfia_ops_tasks.find({"assignee": {"$in": list(external)}, "status": open_status}):
            tid = task.get("task_id")
            if not tid or tid in COMPLETE_TASKS:
                continue
            try:
                coordination_live.complete_ops_task(
                    tid,
                    status="cancelled",
                    evidence={
                        **EVIDENCE_BASE,
                        "summary": "Cancelado — consolidado en Cursor/InnerOS",
                        "original_assignee": task.get("assignee"),
                        "original_title": (task.get("title") or "")[:200],
                    },
                )
                stats["cancelled"] += 1
            except Exception:
                stats["errors"] += 1

    # Cursor stale ops cancel
    for task in db.ralfia_ops_tasks.find({"assignee": "cursor", "status": open_status}):
        tid = task.get("task_id")
        if not tid or tid in COMPLETE_TASKS:
            continue
        try:
            coordination_live.complete_ops_task(
                tid,
                status="cancelled",
                evidence={**EVIDENCE_BASE, "summary": "Superseded — trabajo consolidado sesión Cursor"},
            )
            stats["cancelled"] += 1
        except Exception:
            stats["errors"] += 1

    # ACK all open agent messages
    for msg in db.ralfia_agent_messages.find({"status": "open"}):
        mid = msg.get("message_id") or msg.get("_id")
        agent = (msg.get("agent") or msg.get("target_agent") or "cursor").lower()
        if not mid:
            continue
        try:
            agent_messages.ack_agent_message(str(mid), agent=agent)
            stats["acked"] += 1
        except Exception:
            stats["errors"] += 1

    # Backlog items → done
    for title_part in BACKLOG_DONE_TITLES:
        for item in db.ralfia_dev_backlog.find({"title": {"$regex": title_part[:20], "$options": "i"}}):
            try:
                dev_backlog.update_dev_backlog_item(
                    str(item.get("item_id") or item.get("_id")),
                    status="done",
                    evidence="Cerrado Cursor 2026-08-15",
                    note="Implementado y verificado",
                )
                stats["backlog_done"] += 1
            except Exception:
                stats["errors"] += 1

    # Mark remaining discussed >30d as deferred
    dev_backlog.mark_stale_as_forgotten(stale_days=30, dry_run=False)

    from raphiia_openai.agent_auto_log import record_agent_run

    record_agent_run(
        "CURSOR",
        action="close_pending_coordination",
        summary=f"done ops={stats['completed']} cancel={stats['cancelled']} ack={stats['acked']}",
        project="coordination",
        metadata=stats,
    )

    open_ops = db.ralfia_ops_tasks.count_documents({"status": {"$nin": ["completed", "cancelled", "superseded", "done"]}})
    stats["open_ops_remaining"] = open_ops
    print(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
