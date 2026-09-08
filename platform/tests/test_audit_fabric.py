from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from inneros_core_runtime import audit_fabric, durable_coordination_spine, mcp_profiles, resource_fabric


class _Cursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def __iter__(self):
        return iter(self.rows)

    def sort(self, *_args):
        return self

    def limit(self, n):
        self.rows = self.rows[:n]
        return self


class _Collection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find(self, query, projection=None):
        rows = []
        for row in self.rows:
            if _matches(row, query):
                item = dict(row)
                item.pop("_id", None)
                rows.append(item)
        return _Cursor(rows)

    def find_one(self, query, projection=None):
        for row in self.rows:
            if _matches(row, query):
                item = dict(row)
                item.pop("_id", None)
                return item
        return None

    def update_one(self, query, update, upsert=False):
        row = self.find_one(query) or {}
        row.update(update.get("$setOnInsert") or {})
        row.update(update.get("$set") or {})
        self.rows.append(row)


class _DB:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        self.collections.setdefault(name, _Collection())
        return self.collections[name]

    def __setitem__(self, name, value):
        self.collections[name] = value


def _dotted(row, key):
    value = row
    for part in key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _matches(row, query):
    for key, expected in query.items():
        value = _dotted(row, key)
        if isinstance(expected, dict) and "$regex" in expected:
            import re

            if not re.search(expected["$regex"], str(value or "")):
                return False
        elif isinstance(value, list):
            if expected not in value:
                return False
        elif value != expected:
            return False
    return True


class AuditFabricTests(unittest.TestCase):
    def test_emit_audit_hook_dry_run_builds_tracking_envelope_and_htr(self):
        result = audit_fabric.emit_audit_hook(
            "quality",
            actor="chatgpt",
            task_id="ops_quality",
            correlation_id="corr-quality",
            tenant_id="tenant-demo",
            workflow_id="wf-service",
            status="pass",
            productivity={
                "task_key": "wf-service",
                "human_baseline_minutes": 60,
                "assisted_minutes": 15,
                "rework_minutes": 5,
                "measurement_class": "measured",
                "verified": True,
                "measurement_source": "task timer",
            },
            decision_evidence={"decision_id": "decision-1"},
            evidence_refs=[{"kind": "forensic_bundle", "sha256": "abc"}],
            forensic_bundle_ref="bundle://corr-quality",
            dry_run=True,
        )

        self.assertTrue(result["ok"])
        event = result["event"]
        self.assertEqual(event["event_type"], "audit.quality")
        self.assertEqual(event["correlation_id"], "corr-quality")
        self.assertEqual(event["payload"]["tenant_id"], "tenant-demo")
        self.assertEqual(event["payload"]["htr_record"]["measurement_mode"], "MEASURED")
        self.assertEqual(event["payload"]["htr_record"]["returned_human_minutes"], 40.0)
        self.assertIn("traceparent", event["envelope"])

    def test_estimated_htr_is_explicit_when_not_verified(self):
        htr = audit_fabric.htr_record_from_productivity(
            {
                "task_key": "estimate",
                "human_baseline_minutes": 30,
                "assisted_minutes": 12,
                "measurement_class": "measured",
                "verified": False,
            }
        )

        self.assertEqual(htr["measurement_mode"], "ESTIMATED")
        self.assertEqual(htr["estimate_reason"], "not verified as measured")
        self.assertEqual(htr["quality_gate"]["gate"], "estimated")

    def test_resource_route_emits_routing_evidence_without_blocking_selection(self):
        db = _DB()
        db[resource_fabric.COL_MODEL_REGISTRY].rows.append(
            {
                "model_provider": "local-amd",
                "provider_id": "local-amd-5",
                "task_classes": ["coding"],
                "priority": 1,
                "cost_policy": "local_first",
            }
        )
        db[resource_fabric.COL_PROVIDERS].rows.append(
            {"provider_id": "local-amd-5", "label": "Local AMD .5", "kind": "local_node"}
        )
        with patch.object(resource_fabric.mongo_store, "get_db", return_value=db):
            result = resource_fabric.route_resource_request(
                "innerops-service-ops",
                "coding",
                correlation_id="corr-route",
                tenant_id="tenant-demo",
                workflow_id="wf-route",
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["audit"]["ok"])
        self.assertEqual(result["audit"]["event"]["event_type"], "audit.route")
        routing = result["audit"]["event"]["payload"]["routing_evidence"]
        self.assertEqual(routing["provider_id"], "local-amd-5")
        self.assertEqual(routing["local_cloud"], "local")

    def test_query_audit_events_is_read_only_and_filters_tenant(self):
        rows = [
            {"event_type": "audit.start", "correlation_id": "corr-1", "payload": {"tenant_id": "a", "workflow_id": "wf"}},
            {"event_type": "audit.result", "correlation_id": "corr-2", "payload": {"tenant_id": "b", "workflow_id": "wf"}},
            {"event_type": "task.completed", "correlation_id": "corr-1", "payload": {"tenant_id": "a"}},
        ]
        db = _DB()
        db[durable_coordination_spine.EVENTS_COL] = _Collection(rows)
        with patch("raphiia_openai.mongo_store.get_db", return_value=db):
            result = audit_fabric.list_audit_events(tenant_id="a")

        self.assertTrue(result["ok"])
        self.assertTrue(result["read_only"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["events"][0]["event_type"], "audit.start")

    def test_audit_event_types_are_native_spine_events(self):
        event = durable_coordination_spine.build_event("audit.start", actor="codex", correlation_id="corr")

        self.assertEqual(event["event_type"], "audit.start")
        self.assertEqual(event["correlation_id"], "corr")

    def test_small_compact_profiles_are_not_expanded_by_audit_fabric_tools(self):
        audit_tools = {"audit_fabric_emit_hook", "audit_fabric_query_events", "audit_fabric_status"}
        compact_profiles = {
            name: profile
            for name, profile in mcp_profiles.PROFILES.items()
            if profile.get("model_minimum") == "small" and int(profile.get("max_tools") or 0) <= 18
        }

        self.assertTrue(compact_profiles)
        for name, profile in compact_profiles.items():
            self.assertTrue(audit_tools.isdisjoint(set(profile.get("tools") or [])), name)


if __name__ == "__main__":
    unittest.main()
