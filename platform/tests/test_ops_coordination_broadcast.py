from unittest.mock import patch

from inneros_core_runtime import ops_coordination_broadcast as ocb


def test_fanout_created_sends_assignee_and_observers():
    task = {
        "task_id": "ops_abc123",
        "correlation_id": "corr-1",
        "title": "Smoke",
        "assignee": "antigravity",
        "status": "queued",
        "preferred_provider": "antigravity",
    }
    captured: list[dict] = []

    def _fake_create(**kwargs):
        captured.append(kwargs)
        return {"ok": True, "message_id": f"msg_{kwargs['recipient']}", "duplicate": False}

    with patch.object(ocb, "resolve_execution_binding", return_value={"runner": "antigravity_headless", "allowed": True}), patch(
        "inneros_core_runtime.durable_coordination_spine.create_durable_message",
        side_effect=_fake_create,
    ):
        out = ocb.fanout_ops_phase(task, phase="created", actor="chatgpt")

    assert out["ok"] is True
    recipients = {row["recipient"] for row in captured}
    assert recipients == {"antigravity", "chatgpt", "cursor"}
    assert all(row.get("metadata", {}).get("ops_coordination") for row in captured)


def test_format_includes_external_spend_gate():
    task = {
        "task_id": "ops_x",
        "assignee": "antigravity",
        "title": "t",
        "status": "queued",
    }
    with patch.object(ocb, "resolve_execution_binding", return_value={"runner": "antigravity_headless", "allowed": True}), patch.object(
        ocb,
        "requires_external_owner_authorization",
        return_value=True,
    ):
        body = ocb.format_ops_report(task, phase="created")
    assert "external_spend" in body
    assert "wait_owner_authorization" in body