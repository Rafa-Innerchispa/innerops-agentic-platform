from __future__ import annotations

from unittest import mock

from inneros_core_runtime import judge_telemetry, judge_workflows, mcp_profiles
from inneros_core_runtime.mcp_catalog import tool_catalog


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_args):
        return self

    def limit(self, n):
        return self.rows[:n]


class FakeCollection:
    def __init__(self):
        self.docs = []

    def insert_one(self, doc):
        self.docs.append(dict(doc))
        return mock.Mock(inserted_id="fake")

    def update_one(self, query, update, upsert=False):
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                doc.update(update.get("$set", {}))
                if "$inc" in update:
                    for k, v in update["$inc"].items():
                        doc[k] = doc.get(k, 0) + v
                return mock.Mock(modified_count=1, upserted_id=None)
        if upsert:
            new = dict(query)
            new.update(update.get("$setOnInsert", {}))
            new.update(update.get("$set", {}))
            if "$inc" in update:
                for k, v in update["$inc"].items():
                    new[k] = new.get(k, 0) + v
            self.docs.append(new)
            return mock.Mock(modified_count=0, upserted_id="fake")
        return mock.Mock(modified_count=0, upserted_id=None)

    def find_one(self, query, projection=None):
        for doc in reversed(self.docs):
            if all(doc.get(k) == v for k, v in query.items()):
                return {k: v for k, v in doc.items() if k != "_id"}
        return None

    def find(self, query, projection=None):
        rows = []
        for doc in reversed(self.docs):
            if all(doc.get(k) == v for k, v in query.items()):
                rows.append({k: v for k, v in doc.items() if k != "_id"})
        return FakeCursor(rows)


class FakeDb(dict):
    def __getitem__(self, key):
        if key not in self:
            self[key] = FakeCollection()
        return dict.__getitem__(self, key)


def test_trace_rejects_simulated_or_degraded_pass() -> None:
    assert judge_telemetry.record_trace_event(
        {"correlation_id": "c1", "status": "PASS", "verified": True, "simulated": True}
    )["error"] == "simulated_or_degraded_cannot_be_verified"
    assert judge_telemetry.record_trace_event(
        {"correlation_id": "c1", "status": "PASS", "verified": False}
    )["error"] == "pass_requires_verified_true"


def test_workflow_asks_only_missing_fields_and_blocks_execution() -> None:
    db = FakeDb()
    with (
        mock.patch.object(judge_workflows, "_db", return_value=db),
        mock.patch.object(judge_telemetry, "_db", return_value=db),
    ):
        started = judge_workflows.start_workflow(
            "Hazme plan de emergencia ISKCON domingo",
            correlation_id="corr-emergency",
        )
        assert started["ok"] is True
        assert started["status"] == "awaiting_input"
        assert "scenario" not in started["missing_fields"]
        assert "event_date" not in started["missing_fields"]
        blocked = judge_workflows.execute_workflow(started["workflow_id"])
        assert blocked["ok"] is False
        assert blocked["error"] == "workflow_requirements_incomplete"


def test_workflow_executes_complete_emergency_plan_and_preserves_correlation() -> None:
    db = FakeDb()
    with (
        mock.patch.object(judge_workflows, "_db", return_value=db),
        mock.patch.object(judge_telemetry, "_db", return_value=db),
        mock.patch("raphiia_openai.judge_telemetry._db", return_value=db),
        mock.patch("raphiia_openai.module_contract.route_module_action", return_value={"ok": True, "artifact": {"artifact_id": "art1"}}),
    ):
        started = judge_workflows.start_workflow(
            "Hazme plan de emergencia ISKCON domingo",
            fields={"location": "ISKCON Guayaquil", "responsible_contact": "Rafael"},
            correlation_id="corr-emergency-complete",
        )
        completed = judge_workflows.continue_workflow(started["workflow_id"], execute=True)
        assert completed["ok"] is True
        assert completed["status"] == "executing"
        assert completed["execution"]["artifact_id"] == "art1"
        events = judge_telemetry.list_trace_events(correlation_id="corr-emergency-complete", limit=20)
        assert events["count"] >= 2
        assert {e["correlation_id"] for e in events["events"]} == {"corr-emergency-complete"}
        assert any(e.get("status") == "PASS" and e.get("verified") is True for e in events["events"])


def test_judge_profile_and_catalog_expose_compact_tools() -> None:
    profile = mcp_profiles.PROFILES["judge_console"]
    assert profile["model_minimum"] == "small"
    assert profile["max_tools"] <= 24
    for name in (
        "judge_workflow_start",
        "judge_workflow_continue",
        "judge_trace_current",
        "judge_trace_kpis",
        "judge_resource_telemetry",
        "judge_safe_trigger",
    ):
        assert name in profile["tools"]
        assert name in tool_catalog.ALL_MCP_TOOL_NAMES
        assert tool_catalog.describe_tool(name)["ok"] is True
