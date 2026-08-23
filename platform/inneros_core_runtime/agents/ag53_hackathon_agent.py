"""AG-53 Hackathon Agent — oportunidades + docs hackathon (AG-21/22/23/24)."""

from __future__ import annotations

from typing import Any

from raphiia_openai.agent_auto_log import record_agent_run

AGENT_ID = "AG-53_HACKATHON_AGENT"


def agent_hackathon_status() -> dict[str, Any]:
    from raphiia_openai import funding_registry

    funding = funding_registry.get_funding_registry_summary(limit=10)
    programs = funding_registry.list_funding_programs(limit=15)
    hack = [
        p for p in (programs.get("items") or [])
        if any(x in str(p.get("name", "")).lower() + str(p.get("tags", [])).lower()
               for x in ("hackathon", "devpost", "uipath", "gemini", "xprize"))
    ]
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "funding_summary": funding,
        "hackathon_programs": hack[:10],
        "delegates": {
            "AG-21": "hackathon_docs_harvester",
            "AG-22": "opportunity_collector",
            "AG-23": "opportunity_analyst",
            "AG-24": "application_drafter",
        },
        "profile_mcp": "hackathon_funding",
    }


def agent_hackathon_scan_emails(query: str = "hackathon credits grant devpost", limit: int = 15) -> dict[str, Any]:
    from raphiia_openai.notifications import email_archive

    result = email_archive.search_email_archive(query=query, limit=limit)
    hits = []
    keywords = ("hackathon", "credit", "grant", "devpost", "google cloud", "aws", "azure", "prize")
    for row in (result.get("results") or result.get("messages") or []):
        subj = str(row.get("subject") or "").lower()
        if any(k in subj for k in keywords):
            hits.append({
                "message_id": row.get("message_id") or row.get("_id"),
                "subject": row.get("subject"),
                "from": row.get("from") or row.get("sender"),
                "date": row.get("date") or row.get("received_at"),
            })
    record_agent_run(AGENT_ID, action="hackathon_scan_emails", summary=f"hits={len(hits)}", project="funding")
    return {"ok": True, "agent_id": AGENT_ID, "query": query, "count": len(hits), "opportunities": hits[:limit]}
