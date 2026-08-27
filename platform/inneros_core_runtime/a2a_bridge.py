"""A2A transport bridge for the InnerOS agent fabric.

A2A is deliberately a transport/projection layer. The durable source of truth
remains ``ralfia_ops_tasks`` + RACB in MongoDB. This prevents a second task
lifecycle from drifting away from the control plane already used by MCP,
Dev Swarm and External Repair.
"""

from __future__ import annotations

import importlib.metadata
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

A2A_TASKS_COL = "ralfia_a2a_tasks"
A2A_PROTOCOL_VERSION = "1.0"
BRIDGE_VERSION = "1.0.0"

A2A_TERMINAL_STATES = frozenset({"completed", "failed", "canceled", "rejected"})

OPS_TO_A2A_STATE = {
    "proposed": "submitted",
    "pending": "submitted",
    "accepted": "working",
    "dispatched": "working",
    "in_progress": "working",
    "verification": "working",
    "blocked": "input-required",
    "awaiting_approval": "input-required",
    "completed": "completed",
    "partial": "failed",
    "failed": "failed",
    "cancelled": "canceled",
}

AGENT_CARDS: dict[str, dict[str, Any]] = {
    "inneros-orchestrator": {
        "name": "InnerOS Orchestrator",
        "description": "RalfIA/AG-25 orchestration and delegation across the InnerOS fabric.",
        "url": "inneros://a2a/inneros-orchestrator",
        "version": BRIDGE_VERSION,
        "protocolVersion": A2A_PROTOCOL_VERSION,
        "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": True},
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [{"id": "orchestrate", "name": "Orchestrate", "description": "Route and coordinate durable InnerOS work."}],
        "metadata": {"inneros_role": "orchestrator", "assignee": "ralfia", "local_first": True},
    },
    "qwen-coding": {
        "name": "Qwen Coding",
        "description": "Local AMD .5 coding lane using the configured Qwen3 Coder runtime.",
        "url": "inneros://a2a/qwen-coding",
        "version": BRIDGE_VERSION,
        "protocolVersion": A2A_PROTOCOL_VERSION,
        "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": True},
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [{"id": "coding", "name": "Local coding", "description": "Implement bounded software changes through Dev Swarm."}],
        "metadata": {"inneros_role": "coding", "assignee": "ralfia", "provider": "local-amd-5", "local_first": True},
    },
    "codex-repair": {
        "name": "Codex Repair",
        "description": "External repair escalation lane, admitted only through InnerOS approval and credit gates.",
        "url": "inneros://a2a/codex-repair",
        "version": BRIDGE_VERSION,
        "protocolVersion": A2A_PROTOCOL_VERSION,
        "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": True},
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [{"id": "repair", "name": "Repair escalation", "description": "Repair a locally blocked task without bypassing spend gates."}],
        "metadata": {"inneros_role": "repair", "assignee": "codex", "external": True, "approval_gated": True},
    },
    "integration-guardian": {
        "name": "Integration Guardian",
        "description": "Independent verification lane for tests, diffs, evidence and false-PASS rejection.",
        "url": "inneros://a2a/integration-guardian",
        "version": BRIDGE_VERSION,
        "protocolVersion": A2A_PROTOCOL_VERSION,
        "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": True},
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [{"id": "verify", "name": "Integration verification", "description": "Verify implementation evidence before integration."}],
        "metadata": {"inneros_role": "guardian", "assignee": "ralfia", "independent_verifier": True},
    },
    "browser-qa": {
        "name": "Browser QA",
        "description": "AG-55 browser review lane for local previews and approved web surfaces.",
        "url": "inneros://a2a/browser-qa",
        "version": BRIDGE_VERSION,
        "protocolVersion": A2A_PROTOCOL_VERSION,
        "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": True},
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [{"id": "browser_qa", "name": "Browser QA", "description": "Review a UI through the bounded Browser Ops plane."}],
        "metadata": {"inneros_role": "browser_qa", "assignee": "ralfia", "agent_id": "AG-55", "local_first": True},
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sdk_version() -> str | None:
    try:
        return importlib.metadata.version("a2a-sdk")
    except importlib.metadata.PackageNotFoundError:
        return None


