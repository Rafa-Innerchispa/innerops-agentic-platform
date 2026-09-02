from __future__ import annotations

from unittest import mock

from raphiia_openai import coordination_live
from raphiia_openai import dev_swarm_scheduler as scheduler
from raphiia_openai import execution_policy
from raphiia_openai import local_execution_plane as lep
from raphiia_openai import resource_fabric


def test_dev_swarm_is_canonical_assignee_regression() -> None:
    assert "dev_swarm" in coordination_live.ASSIGNEES
    assert "dev_swarm" in scheduler.ALLOWED_ASSIGNEES


def test_local_first_contract_prefers_amd_qwen3_coder() -> None:
    contract = execution_policy.task_contract(task_class="coding")
    assert contract["execution_policy"] == "local_first"
    assert contract["local_first_required"] is True
    assert contract["preferred_provider"] == "local-amd-5"
    assert "Qwen3-Coder" in contract["preferred_model"]


def test_external_paid_execution_blocked_without_reason_and_approval() -> None:
    decision = execution_policy.external_execution_decision(task_class="coding", local_available=True)
    assert decision["ok"] is False
    assert decision["decision"] == "blocked_local_capable"


def test_explicit_owner_override_allows_external_route() -> None:
    decision = execution_policy.external_execution_decision(
        task_class="coding",
        local_available=True,
        fallback_reason="owner_override",
        approval_id="owner-approved-fixture",
        owner_override=True,
    )
    assert decision["ok"] is True
    assert decision["decision"] == "allowed_by_owner_override"


def test_future_provider_obeys_reason_and_approval_gate() -> None:
    blocked = execution_policy.external_execution_decision(
        task_class="future_provider_eval",
        local_available=False,
        fallback_reason="new_vendor_trial",
        approval_id="owner-approved-fixture",
    )
    assert blocked["ok"] is False
    assert blocked["decision"] == "fallback_reason_not_allowed"
    allowed = execution_policy.external_execution_decision(
        task_class="future_provider_eval",
        local_available=False,
        fallback_reason="capability_failure",
        approval_id="owner-approved-fixture",
    )
    assert allowed["ok"] is True


def test_scheduler_capacity_free_p0_eligible_selects_worker() -> None:
    task = {
        "task_id": "ops_local_first_fixture",
        "status": "proposed",
        "assignee": "dev_swarm",
        "priority": "p0",
        "repo": "Rafa-Innerchispa/innerops-agentic-platform",
        "title": "Repair platform scheduler",
        "checklist": ["Edit platform runtime and run tests"],
    }
    with mock.patch.object(scheduler, "_db"), \
        mock.patch.object(scheduler, "reconcile_capacity_state", return_value={"ok": True}), \
        mock.patch.object(scheduler, "_state", return_value={"enabled": True, "max_concurrent": 4}), \
        mock.patch.object(scheduler, "capacity_status", return_value={"ok": True, "recommendation": {"recommended_concurrency_total": 4}}), \
        mock.patch.object(scheduler, "_load_scheduler_candidates", return_value=[task]), \
        mock.patch.object(scheduler.local_execution_plane, "repo_policy_status", return_value={"ok": True, "write_scope": "worktree"}):
        db = scheduler._db.return_value
        db.__getitem__.return_value.count_documents.return_value = 0
        result = scheduler.scheduler_tick(limit=1, dry_run=True)
    assert result["ok"] is True
    assert result["available"] == 4
    assert len(result["selected"]) == 1
    assert result["selected"][0]["task_id"] == "ops_local_first_fixture"
    assert result["selected"][0]["preferred_provider"] == "local-amd-5"


def test_related_project_canonical_repo_wins_over_generic_dev_swarm_text() -> None:
    task = {
        "task_id": "ops_alpaca_fixture",
        "status": "proposed",
        "assignee": "dev_swarm",
        "priority": "p0",
        "related_project": "Rafa-Innerchispa/inneros-alpha-alpaca",
        "title": "Dev Swarm local execution: Rafa-Innerchispa/inneros-alpha-alpaca",
        "checklist": ["Verify isolated worktree"],
    }
    with mock.patch.object(scheduler.local_execution_plane, "repo_policy_status", return_value={"ok": True, "write_scope": "worktree"}):
        ok, reason, repo = scheduler._eligible_reason(task)
    assert ok is True
    assert reason == "eligible"
    assert repo == "Rafa-Innerchispa/inneros-alpha-alpaca"


