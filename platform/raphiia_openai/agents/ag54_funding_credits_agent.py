"""AG-54 Funding Credits Agent — créditos, grants, no desperdiciar (email + registry)."""

from __future__ import annotations

import re
from typing import Any

from raphiia_openai.agent_auto_log import record_agent_run

AGENT_ID = "AG-54_FUNDING_CREDITS"

CREDIT_KEYWORDS = (
    "credit", "crédito", "grant", "funding", "aws activate", "google cloud",
    "azure", "startup", "credits", "coupon", "voucher", "devpost", "apply by",
    "deadline", "expires", "expira", "bright data", "brightdata", "prize",
    "winner", "ganador", "premio", "free trial", "promotional", "redeem",
    "activation", "startup program", "founders", "credits remaining",
)

PROVIDER_HINTS = {
    "bright data": "Bright Data",
    "brightdata": "Bright Data",
    "aws": "AWS Activate",
    "google cloud": "Google Cloud",
    "azure": "Microsoft Azure",
    "devpost": "Devpost",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "nvidia": "NVIDIA",
}


def agent_funding_status() -> dict[str, Any]:
    from raphiia_openai import funding_registry

    summary = funding_registry.get_funding_registry_summary(limit=10)
    programs = funding_registry.list_funding_programs(status="active", limit=30)
    apps = funding_registry.list_funding_applications(limit=20)
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "summary": summary,
        "active_programs": len(programs.get("items") or []),
        "applications": len(apps.get("items") or []),
        "mission": "Rastrear créditos disponibles, consumos y oportunidades en correo",
        "profile_mcp": "hackathon_funding",
    }


def _guess_provider(text: str) -> str | None:
    low = text.lower()
    for hint, name in PROVIDER_HINTS.items():
        if hint in low:
            return name
    return None


def agent_funding_sync_and_scan(
    query: str = "bright data credits grant funding prize winner cloud startup",
    limit: int = 40,
    *,
    poll_email: bool = True,
) -> dict[str, Any]:
    """Poll IMAP → archive → scan créditos (Bright Data, cloud, grants)."""
    steps: dict[str, Any] = {}
    if poll_email:
        try:
            from raphiia_openai.notifications import email_monitor

            steps["poll"] = email_monitor.trigger_email_poll()
        except Exception as exc:
            steps["poll"] = {"ok": False, "error": str(exc)[:200]}
        try:
            from raphiia_openai.notifications import email_archive

            steps["archive_sync"] = email_archive.sync_email_archive_from_messages(limit=500)
        except Exception as exc:
            steps["archive_sync"] = {"ok": False, "error": str(exc)[:200]}

    scan = agent_funding_scan_emails(query=query, limit=limit)
    scan["sync_steps"] = steps
    scan["action"] = "agent_funding_sync_and_scan"
    return scan


def agent_funding_scan_emails(query: str = "credits grant funding cloud startup", limit: int = 25) -> dict[str, Any]:
    from raphiia_openai.notifications import email_archive

    result = email_archive.search_email_archive(query=query, limit=limit)
    opportunities: list[dict[str, Any]] = []
    for row in (result.get("messages") or result.get("results") or []):
        subj = str(row.get("subject") or "")
        snippet = str(
            row.get("snippet")
            or row.get("body_preview")
            or row.get("body_text")
            or row.get("preview")
            or ""
        )[:500]
        text = f"{subj} {snippet}".lower()
        if any(k in text for k in CREDIT_KEYWORDS):
            provider = _guess_provider(text)
            mail_id = row.get("mail_id") or row.get("message_id") or row.get("_id")
            opportunities.append({
                "message_id": mail_id,
                "subject": subj,
                "from": row.get("from") or row.get("from_addr") or row.get("sender"),
                "date": row.get("date") or row.get("received_at"),
                "matched": [k for k in CREDIT_KEYWORDS if k in text][:5],
                "provider_hint": provider,
                "suggested_program_name": provider or (subj[:80] if subj else "Unknown program"),
                "view_url": row.get("view_url"),
            })
    record_agent_run(AGENT_ID, action="funding_scan_emails", summary=f"found={len(opportunities)}", project="funding")
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "query": query,
        "count": len(opportunities),
        "opportunities": opportunities,
        "next": "Registrar con save_funding_program / save_funding_application",
    }


def agent_funding_register_from_email(
    message_id: str,
    program_name: str,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    from raphiia_openai.notifications import email_archive
    from raphiia_openai import funding_registry

    msg = email_archive.get_email_archive_message(message_id)
    if not msg.get("ok") and not msg.get("subject"):
        return {"ok": False, "error": "email_not_found", "message_id": message_id}
    payload = {
        "name": program_name,
        "status": "active",
        "source": "email_archive",
        "description": (msg.get("subject") or "")[:500],
        "tags": ["email-sourced", "credits"],
        "metadata": {"source_message_id": message_id},
    }
    if dry_run:
        return {"ok": True, "dry_run": True, "agent_id": AGENT_ID, "would_register": payload}
    saved = funding_registry.save_funding_program(**payload)
    return {"ok": bool(saved.get("ok", True)), "agent_id": AGENT_ID, **saved}
