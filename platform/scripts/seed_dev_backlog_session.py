#!/usr/bin/env python3
"""Seed inicial del backlog de desarrollo — sesión Memory Curator + backlog histórico."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raphiia_openai import dev_backlog  # noqa: E402

CONV_REF = "cursor-405a4e59-a8f5-43af-a2a3-0ed8e1a11d59"

SESSION_ITEMS = [
    # --- HECHO esta sesión ---
    {
        "title": "Memory Curator v1 STRICT (VKR) — registros tabulares canónicos",
        "body": "memory_record_schema.py + memory_record_store.py. Solo verification_status=canonical buscable. Dedupe por fingerprint y content hash.",
        "status": "done",
        "kind": "architecture",
        "source_agent": "CURSOR",
        "project": "memory-curator",
        "tags": ["vkr", "drive", "done"],
        "conversation_ref": CONV_REF,
        "ops_task_id": "ops_30226c8b57ef",
        "evidence": "ralfia_memory_records: 15 registros; Novomode 12 canonical + 3 review",
    },
    {
        "title": "Fix AG-45 Local Exec — aliases local_exec_inspect_repo",
        "body": "local_execution_plane.py exportaba inspect_repo sin alias MCP.",
        "status": "done",
        "kind": "bug",
        "source_agent": "CURSOR",
        "project": "inneros",
        "tags": ["ag-45", "done"],
        "conversation_ref": CONV_REF,
        "evidence": "Aliases añadidos al final de local_execution_plane.py",
    },
    {
        "title": "Flota Memory Curator dual-nodo (AMD Drive + Intel Notion)",
        "body": "systemd ralfia-memory-curator@N + run_memory_curator_fleet.sh",
        "status": "done",
        "kind": "task",
        "source_agent": "CURSOR",
        "project": "memory-curator",
        "tags": ["fleet", "done"],
        "conversation_ref": CONV_REF,
        "evidence": "4 workers AMD + 2 Intel Notion; checkpoints Mongo compartidos",
    },
    {
        "title": "Sistema ralfia_dev_backlog + MCP finalize_session_handoff",
        "body": "dev_backlog.py + tools MCP capture/list/update/summary + PROTOCOLO_BACKLOG_SESION.md",
        "status": "done",
        "kind": "architecture",
        "source_agent": "CURSOR",
        "project": "coordination",
        "tags": ["backlog", "done"],
        "conversation_ref": CONV_REF,
        "evidence": "dev_backlog.py, mcp_server tools, HUB/PROTOCOLO_BACKLOG_SESION.md",
    },
    {
        "title": "Memory Curator reporta batches via record_agent_run",
        "body": "run_batch llama record_agent_run tras procesar archivos.",
        "status": "done",
        "kind": "task",
        "source_agent": "CURSOR",
        "project": "memory-curator",
        "tags": ["logging", "done"],
        "conversation_ref": CONV_REF,
    },
    # --- PLANNED (decidido, pendiente) ---
    {
        "title": "Dedupe cross-fuente Contifico ↔ Drive por ralfia_number",
        "body": "Llave canónica {tipo}-{documento} ej FAC-001-001-000000056. Colección commercial_documents padre con sources[].",
        "status": "planned",
        "kind": "architecture",
        "source_agent": "CURSOR",
        "project": "memory-curator",
        "tags": ["contifico", "dedupe", "vkr"],
        "conversation_ref": CONV_REF,
    },
    {
        "title": "Wire search_memory_records a MCP para ChatGPT/RalfIA",
        "body": "Exponer búsqueda granular VKR en MCP profile memory.",
        "status": "planned",
        "kind": "task",
        "source_agent": "CURSOR",
        "project": "memory-curator",
        "tags": ["mcp", "vkr"],
        "conversation_ref": CONV_REF,
    },
    {
        "title": "Pipeline VKR email_archive + PST",
        "body": "Extender Memory Curator a correos archivados y PST.",
        "status": "planned",
        "kind": "task",
        "source_agent": "CURSOR",
        "project": "memory-curator",
        "tags": ["email", "pst"],
        "conversation_ref": CONV_REF,
    },
    {
        "title": "OCR PDFs escaneados con qwen2.5vl",
        "body": "PDFs sin texto extraíble necesitan visión.",
        "status": "planned",
        "kind": "task",
        "source_agent": "CURSOR",
        "project": "memory-curator",
        "tags": ["ocr", "ollama"],
        "conversation_ref": CONV_REF,
    },
    {
        "title": "Limpiar/marcar legacy memory v0 como no buscable",
        "body": "~1400 ralfia_memory_items tag memory-curator son ruido semántico.",
        "status": "planned",
        "kind": "task",
        "source_agent": "CURSOR",
        "project": "memory-curator",
        "tags": ["cleanup", "legacy"],
        "conversation_ref": CONV_REF,
    },
    {
        "title": "render_contifico_document — PDF desde JSON API",
        "body": "render_quote_document existe; falta equivalente Contifico.",
        "status": "planned",
        "kind": "task",
        "source_agent": "CURSOR",
        "project": "contifico-exit",
        "tags": ["contifico", "pdf"],
        "conversation_ref": CONV_REF,
    },
    # --- DISCUSSED (hablado, sin owner claro) ---
    {
        "title": "Notion delta vía AG-07 API además de backup export",
        "body": "Curator Notion usa export; falta sync incremental API.",
        "status": "discussed",
        "kind": "idea",
        "source_agent": "CURSOR",
        "project": "memory-curator",
        "tags": ["notion", "ag-07"],
        "conversation_ref": CONV_REF,
    },
    {
        "title": "Confirmar dirección personal owner-validated (LinkedIn hlopezgye)",
        "body": "LinkedIn encontrado; dirección personal pendiente validación Rafael.",
        "status": "discussed",
        "kind": "question",
        "source_agent": "CURSOR",
        "project": "memory-curator",
        "tags": ["identity", "owner-validated"],
        "conversation_ref": CONV_REF,
    },
    # --- Backlog histórico ChatGPT / roadmap (pendiente) ---
    {
        "title": "P0: ChatGPT invocable invoke_agent/ralfia_dispatch sin ralfia:admin",
        "body": "ops_22d42fe7e844 / ops_3366775b18f2. AG-14/12/45 fallan dry_run missing_scope.",
        "status": "planned",
        "kind": "task",
        "source_agent": "CHATGPT",
        "project": "inneros",
        "tags": ["mcp", "oauth", "p0"],
        "ops_task_id": "ops_22d42fe7e844",
    },
    {
        "title": "P0: AG-14 CRM Onboarder + migración Contifico 30 días",
        "body": "Caso E2E EDIFICIO BAIRES. ops_30a5c57af8df.",
        "status": "planned",
        "kind": "task",
        "source_agent": "CHATGPT",
        "project": "contifico-exit",
        "tags": ["ag-14", "p0"],
        "ops_task_id": "ops_30a5c57af8df",
    },
    {
        "title": "P0: Canonicalizar MCP public entrypoints (ngrok solo backup)",
        "body": "ops_5dba6bbb2e66. chatgpt_ngrok confunde; canónico mcp.pcdoctor.ai.",
        "status": "planned",
        "kind": "task",
        "source_agent": "CODEX",
        "project": "inneros",
        "tags": ["mcp", "p0"],
        "ops_task_id": "ops_5dba6bbb2e66",
    },
    {
        "title": "XPRIZE Gemini evidence pack — deadline 2026-08-17",
        "body": "ops_0187ec7824cb. CI verde + demo E2E + evidencia producción.",
        "status": "in_progress",
        "kind": "task",
        "source_agent": "CHATGPT",
        "project": "xprize",
        "tags": ["hackathon", "p0"],
        "ops_task_id": "ops_0187ec7824cb",
    },
    {
        "title": "Núcleo central: perfiles MCP validate_profiles PASS",
        "body": "NUCLEO_CENTRAL_PRIORIDADES N5 pendiente verificación.",
        "status": "planned",
        "kind": "task",
        "source_agent": "CURSOR",
        "project": "inneros",
        "tags": ["nucleo", "mcp"],
    },
    {
        "title": "FAC SRI / AG-48 Billing Agent — facturación fiscal bloqueada",
        "body": "agent_invoice_prepare existe pero FAC gated.",
        "status": "deferred",
        "kind": "task",
        "source_agent": "CURSOR",
        "project": "vero-facturacion",
        "tags": ["billing", "fiscal"],
    },
    {
        "title": "FEMAR cotización E2E completa",
        "body": "Después del núcleo. Flujo cotización multicanal.",
        "status": "deferred",
        "kind": "task",
        "source_agent": "RAFAEL",
        "project": "femar",
        "tags": ["cotizacion", "post-nucleo"],
    },
    {
        "title": "Notion webhook → Mongo ops_tasks automático",
        "body": "Sugerencia ChatGPT jul-2026; pendiente AG-07.",
        "status": "discussed",
        "kind": "idea",
        "source_agent": "CHATGPT",
        "project": "notion",
        "tags": ["webhook", "coordination"],
    },
    {
        "title": "Sandbox/security/oauth hardening flota agentes",
        "body": "Conversaciones anteriores; no urgente vs memoria.",
        "status": "discussed",
        "kind": "architecture",
        "source_agent": "CURSOR",
        "project": "inneros",
        "tags": ["security", "oauth"],
    },
]

SESSION_SUMMARY = (
    "Sesión Cursor Memory Curator: implementado VKR v1 STRICT (registros tabulares canónicos), "
    "flota dual-nodo, fix AG-45, diagnóstico gap logging (chat vs Mongo). "
    "Creado ralfia_dev_backlog + protocolo cierre sesión + MCP tools. "
    "Pendiente: dedupe Contifico↔Drive, wire MCP search VKR, cleanup legacy v0."
)


def main() -> None:
    result = dev_backlog.finalize_session_handoff(
        agent="CURSOR",
        session_summary=SESSION_SUMMARY,
        items=SESSION_ITEMS,
        conversation_ref=CONV_REF,
        project="memory-curator",
    )
    summary = dev_backlog.get_dev_backlog_summary()
    print("Handoff:", result.get("ok"), "backlog:", result.get("backlog"))
    print("Summary total:", summary.get("total"), "by_status:", summary.get("by_status"))


if __name__ == "__main__":
    main()
