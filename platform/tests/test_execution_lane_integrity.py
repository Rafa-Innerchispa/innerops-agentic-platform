from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

PLATFORM = Path(__file__).resolve().parents[1]
PLATFORM_TEXT = str(PLATFORM)
sys.path[:] = [item for item in sys.path if item != PLATFORM_TEXT]
sys.path.insert(0, PLATFORM_TEXT)

for prefix in ("raphiia_openai", "inneros_core_runtime"):
    for module_name in [name for name in sys.modules if name == prefix or name.startswith(prefix + ".")]:
        sys.modules.pop(module_name, None)

from inneros_core_runtime import coordination_live
from inneros_core_runtime import dev_swarm_scheduler as scheduler
from inneros_core_runtime import ide_task_bridge
from inneros_core_runtime import task_envelope


def _registry_result(project_id: str, repo: str):
    return {
        "ok": True,
        "node": "primary",
        "project_path": f"/home/rlopez/projects/{project_id}",
        "project": {"project_id": project_id, "repo": repo},
    }


def _local_task(task_id: str = "ops_alpaca"):
    return {
        "task_id": task_id,
        "status": "proposed",
        "assignee": "chatgpt",
        "priority": "p0",
        "project_id": "inneros-alpha-alpaca",
        "repo": "Rafa-Innerchispa/inneros-alpha-alpaca",
        "base_ref": "main",
        "task_class": "coding",
        "execution_lane": "local_dev_swarm",
        "provider_transport": "local_vllm",
        "correlation_id": "alpaca-envelope-regression",
        "write_capable": True,
    }


def test_scheduler_import_is_from_current_worktree():
    assert Path(scheduler.__file__).resolve().is_relative_to(PLATFORM)
    assert Path(coordination_live.__file__).resolve().is_relative_to(PLATFORM)
    assert Path(ide_task_bridge.__file__).resolve().is_relative_to(PLATFORM)


def test_cursor_task_is_rejected_before_repo_policy_or_worktree():
    task = {
        **_local_task("ops_36fc23d6155b"),
        "assignee": "cursor",
        "execution_lane": "cursor",
        "provider_transport": "ide_inbox",
    }
    with mock.patch.object(scheduler.local_execution_plane, "repo_policy_status") as policy:
        ok, reason, repo = scheduler._eligible_reason(task)
    assert ok is False
    assert reason == "execution_lane_not_local_dev_swarm"
    assert repo == "Rafa-Innerchispa/inneros-alpha-alpaca"
    policy.assert_not_called()


def test_codex_task_is_rejected_before_repo_policy_or_worktree():
    task = {
        **_local_task("ops_2bb28a5e80bf"),
        "assignee": "codex",
        "execution_lane": "codex",
        "provider_transport": "external_repair",
    }
    with mock.patch.object(scheduler.local_execution_plane, "repo_policy_status") as policy:
        ok, reason, _repo = scheduler._eligible_reason(task)
    assert ok is False
    assert reason == "execution_lane_not_local_dev_swarm"
    policy.assert_not_called()


def test_local_alpaca_task_uses_exact_registry_repo():
    task = _local_task()
    with mock.patch.object(task_envelope.prr, "resolve_project", return_value=_registry_result("inneros-alpha-alpaca", "Rafa-Innerchispa/inneros-alpha-alpaca")), \
        mock.patch.object(scheduler.local_execution_plane, "repo_policy_status", return_value={"ok": True, "policy": {"write_scope": "worktree"}}):
        ok, reason, repo = scheduler._eligible_reason(task)
    assert ok is True
    assert reason == "eligible"
    assert repo == "Rafa-Innerchispa/inneros-alpha-alpaca"


def test_missing_structured_binding_is_not_inferred_from_title():
    task = {
        "task_id": "ops_missing_binding",
        "status": "proposed",
        "assignee": "dev_swarm",
        "execution_lane": "local_dev_swarm",
        "provider_transport": "local_vllm",
        "base_ref": "main",
        "task_class": "coding",
        "correlation_id": "missing-binding-regression",
        "title": "Repair InnerOS in Rafa-Innerchispa/innerops-agentic-platform",
        "checklist": ["Write platform runtime files"],
    }
    with mock.patch.object(scheduler.local_execution_plane, "repo_policy_status") as policy:
        ok, reason, repo = scheduler._eligible_reason(task)
    assert ok is False
    assert reason == "task_envelope_missing_required_fields"
    assert repo is None
    policy.assert_not_called()


def test_direct_fanout_cannot_claim_external_lane():
    task = {
        **_local_task("ops_cursor_direct"),
        "execution_lane": "cursor",
        "provider_transport": "ide_inbox",
    }
    with mock.patch.object(scheduler, "_task_doc", return_value=task), \
        mock.patch.object(scheduler, "_fanout_execute_one_without_envelope_gate") as old_executor:
        result = scheduler._fanout_execute_one("Rafa-Innerchispa/inneros-alpha-alpaca", "ops_cursor_direct")
    assert result["ok"] is False
    assert result["zero_worktree_created"] is True
    assert result["ownership_claimed"] is False
    old_executor.assert_not_called()