def test_pytest_project_uses_pytest_not_unittest(tmp_path) -> None:
    worktree = tmp_path
    (worktree / "pyproject.toml").write_text("[project]\nname='x'\n[tool.pytest.ini_options]\ntestpaths=['tests']\n", encoding="utf-8")
    (worktree / "src").mkdir()
    (worktree / "tests").mkdir()
    (worktree / "tests" / "test_probe.py").write_text("def test_probe():\n    assert True\n", encoding="utf-8")
    commands = scheduler._test_commands_for_policy("Rafa-Innerchispa/inneros-alpha-alpaca", worktree, ["src/probe.py", "tests/test_probe.py"])
    assert ["python3", "-m", "pytest", "tests", "-q"] in commands
    assert ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"] not in commands


def test_local_execution_uses_platform_venv_for_test_tools() -> None:
    path = lep._execution_env()["PATH"].split(":")
    assert path[0] == "/home/rlopez/inneros/inneros_core/platform/venv/bin"


def test_legacy_projects_local_exec_root_is_migrated_to_inneros(monkeypatch) -> None:
    monkeypatch.setenv("RALFIA_LOCAL_EXEC_ROOT", "/home/rlopez/projects/inneros-local-execution-worktrees")
    monkeypatch.setenv("INNEROS_CORE_ROOT", "/home/rlopez/inneros/inneros_core")
    assert str(lep._root()) == "/home/rlopez/inneros/inneros_core/var/local_execution"


def test_dev_swarm_prompt_guides_python_tests_to_unittest_by_default() -> None:
    source = scheduler._execute_existing_worker_generic.__code__.co_consts
    serialized = " ".join(str(item) for item in source)
    assert "For Python tests, prefer unittest-compatible tests unless pytest is declared by the repository." in serialized


def test_email_tasks_do_not_contaminate_development_queue() -> None:
    task = {
        "task_id": "ops_email_fixture",
        "status": "proposed",
        "assignee": "chatgpt",
        "priority": "p0",
        "kind": "email_ops",
        "tags": ["email"],
        "title": "Fix customer email reply and WhatsApp alert",
        "checklist": ["Operational email handling, no repo write"],
    }
    ok, reason, repo = scheduler._eligible_reason(task)
    assert ok is False
    assert reason == "non_development_ops_filtered"
    assert repo is None


def test_dev_swarm_launch_auto_normalizes_missing_task_metadata() -> None:
    generated = {
        "ok": True,
        "task_id": "ops_generated1234",
        "task": {"task_id": "ops_generated1234"},
    }
    with mock.patch.object(lep, "_repo_config", return_value={"profile": "python-tests", "allowed_paths": ["platform"], "source_path": "/tmp/source"}), \
        mock.patch("raphiia_openai.coordination_live.create_ops_task", return_value=generated):
        result = lep.dev_swarm_launch_task(
            repo="Rafa-Innerchispa/innerops-agentic-platform",
            objective="Repair local-first fixture",
            actor="chatgpt",
            dry_run=True,
        )
    assert result["ok"] is True
    assert result["plan"]["task_id"] == "ops_generated1234"
    assert result["plan"]["correlation_id"].startswith("dev-swarm-")
    assert result["plan"]["idempotency_key"]
    assert result["plan"]["execution_policy"] == "local_first"


def test_resource_fabric_routes_local_when_capable_and_blocks_silent_cloud() -> None:
    local_model = {
        "model_provider": "local-amd",
        "provider_id": "local-amd-5",
        "task_classes": ["coding"],
        "priority": 10,
        "cost_policy": "local_first",
        "model_name": execution_policy.DEFAULT_PREFERRED_MODEL,
    }
    cloud_model = {
        "model_provider": "paid-cloud",
        "provider_id": "paid-cloud-1",
        "task_classes": ["coding"],
        "priority": 1,
        "cost_policy": "explicit_burst_only",
    }
    provider_docs = {
        "local-amd-5": {"provider_id": "local-amd-5", "kind": "local_node"},
        "paid-cloud-1": {"provider_id": "paid-cloud-1", "kind": "cloud"},
    }

    class Cursor(list):
        def sort(self, key, direction):
            return Cursor(sorted(self, key=lambda row: row.get(key, 0), reverse=direction < 0))

        def limit(self, n):
            return Cursor(self[:n])

    class Models:
        def find(self, query, projection):
            rows = [local_model, cloud_model]
            if query.get("cost_policy"):
                rows = [row for row in rows if row.get("cost_policy") == query["cost_policy"]]
            if query.get("task_classes"):
                rows = [row for row in rows if query["task_classes"] in row.get("task_classes", [])]
            return Cursor(rows)

    class Providers:
        def find_one(self, query, projection):
            return provider_docs.get(query.get("provider_id"))

    fake_db = {
        resource_fabric.COL_MODEL_REGISTRY: Models(),
        resource_fabric.COL_PROVIDERS: Providers(),
    }

    with mock.patch.object(resource_fabric.mongo_store, "get_db", return_value=fake_db):
        local = resource_fabric.route_resource_request("proj", "coding")
        blocked = resource_fabric.route_resource_request("proj", "coding", prefer_cloud=True)
        override = resource_fabric.route_resource_request(
            "proj",
            "coding",
            prefer_cloud=True,
            fallback_reason="owner_override",
            approval_id="owner-approved-fixture",
            owner_override=True,
        )
    assert local["ok"] is True
    assert local["selected"]["provider"]["provider_id"] == "local-amd-5"
    assert blocked["ok"] is False
    assert blocked["error"] == "blocked_local_capable"
    assert override["ok"] is True
    assert override["selected"]["provider"]["provider_id"] == "paid-cloud-1"


