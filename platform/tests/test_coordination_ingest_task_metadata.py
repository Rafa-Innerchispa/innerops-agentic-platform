from __future__ import annotations

from raphiia_openai import coordination_ingest


def test_task_normalization_preserves_repo_and_execution_metadata(monkeypatch) -> None:
    captured = {}

    def fake_create_agent_message(**kwargs):
        return {
            "ok": True,
            "created": True,
            "message_id": "msg_metadata",
            "correlation_id": kwargs["correlation_id"] or "corr-metadata",
        }

    def fake_create_ops_task(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "task_id": "ops_metadata"}

    class _Collection:
        def update_one(self, *args, **kwargs):
            captured["message_update"] = {"args": args, "kwargs": kwargs}

    class _DB(dict):
        def __getitem__(self, _item):
            return _Collection()

    import raphiia_openai.memory.agent_messages as agent_messages

    monkeypatch.setattr(agent_messages, "create_agent_message", fake_create_agent_message)
    monkeypatch.setattr(coordination_ingest.coordination_live, "create_ops_task", fake_create_ops_task)
    monkeypatch.setattr(coordination_ingest.mongo_store, "get_db", lambda: _DB())

    result = coordination_ingest.ingest_agent_message(
        from_agent="chatgpt",
        target_agent="dev_swarm",
        title="[OPS] HyperLoom finalizer",
        body="- Run bounded local verification\n",
        priority="critical",
        correlation_id="hyperloom-r9700-finalize-20260910",
        message_type="task",
        payload={
            "repo": "Rafa-Innerchispa/hyperloom-r9700-experimental",
            "project_id": "hyperloom-r9700-experimental",
            "base_ref": "main",
            "work_branch": "chatgpt/r9700-finalizer",
            "task_class": "coding",
            "execution_lane": "local_dev_swarm",
            "provider_transport": "local_execution_plane",
            "runtime_profile": "python-tests",
            "execution_policy": "local_first",
            "preferred_provider": "local-amd-5",
            "preferred_model": "qwen",
            "idempotency_key": "hyperloom-r9700-finalize-20260910-v1",
        },
    )

    assert result["normalization"]["ok"] is True
    assert captured["assignee"] == "dev_swarm"
    assert captured["repo"] == "Rafa-Innerchispa/hyperloom-r9700-experimental"
    assert captured["related_project"] == "Rafa-Innerchispa/hyperloom-r9700-experimental"
    assert captured["project_id"] == "hyperloom-r9700-experimental"
    assert captured["execution_lane"] == "local_dev_swarm"
    assert captured["task_class"] == "coding"
    assert captured["work_branch"] == "chatgpt/r9700-finalizer"
    assert captured["idempotency_key"] == "hyperloom-r9700-finalize-20260910-v1"