def test_direct_fanout_rejects_repo_argument_mismatch_before_old_executor():
    task = _local_task("ops_repo_mismatch")
    with mock.patch.object(task_envelope.prr, "resolve_project", return_value=_registry_result("inneros-alpha-alpaca", "Rafa-Innerchispa/inneros-alpha-alpaca")), \
        mock.patch.object(scheduler, "_task_doc", return_value=task), \
        mock.patch.object(scheduler, "_fanout_execute_one_without_envelope_gate") as old_executor:
        result = scheduler._fanout_execute_one("Rafa-Innerchispa/innerops-agentic-platform", "ops_repo_mismatch")
    assert result["ok"] is False
    assert result["error"] == "repo_argument_binding_mismatch"
    assert result["zero_worktree_created"] is True
    old_executor.assert_not_called()


def test_new_tasks_do_not_infer_base_ref_from_checklist():
    task = {
        **_local_task("ops_base_ref"),
        "base_ref": "develop/post-hackathon-20260901",
        "checklist": ["please use branch totally-wrong-branch-from-prose"],
    }
    assert scheduler._task_base_ref(task) == "develop/post-hackathon-20260901"
    task.pop("base_ref")
    assert scheduler._task_base_ref(task) == ""


class _Collection:
    def __init__(self, doc: dict):
        self.doc = dict(doc)

    def find_one(self, query, projection=None):
        return dict(self.doc) if self.doc.get("task_id") == query.get("task_id") else None

    def update_one(self, query, update):
        if self.doc.get("task_id") == query.get("task_id"):
            self.doc.update(dict(update.get("$set") or {}))
        return type("Result", (), {"modified_count": 1})()


class _DB:
    def __init__(self, doc: dict):
        self.collection = _Collection(doc)

    def __getitem__(self, name: str):
        assert name == coordination_live.OPS_TASKS_COL
        return self.collection


def test_bind_task_envelope_persists_verified_fields():
    doc = {"task_id": "ops_bind", "correlation_id": "bind-corr", "status": "proposed"}
    db = _DB(doc)
    with mock.patch.object(coordination_live.mongo_store, "get_db", return_value=db), \
        mock.patch.object(task_envelope.prr, "resolve_project", return_value=_registry_result("inneros-alpha-alpaca", "Rafa-Innerchispa/inneros-alpha-alpaca")):
        result = coordination_live.bind_task_envelope(
            "ops_bind",
            repo="Rafa-Innerchispa/inneros-alpha-alpaca",
            base_ref="main",
            execution_lane="local_dev_swarm",
            provider_transport="local_vllm",
            correlation_id="bind-corr",
        )
    assert result["ok"] is True
    assert db.collection.doc["task_binding_status"] == "verified"
    assert db.collection.doc["project_id"] == "inneros-alpha-alpaca"
    assert db.collection.doc["repo"] == "Rafa-Innerchispa/inneros-alpha-alpaca"
    assert db.collection.doc["execution_lane"] == "local_dev_swarm"


class _DispatchStore:
    def __init__(self):
        self.rows = {}

    def get_by_key(self, key):
        return None

    def get(self, dispatch_id):
        return self.rows.get(dispatch_id)

    def put(self, record):
        self.rows[record["dispatch_id"]] = dict(record)


def test_ide_dispatch_persists_matching_execution_lane(monkeypatch):
    store = _DispatchStore()

    def fake_legacy(**kwargs):
        record = {
            "ok": True,
            "dispatch_id": "ide_test",
            "idempotency_key": "idem",
            "ide": "cursor",
            "ops_task_id": "ops_cursor",
            "correlation_id": "cursor-corr",
            "repo": "Rafa-Innerchispa/inneros-webmcp",
            "branch": "main",
            "transport": "ide_inbox",
            "execution_state": "queued",
        }
        store.put(record)
        return dict(record)

    monkeypatch.setattr(ide_task_bridge, "_dispatch_task_without_envelope", fake_legacy)
    monkeypatch.setattr(
        coordination_live,
        "bind_task_envelope",
        lambda task_id, **kwargs: {
            "ok": True,
            "binding_status": "verified",
            "envelope": {
                "binding_status": "verified",
                "project_id": "inneros-webmcp",
                "repo": "Rafa-Innerchispa/inneros-webmcp",
                "base_ref": "main",
                "execution_lane": "cursor",
                "provider_transport": "ide_inbox",
            },
        },
    )
    result = ide_task_bridge.dispatch_task(
        ide="cursor",
        title="test",
        body="test body",
        repo="Rafa-Innerchispa/inneros-webmcp",
        branch="main",
        store=store,
    )
    assert result["ok"] is True
    assert result["executable"] is True
    assert result["execution_lane"] == "cursor"
    assert store.rows["ide_test"]["task_binding_status"] == "verified"


def test_ide_claim_fails_when_binding_is_not_verified():
    store = _DispatchStore()
    store.put({
        "dispatch_id": "ide_blocked",
        "ide": "cursor",
        "execution_state": "queued",
        "task_binding_status": "needs_project_binding",
        "execution_lane": "cursor",
    })
    with mock.patch.object(ide_task_bridge, "_claim_task_without_envelope_gate") as legacy_claim:
        result = ide_task_bridge.claim_task("ide_blocked", "cursor", store=store)
    assert result["ok"] is False
    assert result["error"] == "task_binding_not_verified"
    legacy_claim.assert_not_called()