def test_write_task_without_structured_binding_blocks_before_worktree() -> None:
    task = {
        "task_id": "ops_missing_binding_fixture",
        "status": "proposed",
        "assignee": "dev_swarm",
        "priority": "p0",
        "title": "Activate Alpaca runtime",
        "checklist": ["Repo exacto: Rafa-Innerchispa/inneros-alpha-alpaca", "Create files and run tests"],
    }
    ok, reason, repo = scheduler._eligible_reason(task)
    assert ok is False
    assert reason == "blocked_missing_task_binding"
    assert repo is None


def test_project_id_binding_selects_alpaca_repo_without_prose_inference() -> None:
    task = {
        "task_id": "ops_alpaca_project_id_fixture",
        "status": "proposed",
        "assignee": "dev_swarm",
        "priority": "p0",
        "project_id": "inneros-alpha-alpaca",
        "task_class": "coding",
        "title": "Activate runtime",
        "checklist": ["This text intentionally omits the repo name."],
    }
    with mock.patch.object(scheduler, "_registry_resolve_repo", return_value="Rafa-Innerchispa/inneros-alpha-alpaca"), \
        mock.patch.object(scheduler.local_execution_plane, "repo_policy_status", return_value={"ok": True, "write_scope": "worktree"}):
        ok, reason, repo = scheduler._eligible_reason(task)
    assert ok is True
    assert reason == "eligible"
    assert repo == "Rafa-Innerchispa/inneros-alpha-alpaca"


def test_raphiia_openai_shim_imports_runtime_source() -> None:
    import raphiia_openai.coordination_live as legacy_coordination
    import inneros_core_runtime.coordination_live as canonical_coordination

    assert legacy_coordination.__file__ == canonical_coordination.__file__
    assert "inneros_core_runtime" in (legacy_coordination.__file__ or "")


def test_create_ops_task_persists_structured_task_envelope() -> None:
    inserted: dict[str, object] = {}

    class FakeCollection:
        def find_one(self, query, projection):
            return None

        def insert_one(self, doc):
            inserted.update(doc)
            return object()

    class FakeDB(dict):
        def __getitem__(self, key):
            return FakeCollection()

    with mock.patch.object(coordination_live.mongo_store, "get_db", return_value=FakeDB()), \
        mock.patch("raphiia_openai.memory.agent_messages.create_agent_message"), \
        mock.patch.object(coordination_live, "bump_revision"):
        result = coordination_live.create_ops_task(
            assignee="dev_swarm",
            title="Structured fixture",
            checklist=["write code"],
            priority="p0",
            from_agent="CODEX",
            correlation_id="structured-envelope-fixture",
            project_id="inneros-alpha-alpaca",
            repo="Rafa-Innerchispa/inneros-alpha-alpaca",
            base_ref="main",
            task_class="coding",
            execution_lane="local_dev_swarm",
            provider_transport="local_execution_plane",
            runtime_profile="node-tests",
        )
    assert result["ok"] is True
    assert inserted["project_id"] == "inneros-alpha-alpaca"
    assert inserted["repo"] == "Rafa-Innerchispa/inneros-alpha-alpaca"
    assert inserted["base_ref"] == "main"
    assert inserted["task_class"] == "coding"
    assert inserted["execution_lane"] == "local_dev_swarm"
    assert inserted["provider_transport"] == "local_execution_plane"
    assert inserted["runtime_profile"] == "node-tests"
