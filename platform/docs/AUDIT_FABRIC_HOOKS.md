# InnerOS Audit Fabric Hooks

Status: platform integration contract for `ops_2920faf0624a`.

## What Is Live In This Branch

- `audit_fabric_status()` reports the universal Audit Fabric contract and backend readiness.
- `audit_fabric_emit_hook(...)` emits governed audit events for `start`, `route`, `approval`, `action`, `result` and `quality`.
- `audit_fabric_query_events(...)` is read-only and filters audit events by `correlation_id`, `tenant_id` or `workflow_id`.
- `resource_fabric_route(...)` now accepts `correlation_id`, `tenant_id`, `workflow_id` and `emit_audit`; it attaches `RoutingEvidence` without changing the selected provider contract.

## What Is Reused

- `TrackingEnvelope` remains the canonical correlation/trace envelope.
- `Resource Fabric` remains the routing authority.
- `durable_coordination_spine` remains the event sink abstraction for Mongo, optional NATS JetStream and optional OpenTelemetry.
- Temporal remains contract/status only until a workflow has a real recovery benefit.
- Forensic bundle ownership remains in `Rafa-Innerchispa/inneros-forensic-replay`; Platform stores `forensic_bundle_ref` and evidence refs instead of copying raw payloads.

## Event Shape

Each hook publishes a native durable event type:

- `audit.start`
- `audit.route`
- `audit.approval`
- `audit.action`
- `audit.result`
- `audit.quality`

The payload includes:

- `audit_fabric_version`
- `stage`
- `tenant_id`
- `workflow_id`
- `evidence_level` from 0 to 3
- `routing_evidence`
- `htr_record`
- `decision_evidence`
- `evidence_refs`
- `forensic_bundle_ref`
- `approval`, `action`, `result`, `quality`

## HTR Truth Boundary

Productivity telemetry can be converted to `inneros.htr_record.v1`:

- measured + verified -> `MEASURED`
- everything else -> `ESTIMATED`
- measured HTR must carry a source
- estimated HTR carries an estimate reason
- negative returned time is surfaced as `negative_return`

## Safety

- Query tool is read-only.
- Emit tool defaults to `dry_run=True`.
- Compact MCP profiles are not expanded.
- No tenant id from a frontend should be trusted without server-side authorization in the calling workflow.
- Audit write failure must not break the underlying business action; callers should preserve the `audit.ok` field and surface failures in quality gates.

## Example

```python
from raphiia_openai import audit_fabric

result = audit_fabric.emit_audit_hook(
    "quality",
    actor="chatgpt",
    task_id="ops_demo",
    correlation_id="corr_demo",
    tenant_id="demo-tenant",
    workflow_id="service-workflow",
    productivity={
        "task_key": "service-workflow",
        "human_baseline_minutes": 60,
        "assisted_minutes": 12,
        "measurement_class": "measured",
        "verified": True,
        "measurement_source": "task timer",
    },
    forensic_bundle_ref="bundle://corr_demo",
    dry_run=True,
)
```

## Connected / Contract-Only Matrix

- CONNECTED: TrackingEnvelope, Resource Fabric route hook, Mongo-backed durable coordination spine, read-only query surface, HTR mapping.
- CONTRACT-ONLY: Forensic Bundle refs from `inneros-forensic-replay`, Temporal workflow intent, Parquet/DuckDB heavy evidence storage.
- OPTIONAL RUNTIME: NATS JetStream and OpenTelemetry activate only when their environment flags/dependencies are present.
