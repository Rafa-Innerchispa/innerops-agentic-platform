"""Durable coordination spine for MCP/A2A/Dev Swarm lifecycle events.

The spine is intentionally dependency-light: MongoDB remains the default live
store, while NATS JetStream, Temporal and OpenTelemetry are represented as
explicit optional adapters/contracts. This lets InnerOS start emitting a stable
event stream now without making the productive MCP depend on new daemons.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from raphiia_openai import tracking_envelope

EVENTS_COL = "ralfia_coordination_events"
SPINE_VERSION = "0.1.0"
DEFAULT_STREAM = "INNEROS_COORDINATION"
DEFAULT_SUBJECT_PREFIX = "inneros.coordination"
_OTEL_PROVIDER_READY = False

VALID_EVENT_TYPES = frozenset(
    {
        "task.admitted",
        "task.rejected",
        "task.claimed",
        "task.heartbeat",
        "task.started",
        "task.blocked",
        "task.verification_started",
        "task.completed",
        "task.failed",
        "task.cancelled",
        "task.superseded",
        "a2a.dispatched",
        "a2a.status_projected",
        "provider.dispatched",
        "provider.execution_started",
        "provider.evidence_recorded",
        "scheduler.selected",
        "scheduler.skipped",
        "memory.checkpointed",
        "memory.finalized",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(data: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(data).encode("utf-8")).hexdigest()


def _clean_subject(subject: str) -> str:
    parts = [p for p in (subject or "").replace(" ", ".").split(".") if p]
    safe = []
    for part in parts:
        safe.append("".join(ch for ch in part.lower() if ch.isalnum() or ch in "_-"))
    return ".".join(p for p in safe if p) or "inneros.coordination.event"


def dependency_status() -> dict[str, Any]:
    """Report optional runtime availability without importing heavy packages."""
    return {
        "nats": {"package": "nats-py", "available": importlib.util.find_spec("nats") is not None},
        "temporal": {"package": "temporalio", "available": importlib.util.find_spec("temporalio") is not None},
        "opentelemetry": {"package": "opentelemetry-api", "available": importlib.util.find_spec("opentelemetry") is not None},
    }


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
        raise ValueError(f"invalid_coordination_event_type:{event_type}")
    base = dict(envelope or {})
    if traceparent and not base.get("traceparent"):
        base["traceparent"] = traceparent
    if not base:
        base = tracking_envelope.build_envelope(
            original_task_id=task_id,
            correlation_id=correlation_id,
            a2a_task_id=a2a_task_id,
            agent=actor,
            provider=provider,
            model=model,
            repo=repo or "Rafa-Innerchispa/innerops-agentic-platform",
            simulated=(live_mode == "NON-LIVE"),
        )
    else:
        base.setdefault("correlation_id", correlation_id or task_id or a2a_task_id)
        base.setdefault("original_task_id", task_id)
        base.setdefault("a2a_task_id", a2a_task_id)
        base.setdefault("agent", actor)
        base.setdefault("provider", provider)
        base.setdefault("model", model)
        base.setdefault("repo", repo)
        base.setdefault("live_mode", live_mode)
        if not base.get("traceparent"):
            generated = tracking_envelope.build_envelope(correlation_id=str(base.get("correlation_id") or ""))
            base["traceparent"] = generated["traceparent"]
            base["trace_id"] = generated["trace_id"]
            base["span_id"] = generated["span_id"]
    body = {
        "event_type": event_type,
        "event_version": SPINE_VERSION,
        "subject": _clean_subject(f"inneros.{event_type}.{repo or 'platform'}.{task_id or a2a_task_id or 'unbound'}"),
        "actor": actor,
        "task_id": task_id,
        "a2a_task_id": a2a_task_id,
        "correlation_id": str(base.get("correlation_id") or correlation_id or ""),
        "repo": repo or str(base.get("repo") or ""),
        "provider": provider or str(base.get("provider") or ""),
        "model": model or str(base.get("model") or ""),
        "status": status,
        "payload": dict(payload or {}),
        "envelope": base,
        "traceparent": str(base.get("traceparent") or ""),
        "live_mode": str(base.get("live_mode") or live_mode),
        "created_at": _now(),
    }
    body["event_id"] = f"evt_{_sha256(body)[:24]}"
    body["idempotency_key"] = body["event_id"]
    return body


class EventSink(Protocol):
    def publish(self, event: dict[str, Any]) -> dict[str, Any]: ...


def _env_enabled(name: str) -> bool:
    return (os.getenv(name, "") or "").strip().lower() in {"1", "true", "yes", "on"}


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError("async_event_loop_already_running")


def emit_otel_event(event: dict[str, Any]) -> dict[str, Any]:
    if not _env_enabled("INNEROS_OTEL_ENABLED"):
        return {"ok": False, "backend": "opentelemetry", "ready": False, "reason": "otel_disabled"}
    try:
        from opentelemetry import trace
        provider = _ensure_otel_provider()

        tracer = trace.get_tracer("inneros.coordination", SPINE_VERSION)
        with tracer.start_as_current_span(str(event.get("event_type") or "inneros.event")) as span:
            attrs = {
                "inneros.event_id": str(event.get("event_id") or ""),
                "inneros.event_type": str(event.get("event_type") or ""),
                "inneros.task_id": str(event.get("task_id") or ""),
                "inneros.correlation_id": str(event.get("correlation_id") or ""),
                "inneros.repo": str(event.get("repo") or ""),
                "inneros.actor": str(event.get("actor") or ""),
                "inneros.status": str(event.get("status") or ""),
            }
            for key, value in attrs.items():
                span.set_attribute(key, value)
        flushed = None
        if provider is not None and hasattr(provider, "force_flush"):
            flushed = bool(provider.force_flush(timeout_millis=1500))
        return {
            "ok": True,
            "backend": "opentelemetry",
            "event_id": event.get("event_id"),
            "exporter": "otlp" if provider is not None else "api_noop",
            "force_flushed": flushed,
        }
    except Exception as exc:
        return {"ok": False, "backend": "opentelemetry", "ready": False, "reason": str(exc)[:500]}


def _ensure_otel_provider() -> Any | None:
    """Configure OTLP export once when the SDK/exporter packages are present."""
    global _OTEL_PROVIDER_READY
    if _OTEL_PROVIDER_READY:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        return provider if hasattr(provider, "force_flush") else None
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or ""
    if not endpoint:
        return None
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        current = trace.get_tracer_provider()
        if hasattr(current, "force_flush"):
            _OTEL_PROVIDER_READY = True
            return current
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            trace_endpoint = endpoint.rstrip("/")
            if not trace_endpoint.endswith("/v1/traces"):
                trace_endpoint = f"{trace_endpoint}/v1/traces"
            exporter = OTLPSpanExporter(endpoint=trace_endpoint)
        else:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=endpoint)
        provider = TracerProvider(resource=Resource.create({"service.name": "inneros-coordination-spine"}))
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _OTEL_PROVIDER_READY = True
        return provider
    except Exception:
        return None


@dataclass
class MemoryEventSink:
    events: list[dict[str, Any]]

    def publish(self, event: dict[str, Any]) -> dict[str, Any]:
        self.events.append(dict(event))
        return {"ok": True, "backend": "memory", "event_id": event["event_id"], "stored": True}


class MongoEventSink:
    def publish(self, event: dict[str, Any]) -> dict[str, Any]:
        from raphiia_openai import mongo_store

        mongo_store.get_db()[EVENTS_COL].update_one(
            {"event_id": event["event_id"]},
            {"$setOnInsert": dict(event)},
            upsert=True,
        )
        return {"ok": True, "backend": "mongo", "event_id": event["event_id"], "stored": True}


@dataclass
class NatsJetStreamSink:
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
class JetStreamIntentSink:
    stream: str = DEFAULT_STREAM

    def publish(self, event: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": False,
            "backend": "nats_jetstream",
            "ready": False,
            "stream": self.stream,
            "subject": _clean_subject(f"{DEFAULT_SUBJECT_PREFIX}.{event['subject'].removeprefix('inneros.')}") if event.get("subject") else DEFAULT_SUBJECT_PREFIX,
            "event_id": event["event_id"],
            "reason": "nats_runtime_adapter_not_enabled",
        }


@dataclass
class CompositeEventSink:
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
    """Build a Temporal-ready workflow descriptor without starting Temporal."""
    task_id = str(task.get("task_id") or "")
    correlation_id = str(task.get("correlation_id") or task_id)
    repo = str(task.get("repo") or task.get("related_project") or "")
    workflow_id = f"inneros-task-{task_id or hashlib.sha1(correlation_id.encode()).hexdigest()[:12]}"
    return {
        "ok": bool(task_id or correlation_id),
        "backend": "temporal",
        "ready": False,
        "reason": "temporal_runtime_adapter_not_enabled",
        "workflow_id": workflow_id,
        "task_queue": "inneros-control-plane",
        "workflow_type": "InnerOSTaskLifecycleWorkflow",
        "search_attributes": {"task_id": task_id, "correlation_id": correlation_id, "repo": repo},
        "retry_policy": {"maximum_attempts": 3, "non_retryable_errors": ["policy_denied", "unsafe_operation"]},
    }


def status() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "inneros-durable-coordination-spine",
        "version": SPINE_VERSION,
        "default_event_store": EVENTS_COL,
        "event_types": sorted(VALID_EVENT_TYPES),
        "contracts": {
            "mcp_a2a": "public contract and tool surface",
            "nats_jetstream": "durable event bus adapter pending runtime enablement",
            "temporal": "long-running workflow adapter pending runtime enablement",
            "opentelemetry": "trace/span context carried in every event envelope",
        },
        "dependencies": dependency_status(),
        "runtime_flags": {
            "INNEROS_NATS_ENABLED": _env_enabled("INNEROS_NATS_ENABLED"),
            "INNEROS_OTEL_ENABLED": _env_enabled("INNEROS_OTEL_ENABLED"),
            "INNEROS_TEMPORAL_PROBE_ON_STATUS": _env_enabled("INNEROS_TEMPORAL_PROBE_ON_STATUS"),
            "INNEROS_NATS_URL": os.getenv("INNEROS_NATS_URL", "nats://127.0.0.1:4222"),
            "INNEROS_TEMPORAL_ADDRESS": _temporal_address(),
            "OTEL_EXPORTER_OTLP_ENDPOINT": os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", ""),
        },
        "runtime_probe": {
            "temporal": temporal_connection_status() if _env_enabled("INNEROS_TEMPORAL_PROBE_ON_STATUS") else {
                "ok": False,
                "backend": "temporal",
                "ready": False,
                "reason": "probe_disabled",
                "address": _temporal_address(),
            }
        },
        "local_first": True,
        "production_enabled": False,
    }
