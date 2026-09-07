from __future__ import annotations

from raphiia_openai import coordination_ingest


def test_task_normalization_accepts_repo_metadata(monkeypatch) -> None:
    captured = {}

    def fake_create_agent_message(**kwargs):
        return {
            "ok": True,
            "created": True,
            "message_id": "msg_test",
            "correlation_id": kwargs["correlation_id"] or "corr-test",
        }

    def fake_create_ops_task(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "task_id": "ops_test"}

    class _Messages:
        @staticmethod
        def create_agent_message(**kwargs):
            return fake_create_agent_message(**kwargs)

    class _Collection:
        def update_one(self, *args, **kwargs):
            captured["message_update"] = {"args": args, "kwargs": kwargs}

    class _DB(dict):
        def __getitem__(self, item):
            return _Collection()

    monkeypatch.setattr(coordination_ingest.coordination_live, "create_ops_task", fake_create_ops_task)
    monkeypatch.setattr(coordination_ingest.mongo_store, "get_db", lambda: _DB())

    def fake_import(name, *args, **kwargs):
        raise AssertionError(name)

    import raphiia_openai.memory.agent_messages as agent_messages

    monkeypatch.setattr(agent_messages, "create_agent_message", fake_create_agent_message)

    result = coordination_ingest.ingest_agent_message(
        from_agent="chatgpt",
        target_agent="codex",
        title="[OPS] Repair local launch",
        body="- fix launch\n",
        priority="high",
        correlation_id="corr-test",
        message_type="task",
        payload={
            "project_id": "hyperloom-r9700-experimental",
            "repo": "Rafa-Innerchispa/hyperloom-r9700-experimental",
            "base_ref": "main",
            "work_branch": "codex/test",
            "task_class": "coding",
            "execution_lane": "external_repair",
            "provider_transport": "codex",
            "runtime_profile": "python-tests",
            "execution_policy": "local_first",
            "preferred_provider": "local-amd-5",
            "preferred_model": "qwen",
            "idempotency_key": "idem-1",
        },
    )

    assert result["normalization"]["ok"] is True
    assert captured["project_id"] == "hyperloom-r9700-experimental"
    assert captured["repo"] == "Rafa-Innerchispa/hyperloom-r9700-experimental"
    assert captured["related_project"] == "Rafa-Innerchispa/hyperloom-r9700-experimental"
    assert captured["base_ref"] == "main"
    assert captured["work_branch"] == "codex/test"
    assert captured["task_class"] == "coding"
    assert captured["idempotency_key"] == "idem-1"


def test_task_normalization_minimal_body_still_creates_task(monkeypatch) -> None:
    captured = {}

    def fake_create_agent_message(**kwargs):
        return {"ok": True, "created": True, "message_id": "msg_min", "correlation_id": "msg_min"}

    def fake_create_ops_task(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "task_id": "ops_min"}

    import raphiia_openai.memory.agent_messages as agent_messages

    monkeypatch.setattr(agent_messages, "create_agent_message", fake_create_agent_message)
    monkeypatch.setattr(coordination_ingest.coordination_live, "create_ops_task", fake_create_ops_task)
    monkeypatch.setattr(coordination_ingest.mongo_store, "get_db", lambda: {"ralfia_agent_messages": type("C", (), {"update_one": lambda self, *a, **k: None})()})

    result = coordination_ingest.ingest_agent_message(
        from_agent="chatgpt",
        target_agent="codex",
        title="Plain task",
        body="Fix the MCP launch path.",
        message_type="task",
    )

    assert result["normalization"]["ok"] is True
    assert captured["checklist"] == ["Fix the MCP launch path."]
    assert captured["project_id"] is None
    assert captured["repo"] is None