class OpsAdapter(Protocol):
    def create_task(
        self,
        *,
        assignee: str,
        title: str,
        checklist: list[str],
        evidence_required: list[str],
        priority: str,
        correlation_id: str,
        related_project: str | None,
    ) -> dict[str, Any]: ...

    def get_task(self, task_id: str) -> dict[str, Any] | None: ...


class A2AStore(Protocol):
    def put(self, record: dict[str, Any]) -> None: ...

    def get(self, a2a_task_id: str) -> dict[str, Any] | None: ...


class MongoOpsAdapter:
    """Production adapter into the existing RACB/ops task control plane."""

    def create_task(
        self,
        *,
        assignee: str,
        title: str,
        checklist: list[str],
        evidence_required: list[str],
        priority: str,
        correlation_id: str,
        related_project: str | None,
    ) -> dict[str, Any]:
        from raphiia_openai import coordination_live

        return coordination_live.create_ops_task(
            assignee=assignee,
            title=title,
            checklist=checklist,
            evidence_required=evidence_required,
            priority=priority,
            from_agent="A2A",
            correlation_id=correlation_id,
            related_project=related_project,
        )

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        from raphiia_openai import coordination_live, mongo_store

        db = mongo_store.get_db()
        return db[coordination_live.OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0})


class MongoA2AStore:
    """Durable A2A envelope store. It never owns the execution lifecycle."""

    def put(self, record: dict[str, Any]) -> None:
        from raphiia_openai import mongo_store

        mongo_store.get_db()[A2A_TASKS_COL].update_one(
            {"a2a_task_id": record["a2a_task_id"]},
            {"$set": dict(record)},
            upsert=True,
        )

    def get(self, a2a_task_id: str) -> dict[str, Any] | None:
        from raphiia_openai import mongo_store

        return mongo_store.get_db()[A2A_TASKS_COL].find_one({"a2a_task_id": a2a_task_id}, {"_id": 0})


