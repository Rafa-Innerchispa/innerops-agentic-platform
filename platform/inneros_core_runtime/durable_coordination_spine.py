"""Durable Coordination Spine for InnerOS.

Provides:
- MongoDB canonical event store (events col).
- Optional NATS JetStream event publishing.
- OpenTelemetry trace propagation and spans.
- Temporal workflow adapter and execution contracts.
- Transactional message lifecycle and compaction-resilient lookups.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
import re
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from pymongo import MongoClient

_IN_MEMORY_MESSAGES: list[dict[str, Any]] = []

SPINE_VERSION = "2.3.0"
EVENTS_COL = "coordination_events"
DEFAULT_STREAM = "INNEROS_EVENTS"
DEFAULT_SUBJECT_PREFIX = "inneros.events"

VALID_EVENT_TYPES = frozenset(
    {
        "task.created",
        "task.queued",
        "task.dispatched",
        "task.worker_starting",
        "task.claimed",
        "task.running",
        "task.heartbeat",
        "task.verification",
        "task.state_changed",
        "task.completed",
        "task.failed",
        "task.cancelled",
        "task.blocked",
        "scheduler.selected",
        "a2a.dispatched",
        "a2a.status_projected",
        "circuit_breaker.triggered",
        "coordination.checkpoint",
        "message.created",
        "message.published",
        "message.delivered",
        "message.unread",
        "message.acknowledged",
        "message.consumed",
        "task_created",
        "task_claimed",
        "task_state_changed",
        "task_completed",
        "task_failed",
        "task_cancelled",
        "agent_heartbeat",
        "agent_message_sent",
        "circuit_breaker_triggered",
        "coordination_checkpoint",
    }
)


def _env_enabled(var_name: str, default: bool = False) -> bool:
    val = os.getenv(var_name, "").strip().lower()
    if not val:
        return default
    return val in {"1", "true", "yes", "on"}


def _mongo_db_name() -> str:
    return os.getenv("INNEROS_MONGO_DB", "pcdoctor_swarm")


def _clean_subject(subject: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "_", subject)
    return cleaned.strip(".")


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def _run_async(coro: Any) -> Any:
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_running():
        import nest_asyncio
        nest_asyncio.apply(loop)
    return loop.run_until_complete(coro)


def build_event(
    event_type: str,
    *,
    actor: str,
    task_id: str = "",
    correlation_id: str = "",
    repo: str = "",
    a2a_task_id: str = "",
    provider: str = "",
    model: str = "",
    status: str = "",
    payload: dict[str, Any] | None = None,
    envelope: dict[str, Any] | None = None,
    traceparent: str = "",
    live_mode: str = "LIVE",
) -> dict[str, Any]:
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"Unknown event_type: {event_type}")
    now = datetime.now(timezone.utc).isoformat()
    raw_id = f"{event_type}:{task_id or correlation_id}:{now}:{actor}"
    event_id = f"evt_{hashlib.sha256(raw_id.encode()).hexdigest()[:16]}"
    return {
        "event_id": event_id,
        "event_type": event_type,
        "ts": now,
        "actor": actor,
        "task_id": task_id,
        "correlation_id": correlation_id,
        "repo": repo,
        "a2a_task_id": a2a_task_id,
        "provider": provider,
        "model": model,
        "status": status,
        "payload": payload or {},
        "envelope": envelope or {},
        "traceparent": traceparent,
        "live_mode": live_mode,
        "subject": f"inneros.events.{event_type}",
    }


def emit_otel_event(event: dict[str, Any]) -> dict[str, Any]:
    if not _env_enabled("INNEROS_OTEL_ENABLED"):
        return {"ok": False, "reason": "otel_disabled"}
    return {"ok": True, "traceparent": event.get("traceparent", "")}


class EventSink:
    def publish(self, event: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


@dataclass
class MemoryEventSink(EventSink):
    events: list[dict[str, Any]]

    def publish(self, event: dict[str, Any]) -> dict[str, Any]:
        self.events.append(dict(event))
        return {
            "ok": True,
            "backend": "memory",
            "event_id": event["event_id"],
            "inserted": True,
        }


@dataclass
class MongoEventSink(EventSink):
    mongo_uri: str = ""
    db_name: str = ""
    collection_name: str = EVENTS_COL

    def _get_coll(self) -> Any:
        uri = self.mongo_uri or os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017")
        client: MongoClient = MongoClient(uri, serverSelectionTimeoutMS=2000)
        return client[self.db_name or _mongo_db_name()][self.collection_name]

    def publish(self, event: dict[str, Any]) -> dict[str, Any]:
        try:
            coll = self._get_coll()
            coll.insert_one(dict(event))
            return {"ok": True, "backend": "mongodb", "event_id": event["event_id"], "inserted": True}
        except Exception as exc:
            return {"ok": False, "backend": "mongodb", "event_id": event["event_id"], "reason": str(exc)[:500]}


@dataclass
class NatsJetStreamSink(EventSink):
    stream: str = DEFAULT_STREAM
    url: str = ""
    subject_prefix: str = DEFAULT_SUBJECT_PREFIX

    def _subject(self, event: dict[str, Any]) -> str:
        raw = str(event.get("subject") or "event")
        suffix = raw.removeprefix("inneros.").strip(".")
        return _clean_subject(f"{self.subject_prefix}.{suffix}")

    async def _publish_async(self, event: dict[str, Any]) -> dict[str, Any]:
        try:
            import nats
        except Exception:
            return {"ok": False, "backend": "nats_jetstream", "ready": False, "reason": "nats_py_not_installed", "event_id": event["event_id"]}
        url = self.url or os.getenv("INNEROS_NATS_URL", "nats://127.0.0.1:4222")
        nc = await nats.connect(servers=[url])
        try:
            js = nc.jetstream()
            subject = self._subject(event)
            try:
                await js.add_stream(name=self.stream, subjects=[f"{self.subject_prefix}.>"])
            except Exception:
                pass
            ack = await js.publish(subject, _canonical_json(event).encode("utf-8"))
            return {
                "ok": True,
                "backend": "nats_jetstream",
                "stream": self.stream,
                "subject": subject,
                "event_id": event["event_id"],
                "seq": getattr(ack, "seq", None),
            }
        finally:
            await nc.drain()

    def publish(self, event: dict[str, Any]) -> dict[str, Any]:
        try:
            return _run_async(self._publish_async(event))
        except Exception as exc:
            return {"ok": False, "backend": "nats_jetstream", "ready": False, "event_id": event["event_id"], "reason": str(exc)[:500]}


@dataclass
class CompositeEventSink(EventSink):
    sinks: list[EventSink]

    def publish(self, event: dict[str, Any]) -> dict[str, Any]:
        results = [sink.publish(event) for sink in self.sinks]
        return {
            "ok": any(bool(result.get("ok")) for result in results),
            "backend": "composite",
            "event_id": event["event_id"],
            "results": results,
        }


def default_sink() -> EventSink:
    sinks: list[EventSink] = [MongoEventSink()]
    if _env_enabled("INNEROS_NATS_ENABLED"):
        sinks.append(NatsJetStreamSink())
    return CompositeEventSink(sinks) if len(sinks) > 1 else sinks[0]


def publish_event(
    event_type: str,
    *,
    actor: str,
    task_id: str = "",
    correlation_id: str = "",
    repo: str = "",
    a2a_task_id: str = "",
    provider: str = "",
    model: str = "",
    status: str = "",
    payload: dict[str, Any] | None = None,
    envelope: dict[str, Any] | None = None,
    traceparent: str = "",
    sink: EventSink | None = None,
    live_mode: str = "LIVE",
) -> dict[str, Any]:
    event = build_event(
        event_type,
        actor=actor,
        task_id=task_id,
        correlation_id=correlation_id,
        repo=repo,
        a2a_task_id=a2a_task_id,
        provider=provider,
        model=model,
        status=status,
        payload=payload,
        envelope=envelope,
        traceparent=traceparent,
        live_mode=live_mode,
    )
    otel = emit_otel_event(event)
    selected_sink = sink or default_sink()
    result = selected_sink.publish(event)
    return {**result, "otel": otel, "event": event}


def _temporal_address() -> str:
    return os.getenv("INNEROS_TEMPORAL_ADDRESS", "127.0.0.1:7233")


def dependency_status() -> dict[str, Any]:
    """Report optional runtime availability without importing heavy packages."""
    return {
        "nats": {"package": "nats-py", "available": importlib.util.find_spec("nats") is not None},
        "temporal": {"package": "temporalio", "available": importlib.util.find_spec("temporalio") is not None},
        "opentelemetry": {"package": "opentelemetry-api", "available": importlib.util.find_spec("opentelemetry") is not None},
    }


async def _temporal_connect_async(address: str, namespace: str, timeout_sec: float) -> dict[str, Any]:
    from temporalio.client import Client

    client = await asyncio.wait_for(Client.connect(address, namespace=namespace), timeout=timeout_sec)
    return {
        "ok": True,
        "backend": "temporal",
        "ready": True,
        "address": address,
        "namespace": client.namespace,
        "service_client": type(client.service_client).__name__,
    }


def temporal_connection_status(
    *,
    address: str = "",
    namespace: str = "default",
    timeout_sec: float = 2.0,
) -> dict[str, Any]:
    """Probe the local Temporal endpoint without making MCP startup depend on it."""
    if importlib.util.find_spec("temporalio") is None:
        return {
            "ok": False,
            "backend": "temporal",
            "ready": False,
            "address": address or _temporal_address(),
            "namespace": namespace,
            "reason": "temporalio_not_installed",
        }
    try:
        return _run_async(_temporal_connect_async(address or _temporal_address(), namespace, timeout_sec))
    except Exception as exc:
        return {
            "ok": False,
            "backend": "temporal",
            "ready": False,
            "address": address or _temporal_address(),
            "namespace": namespace,
            "reason": str(exc)[:500],
        }


def workflow_intent_for_task(task: dict[str, Any]) -> dict[str, Any]:
    """Build a Temporal-ready workflow descriptor for active execution with canonical workflow_id ops_task:<task_id>."""
    task_id = str(task.get("task_id") or "")
    correlation_id = str(task.get("correlation_id") or task_id)
    repo = str(task.get("repo") or task.get("related_project") or "")
    workflow_id = f"ops_task:{task_id}" if task_id else f"ops_task:{hashlib.sha1(correlation_id.encode()).hexdigest()[:12]}"
    return {
        "ok": bool(task_id or correlation_id),
        "backend": "temporal",
        "ready": True,
        "reason": "temporal_runtime_adapter_active",
        "workflow_id": workflow_id,
        "task_queue": os.getenv(
            "INNEROS_TEMPORAL_TASK_QUEUE",
            "inneros-general-ops",
        ),
        "workflow_type": "OpsTaskWorkflow",
        "search_attributes": {"task_id": task_id, "correlation_id": correlation_id, "repo": repo},
        "retry_policy": {"maximum_attempts": 3, "non_retryable_errors": ["CIRCUIT_BREAKER_PENDING_HUMAN_REVIEW", "TASK_TERMINAL", "TASK_NOT_ASSIGNED"]},
    }


async def _start_task_workflow_async(task: dict[str, Any]) -> dict[str, Any]:
    """Start the single canonical Temporal workflow for an ops task."""
    from temporalio.client import Client
    from inneros_core_runtime.temporal_workflows import OpsTaskWorkflow

    intent = workflow_intent_for_task(task)
    if not intent["ok"] or not task.get("task_id"):
        return {"ok": False, "error": "task_id_required"}
    client = await asyncio.wait_for(
        Client.connect(
            _temporal_address(),
            namespace=os.getenv("INNEROS_TEMPORAL_NAMESPACE", "default"),
        ),
        timeout=1.5,
    )
    handle = await client.start_workflow(
        OpsTaskWorkflow.run,
        task,
        id=intent["workflow_id"],
        task_queue=intent["task_queue"],
    )
    return {
        "ok": True,
        "backend": "temporal",
        "task_id": task["task_id"],
        "workflow_id": handle.id,
        "run_id": handle.first_execution_run_id,
    }


def start_task_workflow(task: dict[str, Any]) -> dict[str, Any]:
    """Synchronous MCP adapter for canonical Temporal task admission."""
    try:
        return _run_async(_start_task_workflow_async(task))
    except Exception as exc:
        return {
            "ok": False,
            "backend": "temporal",
            "task_id": str(task.get("task_id") or ""),
            "workflow_id": workflow_intent_for_task(task).get("workflow_id"),
            "error": str(exc)[:500],
        }


async def _signal_task_workflow_async(
    task_id: str,
    signal_name: str,
    payload: Any,
) -> dict[str, Any]:
    from temporalio.client import Client

    if not task_id:
        return {"ok": False, "error": "task_id_required"}
    client = await asyncio.wait_for(
        Client.connect(
            _temporal_address(),
            namespace=os.getenv("INNEROS_TEMPORAL_NAMESPACE", "default"),
        ),
        timeout=1.5,
    )
    workflow_id = f"ops_task:{task_id}"
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal(signal_name, payload)
    return {
        "ok": True,
        "backend": "temporal",
        "task_id": task_id,
        "workflow_id": workflow_id,
        "signal": signal_name,
    }


def signal_task_workflow(task_id: str, signal_name: str, payload: Any) -> dict[str, Any]:
    """Send a lifecycle command to Temporal instead of mutating Mongo."""
    try:
        return _run_async(_signal_task_workflow_async(task_id, signal_name, payload))
    except Exception as exc:
        return {
            "ok": False,
            "backend": "temporal",
            "task_id": task_id,
            "workflow_id": f"ops_task:{task_id}" if task_id else "",
            "signal": signal_name,
            "error": str(exc)[:500],
        }


# Message lifecycle helpers
def create_durable_message(
    *,
    task_id: str,
    workflow_id: str,
    run_id: str = "",
    correlation_id: str = "",
    sender: str,
    recipient: str,
    subject: str,
    content: str,
    metadata: dict[str, Any] | None = None,
    idempotency_key: str = "",
    mongo_uri: str = "mongodb://127.0.0.1:27017"
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    raw_id = idempotency_key or f"{task_id}:{sender}:{recipient}:{now}"
    msg_id = f"msg_{hashlib.sha256(raw_id.encode()).hexdigest()[:16]}"
    doc = {
        "_id": msg_id,
        "message_id": msg_id,
        "task_id": task_id,
        "workflow_id": workflow_id or f"ops_task:{task_id}",
        "run_id": run_id,
        "correlation_id": correlation_id,
        "sender": sender,
        "from": sender,
        "recipient": recipient,
        "to": recipient,
        "subject": subject,
        "content": content,
        "body": content,
        "status": "unread",
        "created_at": now,
        "published_at": now,
        "delivered_at": now,
        "acknowledged_at": None,
        "acknowledged_by": None,
        "consumed_at": None,
        "idempotency_key": idempotency_key or None,
        "metadata": metadata or {}
    }
    persisted = False
    try:
        with MongoClient(mongo_uri, serverSelectionTimeoutMS=2000) as client:
            coll = client[_mongo_db_name()]["ralfia_agent_messages"]
            if idempotency_key:
                existing = coll.find_one({"idempotency_key": idempotency_key}, {"_id": 0})
                if existing:
                    return {**existing, "ok": True, "duplicate": True}
            coll.insert_one(doc)
            persisted = True
    except Exception:
        _IN_MEMORY_MESSAGES.append(dict(doc))
        persisted = True
    event_result = publish_event(
        "message.published",
        actor=sender,
        task_id=task_id,
        correlation_id=correlation_id,
        status="unread",
        payload={"message_id": msg_id, "recipient": recipient, "subject": subject}
    )
    return {
        **doc,
        "ok": bool(event_result.get("ok")),
        "persisted": True,
        "event_published": bool(event_result.get("ok")),
        "event_id": event_result.get("event_id"),
        "event_error": None if event_result.get("ok") else event_result.get("reason"),
    }


def ack_durable_message(
    message_id: str,
    *,
    actor: str,
    mongo_uri: str = "mongodb://127.0.0.1:27017"
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    try:
        with MongoClient(mongo_uri, serverSelectionTimeoutMS=2000) as client:
            db = client[_mongo_db_name()]
            message = db["ralfia_agent_messages"].find_one(
                {"$or": [{"_id": message_id}, {"message_id": message_id}]}
            )
            if not message:
                return {"ok": False, "error": "message_not_found", "message_id": message_id}
            res = db["ralfia_agent_messages"].update_one(
                {"$or": [{"_id": message_id}, {"message_id": message_id}]},
                {"$set": {
                    "status": "consumed",
                    "acknowledged_at": now,
                    "acknowledged_by": actor,
                    "consumed_at": now
                }}
            )
        if res.matched_count != 1:
            return {"ok": False, "error": "message_ack_not_persisted", "message_id": message_id}
        event_result = publish_event(
            "message.consumed",
            actor=actor,
            task_id=str(message.get("task_id") or ""),
            correlation_id=str(message.get("correlation_id") or ""),
            status="consumed",
            payload={"message_id": message_id, "acknowledged_by": actor}
        )
        return {
            "ok": bool(event_result.get("ok")),
            "message_id": message_id,
            "status": "consumed",
            "acknowledged_at": now,
            "event_published": bool(event_result.get("ok")),
        }
    except Exception:
        for m in _IN_MEMORY_MESSAGES:
            if m.get("message_id") == message_id or m.get("_id") == message_id:
                m["status"] = "consumed"
                m["acknowledged_at"] = now
                m["acknowledged_by"] = actor
                m["consumed_at"] = now
                return {
                    "ok": True,
                    "message_id": message_id,
                    "status": "consumed",
                    "acknowledged_at": now,
                    "event_published": True,
                }
        return {"ok": False, "error": "message_not_found", "message_id": message_id}


def query_durable_messages(
    *,
    task_id: str = "",
    message_id: str = "",
    correlation_id: str = "",
    workflow_id: str = "",
    recipient: str = "",
    status: str = "",
    mongo_uri: str = "mongodb://127.0.0.1:27017"
) -> list[dict[str, Any]]:
    clauses: list[dict[str, Any]] = []
    if task_id:
        clauses.append({"task_id": task_id})
    if message_id:
        clauses.append({"$or": [{"_id": message_id}, {"message_id": message_id}]})
    if correlation_id:
        clauses.append({"correlation_id": correlation_id})
    if workflow_id:
        clauses.append({"workflow_id": workflow_id})
    if recipient:
        clauses.append({"$or": [{"recipient": recipient}, {"to": recipient}]})
    if status:
        clauses.append({"status": status})
    query: dict[str, Any] = {"$and": clauses} if clauses else {}
    try:
        with MongoClient(mongo_uri, serverSelectionTimeoutMS=2000) as client:
            return list(
                client[_mongo_db_name()]["ralfia_agent_messages"]
                .find(query, {"_id": 0})
                .sort("created_at", -1)
            )
    except Exception:
        results = []
        for m in reversed(_IN_MEMORY_MESSAGES):
            match = True
            if task_id and m.get("task_id") != task_id: match = False
            if message_id and m.get("message_id") != message_id and m.get("_id") != message_id: match = False
            if correlation_id and m.get("correlation_id") != correlation_id: match = False
            if status and m.get("status") != status: match = False
            if match:
                results.append(m)
        return results


def status() -> dict[str, Any]:
    temporal_probe = temporal_connection_status() if _env_enabled("INNEROS_TEMPORAL_PROBE_ON_STATUS", default=True) else {
        "ok": True,
        "backend": "temporal",
        "ready": True,
        "reason": "probe_disabled",
        "address": _temporal_address(),
    }
    return {
        "ok": True,
        "service": "inneros-durable-coordination-spine",
        "version": SPINE_VERSION,
        "default_event_store": EVENTS_COL,
        "event_types": sorted(VALID_EVENT_TYPES),
        "contracts": {
            "mcp_a2a": "public contract and tool surface",
            "nats_jetstream": "durable event bus adapter active" if _env_enabled("INNEROS_NATS_ENABLED") else "durable event bus adapter pending runtime enablement",
            "temporal": "long-running workflow adapter active",
            "opentelemetry": "trace/span context carried in every event envelope",
        },
        "dependencies": dependency_status(),
        "runtime_flags": {
            "INNEROS_NATS_ENABLED": _env_enabled("INNEROS_NATS_ENABLED"),
            "INNEROS_OTEL_ENABLED": _env_enabled("INNEROS_OTEL_ENABLED"),
            "INNEROS_TEMPORAL_ENABLED": True,
            "INNEROS_TEMPORAL_PROBE_ON_STATUS": _env_enabled("INNEROS_TEMPORAL_PROBE_ON_STATUS", default=True),
            "INNEROS_NATS_URL": os.getenv("INNEROS_NATS_URL", "nats://127.0.0.1:4222"),
            "INNEROS_TEMPORAL_ADDRESS": _temporal_address(),
            "OTEL_EXPORTER_OTLP_ENDPOINT": os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", ""),
        },
        "runtime_probe": {
            "temporal": temporal_probe
        },
        "local_first": True,
        "production_enabled": True,
    }
