#!/usr/bin/env python3
"""Full hackathon E2E evidence bundle for ops_75de50f2671d."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM))

from inneros_core_runtime import gemini_runtime as gr  # noqa: E402
from inneros_core_runtime import google_adk_a2a  # noqa: E402


def _correlation_id() -> str:
    if os.getenv("INNEROS_E2E_CORRELATION_ID"):
        return os.getenv("INNEROS_E2E_CORRELATION_ID", "").strip()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"cursor-google-e2e-{stamp}"


def _read_firestore_doc(project_id: str, collection: str, document_id: str) -> dict:
    try:
        from google.cloud import firestore

        credentials, project = gr._get_google_credentials(project_id)
        db = firestore.Client(project=project, credentials=credentials)
        snap = db.collection(collection).document(document_id).get()
        return {"ok": snap.exists, "document_id": document_id, "exists": snap.exists}
    except Exception as exc:
        return {"ok": False, "document_id": document_id, "error": str(exc)}


def _query_cloud_logging(project_id: str, correlation_id: str) -> dict:
    try:
        filt = f'jsonPayload.correlation_id="{correlation_id}" OR textPayload:"{correlation_id}"'
        proc = subprocess.run(
            [
                "gcloud",
                "logging",
                "read",
                filt,
                f"--project={project_id}",
                "--limit=5",
                "--format=json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            return {"ok": False, "error": (proc.stderr or proc.stdout)[:300]}
        entries = json.loads(proc.stdout or "[]")
        return {"ok": bool(entries), "entry_count": len(entries), "entries_preview": entries[:2]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main() -> int:
    project_id = "innerops-agentic-platform"
    correlation_id = _correlation_id()
    os.environ.setdefault("INNEROS_GEMINI_MODEL", "gemini-2.5-flash")
    os.environ.setdefault("INNEROS_GEMINI_MODEL_LOCATION", "us-central1")

    runtime = gr.InnerOSGeminiRuntime()
    result = runtime.run(
        prompt="Reply with exactly one word: verified",
        correlation_id=correlation_id,
        allow_external=True,
    )
    evidence = result.get("evidence") or {}
    firestore_ref = evidence.get("firestore") or {}
    pubsub_ref = evidence.get("pubsub") or {}
    memory_ref = evidence.get("memory_bank") or {}

    firestore_doc_id = firestore_ref.get("document_id")
    firestore_verify = (
        _read_firestore_doc(project_id, "gemini_evidence", firestore_doc_id)
        if firestore_doc_id
        else {"ok": False, "error": "missing_firestore_document_id"}
    )

    adk_status = google_adk_a2a.adk_live_status()
    adk_catalog = google_adk_a2a.remote_a2a_agents()
    logging_ref = evidence.get("cloud_logging") or {}

    bundle = {
        "ok": True,
        "correlation_id": correlation_id,
        "branch": "cursor/google-gemma-final-20260828",
        "gemini": {
            "model": result.get("model"),
            "interaction_id": result.get("interaction_id"),
            "live_mode": result.get("live_mode"),
            "status": result.get("status"),
            "verified": evidence.get("verified"),
            "simulated": result.get("simulated"),
            "output_preview": (result.get("output_text") or "")[:120],
        },
        "firestore": {
            "write": firestore_ref,
            "verify": firestore_verify,
        },
        "pubsub": pubsub_ref,
        "memory_bank": memory_ref,
        "cloud_logging": {
            "write": logging_ref,
            "query": _query_cloud_logging(project_id, correlation_id),
        },
        "adk": {
            "sdk": adk_status,
            "remote_agents_count": adk_catalog.get("count"),
            "adk_pattern": adk_catalog.get("adk_pattern"),
        },
        "model_armor": {"template": "inneros-default", "location": "us-central1"},
        "blockers": [],
    }

    if not evidence.get("verified"):
        bundle["blockers"].append("gemini_not_verified")
    if not firestore_ref.get("ok"):
        bundle["blockers"].append("firestore_write_failed")
    if not pubsub_ref.get("ok"):
        bundle["blockers"].append("pubsub_publish_failed")
    if not memory_ref.get("ok"):
        bundle["blockers"].append("memory_bank_mirror_failed")
    if not logging_ref.get("ok"):
        bundle["blockers"].append("cloud_logging_write_failed")
    if not adk_status.get("contract_ok"):
        bundle["blockers"].append("adk_contract_incomplete")

    bundle["ok"] = not bundle["blockers"]
    print(json.dumps(bundle, indent=2, default=str))
    return 0 if bundle["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