@dataclass
class A2ABridge:
    ops: OpsAdapter
    store: A2AStore

    def dispatch(
        self,
        *,
        agent_id: str,
        title: str,
        body: str,
        correlation_id: str = "",
        context_id: str = "",
        priority: str = "p0",
        related_project: str | None = "inneros",
        dry_run: bool = False,
        protocol_task_id: str = "",
    ) -> dict[str, Any]:
        card = AGENT_CARDS.get((agent_id or "").strip())
        if not card:
            return {"ok": False, "error": "unknown_a2a_agent", "agent_id": agent_id, "known_agents": sorted(AGENT_CARDS)}
        clean_title = (title or "").strip()
        clean_body = (body or "").strip()
        if not clean_title or not clean_body:
            return {"ok": False, "error": "title_and_body_required"}

        context_id = (context_id or correlation_id or "").strip() or f"a2a_ctx_{secrets.token_hex(8)}"
        a2a_task_id = (protocol_task_id or "").strip() or f"a2a_{secrets.token_hex(8)}"
        ops_correlation_id = (correlation_id or "").strip() or f"a2a:{context_id}:{a2a_task_id}"
        assignee = str(card["metadata"]["assignee"])
        planned = {
            "ok": True,
            "dry_run": True,
            "a2a_task_id": a2a_task_id,
            "contextId": context_id,
            "agent_id": agent_id,
            "assignee": assignee,
            "state": "submitted",
        }
        if dry_run:
            return planned

        created = self.ops.create_task(
            assignee=assignee,
            title=f"[A2A:{agent_id}] {clean_title}",
            checklist=[clean_body, f"A2A contextId={context_id}", f"A2A agent={agent_id}"],
            evidence_required=["status OK/PARTIAL/FAIL", "evidence_refs/artifacts", "terminal state must match RACB"],
            priority=priority,
            correlation_id=ops_correlation_id,
            related_project=related_project,
        )
        if not created.get("ok"):
            return {"ok": False, "error": "ops_task_create_failed", "details": created}

        ops_task_id = str(created.get("task_id") or (created.get("task") or {}).get("task_id") or "")
        if not ops_task_id:
            return {"ok": False, "error": "ops_task_id_missing", "details": created}

        record = {
            "a2a_task_id": a2a_task_id,
            "context_id": context_id,
            "correlation_id": ops_correlation_id,
            "agent_id": agent_id,
            "ops_task_id": ops_task_id,
            "state": "submitted",
            "created_at": _now(),
            "updated_at": _now(),
            "artifacts": [],
            "bridge_version": BRIDGE_VERSION,
        }
        self.store.put(record)
        return {**planned, "dry_run": False, "ops_task_id": ops_task_id, "created": bool(created.get("created", True))}

    def task_status(self, a2a_task_id: str) -> dict[str, Any]:
        record = self.store.get((a2a_task_id or "").strip())
        if not record:
            return {"ok": False, "error": "a2a_task_not_found", "a2a_task_id": a2a_task_id}
        ops_task_id = str(record.get("ops_task_id") or "")
        ops_task = self.ops.get_task(ops_task_id)
        if not ops_task:
            return {"ok": False, "error": "underlying_ops_task_not_found", "a2a_task_id": a2a_task_id, "ops_task_id": ops_task_id}

        ops_status = str(ops_task.get("status") or "proposed").strip().lower()
        state = OPS_TO_A2A_STATE.get(ops_status, "working")
        evidence = ops_task.get("evidence") if isinstance(ops_task.get("evidence"), dict) else {}
        integrity_error = None
        if state == "completed" and not evidence:
            state = "working"
            integrity_error = "terminal_ops_task_missing_evidence"

        artifacts = []
        if evidence:
            artifacts.append({"artifactId": f"evidence:{ops_task_id}", "name": "InnerOS evidence", "parts": [{"data": evidence}]})

        synced = {
            **record,
            "state": state,
            "updated_at": _now(),
            "artifacts": artifacts,
            "ops_status": ops_status,
        }
        self.store.put(synced)
        result = {
            "ok": True,
            "id": record["a2a_task_id"],
            "contextId": record["context_id"],
            "agent_id": record["agent_id"],
            "ops_task_id": ops_task_id,
            "status": {"state": state},
            "artifacts": artifacts,
            "ops_status": ops_status,
            "terminal": state in A2A_TERMINAL_STATES,
        }
        if integrity_error:
            result["integrity_error"] = integrity_error
        if ops_task.get("blocker"):
            result["status"]["message"] = str(ops_task.get("blocker"))
        return result


def get_bridge() -> A2ABridge:
    return A2ABridge(ops=MongoOpsAdapter(), store=MongoA2AStore())


def agent_cards() -> dict[str, Any]:
    return {"ok": True, "count": len(AGENT_CARDS), "cards": list(AGENT_CARDS.values())}


def status() -> dict[str, Any]:
    sdk = _sdk_version()
    return {
        "ok": True,
        "service": "inneros-a2a-bridge",
        "bridge_version": BRIDGE_VERSION,
        "protocol_version": A2A_PROTOCOL_VERSION,
        "sdk": {"package": "a2a-sdk", "version": sdk, "available": bool(sdk)},
        "source_of_truth": "ralfia_ops_tasks/RACB/MongoDB",
        "durable_transport_store": A2A_TASKS_COL,
        "agent_count": len(AGENT_CARDS),
        "agents": sorted(AGENT_CARDS),
    }


def dispatch(**kwargs: Any) -> dict[str, Any]:
    return get_bridge().dispatch(**kwargs)


def task_status(a2a_task_id: str) -> dict[str, Any]:
    return get_bridge().task_status(a2a_task_id)
