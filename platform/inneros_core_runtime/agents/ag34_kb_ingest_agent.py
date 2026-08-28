"""AG-34 KB Ingest Sentinel — pipeline local unificado."""

from __future__ import annotations

from typing import Any

from raphiia_openai.agent_auto_log import record_agent_run

AGENT_ID = "AG-34_KB_INGEST"


def run_kb_ingest(text: str, *, title: str = "", dry_run: bool = True) -> dict[str, Any]:
    from raphiia_openai import dev_backlog, ingest_pipeline

    body = (text or "").strip()
    if not body:
        return {"ok": False, "agent_id": AGENT_ID, "error": "empty_text"}
    if dry_run:
        return {"ok": True, "agent_id": AGENT_ID, "dry_run": True, "would_save": body[:300]}
    item = dev_backlog.capture_backlog_item(
        title=title or body[:80],
        body=body[:4000],
        status="discussed",
        kind="idea",
        source_agent="SYSTEM",
        tags=["kb-ingest", "ag-34"],
    )
    record_agent_run(AGENT_ID, action="kb_ingest", summary=title[:30], project="ralfia-ops")
    return {"ok": True, "agent_id": AGENT_ID, "backlog": item}


def run_full_ingest(*, email_limit: int = 20, chatgpt_limit: int = 100, dry_run: bool = False) -> dict[str, Any]:
    from raphiia_openai import ingest_pipeline

    return ingest_pipeline.run_full_local_ingest(
        email_limit=email_limit,
        chatgpt_limit=chatgpt_limit,
        dry_run=dry_run,
    )
