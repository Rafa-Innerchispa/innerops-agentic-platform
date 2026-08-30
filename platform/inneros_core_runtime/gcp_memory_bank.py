"""Google Cloud Firestore Memory Bank integration for governed agent states."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("inneros.gcp_memory_bank")

def _get_firestore_client() -> Any | None:
    try:
        from google.cloud import firestore
        from inneros_core_runtime.gemini_runtime import _get_google_credentials
        credentials, project = _get_google_credentials()
        return firestore.Client(project=project, credentials=credentials)
    except Exception as exc:
        logger.warning("Could not initialize Firestore client: %s", exc)
        return None

def save_memory(
    agent_id: str,
    content: dict[str, Any],
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Mirror agent memory/fact to Firestore collection 'inneros_memory_bank'."""
    client = _get_firestore_client()
    now = datetime.now(timezone.utc).isoformat()
    doc_data = {
        "agent_id": agent_id,
        "content": content,
        "correlation_id": correlation_id,
        "created_at": now,
        "updated_at": now,
    }
    
    if not client:
        logger.warning("Firestore client unavailable. Memory not mirrored to GCP: %s", doc_data)
        return {"ok": False, "error": "firestore_unavailable", "data": doc_data}
        
    try:
        col_ref = client.collection("inneros_memory_bank")
        # If content has a memory_id, use it as document ID to avoid duplicates
        doc_id = content.get("memory_id") or content.get("id")
        if doc_id:
            col_ref.document(str(doc_id)).set(doc_data)
        else:
            col_ref.add(doc_data)
            
        logger.info("Successfully mirrored agent memory to Firestore: %s", doc_id or "auto-generated")
        return {"ok": True, "mirrored": True}
    except Exception as exc:
        logger.error("Error writing memory to Firestore: %s", exc)
        return {"ok": False, "error": str(exc), "data": doc_data}
